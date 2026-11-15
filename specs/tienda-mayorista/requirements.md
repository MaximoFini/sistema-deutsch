# Requirements: Tienda mayorista · etapa A (módulo M8a)

**Status:** Approved (2026-11-15)
**Last updated:** 2026-11-15 (reserva hasta facturar)
**Tickets:**
- M8a: DDEV-43 (M8-01), DDEV-48 (M8-06), DDEV-49 (M8-07), DDEV-50 (M8-08), DDEV-51 (M8-09), DDEV-53 (M8-11), DDEV-54 (M8-12).
- Pospuestos que entran acá: DDEV-35 (M5-04, faltantes) y DDEV-42 (M7-02, reportes mayoristas).
- **M8b (después, depende de terceros):** DDEV-44 (M8-02, integración Ecommerce de Contabilium), DDEV-45 (M8-03, ARCA), DDEV-46 (M8-04, subdominio y SSL), DDEV-47 (M8-05, recibir stock y precios de Contabilium), DDEV-52 (M8-10, enviar pedidos a Contabilium) y DDEV-55 (M8-13, margen de seguridad).

**Depende de:** M0 (usuarios, permisos, alertas, auditoría), M3 (catálogo maestro y lista MAYORISTA importada de Contabilium), M4 (centro de pedidos y estados), M5 (preparación) y M7 (reportes).

## Summary

Deutsch tiene su propia tienda mayorista, cerrada y con login. Así deja de pagar comisiones por venta en la función mayorista de Tiendanube.

- **Registro:** los clientes se registran con su CUIT y Deutsch los aprueba.
- **Compra:** ven el catálogo con precios mayoristas sin IVA y cargan cantidades en una grilla talle × color.
- **Cierre del pedido:** pagan por transferencia (suben el comprobante), en efectivo en el local o en cuenta corriente, si la tienen habilitada. Eligen expreso o retiro en el local.
- **En el sistema:** los pedidos entran al centro de pedidos como canal "Mayorista" y siguen el mismo circuito de preparación y despacho.
- **Vendedores y administradores** pueden armar pedidos en nombre de un cliente.

En esta etapa el stock y el precio mayorista salen de lo que ya tiene el sistema (importación de Contabilium de M3 y stock sincronizado). La facturación se marca a mano en Contabilium, como en los pedidos manuales. La integración automática con Contabilium, ARCA y el subdominio propio son la etapa B.

## Goals

- Que un cliente mayorista pueda comprar solo, a cualquier hora, sin escribirle a un vendedor.
- Que ningún pedido mayorista quede afuera del circuito de preparación y despacho.
- Que nunca se venda por la mayorista algo sin stock disponible.
- Que el vendedor cargue en minutos el pedido que el cliente le pasó por WhatsApp.
- Que la tienda tenga la identidad de marca de Deutsch y funcione bien en el celular.

## Non-goals (etapa A)

- **Integración automática con Contabilium** (stock, precios y pedidos): etapa B (M8-02, M8-05 y M8-10). Mientras tanto, el pedido se marca "Facturado en Contabilium" con el número de comprobante, como los manuales.
- **Autocompletar desde ARCA:** etapa B (M8-03).
- **Subdominio `mayoristas.deutsch.com.ar` y SSL:** etapa B (M8-04). En la etapa A la tienda funciona en el mismo servidor, configurable para atender en su propio dominio cuando exista.
- **Pasarela de pago y logística integrada:** fuera de la fase 1 (decisión del PRD).
- **Margen de seguridad de stock entre canales:** spike en la etapa B (M8-13). El sistema deja un margen configurable en 0.
- **Importar y avisar a los clientes actuales:** se hace justo antes del lanzamiento (M9).

## User stories

### US-1: Identidad de marca (DDEV-43)

Como Deutsch, quiero que la tienda se vea como mi marca, para que los clientes la reconozcan y confíen.

**Acceptance criteria:**

- THE SYSTEM SHALL tomar colores, tipografías, logo y reglas de uso del manual de marca de Deutsch (Drive "Deutsch - Kei Software", carpeta "02 Multimedia" › "01 Logo e Identidad de Marca") y definirlos como tokens de diseño reutilizables.
- THE SYSTEM SHALL documentar los componentes base: botones, campos de formulario, tarjeta de producto, grilla de talles, tablas, alertas, encabezado y pie, en escritorio y celular.
- THE SYSTEM SHALL usar ese sistema de diseño en la tienda. El panel interno lo puede adoptar después sin rehacerlo.
- THE SYSTEM SHALL cumplir contraste accesible (WCAG AA) en textos y botones.

### US-2: Registro y acceso de clientes (DDEV-48)

