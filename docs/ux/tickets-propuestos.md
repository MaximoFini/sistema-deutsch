# Tickets propuestos: módulo «M10 · Front y experiencia de uso»

Fecha: 2026-11-20. **Cargados en Plane el 2026-11-20** (proyecto DDEV, módulo «M10 · Front y experiencia de uso», estado Backlog) **como plan: no ejecutados.** Se empieza a trabajar cuando Deutsch/Maico den el OK (regla de trabajo vigente: un módulo por vez, OK explícito).

**Convenciones.** Prioridad: **P0** bloquea todo lo demás o es base · **P1** alto impacto · **P2** importante · **P3** deseable. Estimación gruesa en días de trabajo de una persona (S ≤ 2 días, M 3–5, L 6–10, XL > 10); son órdenes de magnitud, no compromisos. «Prototipo» = se puede probar sin construir (HTML estático, Figma o similar). Los criterios de aceptación son verificables (alguien puede mirar y decir sí/no).

---

## Orden recomendado (resumen)

```
Fase A  Medir y probar sin construir      M10-01 → M10-02 → M10-03 → M10-04
Fase B  Cimientos (sin cambiar el aspecto) M10-05 → M10-06 → M10-07 → M10-08 → M10-09 → M10-17
Fase C  Pantallas por impacto              M10-10 → M10-11 → M10-14 → M10-15 → M10-16 → M10-12 → M10-13
Fase D  Resto de módulos                   M10-18 → M10-19 → M10-20 → M10-21 → M10-22 → M10-23 → M10-24 → M10-25
Fase E  Tienda, cierre y continuidad       M10-26 → M10-27 → M10-28 → M10-29 → M10-30 → M10-31
```
(M10-27 y M10-28 corren **en paralelo** durante todo el módulo; se listan al final por ser transversales.)

### Qué se puede probar con prototipo antes de construir (antes de gastar en código)

| Qué | Cómo | Ticket |
|---|---|---|
| Si los grupos y nombres de la barra lateral los entiende el equipo | Card sorting abierto + tree test con papel o una herramienta online, con el personal real | M10-02 |
| Si el inicio por rol sirve | Prototipo clickeable de 4 pantallas, una persona por rol | M10-03 |
| Si el flujo de Preparar/Despacho funciona con guantes, luz y celular reales | Prototipo en HTML estático en el celular del depósito, en el lugar | M10-04 |
| Tamaños táctiles y contraste | Misma prueba de M10-04 con variantes de 44 y 56 px | M10-04 |
| Niveles y reglas de alertas | Revisar con el equipo las alertas de los últimos 30 días y simular la nueva clasificación en papel | M10-15 |

---

## Fase A: medir y probar sin construir

### [M10-01] Línea de base de usabilidad y de uso real
- **Descripción.** Antes de cambiar nada, medir cómo se usa hoy: tiempos y errores en tareas clave con 3 personas por rol; y, desde datos que ya tiene el sistema, qué módulos se usan, cuántos avisos se generan por día y por tipo y cuántos se leen/accionan, tiempos de respuesta de las pantallas principales en el celular/tablet del depósito. (Auditoría `AU #3` y `AU #10` quedaron como «a confirmar».)
- **Criterios de aceptación.**
  1. Existe un documento con **8–10 tareas** por rol acordadas con Deutsch (ej.: armar una tanda, despachar 3 pedidos, responder una pregunta, cargar un pedido manual, aprobar un cliente).
  2. Se corrieron esas tareas con **3 usuarios por rol** (o todos los que haya, si son menos), con tiempo, éxito y errores anotados.
  3. Hay una tabla de **alertas de los últimos 30 días** por tipo: cantidad, cuántas se leyeron, cuántas llevaron a una acción dentro de 24 h (si el dato no existe, queda anotado como faltante).
  4. Hay mediciones de tiempo de carga de Pedidos, Preparar, Despacho y Hoy **en el dispositivo real del depósito** (3 repeticiones, red real).
  5. Quedan fijadas, **con el equipo**, las metas numéricas del módulo (reemplazan las «a calibrar» de la propuesta).
- **Prioridad.** P0. **Depende de:** nada. **Estimación.** M.

