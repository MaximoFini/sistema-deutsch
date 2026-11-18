"""Migración de datos reales (TiendaQuick, Contabilium y snapshot de Tiendanube) al sistema.

Usa solo archivos que ya están en disco (`local/migracion/`, ignorada por git) y los servicios que
el sistema ya tiene. No llama a ningún canal ni escribe en ninguno. Es repetible: cada paso es
idempotente.

    manage.py migrar_datos catalogo --tn-json RUTA --contabilium-xlsx RUTA
"""

import csv
import io
import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from openpyxl import Workbook, load_workbook

from apps.catalog import contabilium_import
from apps.catalog.contabilium_import import parse_number
from apps.core.db import refresh_statistics
from apps.customers.models import Address, Customer
from apps.integrations.adapters.tiendanube.catalog import upsert_product
from apps.pricing.models import PriceList

User = get_user_model()


class Command(BaseCommand):
    help = "Migra datos reales desde archivos exportados (no llama a ningún canal)."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="paso", required=True)
        cat = sub.add_parser(
            "catalogo", help="Productos desde el snapshot de Tiendanube + export de Contabilium"
        )
        cat.add_argument("--tn-json", required=True)
        cat.add_argument("--contabilium-xlsx", required=True)
        cat.add_argument(
            "--lista-mayorista-csv", required=True, help="Código;Costo interno;Precio;Rentabilidad"
        )
        cli = sub.add_parser("clientes", help="Clientes desde el export de Contabilium")
        cli.add_argument("--contabilium-xlsx", required=True)
        ped = sub.add_parser("pedidos", help="Historial de pedidos de TiendaQuick (un Excel por mes)")
        ped.add_argument("--carpeta", required=True, help="Carpeta con los pedidos_detalle_*.xlsx")

    def handle(self, *args, paso, **options):
        if paso == "catalogo":
            self._catalogo(
                Path(options["tn_json"]),
                Path(options["contabilium_xlsx"]),
                Path(options["lista_mayorista_csv"]),
            )
        elif paso == "clientes":
            self._clientes(Path(options["contabilium_xlsx"]))
        elif paso == "pedidos":
            from apps.sales.historical_import import import_orders

            stats = import_orders(Path(options["carpeta"]))
            refresh_statistics()
            self.stdout.write(f"Pedidos: {stats}")
        else:  # pragma: no cover
            raise CommandError(f"Paso desconocido: {paso}")

    def _catalogo(self, tn_json: Path, xlsx: Path, mayorista_csv: Path):
        products = json.loads(tn_json.read_text(encoding="utf-8"))
        self._stock_actual_de_contabilium(products, xlsx)
        ok, errors = 0, []
        for data in products:
            try:
                upsert_product(data)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                errors.append((data.get("id"), f"{type(exc).__name__}: {exc}"[:200]))
        self.stdout.write(f"Tiendanube: {ok} productos cargados, {len(errors)} con error.")
        for pid, msg in errors[:10]:
            self.stdout.write(f"  - {pid}: {msg}")

        content, filename = self._contabilium_file(xlsx, mayorista_csv)
        user = User.objects.filter(is_active=True).order_by("pk").first()
        imp = contabilium_import.create_preview(filename=filename, content=content, user=user)
        self.stdout.write(f"Contabilium (vista previa): {json.dumps(imp.summary, ensure_ascii=False)[:500]}")
        stats = contabilium_import.apply_import(imp, user=user)
        self.stdout.write(f"Contabilium (aplicado): {stats}")
        refresh_statistics()

    def _stock_actual_de_contabilium(self, products: list[dict], xlsx: Path) -> None:
        """El snapshot de Tiendanube tiene días de antigüedad; el stock disponible vigente es el de Contabilium."""
        rows = list(
            load_workbook(xlsx, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True)
        )
        head = list(rows[0])
        sku_col, stock_col = head.index("SKU"), head.index("Stock Disponible")
        current = {}
        for r in rows[1:]:
            if r[sku_col] is not None and r[stock_col] not in (None, ""):
                current[str(r[sku_col]).strip()] = max(0, int(parse_number(r[stock_col])))
        updated = 0
        for data in products:
            for variant in data.get("variants") or []:
                sku = str(variant.get("sku") or "").strip()
                if sku in current:
                    variant["stock"] = current[sku]
                    updated += 1
        self.stdout.write(
            f"Stock vigente de Contabilium aplicado a {updated} variantes (negativos quedan en 0)."
        )

    @staticmethod
    def _contabilium_file(xlsx: Path, mayorista_csv: Path) -> tuple[bytes, str]:
        """Une el export de productos con la lista MAYORISTA (precio neto) en un solo Excel para el importador."""
        wholesale = {}
        with mayorista_csv.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                code = (row.get("Codigo") or "").strip()
                if code and row.get("Precio"):
                    wholesale[code] = row["Precio"].strip()
        src = load_workbook(xlsx, read_only=True, data_only=True).worksheets[0]
        rows = list(src.iter_rows(values_only=True))
        head = list(rows[0])
        idx = {name: head.index(name) for name in ("SKU", "Nombre", "Precio Final", "Stock")}
        out = Workbook()
        ws = out.active
        ws.append(["SKU", "Nombre", "Precio Final", "Stock", "Precio mayorista"])
        for r in rows[1:]:
            code = str(r[idx["SKU"]] or "").strip()
            if not code:
                continue
            ws.append([code, r[idx["Nombre"]], r[idx["Precio Final"]], r[idx["Stock"]], wholesale.get(code)])
        buf = io.BytesIO()
        out.save(buf)
        return buf.getvalue(), "productos_con_mayorista.xlsx"

    VAT = {"RI": "RI", "MO": "MONOTRIBUTO", "EX": "EXENTO", "CF": "CF"}

    def _clientes(self, xlsx: Path):
        """Clientes de Contabilium → `Customer` mayorista (sin acceso a la tienda: eso es la invitación de M9-03).

        Idempotente por tipo y número de documento. No crea cuentas ni manda emails.
        """
        rows = list(
            load_workbook(xlsx, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True)
        )
        head = list(rows[0])
        mayorista = PriceList.objects.get(code="MAYORISTA")
        created = updated = skipped = 0
        for raw in rows[1:]:
            r = dict(zip(head, raw, strict=False))
            name = str(r.get("Razon Social") or "").strip()
            doc = re.sub(r"\D", "", str(r.get("Documento") or ""))
            if not name:
                skipped += 1
                continue
            doc_type = "CUIT" if str(r.get("Tipo Documeto")) == "CUIT" and len(doc) == 11 else "DNI"
            if doc in ("", "0"):
                doc_type, doc = "CF", ""
            values = {
                "kind": Customer.Kind.WHOLESALE,
                "legal_name": name[:255],
                "trade_name": str(r.get("Nombre Fantasia") or "").strip()[:255],
                "vat_condition": self.VAT.get(str(r.get("Categoria Impositiva")), "CF"),
                "email": str(r.get("Email") or "").strip().lower()[:254],
                "phone": str(r.get("Telefono") or r.get("Celular") or "").strip()[:50],
                "price_list": mayorista if r.get("Lista Precio") == "MAYORISTA" else None,
            }
            customer = Customer.objects.filter(tax_id_type=doc_type, tax_id=doc).first() if doc else None
            if customer is None:
                customer = Customer.objects.create(tax_id_type=doc_type, tax_id=doc, **values)
                created += 1
            else:
                for key, value in values.items():
                    setattr(customer, key, value)
                customer.save()
                updated += 1
            street = str(r.get("Domicilio") or "").strip()
            if street and not customer.addresses.exists():
                Address.objects.create(
                    customer=customer,
                    kind=Address.Kind.FISCAL,
                    street=street[:255],
                    floor=str(r.get("Piso Depto") or "").strip()[:50],
                    city=str(r.get("Ciudad") or "").strip()[:100] or "-",
                    province=str(r.get("Provincia") or "").strip()[:100] or "-",
                    postal_code=str(r.get("Codigo Postal") or "").strip()[:10],
                )
        self.stdout.write(f"Clientes: {created} creados, {updated} actualizados, {skipped} omitidos.")
