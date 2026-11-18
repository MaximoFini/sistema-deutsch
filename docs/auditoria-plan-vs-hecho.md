# Auditoría del proyecto: lo planificado contra lo hecho (2026-11-18)

Se compararon los 67 tickets de Plane (DDEV-1 a 67), el PRD y los specs con el código, los datos reales cargados en la base local y el estado de los canales. Hay 832+ tests pasando y el CI está en verde.

## Resumen

- **El código de la fase 1 está completo salvo M9 y la etapa B de la tienda mayorista.** M0 a M8a están construidos y auditados.
- **Lo que falta casi todo depende de terceros o de decisiones tuyas**, no de programar: ninguna integración corrió nunca contra una cuenta real (Tiendanube, Mercado Libre, Contabilium) y no hay servidor.
- **Ese es el mayor riesgo del proyecto.** Todo el código de canales se probó contra APIs simuladas. Hasta que no se conecten las cuentas reales, hay supuestos sin comprobar (campos de ML, comisiones, Envío Nube, errores reales).

## Estado por módulo

| Módulo | Código | Qué falta para cerrarlo |
|---|---|---|
| M0 Base | Completo | Servidor, SMTP y Sentry (DDEV-3, 7, 8): no hay hosting contratado ni correo saliente. |
| M1 Tiendanube | Completo (simulado) | Crear la app en Partners y probar con la tienda real (DDEV-10 a 13). Spike de Envío Nube (DDEV-14). |
| M2 Mercado Libre | Completo (simulado) | Crear la app en ML Developers, autorizar con la cuenta de Deutsch y probar (DDEV-15 a 22). Spike de convivencia con Contabilium (DDEV-23). |
| M3 Catálogo | Completo | Con datos reales cargados: ver «Calidad de datos». |
| M4 Pedidos | Completo | Nada propio; depende de que entren pedidos reales. |
| M5 Preparación | Completo | Probar con la impresora térmica real (DDEV-33). |
| M6 Operación ML | Completo (simulado) | Probar con la cuenta real (DDEV-36 a 39). Edición masiva (DDEV-40) espera el spike DDEV-23. |
| M7 Reportes | Completo | Validar el neto de ML con la cuenta real (DDEV-41). |
| M8a Tienda mayorista | Completo | Validar la marca (DDEV-43), cargar banco, términos y privacidad. |
| M8b Tienda mayorista, etapa B | **No empezado** | Integración Ecommerce de Contabilium (44, 47, 52), ARCA (45), subdominio y SSL (46), margen de seguridad (55). Dependen de Contabilium, de ARCA y del servidor. |
| M9 Lanzamiento | **Parcial** | Ver más abajo. |
| Futuro (F-01 a F-08) | Fuera de la fase 1 | Facturación, compras, tesorería, impuestos, POS. Planificado para después. |

## M9: qué está hecho y qué falta

| Ticket | Estado real |
|---|---|
| DDEV-56 Historial de 12 meses | **Hecho para TiendaQuick** (2.022 pedidos, incluidos los de ML). No se importó el historial de ML por API: eso aportaría comisión y costo de envío reales de ese período, que hoy faltan en 1.211 ventas de ML. |
| DDEV-57 Prueba punta a punta | **No hecho.** Falta el guion por rol y la prueba automática de todo el circuito. |
| DDEV-58 Importar e invitar | **Hecho hasta el envío**: 582 cuentas listas, 60 sin cuenta. El envío está apagado y no hay correo configurado. |
| DDEV-59 Lanzamiento | **No hecho.** Falta la pantalla de control de lanzamiento, el interruptor de tienda abierta y cerrada, el resumen diario de la primera semana y el checklist de salida. |

## Faltantes que bloquean el lanzamiento

Ninguno se resuelve programando. Todos hay que conseguirlos:

