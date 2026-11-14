"""Señales de ventas para que otros módulos reaccionen sin que `sales` dependa de ellos.

`order_status_changed(sender=SalesDocument, document, old, new, system)` la envía
`states.change_status` después del commit, una vez por cada cambio real de estado.
"""

from django.dispatch import Signal

order_status_changed = Signal()