### [M10-02] Card sorting abierto y prueba de árbol de la navegación
- **Descripción.** Con todo el personal que usa el panel (muestra chica; se lee como cualitativo, ver IN §19), descubrir cómo agrupan y nombran las ~25 secciones y probar la barra lateral propuesta (grupos y etiquetas).
- **Criterios de aceptación.**
  1. Card sorting abierto hecho con **todas las personas que usan el panel** (mínimo 8; si son menos, se dice y se repite).
  2. Tree test de la propuesta con **≥ 6 tareas de encontrar** por rol; resultado registrado: % de primer clic correcto y dónde se pierden.
  3. Lista final de **grupos y nombres** aprobada por Deutsch (reemplaza o confirma la de `propuesta-front.md` §3.2).
  4. Se anotan las palabras exactas que usa el equipo (glosario, alimenta M10-09).
- **Prioridad.** P0. **Depende de:** M10-01 (tareas). **Estimación.** S–M.

### [M10-03] Prototipo de navegación e inicio por rol
- **Descripción.** Prototipo clickeable (sin código de producción) de: barra lateral agrupada, barra superior mínima, buscador global y las 4 pantallas de inicio por rol, con datos de ejemplo realistas.
- **Criterios de aceptación.**
  1. Hay un prototipo navegable de al menos 4 pantallas de inicio + navegación + buscador (fidelidad media, con la marca aplicada).
  2. Probado con **1–3 personas por rol**; cada persona completa las tareas de «encontrar» y de «qué hago primero hoy».
  3. Informe con decisiones: qué se mantiene, qué cambia, qué se descarta (cada cambio con la cita de la prueba).
  4. Aprobación de Deutsch antes de pasar a Fase B.
- **Prioridad.** P0. **Depende de:** M10-02. **Estimación.** M.

### [M10-04] Prueba en el depósito: Preparar/Despacho en celular y tablet con guantes y luz real
- **Descripción.** Prototipo (HTML estático) del flujo de Preparar → hoja de picking → Despacho con variantes de tamaño (44/48/56 px), contraste normal y alto, y acción abajo. Probar en el depósito, con guantes de trabajo, en el celular/tablet real, a distinta luz.
- **Criterios de aceptación.**
  1. Se probaron **≥ 3 personas del depósito** con sus guantes y dispositivos, en el lugar y en al menos dos condiciones de luz.
  2. Registro de aciertos de toque (toques errados / total) por tamaño de objetivo.
  3. Decisión documentada de **tamaño mínimo de objetivo, contraste y posición de acciones** para el modo depósito.
  4. Lista de problemas del dispositivo (brillo, sensibilidad táctil, conexión) para el equipo técnico.
- **Prioridad.** P0. **Depende de:** M10-01. **Estimación.** S–M.

---

## Fase B: cimientos (sin cambiar el aspecto de las pantallas existentes)

### [M10-05] Sistema de diseño: tokens, tipografía, logo, densidad
- **Descripción.** Llevar los tokens de marca (`static/brand/tokens.css`) al panel: color (marca + estados + neutros), Source Sans 3 (con respaldo), escala tipográfica, espaciado, tres densidades (cómoda/normal/compacta), favicon y logo en cabecera. Documentarlo en la página de estilo viva (ver M10-26). **Sin cambiar** HTML de las pantallas todavía.
- **Criterios de aceptación.**
  1. Existe un único archivo de tokens usado por panel y tienda; Tailwind los expone (`bg-brand-*`, `text-brand-*`).
  2. Pasa una prueba automática de contraste: cada par texto/fondo declarado cumple **≥ 4,5:1** (3:1 para texto grande, bordes y íconos de control); el azul `#007DC5` no se usa para texto normal.
  3. El panel carga Source Sans 3 con respaldo Calibri/sans de sistema, sin salto visible de diseño.
  4. El logo negativo se muestra en la cabecera sin deformación, a ≥ 38 px de ancho (mínimo de 10 mm del manual) y con el área de seguridad respetada; favicon = isotipo.
  5. Documentado: qué colores están **reservados** para alertas (rojo/ámbar).
- **Prioridad.** P0. **Depende de:** M10-03 (decisiones), M10-04 (densidad depósito). **Estimación.** M.

