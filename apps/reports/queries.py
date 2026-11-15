"""Consultas de los reportes (M7). Solo lectura: agregan en Postgres, nunca recorren pedidos en Python.

Todas reciben `Filters` (período en hora Argentina y canal) y devuelven dicts/listas listos para la
pantalla y el Excel. Reglas de cálculo: §2 del diseño.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import (
    Coalesce,
    Concat,
    ExtractHour,
    ExtractIsoWeekDay,
    Greatest,
    NullIf,
    TruncDate,
    TruncMonth,
    TruncWeek,
)
from django.utils import timezone

from apps.conversations.models import Question
from apps.inventory.models import StockLevel, Warehouse
from apps.sales import payments, states
from apps.sales.models import ReturnInfo, SalesDocument, SalesLine, Shipment

from .aggregates import Epoch, Percentile
from .filters import TZ, Filters

ORDER = SalesDocument.DocType.ORDER
ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=14, decimal_places=2)
# Siempre el mismo color por canal (paleta accesible, distinguible también en escala de grises).
CHANNEL_COLORS = {
    "tiendanube": "#2563eb",
    "mercadolibre": "#d97706",
    "manual": "#059669",
    "mayorista": "#7c3aed",
}
OTHER_COLOR = "#78716c"
WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip
UNLINKED = "Sin vincular"


def color(code: str) -> str:
    return CHANNEL_COLORS.get(code, OTHER_COLOR)


def _dec(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _doc_q(f: Filters, prefix: str = "", start=None, cancelled: bool = False) -> Q:
    """Pedidos del período (por fecha de alta) y canal. `prefix` = camino al documento."""
    q = Q(
        **{
            f"{prefix}doc_type": ORDER,
            f"{prefix}issued_at__gte": start or f.start_dt,
            f"{prefix}issued_at__lt": f.end_dt,
        }
    )
    if f.channel:
        q &= Q(**{f"{prefix}channel__code": f.channel})
    if not cancelled:
        q &= ~Q(**{f"{prefix}status": states.CANCELLED})
    return q


def sales(f: Filters):
    """Ventas: pedidos no cancelados del período."""
    return SalesDocument.objects.filter(_doc_q(f))


# ── Indicadores ───────────────────────────────────────────────────────────


def _change(current, previous) -> float | None:
    if not previous:
        return None
    return round(float((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100), 1)


def kpis(f: Filters) -> dict:
    """Los 7 indicadores del resumen, con el período anterior de igual duración (4 consultas)."""
    prev = f.previous()
    cur = Q(issued_at__gte=f.start_dt)
    alive = ~Q(status=states.CANCELLED)
    docs = SalesDocument.objects.filter(_doc_q(f, start=prev.start_dt, cancelled=True)).aggregate(
        gross=Sum("total", filter=cur & alive),
        gross_prev=Sum("total", filter=~cur & alive),
        orders=Count("id", filter=cur & alive),
        orders_prev=Count("id", filter=~cur & alive),
        cancelled=Count("id", filter=cur & ~alive),
        cancelled_prev=Count("id", filter=~cur & ~alive),
        net_pending=Count("id", filter=cur & alive & Q(net_pending=True, channel__code="mercadolibre")),
    )
    lcur = Q(document__issued_at__gte=f.start_dt)
    lines = SalesLine.objects.filter(_doc_q(f, "document__", start=prev.start_dt)).aggregate(
        units=Sum("quantity", filter=lcur),
        units_prev=Sum("quantity", filter=~lcur),
        fees=Sum("channel_fee", filter=lcur),
        fees_prev=Sum("channel_fee", filter=~lcur),
    )
    ships = Shipment.objects.filter(_doc_q(f, "document__", start=prev.start_dt)).aggregate(
        cost=Sum("seller_cost", filter=lcur),
        cost_prev=Sum("seller_cost", filter=~lcur),
    )
    returns_qs = ReturnInfo.objects.filter(received_at__gte=prev.start_dt, received_at__lt=f.end_dt)
    if f.channel:
        returns_qs = returns_qs.filter(document__channel__code=f.channel)
    rets = returns_qs.aggregate(
        returns=Count("id", filter=Q(received_at__gte=f.start_dt)),
        returns_prev=Count("id", filter=Q(received_at__lt=f.start_dt)),
    )

    def net(sfx=""):
        return _dec(docs[f"gross{sfx}"]) - _dec(lines[f"fees{sfx}"]) - _dec(ships[f"cost{sfx}"])

    def ticket(sfx=""):
        n = docs[f"orders{sfx}"]
        return (_dec(docs[f"gross{sfx}"]) / n).quantize(Decimal("0.01")) if n else ZERO

    rows = [
        ("gross", "Ventas en bruto", _dec(docs["gross"]), _dec(docs["gross_prev"]), "money", True),
        ("net", "Ventas en neto", net(), net("_prev"), "money", True),
        ("orders", "Pedidos", docs["orders"], docs["orders_prev"], "int", True),
        ("units", "Unidades", Decimal(lines["units"] or 0), Decimal(lines["units_prev"] or 0), "int", True),
        ("ticket", "Ticket promedio", ticket(), ticket("_prev"), "money", True),
        ("cancelled", "Pedidos cancelados", docs["cancelled"], docs["cancelled_prev"], "int", False),
        ("returns", "Devoluciones recibidas", rets["returns"], rets["returns_prev"], "int", False),
    ]
    items = []
    for key, label, value, previous, kind, good_up in rows:
        change = _change(value, previous)
        items.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "previous": previous,
                "kind": kind,
                "change": change,
                # ▲ en verde si subir es bueno (ventas), en rojo si es malo (cancelados, devoluciones).
                "good": None if not change else (change > 0) == good_up,
            }
        )
    return {
        "items": items,
        "by_key": {i["key"]: i for i in items},
        "net_pending": docs["net_pending"],
        "previous": prev,
    }


# ── Series del resumen ────────────────────────────────────────────────────


def bucket_for(f: Filters) -> str:
    if f.days <= 92:
        return "day"
    if f.days <= 366:
        return "week"
    return "month"


def _trunc(bucket: str, field: str):
    if bucket == "day":
        return TruncDate(field, tzinfo=TZ)
    if bucket == "week":
        return TruncWeek(field, tzinfo=TZ)
    return TruncMonth(field, tzinfo=TZ)


def _as_date(value) -> date:
    return value.date() if hasattr(value, "date") and callable(value.date) else value


def _bucket_start(d: date, bucket: str) -> date:
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    if bucket == "month":
        return d.replace(day=1)
    return d


def _bucket_keys(f: Filters, bucket: str) -> list[date]:
    keys, d = [], _bucket_start(f.start, bucket)
    while d <= f.end:
        keys.append(d)
        if bucket == "day":
            d += timedelta(days=1)
        elif bucket == "week":
            d += timedelta(days=7)
        else:
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return keys


def bucket_label(d: date, bucket: str) -> str:
    if bucket == "week":
        return f"Sem. {d:%d/%m}"
    if bucket == "month":
        return f"{MONTHS[d.month - 1].capitalize()} {d.year}"
    return f"{d:%d/%m}"


def sales_by_day(f: Filters) -> dict:
    """Bruto por día (o semana/mes si el período es largo) separado por canal: una consulta."""
    bucket = bucket_for(f)
    rows = (
        sales(f)
        .annotate(k=_trunc(bucket, "issued_at"))
        .values("k", "channel__code", "channel__name")
        .annotate(total=Sum("total"), n=Count("id"))
    )
    keys = _bucket_keys(f, bucket)
    index = {k: i for i, k in enumerate(keys)}
    series: dict[str, dict] = {}
    for r in rows:
        s = series.setdefault(
            r["channel__code"],
            {
                "code": r["channel__code"],
                "name": r["channel__name"],
                "color": color(r["channel__code"]),
                "values": [0.0] * len(keys),
                "total": ZERO,
                "orders": 0,
            },
        )
        i = index.get(_as_date(r["k"]))
        if i is not None:
            s["values"][i] += float(r["total"] or 0)
        s["total"] += _dec(r["total"])
        s["orders"] += r["n"]
    ordered = sorted(series.values(), key=lambda s: s["name"])
    return {
        "bucket": bucket,
        "labels": [bucket_label(k, bucket) for k in keys],
        "series": ordered,
        "empty": not ordered,
    }


def channel_share(f: Filters, by_day: dict | None = None) -> list[dict]:
    """Participación de cada canal en el bruto (reusa la serie por día si ya se calculó)."""
    by_day = by_day or sales_by_day(f)
    total = sum((s["total"] for s in by_day["series"]), ZERO)
    return [
        {
            "code": s["code"],
            "name": s["name"],
            "color": s["color"],
            "total": s["total"],
            "orders": s["orders"],
            "pct": round(float(s["total"] / total * 100), 1) if total else 0.0,
        }
        for s in sorted(by_day["series"], key=lambda s: -s["total"])
    ]


def heatmap(f: Filters) -> dict:
    """Pedidos por día de la semana × hora (hora Argentina): matriz 7×24."""
    rows = (
        sales(f)
        .annotate(dow=ExtractIsoWeekDay("issued_at", tzinfo=TZ), hour=ExtractHour("issued_at", tzinfo=TZ))
        .values("dow", "hour")
        .annotate(n=Count("id"))
    )
    matrix = [[0] * 24 for _ in range(7)]
    for r in rows:
        matrix[r["dow"] - 1][r["hour"]] = r["n"]
    top = max((n for row in matrix for n in row), default=0)
    return {
        "matrix": matrix,
        "max": top,
        "rows": [
            {
                "day": WEEKDAYS[d],
                "total": sum(matrix[d]),
                "cells": [
                    {"hour": h, "count": n, "level": 0 if not n else min(5, 1 + (n * 5 - 1) // top)}
                    for h, n in enumerate(matrix[d])
                ],
            }
            for d in range(7)
        ],
    }


# ── Tabla de ventas ───────────────────────────────────────────────────────

GROUPS = {
    "canal": "Canal",
    "producto": "Producto",
    "variante": "Variante (SKU)",
    "talle": "Talle",
    "color": "Color",
    "dia": "Día",
    "semana": "Semana",
    "mes": "Mes",
}
DOC_GROUPS = {"canal", "dia", "semana", "mes"}  # se agrupan por pedido (bruto = total del pedido)
SORTS = {"clave", "unidades", "pedidos", "bruto", "neto", "precio"}
TIME_BUCKET = {"dia": "day", "semana": "week", "mes": "month"}


def _attr(name: str, prefix: str = "variant__attributes"):
    """Valor de un atributo sin importar mayúsculas en la clave ("talle", "Talle")."""
    keys = [name, name.capitalize(), name.upper()]
    return Coalesce(*[NullIf(KeyTextTransform(k, prefix), Value("")) for k in keys], output_field=CharField())


def _unlinked_label():
    return Concat(
        Value(f"{UNLINKED} ("),
        Coalesce(NullIf(F("sku_snapshot"), Value("")), Value("sin SKU")),
        Value(")"),
        output_field=CharField(),
    )


def _dimension(name: str, default: str):
    return Case(
        When(variant__isnull=True, then=_unlinked_label()),
        default=Coalesce(_attr(name), Value(default)),
        output_field=CharField(),
    )


def default_sort(group_by: str) -> str:
    return "clave" if group_by in TIME_BUCKET else "-bruto"


def _finish(row: dict) -> dict:
    row["bruto"] = _dec(row["bruto"])
    row["neto"] = row["bruto"] - _dec(row.pop("comision", 0)) - _dec(row.pop("envio", 0))
    row["unidades"] = Decimal(row["unidades"] or 0)
    row["precio"] = (row["bruto"] / row["unidades"]).quantize(Decimal("0.01")) if row["unidades"] else ZERO
    return row


def _doc_table(f: Filters, group_by: str) -> list[dict]:
    """Canal y tiempo: bruto = total del pedido y neto descuenta comisiones y envío del vendedor.

    Tres agregados simples (pedidos, líneas y envíos) que se unen por clave en Python.
    """
    if group_by == "canal":

        def key(prefix=""):
            return {"k": F(f"{prefix}channel__code"), "n": F(f"{prefix}channel__name")}
    else:
        bucket = TIME_BUCKET[group_by]

        def key(prefix=""):
            return {"k": _trunc(bucket, f"{prefix}issued_at")}

    docs = sales(f).annotate(**key()).values(*key()).annotate(pedidos=Count("id"), bruto=Sum("total"))
    lines = (
        SalesLine.objects.filter(_doc_q(f, "document__"))
        .annotate(**key("document__"))
        .values("k")
        .annotate(unidades=Sum("quantity"), comision=Sum("channel_fee"))
    )
    ships = (
        Shipment.objects.filter(_doc_q(f, "document__"))
        .annotate(**key("document__"))
        .values("k")
        .annotate(envio=Sum("seller_cost"))
    )
    by_line = {r["k"]: r for r in lines}
    by_ship = {r["k"]: r["envio"] for r in ships}
    rows = []
    for d in docs:
        k = d["k"]
        line = by_line.get(k, {})
        if group_by == "canal":
            label, sort_key = d["n"], d["n"]
        else:
            day = _as_date(k)
            label = f"{day:%d/%m/%Y}" if bucket == "day" else bucket_label(day, bucket)
            if bucket == "week":
                label = f"Semana del {day:%d/%m/%Y}"
            sort_key = day
        rows.append(
            _finish(
                {
                    "clave": label,
                    "sort_key": sort_key,
                    "unidades": line.get("unidades"),
                    "pedidos": d["pedidos"],
                    "bruto": d["bruto"],
                    "comision": line.get("comision"),
                    "envio": by_ship.get(k),
                }
            )
        )
    return rows


def _line_table(f: Filters, group_by: str) -> list[dict]:
    """Producto, variante, talle y color: suman `line_total` (el envío no se reparte entre productos)."""
    qs = SalesLine.objects.filter(_doc_q(f, "document__"))
    measures = {
        "unidades": Sum("quantity"),
        "pedidos": Count("document", distinct=True),
        "bruto": Sum("line_total"),
        "comision": Sum("channel_fee"),
    }
    unlinked_sku = Case(When(variant__isnull=True, then=F("sku_snapshot")), default=Value(""))
    if group_by == "producto":
        qs = qs.annotate(u=unlinked_sku).values("variant__product_id", "variant__product__name", "u")
    elif group_by == "variante":
        qs = qs.annotate(
            u=unlinked_sku,
            talle=Coalesce(_attr("talle"), Value("")),
            color=Coalesce(_attr("color"), Value("")),
        ).values("variant_id", "variant__sku", "variant__product__name", "talle", "color", "u")
    else:
        qs = qs.annotate(k=_dimension(group_by, f"Sin {group_by}")).values("k")
    rows = []
    for r in qs.annotate(**measures):
        row = {m: r[m] for m in measures}
        if group_by in ("producto", "variante"):
            if r["variant_id" if group_by == "variante" else "variant__product_id"] is None:
                row["clave"] = f"{UNLINKED} ({r['u'] or 'sin SKU'})"
                row["unlinked"] = True
            elif group_by == "producto":
                row["clave"] = r["variant__product__name"]
                row["product_id"] = r["variant__product_id"]
            else:
                row["clave"] = r["variant__sku"]
                row["variant_id"] = r["variant_id"]
                row["producto"] = r["variant__product__name"]
                row["talle"] = r["talle"]
                row["color"] = r["color"]
        else:
            row["clave"] = r["k"]
            row["unlinked"] = r["k"].startswith(UNLINKED)
        row["sort_key"] = row["clave"].lower()
        rows.append(_finish(row))
    return rows


def sort_rows(rows: list[dict], order: str) -> list[dict]:
    desc = order.startswith("-")
    field = order.lstrip("-")
    if field not in SORTS:
        field, desc = "bruto", True
    key = (lambda r: r["sort_key"]) if field == "clave" else (lambda r: (r[field], r["sort_key"]))
    return sorted(rows, key=key, reverse=desc)


def sales_table(f: Filters, group_by: str = "canal", order: str | None = None) -> dict:
    if group_by not in GROUPS:
        group_by = "canal"
    order = order or default_sort(group_by)
    rows = _doc_table(f, group_by) if group_by in DOC_GROUPS else _line_table(f, group_by)
    rows = sort_rows(rows, order)
    if group_by in DOC_GROUPS:
        orders = sum(r["pedidos"] for r in rows)
    else:  # un pedido con varios productos cuenta una sola vez en el total
        orders = SalesLine.objects.filter(_doc_q(f, "document__")).values("document").distinct().count()
    bruto = sum((r["bruto"] for r in rows), ZERO)
    unidades = sum((r["unidades"] for r in rows), Decimal(0))
    totals = {
        "unidades": unidades,
        "pedidos": orders,
        "bruto": bruto,
        "neto": sum((r["neto"] for r in rows), ZERO),
        "precio": (bruto / unidades).quantize(Decimal("0.01")) if unidades else ZERO,
    }
    return {"group_by": group_by, "order": order, "rows": rows, "totals": totals}


def add_net_summary(f: Filters, table: dict) -> dict:
    """Por producto, variante, talle o color agrega a los totales el envío del vendedor y el neto del resumen.

    El neto de esas tablas no descuenta el envío (no se reparte entre productos) y por eso no coincide con
    el del resumen: la pantalla y el Excel lo aclaran debajo del total. Mismo cálculo que `kpis` (bruto de
    los pedidos − comisiones − envíos), en dos consultas; las comisiones salen de la propia tabla.
    """
    if table["group_by"] in DOC_GROUPS:
        return table
    totals = table["totals"]
    fees = totals["bruto"] - totals["neto"]
    gross = _dec(sales(f).aggregate(t=Sum("total"))["t"])
    shipping = _dec(Shipment.objects.filter(_doc_q(f, "document__")).aggregate(c=Sum("seller_cost"))["c"])
    totals["envio"] = shipping
    totals["neto_resumen"] = gross - fees - shipping
    return table


# ── Productos ─────────────────────────────────────────────────────────────


def _default_warehouse():
    return Warehouse.objects.filter(is_default=True).first()


def top_products(f: Filters, by: str = "unidades", limit: int = 50) -> dict:
    """Los `limit` productos y variantes más vendidos, con el stock disponible actual (depósito por defecto)."""
    order = "-bruto" if by == "bruto" else "-unidades"
    products = sales_table(f, "producto", order)["rows"][:limit]
    variants = sales_table(f, "variante", order)["rows"][:limit]
    warehouse = _default_warehouse()
    levels = StockLevel.objects.filter(warehouse=warehouse)
    v_ids = [r["variant_id"] for r in variants if r.get("variant_id")]
    v_stock = {
        lv["variant_id"]: lv["on_hand"] - lv["reserved"]
        for lv in levels.filter(variant_id__in=v_ids).values("variant_id", "on_hand", "reserved")
    }
    p_ids = [r["product_id"] for r in products if r.get("product_id")]
    p_stock = {
        lv["variant__product_id"]: (lv["on_hand"] or 0) - (lv["reserved"] or 0)
        for lv in levels.filter(variant__product_id__in=p_ids)
        .values("variant__product_id")
        .annotate(on_hand=Sum("on_hand"), reserved=Sum("reserved"))
    }
    for r in variants:
        r["stock"] = v_stock.get(r.get("variant_id"))
    for r in products:
        r["stock"] = p_stock.get(r.get("product_id"))
    return {"by": "bruto" if by == "bruto" else "unidades", "products": products, "variants": variants}


STOCKOUT_SQL = """
WITH m AS (
    SELECT variant_id, created_at, on_hand_after,
           COALESCE(
               LAG(on_hand_after) OVER (PARTITION BY variant_id ORDER BY created_at, id),
               on_hand_after - quantity
           ) AS before,
           LEAD(created_at) OVER (PARTITION BY variant_id ORDER BY created_at, id) AS next_at
    FROM inventory_stockmovement
    WHERE warehouse_id = %(warehouse)s AND affects = 'on_hand'
      AND on_hand_after IS NOT NULL AND created_at < %(end)s
)
SELECT variant_id,
       COUNT(*) FILTER (WHERE on_hand_after <= 0 AND before > 0 AND created_at >= %(start)s) AS times,
       COALESCE(SUM(EXTRACT(EPOCH FROM
           LEAST(COALESCE(next_at, %(end)s), %(end)s) - GREATEST(created_at, %(start)s)
       )) FILTER (WHERE on_hand_after <= 0 AND COALESCE(next_at, %(end)s) > %(start)s), 0) AS seconds_out
