"""Estados del pedido en palabras del cliente (US-6, §8).

Lo interno («Esperando cliente», «Listo») no le dice nada al cliente: se traduce a lo que le importa.
"""

from apps.sales import states

CLIENT_STATUS = {
    states.AWAITING_PAYMENT: ("Esperando tu pago", "wait"),
    states.NEW: ("En preparación", "info"),
    states.PREPARING: ("En preparación", "info"),
    states.READY: ("En preparación", "info"),
    states.AWAITING_CUSTOMER: ("Esperando tu respuesta", "wait"),
    states.DISPATCHED: ("Despachado", "ok"),
    states.READY_FOR_PICKUP: ("Listo para retirar", "ok"),
    states.DELIVERED: ("Entregado", "ok"),
    states.CANCELLED: ("Cancelado", "off"),
    states.CLAIM: ("En revisión", "wait"),
}


def client_status(status: str) -> str:
    return CLIENT_STATUS.get(status, ("En preparación", "info"))[0]


def client_tone(status: str) -> str:
    return CLIENT_STATUS.get(status, ("", "info"))[1]