Como cliente mayorista, quiero registrarme con mi CUIT para poder comprar. Como administrador, quiero aprobar o rechazar cada registro y habilitar cuenta corriente a clientes puntuales.

**Acceptance criteria:**

- THE SYSTEM SHALL mantener la tienda cerrada: sin sesión solo se ven el ingreso, el registro, la recuperación de contraseña y las páginas legales.
- THE SYSTEM SHALL pedir en el registro:
  - CUIT;
  - razón social y nombre de fantasía;
  - condición de IVA;
  - domicilio (calle, número, localidad, provincia, código postal);
  - teléfono;
  - email;
  - contraseña;
  - aceptación de los términos.
- WHEN se carga el CUIT THE SYSTEM SHALL validar formato y dígito verificador. IF no es válido THEN THE SYSTEM SHALL decir "El CUIT no es válido: revisá los 11 números" y SHALL NOT continuar. IF ese CUIT ya tiene cuenta THEN THE SYSTEM SHALL ofrecer ingresar o recuperar la contraseña.
- WHEN alguien se registra THE SYSTEM SHALL dejar la cuenta **pendiente de aprobación**, mostrarle "Te avisamos por email cuando aprobemos tu cuenta" y avisar a los administradores (alerta nueva).
- THE SYSTEM SHALL tener en el panel una cola de registros pendientes. El administrador revisa los datos, los corrige si hace falta y aprueba o rechaza (con motivo). El cliente recibe un email en ambos casos.
- IF el CUIT coincide con un cliente que ya existe en el sistema (por ejemplo, de pedidos manuales) THEN THE SYSTEM SHALL vincular la cuenta a ese cliente al aprobar, sin duplicarlo.
- THE SYSTEM SHALL permitir al administrador habilitar o deshabilitar la **cuenta corriente** de cada cliente, y suspender o reactivar una cuenta.
- THE SYSTEM SHALL tener un usuario por cliente, con recuperación de contraseña por email.
- THE SYSTEM SHALL proteger el registro contra registros automáticos (campo trampa y límite por IP) y el ingreso contra fuerza bruta (el mismo bloqueo del panel, M0).
- THE SYSTEM SHALL separar a los clientes del panel interno: un cliente nunca puede entrar al panel y un usuario interno no compra como cliente (salvo con "pedido en nombre de", US-7).

### US-3: Catálogo mayorista (DDEV-49)

Como cliente mayorista, quiero ver los productos con su precio mayorista y su disponibilidad.

**Acceptance criteria:**

- THE SYSTEM SHALL mostrar los productos activos que tengan **precio mayorista mayor a $0** (lista MAYORISTA), con fotos, descripción y categoría tomadas de Tiendanube (lo que M1 ya importa).
- THE SYSTEM SHALL mostrar el **precio sin IVA** y el IVA aparte ("+ IVA 21 %"). Si la lista MAYORISTA está cargada con IVA (`CONTABILIUM_WHOLESALE_INCLUDES_VAT`), el sistema lo descuenta para mostrar el neto.
- THE SYSTEM SHALL mostrar para cada variante si está disponible o agotada. Disponible = stock del depósito − reservas de pedidos mayoristas esperando pago − margen de seguridad (configurable, hoy 0). La cantidad exacta no se muestra.
- THE SYSTEM SHALL permitir buscar por nombre o SKU y filtrar por categoría, marca y talle. Los resultados van paginados.
- IF un producto no tiene ninguna variante disponible THEN THE SYSTEM SHALL mostrarlo como "Agotado" al final del listado.

### US-4: Grilla, carrito y checkout (DDEV-50)

Como cliente mayorista, quiero cargar cantidades por talle y color de una vez y cerrar el pedido.

**Acceptance criteria:**

- THE SYSTEM SHALL mostrar en cada producto una **grilla talles × colores**:
  - una casilla de cantidad por variante disponible;
  - la casilla deshabilitada si la variante está agotada;
  - el total de unidades y el subtotal del producto, actualizados al cargar.
  - Se compra por unidades sueltas.
- IF se pide más que lo disponible THEN THE SYSTEM SHALL limitar la cantidad y avisar "Solo podés pedir hasta N".
- THE SYSTEM SHALL tener un carrito que se conserva entre sesiones, con subtotal neto, IVA y total. Se pueden editar cantidades y quitar productos.
- THE SYSTEM SHALL exigir un **mínimo por pedido** configurable desde el panel (hoy $300.000), con o sin IVA según la configuración. Solo aplica a los pedidos que hace el cliente. IF no se llega THEN THE SYSTEM SHALL mostrar cuánto falta y SHALL NOT permitir confirmar.
- THE SYSTEM SHALL pedir la **entrega**:
  - transporte, eligiendo de la lista de expresos (la de M5), con flete a cargo del cliente;
  - o retiro en el local.