### [M10-06] Biblioteca de componentes compartida
- **Descripción.** Componentes reutilizables (partiendo de `templates/store/components/`): botón (jerarquía), chip de estado, mensaje/alerta, tabla (encabezado fijo, columnas, selección múltiple, vista tarjeta), ficha, formulario (campo, error, resumen), estado vacío, filtros con chips, paginación, indicador de carga.
- **Criterios de aceptación.**
  1. Cada componente está documentado con ejemplo en la página de estilo y usa solo tokens.
  2. Cada componente cumple AA (foco visible, contraste, `aria-*` donde corresponde) y está probado con teclado.
  3. Hay pruebas automáticas de render de cada componente (con estados vacío, error, cargando).
  4. Un componente nuevo **no** rompe plantillas viejas (conviven; no se tocan todavía).
  5. «Una sola acción primaria por pantalla» queda en la guía y como **advertencia** en desarrollo si una plantilla usa dos.
- **Prioridad.** P0. **Depende de:** M10-05. **Estimación.** L.

### [M10-07] Registro único de navegación y pruebas de cobertura por rol
- **Descripción.** Un registro en código con grupo, ítem, etiqueta, ícono, URL y permiso que alimente barra lateral, barra inferior, buscador global y migas; con pruebas automáticas. No cambia permisos ni URLs.
- **Criterios de aceptación.**
  1. Un solo lugar define toda la navegación; `_menu.html` actual se deriva de él (sin cambiar lo que ve cada rol).
  2. Test: para cada rol de `roles.py`, el conjunto de ítems visibles coincide con los **que hoy se ven** (21/16/8/7 enlaces; ver auditoría).
  3. Test: toda URL de módulo accesible por permisos aparece en el registro o en una lista explícita de excepciones.
  4. Un permiso inexistente en el registro rompe el test.
- **Prioridad.** P0. **Depende de:** M10-02 (agrupación). **Estimación.** S–M.

### [M10-08] Esqueleto nuevo (barra lateral, barra superior mínima, barra inferior móvil) detrás de un interruptor por usuario
- **Descripción.** Esqueleto nuevo (`UI_V2`) con barra lateral agrupada, ítem activo marcado, grupo actual abierto; barra superior con logo, buscador (hueco hasta M10-18), campana, usuario; barra inferior en celular/tablet; opción «volver a la versión anterior» por usuario; no cambia las pantallas internas.
- **Criterios de aceptación.**
  1. Un usuario con el interruptor activo ve el esqueleto nuevo; los demás siguen igual (verificado por prueba).
  2. La página actual está marcada (`aria-current="page"`); la navegación tiene `aria-label`; hay enlace «Saltar al contenido».
  3. Funciona de 360 px a 1920 px sin scroll horizontal del esqueleto; en < 1024 px aparece la barra inferior.
  4. Los contadores de Mercado Libre y la campana no mueven el diseño al cargar (espacio reservado o renderizados en servidor).
  5. Un clic devuelve al esqueleto viejo y se recuerda por usuario.
  6. Las pruebas actuales (`test_url_permissions` y el resto) siguen verdes.
- **Prioridad.** P0. **Depende de:** M10-05, M10-06, M10-07. **Estimación.** L.

### [M10-09] Glosario, etiquetas y guía de microcopy
- **Descripción.** Con los resultados de M10-02, fijar los nombres de las secciones y estados en el lenguaje del equipo (y la regla «Deutsch», nunca «DEUTSCH»); guía de tono (voseo, directo, cálido, sin dramatismo) y plantillas de mensajes (éxito, error «qué pasó + qué hacer»).
- **Criterios de aceptación.**
  1. Glosario publicado (en `docs/`) con cada término, su definición y dónde se usa.
  2. Guía de microcopy con **≥ 15 ejemplos** de «en vez de / decir» y las plantillas de mensajes.
  3. Las etiquetas del registro de navegación coinciden con el glosario.
  4. Revisado y aprobado por Deutsch.
- **Prioridad.** P1. **Depende de:** M10-02. **Estimación.** S.

---

## Fase C: pantallas de mayor impacto

### [M10-10] Inicio por rol (Hoy)
- **Descripción.** Reemplazar `core/home.html` por 4 inicios (Depósito, Ventas, Vendedor, Administrador) con 4–6 tarjetas accionables ordenadas por urgencia y una acción principal por rol (ver `propuesta-front.md` §4).
- **Criterios de aceptación.**
  1. Cada rol ve **solo** sus tarjetas, con permisos como hoy.
  2. Cada tarjeta muestra un número y lleva a la lista **ya filtrada**; los números coinciden con la lista (prueba automática).
  3. Hay estado vacío con mensaje útil («No hay pedidos para preparar. Último despacho a las 14:20»).
  4. **El rojo aparece solo si algo está vencido**; los contadores de trabajo no son rojos.
  5. Carga en ≤ 1 s con datos de prueba de volumen real (medido).
  6. Probado con ≥ 1 usuario por rol: elige correctamente «qué hago primero» sin ayuda.
