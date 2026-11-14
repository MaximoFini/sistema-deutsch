from django import template

from apps.sales import states
from apps.sales.models import Shipment

register = template.Library()

FAMILY_CLASSES = {
    "flow": "bg-sky-100 text-sky-900",
    "special": "bg-amber-100 text-amber-900",
    "final": "bg-stone-200 text-stone-700",
}


@register.filter
def status_label(status: str) -> str:
    return states.label(status)


@register.filter
def status_classes(status: str) -> str:
    if status == states.DELIVERED:
        return "bg-emerald-100 text-emerald-900"
    if status == states.CANCELLED:
        return "bg-red-100 text-red-800"
    return FAMILY_CLASSES.get(states.FAMILY.get(status, "flow"), FAMILY_CLASSES["flow"])


@register.filter
def ship_label(method: str) -> str:
    return Shipment.Method(method).label if method in Shipment.Method.values else (method or "—")


@register.filter
def is_paid(order) -> bool:
    return order.total <= 0 or (order.paid_amount or 0) >= order.total


@register.filter
def lines_summary(order) -> str:
    lines = list(order.lines.all())
    if not lines:
        return "—"
    qty = lines[0].quantity.normalize() if hasattr(lines[0].quantity, "normalize") else lines[0].quantity
    first = f"{qty:f}× {lines[0].sku_snapshot or lines[0].description_snapshot[:30]}"
    return first + (f" +{len(lines) - 1}" if len(lines) > 1 else "")


@register.filter
def address_text(address) -> str:
    """Domicilio legible para los formatos de TN ({address, number, city…}), ML ({address_line, city:{name}})
    y pedidos manuales."""
    if not isinstance(address, dict):
        return ""
    street = address.get("address_line") or " ".join(
        str(address.get(k) or "") for k in ("address", "number") if address.get(k)
    )
    floor = address.get("floor")
    city = address.get("city")
    if isinstance(city, dict):
        city = city.get("name")
    province = address.get("province")
    if isinstance(province, dict):
        province = province.get("name")
    parts = [
        street + (f" {floor}" if floor else ""),
        address.get("locality"),
        city,
        province,
        address.get("zipcode"),
    ]
    return ", ".join(str(p) for p in parts if p)