- THE SYSTEM SHALL pedir el **medio de pago**:
  - transferencia;
  - efectivo en el local, solo con retiro;
  - cuenta corriente, solo si el cliente la tiene habilitada.
- WHEN el cliente confirma THE SYSTEM SHALL volver a verificar stock y precios, congelar el precio de cada línea y crear el pedido. IF algo cambió (precio o stock) THEN THE SYSTEM SHALL mostrar qué cambió y pedir que confirme de nuevo.
- THE SYSTEM SHALL mostrar una confirmación con el número de pedido y los próximos pasos según el medio de pago.

### US-5: Pagos sin pasarela y pedidos en el centro de pedidos (DDEV-51)

Como Deutsch, quiero confirmar los pagos y que los pedidos mayoristas sigan el mismo circuito que el resto.

**Acceptance criteria:**

- **Transferencia:**
  - WHEN el cliente elige transferencia THE SYSTEM SHALL mostrarle los datos bancarios (configurables) y permitirle subir el comprobante (imagen o PDF, hasta 10 MB), en ese momento o después desde Mi cuenta.
  - El pedido queda en **Esperando pago** y el stock queda reservado.
- WHEN un administrador confirma el pago desde el panel (viendo el comprobante) THE SYSTEM SHALL pasar el pedido a **Nuevo** para preparar y avisar al cliente por email.
- THE SYSTEM SHALL mantener la reserva de stock hasta que el pedido se marque "Facturado en Contabilium" (desde ahí lo descuenta Contabilium), se cancele o se ajuste por faltante (solo la diferencia). *(Ajuste aprobado en el diseño, 2026-11-15: liberarla al confirmar el pago permitía vender dos veces las mismas unidades.)*
- WHEN pasan X días (configurable, hoy 3) sin confirmar el pago THE SYSTEM SHALL cancelar el pedido, liberar la reserva y avisar al cliente. Un día antes le recuerda que suba el comprobante.
- **Efectivo y cuenta corriente:** WHEN el cliente los elige THE SYSTEM SHALL pasar el pedido directo a **Nuevo**. En efectivo se cobra al retirar, y el pedido queda "pendiente de cobro" hasta que se marque cobrado.
- THE SYSTEM SHALL mostrar los pedidos mayoristas en el centro de pedidos (M4) como canal **"Mayorista"**, con los mismos estados, preparación (M5) y despacho. El cobro y "Facturado en Contabilium" se editan como en los manuales.
- El cliente SHALL NOT cancelar ni modificar un pedido confirmado. Solo Deutsch.
- THE SYSTEM SHALL mostrar los comprobantes solo al cliente dueño y a los administradores. Se descargan por un enlace protegido, nunca por una URL pública.
- THE SYSTEM SHALL avisar a los administradores cuando se sube un comprobante.

### US-6: Mi cuenta: historial, repetir pedido, facturas y emails (DDEV-53)

Como cliente mayorista, quiero ver mis pedidos, repetir uno anterior y enterarme por email de cada paso.

**Acceptance criteria:**

- THE SYSTEM SHALL mostrar en "Mi cuenta":
  - los pedidos con fecha, total, estado en palabras del cliente ("Esperando tu pago", "En preparación", "Despachado", "Listo para retirar", "Entregado", "Cancelado"), el detalle y el seguimiento si hay;
  - los datos de la cuenta, que se editan pidiendo el cambio (el CUIT no se cambia).
- THE SYSTEM SHALL permitir **repetir un pedido**: lo carga en el carrito con stock y precios actuales, y avisa lo que no está disponible.
- THE SYSTEM SHALL mostrar el número de factura de Contabilium cuando esté cargado ("La factura te llega por email desde Contabilium").
- THE SYSTEM SHALL enviar emails con la marca de Deutsch en cada paso:
  - registro recibido;
  - registro aprobado o rechazado;
  - pedido recibido;
  - pago confirmado;
  - recordatorio de pago;
  - pedido vencido;
  - consulta por faltante;
  - despachado (con seguimiento) o listo para retirar.
- Los textos de los emails son editables desde el panel. Arrancan con textos propuestos para que Deutsch los revise.
- Mientras no esté configurado el correo saliente (DDEV-7), los emails quedan registrados en el sistema como "pendiente de envío" y se mandan cuando se configure.

### US-7: Pedidos en nombre de clientes (DDEV-54)

Como vendedor, quiero armar en la tienda el pedido que un cliente me pasó por WhatsApp o teléfono.

**Acceptance criteria:**

