"""Señales de ventas para que otros módulos reaccionen sin que `sales` dependa de ellos.

`order_status_changed(sender=SalesDocument, document, old, new, system)` la envía
`states.change_status` después del commit, una vez por cada cambio real de estado.

`order_invoice_changed(sender=SalesDocument, document, invoiced, user)` la envía `manual.update_invoice`
dentro de la misma transacción (M8: marcar "Facturado en Contabilium" libera la reserva mayorista).
"""

from django.dispatch import Signal

order_status_changed = Signal()
order_invoice_changed = Signal()
