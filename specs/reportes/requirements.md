# Requirements: Reportes (módulo M7)

**Status:** Approved (2026-11-15)
**Last updated:** 2026-11-15
**Tickets:** DDEV-41 (M7-01). DDEV-42 (M7-02, reportes mayoristas) se pospone a M8.
**Depende de:** M4 (pedidos y estados), M5 (despacho), M6 (preguntas), M3 (catálogo) y el historial de stock de M0/M3.

## Summary

Un tablero para administración con lo que hoy no se puede ver en ningún lado junto:
- ventas de todos los canales por período, canal, producto, talle y color, en bruto y (en Mercado Libre) en neto después de comisiones y envío;
- productos más vendidos y los que se agotan seguido;
- a qué días y horas entran los pedidos;
- cuánto se tarda en responder preguntas y en despachar.

Hay un resumen con indicadores y gráficos, y pestañas con tablas detalladas que se exportan a Excel.

## Goals

- Responder en segundos preguntas como "¿cuánto vendimos este mes por canal?", "¿qué talle de este buzo se vende más?" o "¿qué se nos agota siempre?".
- Saber cuánto queda de cada venta de Mercado Libre después de comisiones y envío.
- Medir la operación: tiempo de respuesta y de despacho, y Flex despachados a tiempo.
- Llevar cualquier tabla a Excel.

## Non-goals

- **Reportes mayoristas (M7-02):** se hacen en M8.
- Contabilidad, IVA, rentabilidad por costo de mercadería: el costo vive en Contabilium. Fuera de la fase 1.
- Comisiones de Tiendanube y de medios de pago: no vienen por API. En Tiendanube, neto = bruto, con una aclaración.
- Reportes programados por email: se puede sumar después.
- Pronóstico de demanda o reposición automática.

## User stories

### US-1: Resumen con indicadores y gráficos (DDEV-41)

Como Administrador, quiero un tablero con lo más importante del período.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Reportes", visible solo para el rol Administrador.
- THE SYSTEM SHALL permitir elegir el período:
  - con atajos: hoy, últimos 7 días, últimos 30 días, este mes, mes anterior;
  - con un rango libre;
  - y filtrar por canal (todos, Tiendanube, Mercado Libre, manual).
- THE SYSTEM SHALL mostrar indicadores del período, cada uno con la variación contra el período anterior de igual duración:
  - ventas en bruto;
  - ventas en neto;
  - cantidad de pedidos;
  - unidades;
  - ticket promedio;
  - pedidos cancelados;
  - devoluciones recibidas.
- THE SYSTEM SHALL mostrar gráficos:
  - ventas por día, separadas por canal;
  - participación de cada canal;
  - pedidos por día de la semana y hora.
- THE SYSTEM SHALL contar como venta cada pedido no cancelado, por su fecha de alta. Los cancelados se muestran aparte y no suman.
- THE SYSTEM SHALL responder en menos de 2 segundos con 12 meses de datos (~10.000 pedidos).

### US-2: Ventas detalladas (DDEV-41)

Como Administrador, quiero ver las ventas por canal, producto, talle, color y período.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pestaña "Ventas" con una tabla agrupable por:
  - canal;
  - producto;
  - variante (SKU, talle y color);
  - talle;
  - color;
  - día, semana o mes.
- La tabla SHALL mostrar unidades, pedidos, bruto, neto y precio promedio por unidad.
- THE SYSTEM SHALL ordenar por cualquier columna y SHALL exportar la tabla a Excel con el mismo agrupamiento y filtros.
- IF una línea vendida no tiene variante del catálogo THEN THE SYSTEM SHALL agruparla como "Sin vincular (SKU del canal)", para que no se pierda en los totales.

### US-3: Neto de Mercado Libre (DDEV-41)

Como Administrador, quiero saber cuánto queda de cada venta de ML después de comisiones y costo de envío.

**Acceptance criteria:**

- THE SYSTEM SHALL guardar, por cada venta de ML, la comisión de ML (por línea) y el costo de envío que paga el vendedor, a partir de lo que informa la API de ML.
- THE SYSTEM SHALL calcular neto = bruto − comisión − costo de envío del vendedor. En Tiendanube y manuales, neto = bruto, con la aclaración "sin comisiones del canal" en el tablero.
- WHEN se conecta este módulo THE SYSTEM SHALL completar esos datos para las ventas de ML ya importadas, en segundo plano y respetando los límites de la API.
- IF a una venta de ML le falta el dato THEN THE SYSTEM SHALL marcarla como "neto pendiente" y SHALL mostrar cuántas ventas del período están en esa situación.

### US-4: Productos (DDEV-41)

Como Administrador, quiero ver los más vendidos y los que se agotan seguido.

**Acceptance criteria:**

- THE SYSTEM SHALL mostrar los 50 productos y las 50 variantes más vendidos del período (por unidades y por bruto), con el stock actual.
- THE SYSTEM SHALL mostrar los productos que **se agotan seguido**: variantes cuyo stock disponible llegó a 0 al menos 2 veces en el período (configurable), con:
  - cuántas veces se agotaron;
  - cuántos días estuvieron sin stock;
  - las unidades vendidas en el período;
  - el stock actual.

  Se calcula a partir del historial de movimientos de stock.
- THE SYSTEM SHALL exportar ambas listas a Excel.

### US-5: Operación (DDEV-41)

Como Administrador, quiero medir cuánto tardamos en responder y en despachar.

**Acceptance criteria:**

- THE SYSTEM SHALL mostrar los pedidos por día de la semana y hora en una tabla de calor, del período y canal elegidos.
- THE SYSTEM SHALL mostrar el **tiempo de respuesta a preguntas** de ML:
  - mediana y percentil 90;
  - porcentaje respondido en menos de 1 hora y en menos de 12 horas;
  - el mismo detalle por persona, para las preguntas respondidas desde el sistema.
- THE SYSTEM SHALL mostrar el **tiempo de despacho**: desde que el pedido queda Nuevo (pago confirmado) hasta Despachado o Listo para retirar. Incluye mediana y percentil 90 por canal y por forma de envío.
- THE SYSTEM SHALL mostrar el porcentaje de pedidos **Flex y Colecta despachados a tiempo**, es decir, antes de la fecha límite, con la lista de los que salieron tarde.
- THE SYSTEM SHALL listar los **pedidos manuales sin cobrar o sin facturar** a la fecha, con días de antigüedad y total.
- THE SYSTEM SHALL exportar cada tabla a Excel.

## Constraints

- **Solo lectura:** M7 no cambia pedidos, stock ni precios, y no escribe en ningún canal. La única llamada nueva a ML es de lectura, para comisiones y costos de envío.
- **Fuente de verdad:** los montos son los que informan los canales (`SalesDocument`), no los de Contabilium. El tablero lo aclara.
- **Zona horaria:** Argentina (America/Argentina/Buenos_Aires) para días y horas.
- **Acceso:** solo Administrador (permiso nuevo `reports.view_reports`).
- **Rendimiento:** menos de 2 s por pantalla con 12 meses de datos. Los Excel de hasta 50.000 filas, en menos de 10 s.

## Open questions

- Qué costo de envío de ML cuenta como "del vendedor" en cada modalidad (Flex, Colecta, Full) se confirma con la cuenta real. El diseño toma el que informa ML como costo del vendedor.

## Decisiones tomadas

- **M7-02:** se pospone a M8.
- **Acceso:** solo Administrador.
- **Montos:** bruto en todos los canales, más el neto de ML después de comisiones y envío.
- **Formato:** tablero con indicadores y gráficos, más pestañas con tablas y Excel.
