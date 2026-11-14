# Requirements: Preparación y despacho de pedidos (módulo M5)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Tickets:** DDEV-32 (M5-01), DDEV-33 (M5-02), DDEV-34 (M5-03). DDEV-35 (M5-04) se pospone a M8.
**Depende de:** M4 (estados y `change_status`), M2 (envíos y etiquetas de ML), M1 (despacho en Tiendanube). Todos programados.

## Summary

Las pantallas que Depósito (Sergio) usa todos los días para preparar y despachar. Elige los pedidos a preparar y el sistema arma una lista de picking agrupada por producto, con una hoja PDF de doble control: una tilde al juntar y otra al verificar. Después imprime las etiquetas 10×15 (Mercado Libre y rótulo propio para transporte) y avanza los pedidos de estado, uno por uno o en lote.

## Goals

- Preparar varios pedidos de una vez juntando cada producto una sola vez.
- Que ningún pedido salga mal armado: hoja de doble control (juntado y verificado) en papel.
- Imprimir todas las etiquetas del día en la térmica 10×15 con pocos clics.
- Mover los pedidos de En preparación a Despachado desde una sola pantalla, sin entrar a cada ficha.

## Non-goals

- **Faltantes en pedidos mayoristas (M5-04):** se hace en M8, junto con la tienda mayorista.
- **Etiquetas de Envío Nube:** se espera el spike con la tienda real (DDEV-14). Hasta entonces se imprimen desde el admin de Tiendanube como hoy.
- Escaneo con lector de código de barras, ubicaciones en el depósito y conteo de stock: fuera de la fase 1.
- Escribir estados en Mercado Libre: ML se entera del despacho cuando el repartidor o el correo escanea la etiqueta.
- Pedidos Full: los despacha Mercado Libre y no se preparan.

## User stories

### US-1: Armar una tanda de preparación (DDEV-32)

Como Depósito, quiero elegir qué pedidos voy a preparar y obtener una lista agrupada por producto, para juntar todo de una vez.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Preparar" con los pedidos en estado **Nuevo** de Tiendanube, Mercado Libre (salvo Full) y manuales, ordenados por fecha límite de despacho (Flex y Colecta primero) y después por antigüedad.
- THE SYSTEM SHALL mostrar en cada pedido el canal y número, la forma de envío, la fecha límite (en rojo si faltan menos de 2 horas), el comprador y el resumen de productos.
- THE SYSTEM SHALL permitir marcar pedidos uno por uno, o todos los visibles, y filtrar por canal y forma de envío.
- WHEN Depósito confirma la selección THE SYSTEM SHALL crear una **tanda de preparación**, pasar esos pedidos a **En preparación** (vía `change_status`, auditado con el usuario) y mostrar la lista de picking.
- THE SYSTEM SHALL agrupar la lista de picking por SKU, con descripción (producto, talle y color), cantidad total y a qué pedidos va cada unidad (por ejemplo, "BUZ-001-M-NEG · 3 u · TN #1234 (1), ML pack 555 (2)"), ordenada por SKU para recorrer el depósito en orden.
- IF una línea de un pedido no tiene variante del catálogo THEN THE SYSTEM SHALL listarla aparte, con el SKU y la descripción que trajo el canal, marcada como "no está en el catálogo".
- IF un pedido elegido ya no está en Nuevo al confirmar (otra persona lo tomó, o el canal lo canceló) THEN THE SYSTEM SHALL dejarlo afuera de la tanda y avisar cuáles quedaron afuera y por qué.
- THE SYSTEM SHALL permitir ver las tandas abiertas y sus pedidos, y volver a abrir la lista de picking de cualquiera.
- THE SYSTEM SHALL ser usable desde el celular: lista de pedidos en tarjetas, casillas grandes.

### US-2: Hoja PDF de doble control (DDEV-32)

Como Depósito, quiero imprimir una hoja para tachar lo que voy juntando y después verificar cada pedido armado, para que nada salga mal.

**Acceptance criteria:**

- WHEN Depósito pide la hoja de una tanda THE SYSTEM SHALL generar un PDF tamaño A4 con:
  - **Parte 1, picking por producto:** una fila por SKU con descripción, cantidad total, pedidos de destino y dos casillas: **Juntado** y **Verificado**.
  - **Parte 2, armado por pedido:** un bloque por pedido (canal, número, comprador, forma de envío y fecha límite) con sus líneas y, por línea, la cantidad y dos casillas: **Armado** y **Controlado**. Cada bloque cierra con espacio para la firma o iniciales de quien armó y de quien controló.
- THE SYSTEM SHALL incluir en el encabezado el número de tanda, la fecha y hora de generación, el usuario y la cantidad de pedidos y unidades.
- THE SYSTEM SHALL ordenar la parte 2 por fecha límite (lo que se despacha primero, arriba).
- THE SYSTEM SHALL generar el PDF en el servidor (no depende del navegador) y en menos de 3 segundos para una tanda de 50 pedidos.
- THE SYSTEM SHALL ofrecer también la lista de picking en pantalla, con casillas tildables en el celular. Lo tildado en pantalla es una ayuda visual y no cambia estados.

### US-3: Etiquetas 10×15 (DDEV-33)