- **Prioridad.** P1. **Depende de:** M10-08, M10-11. **Estimación.** L.

### [M10-11] Estados de pedido y semántica de color
- **Descripción.** Rediseñar los chips de estado y los colores de estado/alerta: cada estado con ícono + texto + color de la nueva paleta; reservar rojo; separar «estado» de «alerta»; documentarlo.
- **Criterios de aceptación.**
  1. Tabla de **todos** los estados de `sales/states.py` con su chip (ícono, texto, color) documentada.
  2. Ningún estado depende solo del color (prueba visual en escala de grises).
  3. El rojo solo en: vencido, error bloqueante, acción destructiva (revisado por búsqueda en plantillas).
  4. El estado «Cancelado» y los «histórico» no usan colores de alerta.
  5. `FAMILY_CLASSES`/`status_classes` se reemplazan por el componente chip, con prueba de que cubre todos los estados.
- **Prioridad.** P1. **Depende de:** M10-05, M10-06. **Estimación.** M.

### [M10-12] Lista de pedidos nueva (y patrón de listas)
- **Descripción.** Rediseñar `sales/order_list.html` con el patrón de tabla nueva: 6–7 columnas por defecto + «Columnas», filtros con 2–3 visibles y «Más filtros», chips de filtros aplicados, orden por columna, tarjetas desde 1024 px hacia abajo, columna «Límite» con tiempo relativo. Servirá de plantilla para las demás listas.
- **Criterios de aceptación.**
  1. A 1024 px de ancho o menos se ve en tarjetas, sin scroll horizontal; en escritorio, sin scroll horizontal de la tabla con columnas por defecto.
  2. Los filtros aplicados se muestran como chips y «Limpiar todo» los quita.
  3. La columna Límite muestra tiempo relativo (rojo solo si venció) y la fecha completa al pasar el cursor/tocar.
  4. El orden por defecto es por límite de despacho para pedidos abiertos.
  5. Misma información accesible que antes (nada se pierde: verificado contra lista de campos actual).
  6. Carga ≤ 1 s con 5.000 pedidos de prueba (existe `test_rendimiento` como base).
  7. Prueba de usuarios: Ventas y Depósito encuentran un pedido y su límite sin ayuda.
- **Prioridad.** P1. **Depende de:** M10-06, M10-11. **Estimación.** L.

### [M10-13] Ficha de pedido: siguiente paso destacado
- **Descripción.** Rediseñar `order_detail.html`: cabecera con estado + **un botón primario con el siguiente paso**; acciones alternativas secundarias; secciones en orden (qué hacer → quién/qué → cobro → historial); cobro como acción clara.
- **Criterios de aceptación.**
  1. Para cada estado, la acción primaria es la correcta (tabla de estados × acción, probada).
  2. Las acciones destructivas (Cancelar) son secundarias, con texto de consecuencia y confirmación.
  3. El cobro («Cobrado/Pendiente») es visible sin scroll y se confirma con un botón explícito (no «casilla + enlace Guardar»).
  4. Los pedidos históricos siguen en solo lectura, con aviso claro.
  5. AA verificado; carga ≤ 1 s.
  6. Prueba de usuarios: avanzar un pedido de «nuevo» a «despachado» sin ayuda.
- **Prioridad.** P1. **Depende de:** M10-11, M10-12. **Estimación.** M–L.

