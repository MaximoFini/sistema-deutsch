# Requirements: Base del sistema (módulo M0)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Tickets:** DDEV-1 a DDEV-9 (M0-01 … M0-09)

## Summary

La base técnica sobre la que se construye el resto de la fase 1: arquitectura, hosting, repositorio y despliegue, modelo de datos núcleo (preparado para ERP), usuarios y permisos, auditoría, alertas, monitoreo y el framework de integraciones que usan Tiendanube, Mercado Libre y Contabilium. No entrega pantallas de negocio para Deutsch, sino lo que permite que todo lo demás sea confiable.

## Goals

- Que las decisiones técnicas estén escritas y aprobadas antes de programar módulos de negocio (ADR).
- Que el sistema corra en un hosting definido, con staging, backups y costo mensual conocido.
- Que cada cambio pase por tests automáticos y llegue a staging sin pasos manuales.
- Que el modelo de datos soporte la fase 1 **y** el futuro reemplazo de Contabilium (facturación, cuentas corrientes, compras) sin rediseño.
- Que cada persona vea y haga solo lo que su rol y permisos le permiten, y que quede registro de quién hizo qué.
- Que ningún evento de un canal se pierda ni se duplique, y que ninguna escritura de stock o precio a un canal ocurra mientras la regla de oro esté vigente.

## Non-goals

- Integraciones concretas con TN, ML o Contabilium (son M1, M2 y M8). Acá solo se construye el framework común.
- Pantallas de pedidos, catálogo o preparación (M3–M5).
- Autoregistro de usuarios internos, login con Google u otros proveedores.
- Ubicaciones de depósito, control con lector, conteos de stock.
- Facturación electrónica (futuro, F-02). El modelo la contempla, pero no se implementa.

## User stories

### US-1: Decisiones técnicas escritas (DDEV-1)

Como responsable técnico de Kei, quiero un documento de arquitectura aprobado, para que todos los tickets (y los agentes que los programan) sigan las mismas reglas.

**Acceptance criteria:**

- THE SYSTEM SHALL tener un ADR en el repo (`docs/adr/`) y publicado en Plane, con stack, estructura del repo, estrategia de tests y de entornos.
- THE ADR SHALL incluir un diagrama de componentes: sistema, Tiendanube, Mercado Libre, Contabilium, tienda mayorista, email y ARCA (futuro).
- THE ADR SHALL listar los principios "preparado para ERP" que el resto de los tickets debe respetar.

### US-2: Hosting definido y con costo conocido (DDEV-2)

Como Kei, quiero comparar opciones de hosting con su costo mensual, para decidir dónde corre el sistema antes de desplegar.

**Acceptance criteria:**

- THE PROPOSAL SHALL comparar 2 o 3 opciones con costo mensual en USD y ARS, e incluir base Postgres administrada o respaldada, worker de tareas, almacenamiento de archivos (comprobantes) y email saliente.
- THE PROPOSAL SHALL incluir backups automáticos y un entorno de staging en cada opción.
- WHEN Kei apruebe una opción THE DECISION SHALL quedar registrada en el ADR.

### US-3: Repo, entornos y despliegue automático (DDEV-3)

Como desarrollador, quiero levantar el proyecto localmente con un comando y que cada push se pruebe y despliegue a staging, para no romper nada sin enterarnos.

**Acceptance criteria:**

- THE REPO SHALL tener un README con los pasos para levantar el proyecto localmente.
- WHEN se hace push a la rama principal THE CI SHALL correr los tests y, si pasan, desplegar a staging.
- IF los tests fallan THEN THE CI SHALL bloquear el despliegue.
- THE production deploy SHALL requerir un paso manual.
- THE SYSTEM SHALL leer todos los secretos de variables de entorno; ningún secreto SHALL estar en el código ni en el repo.

### US-4: Modelo de datos núcleo preparado para ERP (DDEV-4)

Como Kei, quiero un modelo de datos que hoy sirva para leer de Contabilium y mañana para reemplazarlo, para no tener que rediseñar la base después.

**Acceptance criteria:**

- THE MODEL SHALL incluir: productos y variantes (SKU, código de barras, peso, medidas), depósitos, stock por depósito con movimientos, listas de precio, clientes con datos fiscales (CUIT, condición de IVA, domicilio), documentos de venta genéricos por canal con líneas, pagos y envíos, e IDs externos (TN, ML, Contabilium, mayorista).
- THE SYSTEM SHALL registrar, para cada tipo de dato (stock, precio, producto, cliente, factura), cuál es su fuente de verdad actual, configurable sin cambiar código.
- WHILE la fuente de verdad de un dato sea Contabilium THE SYSTEM SHALL tratar ese dato como solo lectura en el sistema.
- THE MODEL SHALL tener migraciones con tests y un diagrama de entidades.
- THE DESIGN SHALL documentar cómo soporta facturación, cuentas corrientes y compras a futuro sin rediseño.

### US-5: Usuarios, roles y permisos con alta manual (DDEV-5)

Como administrador, quiero crear usuarios a mano y asignarles un rol y permisos puntuales, para que cada persona vea solo lo que necesita.

**Acceptance criteria:**

