# Auditoría M8a, tienda mayorista (2026-11-15)

Revisión de seguridad, montos y casos borde. Probé con tests armados a mano: producto inexistente, variante sin precio mayorista, saldo a favor mayor que el pedido, faltante pagado, escape de datos en emails, redirección del ingreso.

**Lo que está bien:**

- **Accesos.** Cada pedido, comprobante y carrito se busca filtrando por el cliente: el de otro cliente da 404. Los clientes no entran al panel. El vendedor "en nombre de" solo actúa sobre clientes aprobados.
- **Montos.**
  - Una variante sin precio mayorista no entra al carrito aunque se fuerce el formulario.
  - El saldo a favor mayor que el pedido deja el total en $0 y conserva el resto del saldo.
  - El saldo no se puede gastar dos veces: el checkout bloquea el carrito del cliente.
  - El crédito por faltante incluye el IVA ($10.000 neto → $12.100).
- **Seguridad de formularios y emails.**
  - Los datos del cliente se escapan en los emails (no se puede inyectar HTML).
  - El ingreso no redirige a sitios externos (`?next=https://…` vuelve a la tienda).

## Hallazgos

| # | Gravedad | Hallazgo | Corrección |
|---|---|---|---|
| T1 | **Media-alta** | **Pedido pagado entero con saldo a favor queda trabado.** Si el saldo cubre todo, el pedido por transferencia queda "Esperando pago" por $0. Nadie va a subir un comprobante, así que a los 3 días se cancela solo. | Si el total queda en $0, el pedido pasa directo a **Nuevo** con el pago confirmado ("Pagado con saldo a favor"), sin vencimiento ni pedido de comprobante. La pantalla de confirmación lo explica. |
| T2 | **Media** | **Emails viejos cuando se configure el correo.** Mientras no hay SMTP, los emails se acumulan. El día que se configure, la cola manda todos, incluidos avisos que ya no sirven: "tu pago vence mañana" de hace semanas, "pedido despachado" ya entregado. | Al enviar, descartar (estado "vencido, no enviado") los emails de más de 72 h (configurable, `STORE_EMAIL_MAX_AGE_HOURS`). No vencen nunca `registration_approved` ni `registration_rejected`, que siguen siendo útiles. En el panel de emails se ve cuántos se descartaron. |
| T3 | **Media** | **Reserva que nunca se libera si nadie marca "Facturado".** La reserva se mantiene hasta marcar "Facturado en Contabilium" (decisión de diseño). Si alguien se olvida, ese stock queda descontado de la tienda para siempre y la mayorista muestra menos disponible del real. El aviso de "manual sin facturar" de M4 no incluye a los mayoristas. | Extender la alerta `orders.manual_pending` (pedidos sin cobrar o sin facturar hace más de 24 h) a los pedidos mayoristas confirmados. Agregar a "Reportes › Mayorista" el total de unidades reservadas por pedidos sin facturar. |
| T4 | Baja | **Error 500 al agregar al carrito un producto que no existe** (`/mayorista/producto/<id>/agregar/` con un id inválido, por ejemplo un enlace viejo después de borrar un producto). | Devolver 404, la página "no encontrado" de la tienda. |