### [M10-14] Preparación, tandas y despacho: flujo de depósito mobile-first
- **Descripción.** Rediseñar Preparar, Tandas (hoja de picking) y Despacho para celular/tablet según M10-04: objetivos grandes, acción principal abajo, avance de tanda, confirmaciones claras, efectivo a cobrar con importe grande, barra inferior de tareas, modo alto contraste.
- **Criterios de aceptación.**
  1. Medidas de objetivo y contraste **iguales a las decididas en M10-04**.
  2. Todo el flujo se completa **solo con el celular** (sin escritorio) y con una mano.
  3. Los pedidos se ordenan por límite de despacho; el tiempo restante se lee a 1 m de distancia.
  4. Acciones sin retorno muestran consecuencia y ofrecen «Deshacer» donde el sistema lo permita (lista de cuáles se pueden: documentada).
  5. El «un solo envío» es el mecanismo común de M10-16, no un script propio.
  6. Sin scroll horizontal de 360 px a tablet vertical.
  7. Prueba en el depósito con ≥ 3 personas: tiempo y errores no peores que la línea de base (M10-01), idealmente mejores.
- **Prioridad.** P1. **Depende de:** M10-04, M10-06, M10-08, M10-16. **Estimación.** L–XL.

### [M10-15] Estrategia de alertas
- **Descripción.** Implementar los 3 niveles (crítico/atención/informativo), agrupación, centro de avisos accesible desde la campana, reglas de color, campo `nivel` por tipo de aviso, y registro de acción por aviso para medir la tasa de acción.
- **Criterios de aceptación.**
  1. Cada tipo de aviso existente está clasificado en un nivel con dueño, destinatario y acción esperada (tabla aprobada por Deutsch).
  2. La campana muestra un punto/contador solo por avisos de nivel crítico o atención; los informativos no generan insignia roja.
  3. Los contadores de trabajo (preguntas/mensajes/reclamos pendientes) dejan de ser rojos.
  4. Avisos del mismo tipo se agrupan («8 preguntas sin responder»).
  5. Existe un reporte mensual por tipo de aviso: cantidad, leídos, accionados.
  6. Reglas de color/ícono/texto documentadas y revisadas contra WCAG 1.4.1.
  7. Sin sonido por defecto; opción de activar si el equipo lo pide.
- **Prioridad.** P1. **Depende de:** M10-05, M10-06, M10-11; M10-01 (datos). **Estimación.** L.

### [M10-16] Formularios, errores y un solo envío
- **Descripción.** Patrón único de formularios: una columna, validación en línea al salir del campo, resumen de errores arriba, conservar lo ingresado, plantilla de mensaje «qué pasó + qué hacer», y un mecanismo global de «un solo envío» (botón deshabilitado + «Enviando…») para todos los formularios POST del panel.
- **Criterios de aceptación.**
  1. Ningún formulario POST del panel se puede enviar dos veces con doble clic (prueba automática sobre todos los formularios).
  2. Ante un error de validación se conserva lo ingresado y el foco va al resumen de errores, con enlaces a cada campo.
  3. Cada mensaje de error de los formularios principales (pedido manual, estados, cobro, respuestas, mayoristas) sigue la plantilla del glosario (M10-09); revisión de **≥ 30 mensajes**.
  4. Los errores 403/404/500 explican qué hacer y cómo avisar (con código de referencia).
  5. Las acciones difíciles de deshacer muestran su consecuencia antes de confirmarse.
  6. Prueba con lector de pantalla del flujo de pedido manual.
- **Prioridad.** P1. **Depende de:** M10-06, M10-09. **Estimación.** L.

