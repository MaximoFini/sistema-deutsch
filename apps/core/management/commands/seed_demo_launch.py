"""Datos de ensayo para la prueba punta a punta (M9 · DDEV-57).

    manage.py seed_demo_launch --yes             arma los datos de ensayo
    manage.py seed_demo_launch --yes --limpiar   borra solo lo que armó este comando

Seguridad:

- Se niega a correr si `ENVIRONMENT_NAME` es producción y siempre pide `--yes`.
- Todo lo que crea lleva una marca que `--limpiar` usa para borrarlo, y nada más: productos y clientes
  con nombre «ENSAYO …», SKU «ENS-…», emails `@ensayo.invalid` (un dominio que no existe) y pedidos de
  esos clientes, de esos productos o con referencia «ENSAYO …». Un pedido histórico nunca se toca.
- No manda emails (no encola ninguno ni avisos por email) y no llama a ningún canal: los pedidos de
  Mercado Libre y Tiendanube se crean sin vínculo con el canal, así que despacharlos no escribe nada afuera.
- Las contraseñas de prueba se generan al azar, se imprimen UNA vez en la consola y no se guardan en
  ningún archivo. Si ya existían, se conservan (usá `--nuevas-claves` para generar otras).
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.utils import timezone

from apps.accounts.roles import VENDEDOR, sync_roles
from apps.alerts.models import Alert
from apps.catalog.models import Product, Variant
from apps.customers.models import Address, Customer
from apps.fulfillment.models import Carrier, PickBatch, PickBatchOrder
from apps.integrations.models import Channel
from apps.inventory import services as inventory
from apps.inventory.models import StockLevel, StockMovement
from apps.pricing.models import PriceList, PriceListItem
from apps.sales import states
from apps.sales.models import Payment, SalesDocument, SalesLine, Shipment
from apps.wholesale import cart as cart_service
from apps.wholesale import checkout
from apps.wholesale.access import Shopper
from apps.wholesale.models import (
    Cart,
    CartItem,
    CustomerAccount,
    CustomerBalance,
    Invitation,
    OutboundEmail,
    PaymentReceipt,
    Shortage,
)

User = get_user_model()

PREFIX = "ENSAYO"  # nombre de productos, clientes y referencias de pedidos
SKU_PREFIX = "ENS-"
EMAIL_DOMAIN = "ensayo.invalid"
PRODUCTION_NAMES = {"prod", "production", "produccion", "producción"}
PRODUCTION_REFUSAL = (
    "Este comando es solo para ensayos: se niega a correr en producción (ENVIRONMENT_NAME={name})."
)
NEED_YES = "Esto crea (o con --limpiar borra) datos de ensayo. Confirmalo agregando --yes."
WHOLESALE_PRICE = Decimal("10000")  # neto sin IVA, como la lista mayorista de los tests
RETAIL_PRICE = Decimal("18000")
STOCK_PER_VARIANT = 60
PASSWORD_ALPHABET = (
    "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O, 1/l/I: se tipea a mano
)

# nombre, categorías, [(sufijo del SKU, talle, color)]
PRODUCTS = [
    (
        "ENSAYO Malla Entrenamiento",
        ["Mallas"],
        [
            ("MAL-S-AZU", "S", "Azul"),
            ("MAL-S-NEG", "S", "Negro"),
            ("MAL-M-AZU", "M", "Azul"),
            ("MAL-M-NEG", "M", "Negro"),
        ],
    ),
    ("ENSAYO Buzo Canguro", ["Buzos"], [("BUZ-M-GRI", "M", "Gris"), ("BUZ-L-GRI", "L", "Gris")]),
    ("ENSAYO Gorra Silicona", ["Gorras"], [("GOR-U-NEG", "Único", "Negro")]),
]

# CUIT con dígito verificador válido (se calcula); solo «30-99990xxx».
CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def make_cuit(body: str) -> str:
    digits = "30" + body
    total = sum(int(d) * w for d, w in zip(digits, CUIT_WEIGHTS, strict=True))
    check = 11 - total % 11
    if check == 11:
        check = 0
    if check == 10:  # no hay CUIT con este cuerpo: probamos con el siguiente
        return make_cuit(str(int(body) + 1).zfill(len(body)))
    return digits + str(check)


CUSTOMERS = [
    # clave, razón social, cuenta corriente, cuenta ya creada con contraseña
    ("uno", "ENSAYO Natatorio Uno SRL", False, True),
    ("dos", "ENSAYO Club Dos SA", True, True),
    ("tres", "ENSAYO Pileta Tres SRL", False, False),  # sin contraseña: para probar la invitación
]


def email_of(slug: str) -> str:
    return f"{slug}@{EMAIL_DOMAIN}"


# ── Qué es de ensayo ─────────────────────────────────────────────────────────


def demo_variants():
    return Variant.objects.filter(sku__startswith=SKU_PREFIX, product__name__startswith=PREFIX)


def demo_customers():
    return Customer.objects.filter(legal_name__startswith=PREFIX, email__endswith="@" + EMAIL_DOMAIN)


def demo_users():
    return User.objects.filter(email__endswith="@" + EMAIL_DOMAIN)


def demo_documents():
    """Pedidos y devoluciones de ensayo. Un histórico nunca entra, aunque tenga una marca parecida."""
    own = (
        Q(customer__in=demo_customers())
        | Q(lines__variant__in=demo_variants())
        | Q(channel_reference__startswith=PREFIX)
    )
    base = SalesDocument.objects.filter(own, is_historical=False).values("pk")
    returns = SalesDocument.objects.filter(related_document__in=base, is_historical=False).values("pk")
    return SalesDocument.objects.filter(Q(pk__in=base) | Q(pk__in=returns)).distinct()


def has_demo_data() -> bool:
    return (
        demo_variants().exists()
        or demo_customers().exists()
        or demo_users().exists()
        or demo_documents().exists()
    )


class Command(BaseCommand):
    help = "Arma (o con --limpiar borra) los datos de ensayo de la prueba punta a punta. No toca canales ni manda emails."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirma que querés correr el comando.")
        parser.add_argument(
            "--limpiar", action="store_true", help="Borra todo lo marcado como ensayo (y nada más)."
        )
        parser.add_argument(
            "--nuevas-claves",
            action="store_true",
            help="Genera otra contraseña de prueba para los usuarios de ensayo que ya existían.",
        )

    def handle(self, *args, yes=False, limpiar=False, nuevas_claves=False, **options):
        name = str(settings.ENVIRONMENT_NAME).strip().lower()
        if name in PRODUCTION_NAMES:
            raise CommandError(PRODUCTION_REFUSAL.format(name=settings.ENVIRONMENT_NAME))
        if not yes:
            raise CommandError(NEED_YES)
        if limpiar:
            report = clean()
            self.stdout.write(self.style.SUCCESS("Datos de ensayo borrados:"))
            for label, count in report.items():
                self.stdout.write(f"  {label}: {count}")
            return
        result = seed(new_passwords=nuevas_claves)
        self.stdout.write(self.style.SUCCESS("Datos de ensayo listos."))
        for line in result.summary():
            self.stdout.write(f"  {line}")
        if result.passwords:
            self.stdout.write("")
            self.stdout.write(
                "Contraseñas de prueba (se muestran solo ahora; anotalas, no quedan guardadas):"
            )
            for email, password in result.passwords:
                self.stdout.write(f"  {email}  →  {password}")
        else:
            self.stdout.write(
                "Los usuarios de ensayo ya existían: conservan su contraseña (--nuevas-claves para cambiarla)."
            )
        self.stdout.write("Para borrar todo lo de ensayo: manage.py seed_demo_launch --yes --limpiar")


# ── Armar ────────────────────────────────────────────────────────────────────


class SeedResult:
    def __init__(self):
        self.passwords: list[tuple[str, str]] = []
        self.created: dict[str, int] = {}
        self.orders_skipped = False

    def count(self, label: str, n: int = 1):
        self.created[label] = self.created.get(label, 0) + n

    def summary(self) -> list[str]:
        lines = [f"{label}: {n}" for label, n in self.created.items()]
        if self.orders_skipped:
            lines.append("Los pedidos de ensayo ya estaban: no se crearon otros (--limpiar para rearmarlos).")
        return lines


def _password(result: SeedResult, user, *, create: bool, new: bool) -> None:
    """Contraseña de prueba al azar: se imprime una sola vez y nunca se guarda en claro."""
    if not (create or new):
        return
    password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(14))
    user.set_password(password)
    user.save(update_fields=["password"])
    result.passwords.append((user.email, password))


def seed(*, new_passwords: bool = False) -> SeedResult:
    """Crea los datos de ensayo que falten. Idempotente. Nada sale por email ni a los canales."""
    result = SeedResult()
    # Ni emails a clientes ni avisos (que pueden mandar email a los usuarios internos): el seed es mudo.
    with (
        mock.patch("apps.wholesale.mail.enqueue", return_value=None),
        mock.patch("apps.alerts.services.emit", return_value=None),
        transaction.atomic(),
    ):
        _ensure_roles()
        seller = _seller(result, new_passwords)
        catalog = _catalog(result)
        carrier = _carrier(result)
        accounts = _customers(result, new_passwords)
        _retail_customer(result)
        if demo_documents().exists():
            result.orders_skipped = True
        else:
            _orders(result, seller, accounts, catalog, carrier)
    return result


def _ensure_roles() -> None:
    if not Group.objects.filter(name=VENDEDOR).exists():
        sync_roles()


def _demo_user(email: str, full_name: str):
    """El usuario de ensayo con ese email. Devuelve (usuario, es_nuevo). Uno que quedó desactivado por la
    limpieza (porque la auditoría, que no se borra, lo nombra) se reactiva y cuenta como nuevo."""
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        return User.objects.create_user(email=email, full_name=full_name[:150]), True
    if not user.email.endswith("@" + EMAIL_DOMAIN):
        raise CommandError(f"El email {email} ya está en uso y no es de ensayo: no se toca.")
    if user.is_active:
        return user, False
    user.is_active = True
    user.full_name = full_name[:150]
    user.save(update_fields=["is_active", "full_name"])
    return user, True


def _seller(result: SeedResult, new: bool):
    user, created = _demo_user(email_of("vendedor"), "ENSAYO Vendedor")
    if created:
        result.count("Usuario vendedor")
    user.groups.add(Group.objects.get(name=VENDEDOR))
    _password(result, user, create=created, new=new)
    return user


def _catalog(result: SeedResult) -> dict[str, Variant]:
    wholesale = PriceList.objects.get(code="MAYORISTA")
    retail = PriceList.objects.filter(code="MINORISTA").first()
    warehouse = inventory.default_warehouse()
    variants: dict[str, Variant] = {}
    for name, categories, combos in PRODUCTS:
        product, product_created = Product.objects.get_or_create(
            name=name,
            defaults={"brand": "Deutsch", "categories": categories, "description": "Producto de ensayo."},
        )
        if product_created:
            result.count("Productos")
        for suffix, size, color in combos:
            sku = SKU_PREFIX + suffix
            variant, created = Variant.objects.get_or_create(
                sku=sku, defaults={"product": product, "attributes": {"Talle": size, "Color": color}}
            )
            if not variant.product.name.startswith(PREFIX):
                raise CommandError(f"El SKU {sku} ya existe y no es de ensayo: no se toca.")
            if created:
                result.count("Variantes")
                PriceListItem.objects.create(price_list=wholesale, variant=variant, price=WHOLESALE_PRICE)
                if retail is not None:
                    PriceListItem.objects.create(price_list=retail, variant=variant, price=RETAIL_PRICE)
                inventory.apply_sync_level(variant, warehouse, STOCK_PER_VARIANT, note="Stock de ensayo")
            variants[suffix] = variant
    return variants


def _carrier(result: SeedResult) -> Carrier:
    carrier, created = Carrier.objects.get_or_create(name=f"{PREFIX} Expreso")
    if created:
        result.count("Expresos")
    return carrier


def _customers(result: SeedResult, new: bool) -> dict[str, CustomerAccount]:
    wholesale = PriceList.objects.get(code="MAYORISTA")
    accounts: dict[str, CustomerAccount] = {}
    for index, (key, legal_name, credit, with_password) in enumerate(CUSTOMERS, start=1):
        cuit = make_cuit(f"99990{index:03d}")
        email = email_of(f"cliente.{key}")
        existing = CustomerAccount.objects.filter(cuit=cuit).select_related("user", "customer").first()
        if existing is not None:
            if not existing.user.email.endswith("@" + EMAIL_DOMAIN):
                raise CommandError(f"El CUIT {cuit} ya tiene una cuenta que no es de ensayo: no se toca.")
            if with_password:
                _password(result, existing.user, create=False, new=new)
            accounts[key] = existing
            continue
        if Customer.objects.filter(tax_id=cuit).exists():
            raise CommandError(f"El CUIT de «{legal_name}» ya está en uso y no es de ensayo.")
        customer = Customer.objects.create(
            kind=Customer.Kind.WHOLESALE,
            legal_name=legal_name,
            trade_name=legal_name,
            tax_id_type=Customer.TaxIdType.CUIT,
            tax_id=cuit,
            vat_condition=Customer.VatCondition.RI,
            email=email,
            phone="341 555-0000",
            price_list=wholesale,
            credit_enabled=credit,
        )
        Address.objects.create(
            customer=customer,
            kind=Address.Kind.FISCAL,
            street="Calle de Ensayo",
            number="123",
            city="Rosario",
            province="Santa Fe",
            postal_code="2000",
        )
        user, _ = _demo_user(email, legal_name)
        account = CustomerAccount.objects.create(
            user=user,
            customer=customer,
            cuit=cuit,
            status=CustomerAccount.Status.APPROVED,
            credit_enabled=credit,
            reviewed_at=timezone.now(),
            registration={
                "legal_name": legal_name,
                "trade_name": legal_name,
                "vat_condition": "RI",
                "email": email,
                "origen": "datos de ensayo",
            },
            accepted_terms_at=timezone.now() if with_password else None,
        )
        if with_password:
            _password(result, user, create=True, new=new)
        else:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            Invitation.objects.get_or_create(account=account)
        result.count("Clientes mayoristas")
        accounts[key] = account
    return accounts


def _retail_customer(result: SeedResult) -> Customer:
    customer, created = Customer.objects.get_or_create(
        legal_name=f"{PREFIX} Cliente Minorista",
        email=email_of("minorista"),
        defaults={"kind": Customer.Kind.RETAIL, "phone": "341 555-1111"},
    )
    if created:
        result.count("Clientes minoristas")
    return customer


# Pedidos de canales: se crean sin vínculo con el canal (ni notificación ni escritura posible).


def _channel_order(
    code: str, ref: str, *, status, channel_status, variant, quantity, customer, shipment, payment_status
):
    now = timezone.now()
    doc = SalesDocument.objects.create(
        channel=Channel.objects.get(code=code),
        customer=customer,
        status=status,
        status_changed_at=now,
        issued_at=now - timedelta(hours=1),
        ready_at=None if status == states.AWAITING_PAYMENT else now - timedelta(hours=1),
        channel_reference=f"{PREFIX} {ref}",
        channel_status=channel_status,
    )
    SalesLine.objects.create(
        document=doc,
        variant=variant,
        sku_snapshot=variant.sku,
        description_snapshot=variant.product.name,
        quantity=quantity,
        unit_price=RETAIL_PRICE,
    )
    doc.recalculate_totals()
    method = Payment.Method.MERCADOPAGO if code == "mercadolibre" else Payment.Method.TRANSFER
    if code == "tiendanube" and payment_status == "paid":
        method = Payment.Method.MERCADOPAGO
    Payment.objects.create(
        document=doc,
        method=method,
        amount=doc.total,
        status=Payment.Status.CONFIRMED if payment_status == "paid" else Payment.Status.PENDING,
        paid_at=now if payment_status == "paid" else None,
    )
    Shipment.objects.create(document=doc, **shipment)
    return doc


def _place_wholesale(account, seller, items, *, payment, delivery, carrier_name=""):
    """Un pedido mayorista por el camino real (checkout), cargado por el vendedor en nombre del cliente
    (así no pide el mínimo de compra y se puede ensayar sin armar un carrito grande)."""
    shopper = Shopper(account=account, user=seller, acting=True)
    cart = shopper.cart()
    for variant, qty in items.items():
        CartItem.objects.update_or_create(cart=cart, variant=variant, defaults={"quantity": qty})
    snapshot = checkout.sign_snapshot(cart_service.summarize(cart, apply_min=False))
    return checkout.place_order(
        shopper,
        delivery=checkout.Delivery(method=delivery, carrier_name=carrier_name),
        payment_method=payment,
        snapshot=snapshot,
    )


def _orders(result: SeedResult, seller, accounts, catalog, carrier) -> None:
    malla_s_azul, malla_m_negro = catalog["MAL-S-AZU"], catalog["MAL-M-NEG"]
    gorra, buzo = catalog["GOR-U-NEG"], catalog["BUZ-M-GRI"]
    minorista = Customer.objects.get(legal_name=f"{PREFIX} Cliente Minorista")
    now = timezone.now()
    S = Shipment.Method

    # Mercado Libre: Flex que vence pronto, Flex en preparación, Full (despacha ML) y uno ya entregado.
    ml = "mercadolibre"
    _channel_order(ml, "ML Flex 1", status=states.NEW, channel_status="paid/ready_to_ship", variant=gorra,
                   quantity=1, customer=minorista, payment_status="paid",
                   shipment={"method": S.ME_FLEX, "logistic_type": "self_service",
                             "dispatch_deadline": now + timedelta(hours=1), "status": "ready_to_ship"})  # fmt: skip
    _channel_order(ml, "ML Flex 2", status=states.PREPARING, channel_status="paid/ready_to_ship", variant=buzo,
                   quantity=2, customer=minorista, payment_status="paid",
                   shipment={"method": S.ME_FLEX, "logistic_type": "self_service",
                             "dispatch_deadline": now + timedelta(hours=26), "status": "ready_to_ship"})  # fmt: skip
    _channel_order(ml, "ML Full 1", status=states.DISPATCHED, channel_status="paid/ready_to_ship", variant=malla_s_azul,
                   quantity=1, customer=minorista, payment_status="paid",
                   shipment={"method": S.ME_FULL, "logistic_type": "fulfillment", "status": "ready_to_ship"})  # fmt: skip
    _channel_order(ml, "ML Flex 3 (entregado)", status=states.DELIVERED, channel_status="paid/delivered", variant=malla_m_negro,
                   quantity=1, customer=minorista, payment_status="paid",
                   shipment={"method": S.ME_FLEX, "logistic_type": "self_service", "status": "delivered"})  # fmt: skip
    result.count("Pedidos de Mercado Libre", 4)

    # Tiendanube: Envío Nube pagado, retiro en el local pagado y retiro con transferencia sin pagar.
    tn = "tiendanube"
    _channel_order(tn, "TN Envío Nube 1", status=states.NEW, channel_status="open/paid/unpacked", variant=buzo,
                   quantity=1, customer=minorista, payment_status="paid",
                   shipment={"method": S.ENVIO_NUBE, "status": "pending",
                             "address": {"address": "Calle de Ensayo", "number": "1", "city": "Rosario"}})  # fmt: skip
    _channel_order(tn, "TN Retiro 1", status=states.NEW, channel_status="open/paid/unpacked", variant=gorra,
                   quantity=1, customer=minorista, payment_status="paid",
                   shipment={"method": S.PICKUP, "status": "pending"})  # fmt: skip
    _channel_order(tn, "TN Retiro 2 (transferencia sin pagar)", status=states.AWAITING_PAYMENT,
                   channel_status="open/pending/unpacked", variant=malla_s_azul, quantity=1, customer=minorista,
                   payment_status="pending", shipment={"method": S.PICKUP, "status": "pending"})  # fmt: skip
    result.count("Pedidos de Tiendanube", 3)

    # Mayorista, por el circuito real de la tienda.
    uno, dos = accounts["uno"], accounts["dos"]
    name = carrier.name
    _place_wholesale(
        uno, seller, {malla_s_azul: 5}, payment="transfer", delivery="carrier", carrier_name=name
    )
    t2 = _place_wholesale(
        uno, seller, {malla_m_negro: 4, buzo: 2}, payment="transfer", delivery="carrier", carrier_name=name
    )
    _place_wholesale(uno, seller, {gorra: 3}, payment="cash", delivery="pickup")
    _place_wholesale(dos, seller, {malla_s_azul: 6}, payment="account", delivery="carrier", carrier_name=name)
    _confirm_transfer(t2)  # este ya viene con el pago confirmado: listo para preparar
    result.count("Pedidos mayoristas", 4)


def _confirm_transfer(doc: SalesDocument) -> None:
    """Deja la transferencia confirmada como lo hace `payments.confirm_payment`, sin necesitar un administrador."""
    doc.payments.filter(external_reference="mayorista").update(
        status=Payment.Status.CONFIRMED, paid_at=timezone.now()
    )
    states.change_status(doc, states.NEW, system=True, reason="Pago confirmado (ensayo)")


# ── Borrar ───────────────────────────────────────────────────────────────────


def clean() -> dict[str, int]:
    """Borra todo lo de ensayo y nada más. Todo o nada: si algo real depende de un dato de ensayo, avisa."""
    report: dict[str, int] = {}
    try:
        with transaction.atomic():
            docs = list(demo_documents().values_list("pk", flat=True))
            returns = list(
                SalesDocument.objects.filter(pk__in=docs, doc_type=SalesDocument.DocType.RETURN).values_list(
                    "pk", flat=True
                )
            )
            batch_ids = list(
                PickBatch.objects.filter(items__document_id__in=docs).distinct().values_list("pk", flat=True)
            )
            PickBatchOrder.objects.filter(document_id__in=docs).delete()
            empty = PickBatch.objects.filter(pk__in=batch_ids, items__isnull=True)
            report["Tandas de preparación vacías"] = empty.count()
            empty.delete()
            report["Avisos"] = Alert.objects.filter(link_url__in=[f"/pedidos/{pk}/" for pk in docs]).delete()[
                0
            ]
            for receipt in PaymentReceipt.objects.filter(document_id__in=docs):
                receipt.file.delete(save=False)
            report["Saldos a favor"] = CustomerBalance.objects.filter(
                Q(document_id__in=docs) | Q(customer__in=demo_customers())
            ).delete()[0]
            Shortage.objects.filter(document_id__in=docs).delete()
            SalesDocument.objects.filter(pk__in=returns).delete()
            report["Pedidos y devoluciones"] = len(docs)
            SalesDocument.objects.filter(pk__in=docs).delete()
            variants = demo_variants()
            report["Movimientos de stock"] = StockMovement.objects.filter(variant__in=variants).delete()[0]
            StockLevel.objects.filter(variant__in=variants).delete()
            PriceListItem.objects.filter(variant__in=variants).delete()
            CartItem.objects.filter(variant__in=variants).delete()
            report["Productos y variantes"] = variants.count()
            variants.delete()
            Product.objects.filter(name__startswith=PREFIX, variants__isnull=True).delete()
            Cart.objects.filter(customer__in=demo_customers()).delete()
            report["Emails en la cola"] = OutboundEmail.objects.filter(
                to__endswith="@" + EMAIL_DOMAIN
            ).delete()[0]
            report["Cuentas de clientes"] = CustomerAccount.objects.filter(
                user__email__endswith="@" + EMAIL_DOMAIN
            ).delete()[0]
            report["Clientes"] = demo_customers().count()
            demo_customers().delete()
            deleted = kept = 0
            for user in demo_users():
                try:
                    with transaction.atomic():
                        user.delete()
                    deleted += 1
                except ProtectedError:
                    # La auditoría no se borra y nombra a este usuario: queda desactivado y sin contraseña.
                    user.is_active = False
                    user.set_unusable_password()
                    user.save(update_fields=["is_active", "password"])
                    user.groups.clear()
                    kept += 1
            report["Usuarios de ensayo borrados"] = deleted
            if kept:
                report["Usuarios desactivados (los nombra la auditoría, que no se borra)"] = kept
            report["Expresos"] = Carrier.objects.filter(name__startswith=PREFIX).delete()[0]
    except ProtectedError as exc:
        raise CommandError(
            "No se borró nada: hay datos que no son de ensayo y dependen de algo de ensayo. "
            "Revisalo con soporte antes de limpiar."
        ) from exc
    return report