- THE SYSTEM SHALL tener los roles Administrador, Depósito, Ventas y Vendedor.
- WHEN un administrador crea, edita o desactiva un usuario THE SYSTEM SHALL aplicar el cambio sin intervención técnica.
- THE SYSTEM SHALL permitir sumar o quitar permisos puntuales a un usuario sin cambiar su rol.
- IF un usuario intenta abrir una pantalla o ejecutar una acción sin permiso THEN THE SYSTEM SHALL negarlo y SHALL NOT mostrar los datos.
- THE SYSTEM SHALL NOT tener página de registro para usuarios internos.
- WHEN un usuario pide recuperar su contraseña THE SYSTEM SHALL enviarle un link de un solo uso por email.
- IF un usuario está desactivado THEN THE SYSTEM SHALL impedir su login y cortar sus sesiones abiertas.

### US-6: Registro de auditoría (DDEV-6)

Como administrador, quiero saber quién hizo qué y cuándo, para revisar errores y responsabilidades.

**Acceptance criteria:**

- THE SYSTEM SHALL ofrecer un mecanismo común de auditoría que los módulos usan para registrar: cambios de estado de pedidos, respuestas a ML, ediciones de publicaciones, pedidos manuales, aprobaciones de clientes, confirmaciones de pago y devoluciones.
- WHEN se registra una acción THE SYSTEM SHALL guardar usuario (o "sistema"), fecha y hora, acción, objeto afectado y valores antes y después.
- THE SYSTEM SHALL NOT permitir editar ni borrar registros de auditoría desde la aplicación.
- THE SYSTEM SHALL tener una pantalla de consulta con filtros por usuario, fecha y tipo de acción, visible solo para administradores.

### US-7: Motor de alertas (DDEV-7)

Como usuario interno, quiero recibir avisos en el sistema y por email según mi rol, para enterarme a tiempo de lo que requiere acción.

**Acceptance criteria:**

- THE SYSTEM SHALL tener un panel de avisos con estado leído / no leído por usuario.
- WHEN un módulo emite una alerta THE SYSTEM SHALL mostrarla a los usuarios de los roles destinatarios y SHALL enviar email a esos roles si el tipo de alerta lo tiene activado.
- IF el mismo evento emite la misma alerta más de una vez THEN THE SYSTEM SHALL generar una sola alerta.
- IF el envío de email falla THEN THE SYSTEM SHALL reintentar y SHALL mantener la alerta visible en el panel.

### US-8: Backups, monitoreo y estado de integraciones (DDEV-8)

Como Kei, quiero backups probados, errores reportados y un panel con el estado de cada integración, para detectar problemas antes que Deutsch.

**Acceptance criteria:**

- THE SYSTEM SHALL tener un backup diario de la base, con al menos una restauración probada y documentada.
- WHEN ocurre un error no controlado THE SYSTEM SHALL reportarlo a una herramienta de monitoreo, sin incluir secretos ni datos de tarjetas.
- THE SYSTEM SHALL mostrar un panel con el estado de cada integración: última sincronización, errores recientes y cola pendiente.

### US-9: Framework de integraciones (DDEV-9)

Como sistema, quiero una base común para recibir y procesar eventos de TN, ML y Contabilium, para que ningún pedido se pierda ni se duplique.

**Acceptance criteria:**

- WHEN llega un webhook o notificación THE SYSTEM SHALL guardarlo y responder de inmediato (en menos de 2 s), y SHALL procesarlo en segundo plano.
- IF el mismo evento llega dos veces THEN THE SYSTEM SHALL procesarlo una sola vez (verificado por test).
- IF el procesamiento falla THEN THE SYSTEM SHALL reintentar con espera creciente, y IF agota los reintentos THEN THE SYSTEM SHALL emitir una alerta y dejar el evento visible para reprocesar a mano.
- THE SYSTEM SHALL permitir tareas de conciliación periódica por canal, para recuperar eventos que no llegaron.
- THE SYSTEM SHALL guardar las credenciales de cada canal cifradas, y SHALL NOT escribirlas en logs.
- THE SYSTEM SHALL respetar un límite de velocidad configurable por API.
- THE SYSTEM SHALL tener un interruptor por canal que bloquea cualquier escritura de stock o precio. WHILE el interruptor esté apagado (valor por defecto) THE SYSTEM SHALL rechazar esas escrituras y registrarlas en el log.

## Constraints

- Stack: Python + Django + Postgres, con un worker de tareas en segundo plano. Open source y usable en Argentina.
- Regla de oro: Contabilium es dueño de stock, precios y facturación. El sistema no escribe stock ni precio en ML ni TN.
- Volumen chico (menos de 30 pedidos por día) y equipo chico, así que se prioriza simplicidad operativa y bajo costo.
- Todo el código se escribe con agentes de IA. Los tests son obligatorios en integraciones y en permisos.
- Idioma de la interfaz: español (Argentina). Moneda ARS, zona horaria America/Argentina/Buenos_Aires.

## Open questions

Ninguna. Resueltas el 2026-11-14:

- **Casilla de email saliente:** la provee Deutsch, en el dominio deutsch.com.ar.
- **Dominio del panel interno:** `panel.deutsch.com.ar`.
- **Presupuesto de hosting:** sin tope; se elige la opción más barata que cumpla backups y staging.
