# Requirements: Cierre y lanzamiento (módulo M9)

**Status:** Draft, esperando aprobación (2026-11-17)
**Tickets:** DDEV-56 (M9-01), DDEV-57 (M9-02), DDEV-58 (M9-03), DDEV-59 (M9-04).
**Depende de:** M0 a M8a terminados. Lo que depende de terceros (apps de ML y TN, servidor, subdominio, SMTP, export real de Contabilium) queda como checklist, no como código.

## Summary

M9 deja el sistema listo para abrir. Se construye todo lo que no depende de terceros, probado con datos simulados, y se documenta lo que falta con un paso a paso para cada cosa.

1. **Histórico de pedidos (US-1):** importar 12 meses de pedidos de Mercado Libre (por API) y de TiendaQuick (desde un archivo de respaldo) como históricos, para que los reportes comparen contra el año anterior.
2. **Prueba punta a punta (US-2):** guion de prueba para usuarios reales y una prueba automática que recorre el circuito completo.
3. **Clientes mayoristas existentes (US-3):** importar la lista depurada, ya aprobados, con cuenta corriente donde corresponda, y mandar la invitación para crear la contraseña.
4. **Lanzamiento (US-4):** checklist de salida, pantalla de control de lanzamiento y monitoreo reforzado la primera semana.

## Goals

- Que el día del lanzamiento no haya carga manual de clientes ni de historia.
- Que el histórico nunca ensucie la operación: ni preparación, ni alertas, ni stock, ni emails.
- Que se pueda ensayar el lanzamiento completo (importar, invitar, comprar) sin mandar un solo email real ni tocar un canal.
- Que quede escrito, paso por paso, qué hace cada persona el día de la salida y cómo se vuelve atrás.

## Non-goals

- **Configurar el servidor, el DNS y el SMTP:** ya están preparados en `deploy/`, se hacen cuando exista el servidor (M8-04, DDEV-7).
- **Importar el histórico de Tiendanube:** los pedidos de TN entran por la integración de M1 (la API da el historial); acá solo se cubre ML y TiendaQuick.
- **Reconstruir stock o pagos del histórico:** el histórico es de lectura, no mueve inventario ni cuenta corriente.
- **Piloto con unos pocos clientes:** decisión previa, la mayorista se abre a todos el mismo día.

## User stories

### US-1 Histórico de pedidos (DDEV-56)

Como administrador, quiero importar los pedidos de los últimos 12 meses para comparar las ventas de este año contra el anterior.

- **R1.1** Pedidos de ML de los últimos 12 meses, traídos por API con el cliente de M2, paginando y retomando si se corta.
- **R1.2** Pedidos de TiendaQuick desde un archivo (Excel o CSV) con las columnas mapeadas por configuración. El importador acepta el archivo, muestra una vista previa con filas válidas y con error y recién ahí importa.
- **R1.3** Los pedidos quedan marcados como históricos (`SalesDocument.is_historical`). Un histórico:
  - no aparece en preparación, en la bandeja de pendientes ni en el centro de pedidos activo (se ve con un filtro explícito);
  - no genera alertas, no reserva ni mueve stock, no manda emails;
  - no escribe nada en los canales (regla de oro) y no se puede cambiar de estado;
  - sí cuenta en los reportes.
- **R1.4** Es idempotente: repetir la importación no duplica pedidos (clave canal + referencia).
- **R1.5** Los productos que ya no existen en el catálogo se importan igual con el SKU y la descripción tal como estaban (`sku_snapshot`).
- **R1.6** Los reportes de ventas tienen una comparación contra el mismo período del año anterior.
- **R1.7** Resultado de cada corrida: cuántos importados, cuántos ya estaban, cuántos con error y por qué, con descarga de los errores.

### US-2 Prueba punta a punta (DDEV-57)

Como equipo de Deutsch, queremos probar todo el circuito antes de abrir, porque la mayorista se abre a todos juntos.

- **R2.1** Un guion en `docs/runbooks/prueba-punta-a-punta.md`, en castellano simple, con un caso por rol (Maico, Joaquín, Sergio, ventas, un vendedor): qué hacer, qué tiene que pasar, dónde anotar si falló.
- **R2.2** Casos cubiertos: venta ML Flex y Full, venta TN con Envío Nube y retiro, pedido mayorista por transferencia (pago y vencimiento), efectivo y cuenta corriente, faltante, devolución, edición masiva, alertas.
- **R2.3** Una prueba automática recorre el circuito mayorista completo (registro, aprobación, compra, pago, preparación, despacho, facturado) y los circuitos de ML y TN simulados, y corre en el CI.
- **R2.4** Un comando `seed_demo_launch` arma datos de ensayo (productos, stock, clientes, pedidos) en una base de ensayo, para que los usuarios reales prueben sin tocar datos reales.
- **R2.5** Quedan puntos que solo se pueden cerrar con terceros (pedido facturado y anulado en Contabilium, edición masiva ML); se marcan en el guion como "pendiente de tercero".