1. **Servidor, dominio y correo**: Hetzner, `mayoristas.deutsch.com.ar` con SSL, SMTP, Sentry. Hasta entonces, el sistema solo corre en tu computadora.
2. **Apps de Tiendanube y Mercado Libre** creadas y autorizadas por el dueño de la cuenta de Deutsch.
3. **Textos legales y bancarios de la tienda**: términos de venta, política de privacidad y datos bancarios están vacíos en la configuración. Sin eso, los clientes no pueden aceptar términos ni saber dónde transferir.
4. **Texto del email de invitación**: es una propuesta mía; Deutsch debe revisarlo.
5. **Validación de la marca** en `/mayorista/estilo/` (DDEV-43).
6. **Repositorio público**: GitHub tiene el código y el logo de Deutsch a la vista. Conviene hacerlo privado antes de cargar nada sensible.

## Calidad de datos (base local con datos reales)

| Hallazgo | Cantidad | Qué hacer |
|---|---|---|
| Códigos de Contabilium sin producto en el sistema | 29 (por ejemplo 474, 359, 494-TALLE-10) | Revisar si son productos viejos o con otro código en Tiendanube; vincular a mano desde la pantalla de vinculación. |
| Productos «personalizados» sin SKU | 16, inactivos | Decisión pendiente desde antes (DDEV-12): presupuesto por WhatsApp. |
| Variantes activas sin stock | 318 de 734 | Es el stock real de Contabilium; los negativos quedaron en 0. Confirmar con Deutsch que es correcto. |
| Variantes sin precio minorista | 12 | Completar en Contabilium. |
| Variantes sin peso | 13 | Completar (necesario para envíos). |
| Productos activos sin foto | 2 | Cargar. |
| Clientes mayoristas sin email | 2 | Completar en Contabilium. |
| Clientes con CUIT o documento inválido | 58 | Corregir en Contabilium; después se corre `invitar_mayoristas preparar` otra vez. |
| Emails con errores de tipeo evidentes (`hotmaill.com`, `gmail.com.ar`) | Hay varios | Revisar la lista antes de invitar; «Corregir email» está en la pantalla. |
| Pedidos mayoristas históricos sin cliente asociado | 272 de 368 | TiendaQuick solo exporta el nombre y muchos son personas. Los reportes por cliente están incompletos para ese período. |
| Líneas de pedidos históricos sin producto | 565 de 8.299 | Variantes que ya no existen; conservan SKU y descripción. |
| Precio mayorista cargado en Contabilium | Salió de un archivo de Drive del 8/11 | Si cambiaron precios desde entonces, hay que actualizarlo. |
| Pedidos pendientes de pago en el historial | 388 | Quedan como «esperando pago», fieles a TiendaQuick. Los reportes de cobranza los muestran. |

## Lo que encontré hoy y corregí

- **Catálogo oculto:** de 750 variantes solo 15 estaban activas, porque la tienda de Tiendanube todavía está cerrada y el snapshot venía todo oculto. La tienda mayorista habría salido sin productos reales. Ahora lo que Contabilium tiene «Activo» queda activo: 285 productos y 734 variantes.
- **Interruptor de envío:** el envío de invitaciones solo se podía prender con una variable del servidor. Ahora hay un interruptor en el panel.

## Riesgos técnicos que quedan anotados

- Los upserts de ML y Tiendanube sobre un pedido histórico no están bloqueados: podrían emitir una alerta de SKU desconocido si ML reenvía un pedido viejo.
- El enlace de invitación queda guardado dentro del email en la cola. Solo lo ve quien tenga acceso directo a la base.
- La corrección de un email desde el panel puede ser pisada si Contabilium se vuelve a sincronizar.
- Los datos reales viven solo en tu base local. No hay copia hasta que exista el servidor con backups.

## Plane desactualizado

DDEV-56 pasó a «En curso» (ya tiene trabajo hecho). DDEV-58 sigue en «Todo» aunque tiene trabajo hecho: Plane devolvió un error de permiso (403) al editarlo y hay que moverlo a mano. DDEV-41 y 43 siguen «En curso» esperando validaciones externas.

## Orden sugerido

1. Decidir y pedir lo externo, que es lo que más tarda: apps de TN y ML, servidor, dominio, SMTP.
2. Cargar banco, términos y privacidad, y revisar el email de invitación.
3. Terminar M9: guion de prueba punta a punta, control de lanzamiento, interruptor de tienda y checklist.
4. Con las cuentas reales conectadas: probar y cerrar los tickets «En curso».
5. Etapa B de la mayorista (Contabilium Ecommerce, ARCA).