### [M10-17] Accesibilidad base (WCAG 2.2 AA) y control automático
- **Descripción.** Cerrar lo que la auditoría marca (AU #4): enlace saltar al contenido, landmarks, `aria-current`, foco visible, `aria-live` en mensajes, nombre accesible de la campana, contraste, tamaño de objetivos; sumar revisión automática en integración continua.
- **Criterios de aceptación.**
  1. Revisión automática (herramienta tipo axe) sin errores críticos en las pantallas principales (lista de pantallas definida) y corre en cada cambio.
  2. Los 6 flujos clave (propuesta §5) se completan solo con teclado.
  3. Revisión manual con lector de pantalla de al menos 3 flujos, con informe.
  4. Contraste verificado con prueba automática sobre los tokens (M10-05).
  5. Todo estado (pedido, cobro, alerta) se entiende en escala de grises.
  6. Objetivos ≥ 24 px en todo el panel y los de depósito según M10-04.
- **Prioridad.** P1. **Depende de:** M10-05, M10-06. **Estimación.** M.

---

## Fase D: resto de módulos

### [M10-18] Buscador global
- **Descripción.** Buscador en la barra superior (`/` y `Ctrl/⌘+K`), con resultados agrupados (Pedidos, Clientes, Productos, Preguntas) y filtrados por permisos; ícono de búsqueda en la barra inferior móvil.
- **Criterios de aceptación.**
  1. Encuentra por n.º de pedido, nombre/CUIT de comprador o cliente, SKU y nombre de producto.
  2. Nunca devuelve resultados que el rol no puede ver (prueba por rol).
  3. Responde en ≤ 300 ms para la consulta típica con volumen de prueba (propuesta a calibrar con M10-01).
  4. Usable solo con teclado y con lector de pantalla (`role="combobox"`/`listbox` correcto).
  5. El placeholder muestra el atajo; el estado vacío sugiere qué probar.
  6. Prueba: ≥ 80 % de las tareas «encontrar X» se resuelven con el buscador en ≤ 15 s (a ajustar tras M10-01).
- **Prioridad.** P1. **Depende de:** M10-07, M10-08. **Estimación.** L.

### [M10-19] Atajos de teclado
- **Descripción.** Pocos atajos consistentes (`/`, `?`, `g` + letra, `j`/`k` en listas) con ayuda visible y sin interferir con campos de texto ni lectores de pantalla.
- **Criterios de aceptación.**
  1. Cada atajo está en la ayuda (`?`) y se muestra donde corresponde (menú/placeholder).
  2. Ningún atajo se dispara al escribir en un campo.
  3. Se pueden desactivar por usuario.
  4. Documentados en la guía para el cliente.
- **Prioridad.** P3. **Depende de:** M10-18. **Estimación.** S.

### [M10-20] Rendimiento percibido
- **Descripción.** Cumplir las metas de §11: retroalimentación en ≤ 100 ms, navegación sin recargar el esqueleto (`hx-boost`/parcial), indicadores a partir de 1 s, progreso con cancelar a partir de 10 s, HTMX servido localmente, sin saltos de diseño por contadores; medición de campo.
- **Criterios de aceptación.**
  1. HTMX y demás scripts críticos se sirven desde el propio sitio (sin CDN en el camino de carga).
  2. Cada pantalla principal tiene un **presupuesto de tiempo** definido y probado en `tests/test_rendimiento.py` (o equivalente).
  3. Las operaciones de más de 1 s muestran un indicador con texto; las de más de 10 s, progreso y botón Cancelar (lista de operaciones revisada: etiquetas, tandas, exportaciones).
  4. Medición en el dispositivo del depósito: valores antes/después registrados.
  5. Cambio de pantalla sin salto de diseño (verificado visualmente en 3 pantallas).
- **Prioridad.** P1. **Depende de:** M10-01, M10-08. **Estimación.** M–L.

### [M10-21] Atención de Mercado Libre (preguntas, mensajes, reclamos): flujo de responder
- **Descripción.** Rediseñar las colas y fichas: cola por antigüedad con tiempo transcurrido, respuestas guardadas a un toque, un botón primario «Enviar», paso automático a la siguiente.
- **Criterios de aceptación.**
  1. La cola muestra la antigüedad y se ordena por la más vieja.
  2. Responder una pregunta con respuesta guardada toma ≤ 3 interacciones (medido).
  3. Tras enviar, se pasa a la siguiente de la cola, con «Volver a la lista».
  4. Los contadores no son rojos (sí los vencidos o reclamos abiertos, según M10-15).
  5. Prueba: Ventas responde 5 preguntas más rápido que la línea de base (M10-01).
- **Prioridad.** P2. **Depende de:** M10-06, M10-15. **Estimación.** M.

### [M10-22] Catálogo y stock
- **Descripción.** Listas y fichas de Catálogo, Productos sin vincular, Stock y precios por canal y Calidad de datos con el patrón de listas; flujo de vincular con una acción clara.
- **Criterios de aceptación.**
  1. Las 4 pantallas usan la tabla y los filtros del sistema; en tablet, tarjetas.
  2. Vincular un producto toma ≤ 3 interacciones desde la lista (medido).
  3. Los hallazgos de calidad se priorizan por impacto (no un listado plano).
  4. AA verificado.
- **Prioridad.** P2. **Depende de:** M10-12. **Estimación.** M–L.

### [M10-23] Mayoristas (administración): clientes, aprobación, cobro y faltantes
- **Descripción.** Rediseñar clientes, invitaciones, aprobación, confirmación de pago, faltantes y ajustes con los flujos de §5.5 y §5.6, y la ficha del cliente con «Armar pedido para este cliente».
- **Criterios de aceptación.**
  1. «Clientes por aprobar» aparece en Hoy del administrador y lleva a la ficha.
  2. Aprobar/Rechazar son dos botones claros, con motivo obligatorio al rechazar y texto de «qué pasa después».
  3. Confirmar pago muestra importe, medio y referencia antes de confirmar.
  4. El flujo de faltantes (marcar, resolver con saldo o reintegro) explica cada consecuencia en castellano simple.
  5. Prueba de usuarios: el administrador aprueba un cliente y confirma un pago sin ayuda.
- **Prioridad.** P2. **Depende de:** M10-06, M10-13, M10-16. **Estimación.** L.

### [M10-24] Reportes como tablero
- **Descripción.** Una pantalla de resumen con 4–6 indicadores y comparativo destacado (el segundo en detalle), gráficos con tabla alternativa, y filtros con divulgación progresiva.
- **Criterios de aceptación.**
  1. El resumen muestra un solo comparativo principal por KPI; el otro, expandible.
  2. Cada gráfico tiene tabla de datos alternativa accesible.
  3. Colores de gráfico distinguibles sin depender solo del tono (forma/etiqueta) y con contraste ≥ 3:1.
  4. Exportar a Excel sigue funcionando igual (prueba existente verde).
  5. Probado con el dueño/administrador: responde 3 preguntas de negocio en ≤ 2 minutos.
- **Prioridad.** P3. **Depende de:** M10-06, M10-17. **Estimación.** M.

### [M10-25] Pantallas de sistema: integraciones, usuarios, auditoría, expresos, tipos de aviso
- **Descripción.** Aplicar patrones y componentes; la salud de integraciones como semáforo claro y accionable; la pantalla de Usuarios con etiquetas de permisos legibles.
- **Criterios de aceptación.**
  1. Estado de cada integración con ícono + texto y la acción para repararla.
  2. Auditoría con filtros y búsqueda y lectura de cambios legible.
  3. Usuarios: asignar un rol toma ≤ 3 interacciones; los permisos se agrupan por área.
  4. AA verificado.
- **Prioridad.** P3. **Depende de:** M10-12, M10-17. **Estimación.** M.

---

## Fase E: tienda, migración, pruebas y continuidad

### [M10-26] Tienda mayorista: sistema común, auditoría y estilo vivo
- **Descripción.** Que tienda y panel compartan tokens y componentes; convertir `/mayorista/estilo/` en la guía común; auditar la tienda con los mismos criterios (AA, táctil, errores, rendimiento en celular); revisar el flujo de pedido con clientes reales.
- **Criterios de aceptación.**
  1. Una sola fuente de tokens y componentes para panel y tienda (sin duplicados).
  2. La página de estilo documenta todos los componentes del panel y de la tienda.
  3. Informe de auditoría de la tienda (AA, objetivos táctiles, errores, rendimiento) con problemas priorizados; los de impacto alto, resueltos.
  4. Prueba con ≥ 2 clientes mayoristas reales en el flujo de pedido (cuando Deutsch los pueda convocar).
  5. Sin cambios en URLs ni en el flujo de compra.
- **Prioridad.** P2. **Depende de:** M10-05, M10-06. **Estimación.** M.

### [M10-27] Migración gradual pantalla por pantalla (transversal)
- **Descripción.** Gobierno de la migración: interruptor por usuario, orden de pantallas, lista de control por pantalla, regresión visual, retiro del esqueleto viejo al final.
- **Criterios de aceptación.**
  1. Lista de control por pantalla aplicada y firmada en cada pantalla migrada (tokens, componentes, AA, responsive 360 px, estados vacío/error/carga, textos, prueba de usuarios, pruebas verdes).
  2. Capturas automáticas antes/después de las pantallas clave guardadas.
  3. Ninguna URL ni permiso cambia (comprobado por las pruebas actuales en cada entrega).
  4. Plan de vuelta atrás probado (volver al esqueleto viejo con un clic).
  5. El esqueleto viejo se retira solo cuando **todas** las pantallas del plan están migradas y Deutsch lo aprueba.
- **Prioridad.** P0. **Depende de:** M10-08. **Estimación.** M (más seguimiento continuo).

### [M10-28] Rondas de pruebas de usabilidad con usuarios reales (transversal)
- **Descripción.** Rondas con 3 personas por rol: después del prototipo (M10-03), después del depósito (M10-14), después de Pedidos (M10-12/13) y al final; mismas tareas que la línea de base para comparar.
- **Criterios de aceptación.**
  1. **≥ 3 rondas** hechas con **3 usuarios por rol** (o todos los disponibles).
  2. Cada ronda produce un informe corto: éxito, tiempo, errores, SEQ/SUS, hallazgos y decisiones.
  3. Cada hallazgo grave se convierte en un ticket o decisión documentada.
  4. Se compara contra la línea de base (M10-01) y se informa si mejoró, empeoró o quedó igual.
- **Prioridad.** P0. **Depende de:** M10-01. **Estimación.** M (repartido).

### [M10-29] Medición de uso y métricas de UX en producción
- **Descripción.** Registro simple, sin datos personales sensibles, de: uso de módulos, uso del buscador y atajos, tiempos de operaciones, errores de formulario, tasa de acción de avisos.
- **Criterios de aceptación.**
  1. Un panel interno (solo administrador) muestra las métricas definidas en `propuesta-front.md` §12.2.
  2. No se registran contraseñas ni datos de clientes; el campo guardado está documentado.
  3. Retención y acceso definidos y aprobados por Deutsch.
  4. Se puede apagar sin romper nada.
- **Prioridad.** P2. **Depende de:** M10-15, M10-20. **Estimación.** M.

### [M10-30] Guía para el equipo y ayuda en contexto
- **Descripción.** Actualizar la guía simple para Maico/Deutsch (regla ya vigente) con cada cambio; ayuda breve en cada pantalla («¿Cómo se usa?»); aviso de novedades al activar el esqueleto nuevo; capacitación corta por rol.
- **Criterios de aceptación.**
  1. La guía para el cliente describe cada cambio de navegación y flujo, con capturas, antes de activarlo.
  2. Cada pantalla migrada tiene una ayuda corta (≤ 5 líneas) que abre y cierra con el teclado.
  3. Hay un «qué cambió» visible la primera vez que un usuario activa el esqueleto nuevo.
  4. Una sesión de capacitación de ≤ 30 minutos por rol, realizada y registrada.
- **Prioridad.** P2. **Depende de:** M10-08. **Estimación.** S–M (continuo).

### [M10-31] Modo alto contraste y tamaño de letra
- **Descripción.** Opción por usuario de alto contraste y de tamaño de texto mayor (útil con luz fuerte, baja visión y cansancio); recordada por usuario y por dispositivo.
- **Criterios de aceptación.**
  1. El modo alto contraste cumple **≥ 7:1** en texto normal (AAA) y se aplica a todo el panel.
  2. El texto se agranda al 200 % sin perder funciones ni generar scroll horizontal.
  3. La opción se recuerda al volver a entrar.
  4. Probado en el depósito (M10-04) con luz fuerte.
- **Prioridad.** P2. **Depende de:** M10-05, M10-04. **Estimación.** S–M.

---

## Resumen

- **Total: 31 tickets** (4 de prueba/prototipo, 6 de cimientos, navegación y accesibilidad, 15 de pantallas y módulos, 6 de cierre y continuidad).
- **P0: M10-01, 02, 03, 04, 05, 06, 07, 08, 27, 28** (10). **P1: M10-09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20** (11). **P2: M10-21, 22, 23, 26, 29, 30, 31** (7). **P3: M10-19, 24, 25** (3).
- Estimación total gruesa: sumando los rangos de cada ticket (S≈2, M≈4, L≈8, XL≈12 días) da del orden de **150 a 170 días de trabajo de una persona, unas 30 a 35 semanas-persona**. Es un orden de magnitud sin compromiso: se puede paralelizar (diseño y desarrollo) y recortar si se posterga lo P2/P3; depende de cuántas rondas de prueba se hagan y de qué tan rápido responda Deutsch a las decisiones. Un primer corte útil (Fases A y B + M10-10, 11, 14, 15, 16, 17) ronda las 16 a 20 semanas-persona.
- Dependencias principales: Fase A condiciona a B y a M10-14; M10-05/06 son la base de casi todo; M10-08 habilita la migración; M10-16 es prerrequisito de M10-14.