Como Depósito, quiero imprimir las etiquetas de envío en la térmica 10×15, de a una o todas juntas.

**Acceptance criteria:**

- THE SYSTEM SHALL permitir descargar la etiqueta de Mercado Libre de un pedido (Flex, Colecta y punto de entrega / correo) en el formato configurado (`ML_LABEL_FORMAT`: PDF o ZPL), usando lo que ya trae M2.
- THE SYSTEM SHALL permitir descargar en un solo archivo las etiquetas de ML de todos los pedidos de una tanda, o de los pedidos marcados en la pantalla de despacho.
- IF Mercado Libre todavía no habilita la etiqueta de un envío (no está listo para imprimir, o se canceló) THEN THE SYSTEM SHALL saltear ese pedido, imprimir el resto y decir cuáles faltan y por qué, en castellano claro.
- THE SYSTEM SHALL generar un **rótulo propio 10×15** (PDF, 100 × 150 mm) para envíos por transporte, con:
  - remitente (datos de Deutsch, configurables);
  - destinatario: nombre, documento, teléfono y domicilio completo;
  - expreso / transporte;
  - número de pedido;
  - número de bulto ("Bulto 1 de 3").
- WHEN Depósito imprime un rótulo de transporte THE SYSTEM SHALL pedir el expreso (de una lista editable por un administrador, con opción de escribir otro) y la cantidad de bultos, guardarlos en el envío y generar un rótulo por bulto.
- THE SYSTEM SHALL registrar en auditoría quién imprimió cada etiqueta o rótulo, y mostrar en el pedido si ya se imprimió (para no imprimir dos veces sin darse cuenta; reimprimir se permite).
- IF el pedido es de Envío Nube THEN THE SYSTEM SHALL indicar "La etiqueta se imprime desde Tiendanube" con un enlace al pedido en el admin de Tiendanube.

### US-4: Pantalla de despacho (DDEV-34)

Como Depósito, quiero avanzar los pedidos de estado desde una sola pantalla mientras preparo y despacho.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Despacho" con los pedidos En preparación, Listo y Listo para retirar, agrupados por estado y ordenados por fecha límite.
- THE SYSTEM SHALL permitir avanzar un pedido o varios marcados a la vez, con estas acciones:
  - En preparación → **Listo**;
  - Listo → **Despachado** (envíos) o **Listo para retirar** (retiro en local);
  - Listo para retirar → **Entregado** (cuando el cliente lo retira).
- THE SYSTEM SHALL aplicar cada cambio con `change_status` del M4: mismas reglas de transición y permisos, auditoría con el usuario. En pedidos de Tiendanube el cambio se informa a Tiendanube.
- WHEN se despachan pedidos por transporte THE SYSTEM SHALL permitir cargar el número de guía o seguimiento (opcional) antes de confirmar.
- IF en una acción en lote algún pedido no puede avanzar (cambió de estado, no corresponde la transición) THEN THE SYSTEM SHALL avanzar los demás y listar los que no, con el motivo.
- WHEN un pedido de una tanda llega a Despachado, Listo para retirar o Cancelado THE SYSTEM SHALL considerarlo resuelto en la tanda. WHEN todos los pedidos de una tanda están resueltos THE SYSTEM SHALL cerrar la tanda.
- THE SYSTEM SHALL permitir sacar un pedido de una tanda y devolverlo a Nuevo (por ejemplo, si no se puede armar hoy).
- THE SYSTEM SHALL mostrar las acciones de esta pantalla a quien tenga `sales.change_order_status` (Depósito, Ventas, Administrador).

## Constraints

- **Regla de oro:** M5 no escribe stock ni precios en ningún canal. A Tiendanube solo se le informan estados de despacho (servicio de M1, ya existente).
- Todos los cambios de estado pasan por `apps/sales/states.change_status`: no hay otra forma de cambiar un estado.
- Impresora: el formato de ML sigue configurable (PDF o ZPL) hasta que Deutsch confirme la térmica. El rótulo propio sale en PDF 100 × 150 mm. La prueba con la impresora real (criterio de DDEV-33) queda pendiente de que Deutsch la tenga.
- Volumen: menos de 30 pedidos por día; una tanda típica tiene 5 a 30 pedidos.
- Celular: Sergio puede usar el panel desde el teléfono en el depósito.

## Open questions

- **Datos del remitente para el rótulo** (razón social, dirección, teléfono): se cargan en la configuración; los completa Deutsch.
- **Lista inicial de expresos:** se arranca vacía y la carga un administrador.
- **Formato de la térmica** (PDF o ZPL): pendiente de Deutsch, como en M2.

## Decisiones tomadas

- **Entrada a preparación:** Depósito elige los pedidos y arma una tanda; esos pedidos pasan solos a En preparación.
- **Doble control:** hoja PDF con dos casillas por producto (Juntado / Verificado) y por línea de cada pedido (Armado / Controlado).
- **Rótulo de transporte:** expreso y bultos los carga Depósito al imprimir; un rótulo por bulto.
- **Envío Nube:** se espera el spike con la tienda real; por ahora no se implementa.
- **Faltantes mayoristas (M5-04):** se posponen a M8.