- THE SYSTEM SHALL permitir a **Vendedores y Administradores** elegir cualquier cliente aprobado y comprar en la tienda en su nombre, con un aviso visible arriba ("Estás armando un pedido para «Cliente»").
- THE SYSTEM SHALL NOT aplicar el mínimo de compra a esos pedidos, y SHALL permitir los medios de pago que tenga habilitados el cliente.
- THE SYSTEM SHALL registrar en el pedido y en la auditoría quién lo cargó. El cliente lo ve en su historial como "Cargado por Deutsch".
- THE SYSTEM SHALL permitir a los Vendedores ver todos los clientes mayoristas y sus pedidos en el panel interno.
- La carga de pedidos mayoristas desde el pedido manual de M4 SHALL redirigir a este circuito, como ya lo avisa M4.

### US-8: Faltantes en pedidos mayoristas (DDEV-35, pospuesto de M5)

Como Depósito, quiero marcar que falta un producto en un pedido mayorista para que se consulte al cliente antes de despachar.

**Acceptance criteria:**

- THE SYSTEM SHALL permitir a Depósito marcar en un pedido mayorista En preparación, por línea, la cantidad que falta. El pedido pasa a **Esperando cliente**.
- WHEN se marca un faltante THE SYSTEM SHALL enviar un email al cliente con el detalle y avisar a los administradores.
- THE SYSTEM SHALL permitir a un administrador ajustar el pedido con la respuesta del cliente: quitar o reducir líneas, o reemplazarlas por otra variante con stock. Al terminar, el pedido vuelve a **En preparación**, se recalcula el total y queda auditado.
- IF el pedido ya estaba pagado y el total bajó THEN THE SYSTEM SHALL pedir al administrador que elija, caso por caso:
  - **saldo a favor**, que queda en la cuenta del cliente y se descuenta automáticamente en su próximo pedido, visible en Mi cuenta;
  - o **reintegro**, hecho por fuera, que el sistema solo registra con fecha y referencia.
- IF el pedido ya estaba marcado "Facturado en Contabilium" THEN THE SYSTEM SHALL marcarlo "Corregir en Contabilium" y avisar a los administradores.

### US-9: Reportes mayoristas (DDEV-42, pospuesto de M7)

Como Administrador, quiero ver las ventas mayoristas por cliente y por vendedor.

**Acceptance criteria:**

- THE SYSTEM SHALL sumar a Reportes (M7) una pestaña "Mayorista" con:
  - ventas por cliente;
  - ventas por vendedor que cargó el pedido (o "el cliente");
  - pedidos esperando pago, vencidos y sin facturar;
  - saldos a favor vigentes.
- Mismos filtros de período y exportación a Excel que el resto de M7.
- El canal "Mayorista" SHALL aparecer en todos los reportes existentes con su propio color.

## Constraints

- **Regla de oro:** la tienda no escribe stock ni precios en Tiendanube ni en Mercado Libre. Las reservas son internas del sistema.
- **Fuente de verdad (etapa A):** precio mayorista = lista MAYORISTA del sistema (importada de Contabilium). Stock = stock del sistema (depósito por defecto). El precio queda congelado en el pedido al confirmar.
- **Datos personales:** los comprobantes y los datos de los clientes son privados. Los archivos se guardan fuera de la carpeta pública y se sirven solo con permiso.
- **Celular primero:** la mayoría de los clientes compra desde el teléfono. La grilla tiene que poder usarse con el pulgar.
- **Rendimiento:** el catálogo (hasta ~1.000 productos) carga en menos de 1 s y la grilla responde al instante.
- **Correo:** depende de DDEV-7 (datos SMTP de Deutsch). Mientras tanto, los emails quedan en cola.

## Open questions

- Datos bancarios para transferencia, días de vencimiento (propuesto: 3) y textos legales (términos de venta mayorista y privacidad): los define Deutsch. Se cargan desde el panel.
- Textos de los emails: se proponen y Deutsch los revisa.

## Decisiones tomadas

- **Etapas:** M8a ahora; M8b (Contabilium Ecommerce, ARCA y subdominio) después.
- **Contabilium Ecommerce:** lo gestiona el usuario por fuera (consulta a soporte y adhesión). Kei deja el documento con qué preguntar y cómo probar.
- **Diferencia de plata por faltante:** el administrador decide caso por caso, saldo a favor o reintegro.
- **CUIT:** validación de formato y dígito verificador, más revisión del administrador. ARCA en la etapa B.

## Entregable adicional

- `docs/spikes/contabilium-ecommerce.md`: preguntas para el soporte de Contabilium y procedimiento de prueba de la integración Ecommerce. Destraba M8-02, que gestiona el usuario.