FROM m
GROUP BY variant_id
HAVING COUNT(*) FILTER (WHERE on_hand_after <= 0 AND before > 0 AND created_at >= %(start)s) >= %(min_times)s
"""


def stockouts(f: Filters, min_times: int = 2) -> dict:
    """Variantes que quedaron en 0 al menos `min_times` veces en el período (historial de stock).

    "Se agota" = un movimiento deja el físico en ≤ 0 cuando antes era > 0. "Días sin stock" suma los
    tramos en ≤ 0 dentro del período (hasta ahora si el período incluye hoy).
    """
    from apps.catalog.models import Variant
    from apps.inventory.models import StockMovement

    warehouse = _default_warehouse()
    since = (
        StockMovement.objects.filter(on_hand_after__isnull=False)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    result = {"rows": [], "min_times": min_times, "history_since": None}
    if since is not None:
        result["history_since"] = timezone.localtime(since).date()
    if warehouse is None or since is None:
        return result
    end = min(f.end_dt, timezone.now())
    with connection.cursor() as cursor:
        cursor.execute(
            STOCKOUT_SQL,
            {"warehouse": warehouse.pk, "start": f.start_dt, "end": end, "min_times": max(1, min_times)},
        )
        found = {vid: (times, secs) for vid, times, secs in cursor.fetchall()}
    if not found:
        return result
    variants = Variant.objects.filter(pk__in=found).select_related("product")
    sold = dict(
        SalesLine.objects.filter(_doc_q(f, "document__"), variant_id__in=found)
        .values("variant_id")
        .annotate(u=Sum("quantity"))
        .values_list("variant_id", "u")
    )
    stock = {
        lv["variant_id"]: lv["on_hand"] - lv["reserved"]
        for lv in StockLevel.objects.filter(warehouse=warehouse, variant_id__in=found).values(
            "variant_id", "on_hand", "reserved"
        )
    }
    from apps.catalog.attributes import attributes_text

    rows = []
    for v in variants:
        times, secs = found[v.pk]
        rows.append(
            {
                "variant_id": v.pk,
                "sku": v.sku,
                "producto": v.product.name,
                "atributos": attributes_text(v.attributes),
                "veces": times,
                "dias_sin_stock": round(float(secs) / 86400, 1),
                "vendidas": Decimal(sold.get(v.pk) or 0),
                "stock": stock.get(v.pk),
            }
        )
    result["rows"] = sorted(rows, key=lambda r: (-r["veces"], -r["dias_sin_stock"], r["sku"]))
    return result


# ── Operación ─────────────────────────────────────────────────────────────


def _time_stats(seconds: str = "secs", **limits) -> dict:
    """Agregados: cantidad, mediana, p90 y cuántos quedan por debajo de cada límite (segundos)."""
    return {
        "n": Count("id"),
        "p50": Percentile(seconds, 0.5),
        "p90": Percentile(seconds, 0.9),
        **{name: Count("id", filter=Q(**{f"{seconds}__lt": secs})) for name, secs in limits.items()},
    }


def _hours(seconds) -> float | None:
    return None if seconds is None else round(seconds / 3600, 1)


def _shape(row: dict, limits: dict) -> dict:
    n = row["n"]
    out = {"n": n, "mediana_h": _hours(row["p50"]), "p90_h": _hours(row["p90"])}
    for name in limits:
        out[name] = round(row[name] * 100 / n, 1) if n else None
    return out


def response_times(f: Filters) -> dict:
    """Tiempo de respuesta a preguntas de ML respondidas en el período (general y por persona)."""
    if f.channel and f.channel != "mercadolibre":
        return {"available": False}
    limits = {"pct_1h": 3600, "pct_12h": 12 * 3600}
    qs = Question.objects.filter(
        answered_at__gte=f.start_dt, answered_at__lt=f.end_dt, asked_at__isnull=False
    )
    qs = qs.annotate(secs=Greatest(Epoch(F("answered_at") - F("asked_at")), Value(0.0)))
    measures = _time_stats(**limits)
    overall = _shape(qs.aggregate(**measures), limits)
    people = [
        {"persona": r["answered_by__full_name"] or r["answered_by__email"], **_shape(r, limits)}
        for r in qs.filter(answered_by__isnull=False)
        .values("answered_by", "answered_by__full_name", "answered_by__email")
        .annotate(**measures)
        .order_by("answered_by__full_name")
    ]
    return {"available": True, "overall": overall, "people": people}


def _dispatched(f: Filters):
    qs = SalesDocument.objects.filter(
        doc_type=ORDER, dispatched_at__gte=f.start_dt, dispatched_at__lt=f.end_dt
    ).exclude(status=states.CANCELLED)
    if f.channel:
        qs = qs.filter(channel__code=f.channel)
    return qs


def dispatch_times(f: Filters) -> dict:
    """Desde Nuevo (pago confirmado) hasta Despachado / Listo para retirar. Excluye Full (despacha ML)."""
    full = Shipment.objects.filter(document=OuterRef("pk"), method=Shipment.Method.ME_FULL)
    method = Shipment.objects.filter(document=OuterRef("pk")).order_by("id").values("method")[:1]
    qs = (
        _dispatched(f)
        .exclude(Exists(full))
        .annotate(
            secs=Greatest(Epoch(F("dispatched_at") - Coalesce("ready_at", "issued_at")), Value(0.0)),
            metodo=Coalesce(Subquery(method), Value("")),
        )
    )
    limits = {}
    measures = _time_stats()
    labels = dict(Shipment.Method.choices)
    by_channel = [
        {"clave": r["channel__name"], **_shape(r, limits)}
        for r in qs.values("channel__name").annotate(**measures).order_by("channel__name")
    ]
    by_method = [
        {"clave": labels.get(r["metodo"], r["metodo"] or "Sin envío"), **_shape(r, limits)}
        for r in qs.values("metodo").annotate(**measures).order_by("metodo")
    ]
    return {
        "overall": _shape(qs.aggregate(**measures), limits),
        "by_channel": by_channel,
        "by_method": by_method,
    }


def flex_on_time(f: Filters, now=None) -> dict:
    """Flex y Colecta con fecha límite en el período: a tiempo, tarde y vencidos sin despachar.

    El período se toma por fecha límite (no por fecha de despacho). Cuenta como tarde lo despachado
    después de la fecha límite y lo que venció y sigue sin despachar (no cancelado); la demora de
    estos se mide hasta ahora. Los que todavía no vencieron y no salieron no cuentan.
    """
    now = now or timezone.now()
    qs = Shipment.objects.filter(
        method__in=[Shipment.Method.ME_FLEX, Shipment.Method.ME_COLECTA],
        document__doc_type=ORDER,
        dispatch_deadline__gte=f.start_dt,
        dispatch_deadline__lt=f.end_dt,
    ).exclude(document__status=states.CANCELLED)
    if f.channel:
        qs = qs.filter(document__channel__code=f.channel)
    on_time_q = Q(document__dispatched_at__lte=F("dispatch_deadline"))
    # Sin fecha de despacho pero ya despachado/entregado (datos viejos): no se sabe, no cuenta.
    pending_q = Q(document__dispatched_at__isnull=True) & ~Q(
        document__status__in=[states.DISPATCHED, states.READY_FOR_PICKUP, states.DELIVERED]
    )
    late_q = Q(document__dispatched_at__gt=F("dispatch_deadline")) | (
        pending_q & Q(dispatch_deadline__lt=now)
    )
    agg = qs.aggregate(on_time=Count("id", filter=on_time_q), late=Count("id", filter=late_q))
    labels = dict(Shipment.Method.choices)
    late = []
    for s in (
        qs.filter(late_q)
        .values(
            "document_id",
            "document__channel_reference",
            "document__number",
            "method",
            "dispatch_deadline",
            "document__dispatched_at",
        )
        .order_by("-dispatch_deadline", "-id")
    ):
        out = s["document__dispatched_at"]
        delay = (out or now) - s["dispatch_deadline"]
        late.append(
            {
                "document_id": s["document_id"],
                "pedido": s["document__channel_reference"] or f"Pedido #{s['document__number']}",
                "modalidad": labels.get(s["method"], s["method"]),
                "limite": s["dispatch_deadline"],
                "despachado": out,
                "sin_despachar": out is None,
                "demora_h": round(delay.total_seconds() / 3600, 1),
            }
        )
    total = agg["on_time"] + agg["late"]
    return {
        "total": total,
        "on_time": agg["on_time"],
        "late_count": agg["late"],
        "pending_count": sum(1 for r in late if r["sin_despachar"]),
        "pct": round(agg["on_time"] * 100 / total, 1) if total else None,
        "late": late,
    }


def manual_pending(today: date | None = None) -> dict:
    """Pedidos manuales sin cobrar o sin facturar a la fecha (no depende del período)."""
    today = today or timezone.localdate()
    docs = (
        payments.annotate_paid(
            SalesDocument.objects.filter(channel__code="manual", doc_type=ORDER).exclude(
                status=states.CANCELLED
            )
        )
        .filter(~payments.paid_q() | Q(invoiced_in_contabilium=False))
        .select_related("channel", "customer")
        .order_by("issued_at")
    )
    rows = []
    for d in docs:
        missing = []
        if not payments.is_paid(d):
            missing.append("sin cobrar")
        if not d.invoiced_in_contabilium:
            missing.append("sin facturar")
        rows.append(
            {
                "document_id": d.pk,
                "pedido": d.channel_reference or str(d),
                "cliente": str(d.customer) if d.customer else "",
                "fecha": timezone.localtime(d.issued_at),
                "dias": (today - timezone.localtime(d.issued_at).date()).days,
                "total": d.total,
                "falta": " y ".join(missing).capitalize(),
                "estado": states.label(d.status),
            }
        )
    return {"rows": rows, "count": len(rows), "total": sum((r["total"] for r in rows), ZERO)}


# ── Mayorista (M8a · US-9) ────────────────────────────────────────────────


def _wholesale_q(f: Filters) -> Q:
    """Pedidos mayoristas del período, sin cancelados (el filtro de canal no aplica: siempre mayorista)."""
    return Q(
        doc_type=ORDER,
        channel__code="mayorista",
        issued_at__gte=f.start_dt,
        issued_at__lt=f.end_dt,
    ) & ~Q(status=states.CANCELLED)


def wholesale(f: Filters, today: date | None = None) -> dict:
    """Pestaña Mayorista: ventas por cliente y por quién cargó, pendientes y saldos a favor (6 consultas)."""
    from apps.wholesale.models import CustomerBalance, WholesaleOrder

    today = today or timezone.localdate()
    base = SalesDocument.objects.filter(_wholesale_q(f))
    by_customer = list(
        base.values("customer_id", "customer__legal_name", "customer__trade_name")
        .annotate(n_docs=Count("id"), net_sum=Sum("subtotal"), gross_sum=Sum("total"))
        .order_by("-gross_sum", "customer__legal_name")
    )
    customers = [
        {
            "clave": r["customer__trade_name"] or r["customer__legal_name"] or "Sin cliente",
            "pedidos": r["n_docs"],
            "neto": _dec(r["net_sum"]),
            "total": _dec(r["gross_sum"]),
        }
        for r in by_customer
    ]
    by_seller = list(
        base.values("wholesale__on_behalf", "wholesale__placed_by__full_name", "wholesale__placed_by__email")
        .annotate(n_docs=Count("id"), net_sum=Sum("subtotal"), gross_sum=Sum("total"))
        .order_by("-gross_sum")
    )
    customer_row = {"clave": "El cliente (en la tienda)", "pedidos": 0, "neto": ZERO, "total": ZERO}
    sellers = []
    for r in by_seller:
        if not r["wholesale__on_behalf"]:
            customer_row["pedidos"] += r["n_docs"]
            customer_row["neto"] += _dec(r["net_sum"])
            customer_row["total"] += _dec(r["gross_sum"])
            continue
        name = r["wholesale__placed_by__full_name"] or r["wholesale__placed_by__email"] or "Sin dato"
        sellers.append(
            {"clave": name, "pedidos": r["n_docs"], "neto": _dec(r["net_sum"]), "total": _dec(r["gross_sum"])}
        )
    if customer_row["pedidos"]:
        sellers.append(customer_row)
    sellers.sort(key=lambda r: r["total"], reverse=True)

    def rows(qs, kind):
        out = []
        for o in qs.select_related("document__customer").order_by("document__issued_at"):
            d = o.document
            out.append(
                {
                    "document_id": d.pk,
                    "pedido": d.channel_reference or str(d),
                    "cliente": str(d.customer) if d.customer else "",
                    "fecha": timezone.localtime(d.issued_at),
                    "dias": (today - timezone.localtime(d.issued_at).date()).days,
                    "total": d.total,
                    "vence": o.expires_at,
                    "estado": states.label(d.status),
                    "tipo": kind,
                }
            )
        return out

    orders = WholesaleOrder.objects.filter(document__doc_type=ORDER)
    awaiting = rows(orders.filter(document__status=states.AWAITING_PAYMENT), "Esperando pago")
    # Vencidos: transferencias canceladas por el sistema al vencer el plazo, dentro del período.
    expired = rows(
        orders.filter(
            expired_at__isnull=False,
            document__issued_at__gte=f.start_dt,
            document__issued_at__lt=f.end_dt,
        ),
        "Vencido",
    )
    not_invoiced = rows(
        orders.filter(document__invoiced_in_contabilium=False).exclude(
            document__status__in=[states.CANCELLED, states.AWAITING_PAYMENT]
        ),
        "Sin facturar",
    )
    balances = list(
        CustomerBalance.objects.values("customer_id", "customer__legal_name", "customer__trade_name")
        .annotate(saldo=Sum("amount"))
        .filter(saldo__gt=0)
        .order_by("-saldo")
    )
    balance_rows = [
        {"clave": r["customer__trade_name"] or r["customer__legal_name"], "saldo": _dec(r["saldo"])}
        for r in balances
    ]

    def total(items, key="total"):
        return sum((i[key] for i in items), ZERO)

    return {
        "customers": customers,
        "customers_total": {
            "pedidos": sum(r["pedidos"] for r in customers),
            "neto": total(customers, "neto"),
            "total": total(customers),
        },
        "sellers": sellers,
        "awaiting": awaiting,
        "expired": expired,
        "not_invoiced": not_invoiced,
        "balances": balance_rows,
        "balances_total": total(balance_rows, "saldo"),
    }
