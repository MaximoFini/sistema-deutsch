# Auditoría M4–M5 (2026-11-14)

Revisión de M5 (preparación y despacho) y de cómo se integra con M4 (centro de pedidos), después de la auditoría M0–M4.

## Bugs y errores de lógica

| # | Gravedad | Hallazgo | Corrección |
|---|---|---|---|
| L1 | Alta | Si el pedido sale por el canal y nadie lo marca en el sistema, queda en Nuevo, En preparación o Listo para siempre. Pasa en dos casos: en Flex, el repartidor escanea la etiqueta y Mercado Libre informa `shipped`; en Envío Nube, la etiqueta se imprime y despacha desde el admin de Tiendanube. Consecuencias: el aviso de Flex por vencer salta aunque el paquete ya salió, el pedido queda colgado en Despacho y la tanda nunca se cierra. | Regla nueva en `sales/sync._target`, después de cancelado/entregado/reclamo: si el canal dice despachado (ML: algún envío en `shipped`; TN: `shipping_status` `shipped`) y el estado es Nuevo, En preparación, Listo o Esperando cliente → **Despachado**, con motivo "Despachado según «canal»". Si el envío es retiro en local → Listo para retirar. Es un cambio de sistema: no escribe en Tiendanube y la tanda lo toma como resuelto por la señal. |
| L2 | Media | La etiqueta de ML queda guardada la primera vez y no se vuelve a pedir nunca. Si Mercado Libre cambia el envío (domicilio, logística o reprogramación), al reimprimir sale la etiqueta vieja. | En `mercadolibre/shipments.refresh`, si cambian el domicilio, el `logistic_type` o el número de seguimiento, borrar los archivos de etiqueta guardados (PDF y ZPL) para que se pidan de nuevo. |
| L3 | Media | Doble clic en "Armar tanda" o en un botón de Despacho: la segunda vez aparece un error confuso ("No se armó la tanda: ningún pedido se podía preparar" aunque sí se armó, o "ahora está «Despachado»"). | Deshabilitar el botón al enviar ("Armando…", "Guardando…") en Preparar, Despacho, Sacar de la tanda y el formulario de rótulo. |
| L4 | Media | El rótulo propio se puede hacer para cualquier envío, incluso de Mercado Libre: pisa el `carrier_name` que trae ML. | Permitir el rótulo solo para envíos por Transporte u Otro. Si no, mostrar "Este pedido no lleva rótulo propio: …" según el caso. |
| L5 | Baja | Un pedido de la tanda que pasa a Con reclamo o Esperando cliente deja la tanda abierta sin explicación. | En el detalle de la tanda, marcar esos pedidos como "Frenado: «estado»" con el botón para sacarlo de la tanda. |
| L6 | Baja | Preparar muestra como máximo 300 pedidos y Despacho 500, sin avisar que hay más. | Avisar "Se muestran los primeros N de M. Usá los filtros." |
| L7 | Baja | Se puede despachar un pedido de ML o de transporte sin haber impreso la etiqueta o el rótulo, y no hay ninguna señal. | En Despacho, junto a cada pedido de ML o transporte, una marca "Etiqueta sin imprimir" o "Rótulo sin imprimir". Es solo un aviso visual: no bloquea. |
| L8 | Baja | Se pueden marcar más de 60 pedidos en Preparar y el error recién aparece al enviar. | En la página, cuando se pasa del tope, deshabilitar el botón y mostrar "Máximo 60 por tanda". El servidor mantiene su validación. |

## Mensajes

| # | Hallazgo | Corrección |
|---|---|---|
| M1 | Excluidos con motivo técnico de `change_status` (por ejemplo "No se puede pasar de «X» a «Y»"). | Traducir a "ya no está Nuevo (ahora: «X»)" cuando corresponda. |
| M2 | En Despacho, "No se pudieron avanzar N: ref (ahora está «Despachado»)": no dice qué hacer. | Agregar "Actualizá la página para ver el estado actual." cuando el motivo es un cambio de estado. |

## Rendimiento (medido con 3.000 pedidos)

| Operación | Resultado |
|---|---|
| Preparar (hasta 300 pedidos) | 0,21 s, 8 consultas |
| Despacho (hasta 500 pedidos) | 0,52 s, 9 consultas |
| Armar tanda de 60 pedidos | 0,37 s |
| PDF de doble control, 60 pedidos | 0,37 s (requisito < 3 s) |
| Detalle de tanda, 60 pedidos | 0,10 s, 11 consultas |
| Despacho en lote, 60 pedidos | 0,36 s |

No hace falta optimizar nada. Solo se agrega el aviso de L6.

## A verificar en el spike de Envío Nube (DDEV-14), no se cambia ahora

- Al marcar Despachado en el sistema un pedido de Envío Nube, se escribe `DISPATCHED` en Tiendanube. Hay que confirmar con la tienda real que no choca con el flujo de Envío Nube (que despacha desde el admin de TN). Si choca, se saltea la escritura para ese método.