### US-3 Clientes mayoristas existentes (DDEV-58)

Como administrador, quiero cargar a los clientes mayoristas que ya tiene Deutsch para que el día del lanzamiento solo tengan que crear su contraseña.

- **R3.1** Importador de clientes desde un archivo (Excel o CSV) con una plantilla descargable: razón social, CUIT, email, teléfono, condición de IVA, domicilio, cuenta corriente (sí/no) y límite.
- **R3.2** Validación por fila: CUIT (módulo 11 de M8a), email válido, duplicados dentro del archivo y contra clientes ya cargados. Vista previa con errores antes de importar; los errores no frenan las filas válidas.
- **R3.3** Se importan ya aprobados, vinculados al `Customer` si ya existe con ese CUIT, y con cuenta corriente donde corresponda. Sin contraseña: la cuenta no puede ingresar hasta aceptar la invitación.
- **R3.4** La invitación es un email con un enlace de un solo uso que vence (7 días, configurable) para crear la contraseña y aceptar los términos.
- **R3.5** El envío es **separado** de la importación: el administrador importa y revisa, y recién el día del lanzamiento aprieta "Enviar invitaciones". Se puede enviar a todos, a seleccionados o reenviar a los que no entraron.
- **R3.6** El envío usa la cola de emails de M8a (con límite de ritmo para no pasar los topes del proveedor de correo). Los emails de invitación nunca vencen por antigüedad.
- **R3.7** Pantalla de seguimiento: invitados, invitación enviada, entraron, nunca entraron, rebotados.
- **R3.8** Ensayo seguro: con el modo "ensayo" (`STORE_EMAIL_DRY_RUN`) la cola registra qué mandaría sin enviar nada.

### US-4 Lanzamiento (DDEV-59)

Como administrador, quiero un procedimiento de salida controlado y poder vigilar la primera semana.

- **R4.1** Checklist de lanzamiento en `docs/runbooks/lanzamiento.md`: quién hace qué, en qué orden, cómo se vuelve atrás (cerrar la tienda, volver a poner la lista mayorista en Tiendanube).
- **R4.2** Pantalla "Control de lanzamiento" (solo Administrador) que verifica en vivo y muestra en verde o rojo: canales conectados y sin errores, cola de tareas viva, SMTP configurado y probado, bancos y textos de la tienda cargados, última copia de seguridad, clientes importados e invitados, histórico importado, dominio y SSL.
- **R4.3** Interruptor "Tienda abierta/cerrada" (con mensaje de mantenimiento en castellano) para abrir y cerrar sin tocar el servidor.
- **R4.4** Monitoreo reforzado de la primera semana: un resumen diario por email al administrador con pedidos, pagos pendientes, errores de integración, emails fallidos y alertas abiertas; se apaga solo a los 7 días.
- **R4.5** Lo que depende de otros queda como ítems del checklist con responsable: sacar la lista mayorista de Tiendanube y avisar en TN (proyecto DEUSTCH), subdominio, servidor, SMTP.

## Edge cases

- Archivo del respaldo de TiendaQuick con columnas distintas a las esperadas: el mapeo es configurable y la vista previa lo muestra antes de importar.
- Un pedido histórico de ML con un pedido igual ya importado por la integración normal: se detecta por canal + referencia y no se duplica.
- Cliente del archivo que ya se registró solo en la tienda: se aprueba esa cuenta y no se crea otra.
- Email rebotado o inexistente: queda marcado y se puede corregir y reenviar.
- Invitación vencida: el cliente la pide de nuevo desde el ingreso con su CUIT y email.
- Importar de nuevo el mismo archivo de clientes: actualiza, no duplica.

## Success metrics

- 100% de las filas válidas del archivo de clientes quedan importadas; las inválidas salen con motivo.
- 0 emails reales enviados en modo ensayo.
- 0 histórico visible en preparación o alertas (verificado por test).
- Comparación contra el año anterior disponible en los reportes de ventas y de canal.
- El control de lanzamiento queda todo en verde antes de abrir.

## Open questions

| Pregunta | Quién responde | Bloquea |
|---|---|---|
| Formato real del respaldo de TiendaQuick (columnas, archivo) | Deutsch | No: el mapeo es configurable |
| Cantidad aproximada de clientes mayoristas y de pedidos del año | Deutsch | No |
| Fecha objetivo de lanzamiento | Maico | No |
