# Tickets propuestos: módulo «M10 · Front y experiencia de uso»

Fecha: 2026-11-20. **Cargados en Plane el 2026-11-20** (proyecto DDEV, módulo «M10 · Front y experiencia de uso», estado Backlog) **como plan: no ejecutados.** **Versión de 13 tickets (20/11/2026):** el dueño aprobó reducir los 31 originales a 13, con el mismo alcance; los 18 absorbidos quedaron en Plane en estado Cancelled, fuera del módulo, con un comentario que dice en cuál se fusionaron (tabla de equivalencia al final). Se empieza a trabajar cuando Deutsch/Maico den el OK (regla de trabajo vigente: un módulo por vez, OK explícito).

**Convenciones.** Prioridad: **P0** bloquea todo lo demás o es base · **P1** alto impacto · **P2** importante · **P3** deseable (en Plane: P0 = alta, P1 = media, P2 = baja, P3 = ninguna; un ticket fusionado toma la prioridad más alta de los que junta). Estimación gruesa en días de trabajo de una persona (S ≤ 2 días, M 3–5, L 6–10, XL > 10); son órdenes de magnitud, no compromisos; en los fusionados se suman las partes (S≈2, M≈4, L≈8, XL≈12). «Prototipo» = se puede probar sin construir (HTML estático, Figma o similar). Los criterios de aceptación son verificables (alguien puede mirar y decir sí/no); en los fusionados se agrupan por subtítulo y no se perdió ninguno.

---

## Orden recomendado (resumen)

```
Fase A  Medir y probar sin construir       M10-01 → M10-02 → M10-03 (primera parte: prueba en el depósito)
Fase B  Cimientos (sin cambiar el aspecto) M10-04 → M10-05 → M10-06 → M10-10
Fase C  Pantallas por impacto              M10-07 → M10-08 → M10-09 → M10-03 (segunda parte: nuevo flujo de depósito)
Fase D  Resto de módulos                   M10-11
Fase E  Tienda                             M10-12
Transversal (todo el módulo)               M10-13
```
(M10-13 corre **en paralelo** durante todo el módulo. M10-03 empieza en la fase A con el prototipo y se construye en la C. Las métricas en producción de M10-01 se cierran en C/D.)

### Qué se puede probar con prototipo antes de construir (antes de gastar en código)

| Qué | Cómo | Ticket |
|---|---|---|
| Si los grupos y nombres de la barra lateral los entiende el equipo | Card sorting abierto + tree test con papel o una herramienta online, con el personal real | M10-02 |
| Si el inicio por rol sirve | Prototipo clickeable de 4 pantallas, una persona por rol | M10-02 |
| Si el flujo de Preparar/Despacho funciona con guantes, luz y celular reales | Prototipo en HTML estático en el celular del depósito, en el lugar | M10-03 |
| Tamaños táctiles y contraste | Misma prueba de M10-03 con variantes de 44 y 56 px (alimenta M10-04) | M10-03 |
| Niveles y reglas de alertas | Revisar con el equipo las alertas de los últimos 30 días y simular la nueva clasificación en papel | M10-09 |

---

## Fase A: medir y probar sin construir

### [M10-01] Medición: línea de base y métricas de uso en producción
- **Descripción.** Antes de cambiar nada, medir cómo se usa hoy: tiempos y errores en tareas clave con 3 personas por rol; y, desde datos que ya tiene el sistema, qué módulos se usan, cuántos avisos se generan por día y por tipo y cuántos se leen/accionan, tiempos de respuesta de las pantallas principales en el celular/tablet del depósito. (Auditoría `AU #3` y `AU #10` quedaron como «a confirmar».) Después, un registro simple, sin datos personales sensibles, de uso en producción: uso de módulos, uso del buscador y atajos, tiempos de operaciones, errores de formulario, tasa de acción de avisos.
- **Criterios de aceptación.**
  - *Línea de base (antes de cambiar nada)*
    1. Existe un documento con **8–10 tareas** por rol acordadas con Deutsch (ej.: armar una tanda, despachar 3 pedidos, responder una pregunta, cargar un pedido manual, aprobar un cliente).
    2. Se corrieron esas tareas con **3 usuarios por rol** (o todos los que haya, si son menos), con tiempo, éxito y errores anotados.
    3. Hay una tabla de **alertas de los últimos 30 días** por tipo: cantidad, cuántas se leyeron, cuántas llevaron a una acción dentro de 24 h (si el dato no existe, queda anotado como faltante).
    4. Hay mediciones de tiempo de carga de Pedidos, Preparar, Despacho y Hoy **en el dispositivo real del depósito** (3 repeticiones, red real).
    5. Quedan fijadas, **con el equipo**, las metas numéricas del módulo (reemplazan las «a calibrar» de la propuesta).
  - *Métricas en producción*
    6. Un panel interno (solo administrador) muestra las métricas definidas en `propuesta-front.md` §12.2.
    7. No se registran contraseñas ni datos de clientes; el campo guardado está documentado.
    8. Retención y acceso definidos y aprobados por Deutsch.
    9. Se puede apagar sin romper nada.
- **Prioridad.** P0. **Depende de:** nada para empezar. La parte de métricas en producción necesita los niveles de aviso de M10-09 y la medición de tiempos de M10-10 (no cargado como bloqueo en Plane: esos dependen de la línea de base y sería un ciclo). **Fase.** A (producción se cierra en C/D). **Estimación.** M + M ≈ 8 días.
- *Junta los antiguos M10-01 y M10-29.*

### [M10-02] Navegación: card sorting, prueba de árbol y prototipo de navegación e inicio por rol
- **Descripción.** Con todo el personal que usa el panel (muestra chica; se lee como cualitativo, ver IN §19), descubrir cómo agrupan y nombran las ~25 secciones y probar la barra lateral propuesta (grupos y etiquetas). Con eso, prototipo clickeable (sin código de producción) de: barra lateral agrupada, barra superior mínima, buscador global y las 4 pantallas de inicio por rol, con datos de ejemplo realistas.
- **Criterios de aceptación.**
  - *Card sorting y prueba de árbol*
    1. Card sorting abierto hecho con **todas las personas que usan el panel** (mínimo 8; si son menos, se dice y se repite).
    2. Tree test de la propuesta con **≥ 6 tareas de encontrar** por rol; resultado registrado: % de primer clic correcto y dónde se pierden.
    3. Lista final de **grupos y nombres** aprobada por Deutsch (reemplaza o confirma la de `propuesta-front.md` §3.2).
    4. Se anotan las palabras exactas que usa el equipo (glosario, alimenta M10-06).
  - *Prototipo de navegación e inicio por rol*
    5. Hay un prototipo navegable de al menos 4 pantallas de inicio + navegación + buscador (fidelidad media, con la marca aplicada).
    6. Probado con **1–3 personas por rol**; cada persona completa las tareas de «encontrar» y de «qué hago primero hoy».
    7. Informe con decisiones: qué se mantiene, qué cambia, qué se descarta (cada cambio con la cita de la prueba).
    8. Aprobación de Deutsch antes de pasar a Fase B.
- **Prioridad.** P0. **Depende de:** M10-01 (tareas). **Fase.** A. **Estimación.** S–M + M ≈ 6–8 días. **Prototipo:** sí, es todo prototipo.
- *Junta los antiguos M10-02 y M10-03.*

### [M10-03] Depósito mobile: prueba en el lugar y nuevo flujo de Preparar y Despacho
- **Descripción.** Primero, prototipo (HTML estático) del flujo de Preparar → hoja de picking → Despacho con variantes de tamaño (44/48/56 px), contraste normal y alto, y acción abajo, probado en el depósito con guantes de trabajo, en el celular/tablet real, a distinta luz. Después, rediseñar Preparar, Tandas (hoja de picking) y Despacho para celular/tablet según lo decidido: objetivos grandes, acción principal abajo, avance de tanda, confirmaciones claras, efectivo a cobrar con importe grande, barra inferior de tareas, modo alto contraste.
- **Criterios de aceptación.**
  - *Primera parte: prueba en el depósito (prototipo)*
    1. Se probaron **≥ 3 personas del depósito** con sus guantes y dispositivos, en el lugar y en al menos dos condiciones de luz.
    2. Registro de aciertos de toque (toques errados / total) por tamaño de objetivo.
    3. Decisión documentada de **tamaño mínimo de objetivo, contraste y posición de acciones** para el modo depósito.
    4. Lista de problemas del dispositivo (brillo, sensibilidad táctil, conexión) para el equipo técnico.
  - *Segunda parte: nuevo flujo de depósito mobile-first*
    5. Medidas de objetivo y contraste **iguales a las decididas en la primera parte**.
    6. Todo el flujo se completa **solo con el celular** (sin escritorio) y con una mano.
    7. Los pedidos se ordenan por límite de despacho; el tiempo restante se lee a 1 m de distancia.
    8. Acciones sin retorno muestran consecuencia y ofrecen «Deshacer» donde el sistema lo permita (lista de cuáles se pueden: documentada).
    9. El «un solo envío» es el mecanismo común de M10-06, no un script propio.
    10. Sin scroll horizontal de 360 px a tablet vertical.
    11. Prueba en el depósito con ≥ 3 personas: tiempo y errores no peores que la línea de base (M10-01), idealmente mejores.
- **Prioridad.** P0. **Depende de:** M10-01 (para la prueba). La segunda parte además necesita M10-04, M10-05 y M10-06 (no cargado como bloqueo en Plane: la primera parte alimenta a M10-04 y sería un ciclo). **Fase.** A → C (primero prototipo en el depósito, después construir). **Estimación.** S–M + L–XL ≈ 11–15 días. **Prototipo:** sí, la primera parte.
- *Junta los antiguos M10-04 y M10-14.*

---

## Fase B: cimientos (sin cambiar el aspecto de las pantallas existentes)

### [M10-04] Sistema de diseño: tokens, componentes, colores de estado y modo alto contraste
- **Descripción.** Llevar los tokens de marca (`static/brand/tokens.css`) al panel: color (marca + estados + neutros), Source Sans 3 (con respaldo), escala tipográfica, espaciado, tres densidades (cómoda/normal/compacta), favicon y logo en cabecera; documentado en la página de estilo viva (ver M10-12), **sin cambiar** HTML de las pantallas todavía. Componentes reutilizables (partiendo de `templates/store/components/`): botón (jerarquía), chip de estado, mensaje/alerta, tabla (encabezado fijo, columnas, selección múltiple, vista tarjeta), ficha, formulario (campo, error, resumen), estado vacío, filtros con chips, paginación, indicador de carga. Chips y colores de estado/alerta rediseñados: cada estado con ícono + texto + color de la nueva paleta; rojo reservado; «estado» separado de «alerta». Opción por usuario de alto contraste y de texto más grande (luz fuerte, baja visión, cansancio), recordada por usuario y por dispositivo.
- **Criterios de aceptación.**
  - *Tokens, tipografía, logo y densidad*
    1. Existe un único archivo de tokens usado por panel y tienda; Tailwind los expone (`bg-brand-*`, `text-brand-*`).
    2. Pasa una prueba automática de contraste: cada par texto/fondo declarado cumple **≥ 4,5:1** (3:1 para texto grande, bordes y íconos de control); el azul `#007DC5` no se usa para texto normal.
    3. El panel carga Source Sans 3 con respaldo Calibri/sans de sistema, sin salto visible de diseño.
    4. El logo negativo se muestra en la cabecera sin deformación, a ≥ 38 px de ancho (mínimo de 10 mm del manual) y con el área de seguridad respetada; favicon = isotipo.
    5. Documentado: qué colores están **reservados** para alertas (rojo/ámbar).
  - *Biblioteca de componentes*
    6. Cada componente está documentado con ejemplo en la página de estilo y usa solo tokens.
    7. Cada componente cumple AA (foco visible, contraste, `aria-*` donde corresponde) y está probado con teclado.
    8. Hay pruebas automáticas de render de cada componente (con estados vacío, error, cargando).
    9. Un componente nuevo **no** rompe plantillas viejas (conviven; no se tocan todavía).
    10. «Una sola acción primaria por pantalla» queda en la guía y como **advertencia** en desarrollo si una plantilla usa dos.
  - *Estados de pedido y semántica de color*
    11. Tabla de **todos** los estados de `sales/states.py` con su chip (ícono, texto, color) documentada.
    12. Ningún estado depende solo del color (prueba visual en escala de grises).
    13. El rojo solo en: vencido, error bloqueante, acción destructiva (revisado por búsqueda en plantillas).
    14. El estado «Cancelado» y los «histórico» no usan colores de alerta.
    15. `FAMILY_CLASSES`/`status_classes` se reemplazan por el componente chip, con prueba de que cubre todos los estados.
  - *Modo alto contraste y tamaño de letra*
    16. El modo alto contraste cumple **≥ 7:1** en texto normal (AAA) y se aplica a todo el panel.
    17. El texto se agranda al 200 % sin perder funciones ni generar scroll horizontal.
    18. La opción se recuerda al volver a entrar.
    19. Probado en el depósito (prueba de M10-03) con luz fuerte.
- **Prioridad.** P0. **Depende de:** M10-02 (decisiones). También usa la densidad y el contraste decididos en la primera parte de M10-03 (no cargado como bloqueo en Plane para evitar el ciclo con la segunda parte de M10-03). **Fase.** B. **Estimación.** M + L + M + S–M ≈ 18–20 días. **Prototipo:** en parte (tamaños y contraste, con el prototipo de M10-03).
- *Junta los antiguos M10-05, M10-06, M10-11 y M10-31.*

### [M10-05] Esqueleto nuevo: barra lateral con interruptor por usuario, registro de navegación y buscador global
- **Descripción.** Un registro en código con grupo, ítem, etiqueta, ícono, URL y permiso que alimente barra lateral, barra inferior, buscador global y migas; con pruebas automáticas; no cambia permisos ni URLs. Esqueleto nuevo (`UI_V2`) con barra lateral agrupada, ítem activo marcado, grupo actual abierto; barra superior con logo, buscador, campana, usuario; barra inferior en celular/tablet; opción «volver a la versión anterior» por usuario; no cambia las pantallas internas. Buscador en la barra superior (`/` y `Ctrl/⌘+K`), con resultados agrupados (Pedidos, Clientes, Productos, Preguntas) y filtrados por permisos; ícono de búsqueda en la barra inferior móvil. El resto de los atajos de teclado está en M10-11, con prioridad baja.
- **Criterios de aceptación.**
  - *Registro único de navegación*
    1. Un solo lugar define toda la navegación; `_menu.html` actual se deriva de él (sin cambiar lo que ve cada rol).
    2. Test: para cada rol de `roles.py`, el conjunto de ítems visibles coincide con los **que hoy se ven** (21/16/8/7 enlaces; ver auditoría).
    3. Test: toda URL de módulo accesible por permisos aparece en el registro o en una lista explícita de excepciones.
    4. Un permiso inexistente en el registro rompe el test.
  - *Esqueleto nuevo con interruptor por usuario*
    5. Un usuario con el interruptor activo ve el esqueleto nuevo; los demás siguen igual (verificado por prueba).
    6. La página actual está marcada (`aria-current="page"`); la navegación tiene `aria-label`; hay enlace «Saltar al contenido».
    7. Funciona de 360 px a 1920 px sin scroll horizontal del esqueleto; en < 1024 px aparece la barra inferior.
    8. Los contadores de Mercado Libre y la campana no mueven el diseño al cargar (espacio reservado o renderizados en servidor).
    9. Un clic devuelve al esqueleto viejo y se recuerda por usuario.
    10. Las pruebas actuales (`test_url_permissions` y el resto) siguen verdes.
  - *Buscador global*
    11. Encuentra por n.º de pedido, nombre/CUIT de comprador o cliente, SKU y nombre de producto.
    12. Nunca devuelve resultados que el rol no puede ver (prueba por rol).
    13. Responde en ≤ 300 ms para la consulta típica con volumen de prueba (propuesta a calibrar con M10-01).
    14. Usable solo con teclado y con lector de pantalla (`role="combobox"`/`listbox` correcto).
    15. El placeholder muestra cómo abrirlo; el estado vacío sugiere qué probar.
    16. Prueba: ≥ 80 % de las tareas «encontrar X» se resuelven con el buscador en ≤ 15 s (a ajustar tras M10-01).
- **Prioridad.** P0. **Depende de:** M10-04 (y, a través de él, de la agrupación decidida en M10-02). **Fase.** B (el buscador puede cerrarse en C/D sin frenar el resto). **Estimación.** S–M + L + L ≈ 18 días. **Prototipo:** la navegación y el buscador ya se prueban en M10-02.
- *Junta los antiguos M10-07, M10-08 y M10-18. Los atajos (antiguo M10-19) pasaron a M10-11 el 20/11/2026, a pedido del dueño, para que queden con prioridad baja.*

### [M10-06] Lenguaje: glosario, formularios, mensajes de error y ayuda en contexto
- **Descripción.** Con los resultados de M10-02, fijar los nombres de las secciones y estados en el lenguaje del equipo (y la regla «Deutsch», nunca «DEUTSCH»); guía de tono (voseo, directo, cálido, sin dramatismo) y plantillas de mensajes (éxito, error «qué pasó + qué hacer»). Patrón único de formularios: una columna, validación en línea al salir del campo, resumen de errores arriba, conservar lo ingresado, y un mecanismo global de «un solo envío» (botón deshabilitado + «Enviando…») para todos los formularios POST del panel. Actualizar la guía simple para Maico/Deutsch (regla ya vigente) con cada cambio; ayuda breve en cada pantalla («¿Cómo se usa?»); aviso de novedades al activar el esqueleto nuevo; capacitación corta por rol.
- **Criterios de aceptación.**
  - *Glosario y guía de microcopy*
    1. Glosario publicado (en `docs/`) con cada término, su definición y dónde se usa.
    2. Guía de microcopy con **≥ 15 ejemplos** de «en vez de / decir» y las plantillas de mensajes.
    3. Las etiquetas del registro de navegación (M10-05) coinciden con el glosario.
    4. Revisado y aprobado por Deutsch.
  - *Formularios, errores y un solo envío*
    5. Ningún formulario POST del panel se puede enviar dos veces con doble clic (prueba automática sobre todos los formularios).
    6. Ante un error de validación se conserva lo ingresado y el foco va al resumen de errores, con enlaces a cada campo.
    7. Cada mensaje de error de los formularios principales (pedido manual, estados, cobro, respuestas, mayoristas) sigue la plantilla del glosario; revisión de **≥ 30 mensajes**.
    8. Los errores 403/404/500 explican qué hacer y cómo avisar (con código de referencia).
    9. Las acciones difíciles de deshacer muestran su consecuencia antes de confirmarse.
    10. Prueba con lector de pantalla del flujo de pedido manual.
  - *Guía para el equipo y ayuda en contexto*
    11. La guía para el cliente describe cada cambio de navegación y flujo, con capturas, antes de activarlo.
    12. Cada pantalla migrada tiene una ayuda corta (≤ 5 líneas) que abre y cierra con el teclado.
    13. Hay un «qué cambió» visible la primera vez que un usuario activa el esqueleto nuevo.
    14. Una sesión de capacitación de ≤ 30 minutos por rol, realizada y registrada.
- **Prioridad.** P1. **Depende de:** M10-02, M10-04. La ayuda en contexto y el «qué cambió» necesitan el esqueleto de M10-05 (no cargado como bloqueo, para que el glosario pueda empezar antes). **Fase.** B (glosario) → C (formularios); guía y ayuda continuas. **Estimación.** S + L + S–M ≈ 13 días.
- *Junta los antiguos M10-09, M10-16 y M10-30.*

### [M10-10] Accesibilidad (WCAG 2.2 AA) y rendimiento percibido
(Se lista acá por fase; el código sigue el orden de la fusión.)
- **Descripción.** Cerrar lo que la auditoría marca (AU #4): enlace saltar al contenido, landmarks, `aria-current`, foco visible, `aria-live` en mensajes, nombre accesible de la campana, contraste, tamaño de objetivos; sumar revisión automática en integración continua. Cumplir las metas de §11: retroalimentación en ≤ 100 ms, navegación sin recargar el esqueleto (`hx-boost`/parcial), indicadores a partir de 1 s, progreso con cancelar a partir de 10 s, HTMX servido localmente, sin saltos de diseño por contadores; medición de campo.
- **Criterios de aceptación.**
  - *Accesibilidad base y control automático*
    1. Revisión automática (herramienta tipo axe) sin errores críticos en las pantallas principales (lista de pantallas definida) y corre en cada cambio.
    2. Los 6 flujos clave (propuesta §5) se completan solo con teclado.
    3. Revisión manual con lector de pantalla de al menos 3 flujos, con informe.
    4. Contraste verificado con prueba automática sobre los tokens (M10-04).
    5. Todo estado (pedido, cobro, alerta) se entiende en escala de grises.
    6. Objetivos ≥ 24 px en todo el panel y los de depósito según M10-03.
  - *Rendimiento percibido*
    7. HTMX y demás scripts críticos se sirven desde el propio sitio (sin CDN en el camino de carga).
    8. Cada pantalla principal tiene un **presupuesto de tiempo** definido y probado en `tests/test_rendimiento.py` (o equivalente).
    9. Las operaciones de más de 1 s muestran un indicador con texto; las de más de 10 s, progreso y botón Cancelar (lista de operaciones revisada: etiquetas, tandas, exportaciones).
    10. Medición en el dispositivo del depósito: valores antes/después registrados.
    11. Cambio de pantalla sin salto de diseño (verificado visualmente en 3 pantallas).
- **Prioridad.** P1. **Depende de:** M10-01, M10-04, M10-05. **Fase.** B/C. **Estimación.** M + M–L ≈ 10 días.
- *Junta los antiguos M10-17 y M10-20.*

---

## Fase C: pantallas de mayor impacto

### [M10-07] Inicio por rol («Hoy»)
- **Descripción.** Reemplazar `core/home.html` por 4 inicios (Depósito, Ventas, Vendedor, Administrador) con 4–6 tarjetas accionables ordenadas por urgencia y una acción principal por rol (ver `propuesta-front.md` §4).
- **Criterios de aceptación.**
  1. Cada rol ve **solo** sus tarjetas, con permisos como hoy.
  2. Cada tarjeta muestra un número y lleva a la lista **ya filtrada**; los números coinciden con la lista (prueba automática).
  3. Hay estado vacío con mensaje útil («No hay pedidos para preparar. Último despacho a las 14:20»).
  4. **El rojo aparece solo si algo está vencido**; los contadores de trabajo no son rojos.
  5. Carga en ≤ 1 s con datos de prueba de volumen real (medido).
  6. Probado con ≥ 1 usuario por rol: elige correctamente «qué hago primero» sin ayuda.
- **Prioridad.** P1. **Depende de:** M10-04, M10-05. **Fase.** C. **Estimación.** L. **Prototipo:** ya probado en M10-02.
- *Antiguo M10-10 (sin fusión).*

### [M10-08] Pedidos: lista y ficha con el siguiente paso destacado
- **Descripción.** Rediseñar `sales/order_list.html` con el patrón de tabla nueva: 6–7 columnas por defecto + «Columnas», filtros con 2–3 visibles y «Más filtros», chips de filtros aplicados, orden por columna, tarjetas desde 1024 px hacia abajo, columna «Límite» con tiempo relativo; servirá de plantilla para las demás listas. Rediseñar `order_detail.html`: cabecera con estado + **un botón primario con el siguiente paso**; acciones alternativas secundarias; secciones en orden (qué hacer → quién/qué → cobro → historial); cobro como acción clara.
- **Criterios de aceptación.**
  - *Lista de pedidos (y patrón de listas)*
    1. A 1024 px de ancho o menos se ve en tarjetas, sin scroll horizontal; en escritorio, sin scroll horizontal de la tabla con columnas por defecto.
    2. Los filtros aplicados se muestran como chips y «Limpiar todo» los quita.
    3. La columna Límite muestra tiempo relativo (rojo solo si venció) y la fecha completa al pasar el cursor/tocar.
    4. El orden por defecto es por límite de despacho para pedidos abiertos.
    5. Misma información accesible que antes (nada se pierde: verificado contra lista de campos actual).
    6. Carga ≤ 1 s con 5.000 pedidos de prueba (existe `test_rendimiento` como base).
    7. Prueba de usuarios: Ventas y Depósito encuentran un pedido y su límite sin ayuda.
  - *Ficha de pedido: siguiente paso destacado*
    8. Para cada estado, la acción primaria es la correcta (tabla de estados × acción, probada).
    9. Las acciones destructivas (Cancelar) son secundarias, con texto de consecuencia y confirmación.
    10. El cobro («Cobrado/Pendiente») es visible sin scroll y se confirma con un botón explícito (no «casilla + enlace Guardar»).
    11. Los pedidos históricos siguen en solo lectura, con aviso claro.
    12. AA verificado; carga ≤ 1 s.
    13. Prueba de usuarios: avanzar un pedido de «nuevo» a «despachado» sin ayuda.
- **Prioridad.** P1. **Depende de:** M10-04, M10-05. **Fase.** C. **Estimación.** L + M–L ≈ 14 días.
- *Junta los antiguos M10-12 y M10-13.*

### [M10-09] Estrategia de alertas
- **Descripción.** Implementar los 3 niveles (crítico/atención/informativo), agrupación, centro de avisos accesible desde la campana, reglas de color, campo `nivel` por tipo de aviso, y registro de acción por aviso para medir la tasa de acción.
- **Criterios de aceptación.**
  1. Cada tipo de aviso existente está clasificado en un nivel con dueño, destinatario y acción esperada (tabla aprobada por Deutsch).
  2. La campana muestra un punto/contador solo por avisos de nivel crítico o atención; los informativos no generan insignia roja.
  3. Los contadores de trabajo (preguntas/mensajes/reclamos pendientes) dejan de ser rojos.
  4. Avisos del mismo tipo se agrupan («8 preguntas sin responder»).
  5. Existe un reporte mensual por tipo de aviso: cantidad, leídos, accionados.
  6. Reglas de color/ícono/texto documentadas y revisadas contra WCAG 1.4.1.
  7. Sin sonido por defecto; opción de activar si el equipo lo pide.
- **Prioridad.** P1. **Depende de:** M10-01 (datos), M10-04. **Fase.** C. **Estimación.** L. **Prototipo:** sí (simulación en papel).
- *Antiguo M10-15 (sin fusión).*

---

## Fase D: resto de módulos

### [M10-11] Resto de módulos: atención ML, catálogo y stock, mayoristas, reportes, pantallas de sistema y atajos de teclado
- **Descripción.** Llevar al sistema nuevo las pantallas que quedan. **Atención de Mercado Libre:** colas y fichas con cola por antigüedad y tiempo transcurrido, respuestas guardadas a un toque, un botón primario «Enviar», paso automático a la siguiente. **Catálogo y stock:** listas y fichas de Catálogo, Productos sin vincular, Stock y precios por canal y Calidad de datos con el patrón de listas; flujo de vincular con una acción clara. **Mayoristas (administración):** clientes, invitaciones, aprobación, confirmación de pago, faltantes y ajustes con los flujos de §5.5 y §5.6, y la ficha del cliente con «Armar pedido para este cliente». **Reportes como tablero:** una pantalla de resumen con 4–6 indicadores y comparativo destacado (el segundo en detalle), gráficos con tabla alternativa, y filtros con divulgación progresiva. **Pantallas de sistema** (integraciones, usuarios, auditoría, expresos, tipos de aviso): patrones y componentes; la salud de integraciones como semáforo claro y accionable; Usuarios con etiquetas de permisos legibles.
- **Criterios de aceptación.**
  - *Atención de Mercado Libre (preguntas, mensajes, reclamos)*
    1. La cola muestra la antigüedad y se ordena por la más vieja.
    2. Responder una pregunta con respuesta guardada toma ≤ 3 interacciones (medido).
    3. Tras enviar, se pasa a la siguiente de la cola, con «Volver a la lista».
    4. Los contadores no son rojos (sí los vencidos o reclamos abiertos, según M10-09).
    5. Prueba: Ventas responde 5 preguntas más rápido que la línea de base (M10-01).
  - *Catálogo y stock*
    6. Las 4 pantallas usan la tabla y los filtros del sistema; en tablet, tarjetas.
    7. Vincular un producto toma ≤ 3 interacciones desde la lista (medido).
    8. Los hallazgos de calidad se priorizan por impacto (no un listado plano).
    9. AA verificado.
  - *Mayoristas (administración): clientes, aprobación, cobro y faltantes*
    10. «Clientes por aprobar» aparece en Hoy del administrador y lleva a la ficha.
    11. Aprobar/Rechazar son dos botones claros, con motivo obligatorio al rechazar y texto de «qué pasa después».
    12. Confirmar pago muestra importe, medio y referencia antes de confirmar.
    13. El flujo de faltantes (marcar, resolver con saldo o reintegro) explica cada consecuencia en castellano simple.
    14. Prueba de usuarios: el administrador aprueba un cliente y confirma un pago sin ayuda.
  - *Reportes como tablero*
    15. El resumen muestra un solo comparativo principal por KPI; el otro, expandible.
    16. Cada gráfico tiene tabla de datos alternativa accesible.
    17. Colores de gráfico distinguibles sin depender solo del tono (forma/etiqueta) y con contraste ≥ 3:1.
    18. Exportar a Excel sigue funcionando igual (prueba existente verde).
    19. Probado con el dueño/administrador: responde 3 preguntas de negocio en ≤ 2 minutos.
  - *Pantallas de sistema*
    20. Estado de cada integración con ícono + texto y la acción para repararla.
    21. Auditoría con filtros y búsqueda y lectura de cambios legible.
    22. Usuarios: asignar un rol toma ≤ 3 interacciones; los permisos se agrupan por área.
    23. AA verificado.
  - *Atajos de teclado (prioridad más baja: se hacen al final, si hay tiempo)*
    24. Pocos atajos consistentes (`?`, `g` + letra, `j`/`k` en listas); cada uno está en la ayuda (`?`) y se muestra donde corresponde.
    25. Ningún atajo se dispara al escribir en un campo.
    26. Se pueden desactivar por usuario.
    27. Documentados en la guía para el cliente.
- **Prioridad.** P2 (Reportes y Sistema solos eran P3; los atajos, P3, van último). **Depende de:** M10-05, M10-06, M10-08, M10-09 (niveles de alerta, para Atención ML), M10-10 (control de accesibilidad, para Reportes y Sistema). **Fase.** D. **Estimación.** M + M–L + L + M + M + S ≈ 28 días (se puede partir por pantalla al ejecutarlo).
- *Junta los antiguos M10-21, M10-22, M10-23, M10-24, M10-25 y M10-19 (atajos, movidos desde M10-05).*

---

## Fase E: tienda

### [M10-12] Tienda mayorista: sistema común y estilo vivo
- **Descripción.** Que tienda y panel compartan tokens y componentes; convertir `/mayorista/estilo/` en la guía común; auditar la tienda con los mismos criterios (AA, táctil, errores, rendimiento en celular); revisar el flujo de pedido con clientes reales.
- **Criterios de aceptación.**
  1. Una sola fuente de tokens y componentes para panel y tienda (sin duplicados).
  2. La página de estilo documenta todos los componentes del panel y de la tienda.
  3. Informe de auditoría de la tienda (AA, objetivos táctiles, errores, rendimiento) con problemas priorizados; los de impacto alto, resueltos.
  4. Prueba con ≥ 2 clientes mayoristas reales en el flujo de pedido (cuando Deutsch los pueda convocar).
  5. Sin cambios en URLs ni en el flujo de compra.
- **Prioridad.** P2. **Depende de:** M10-04. **Fase.** E. **Estimación.** M.
- *Antiguo M10-26 (sin fusión).*

---

## Transversal (todo el módulo)

### [M10-13] Migración gradual y pruebas con usuarios reales (transversal)
- **Descripción.** Gobierno de la migración: interruptor por usuario, orden de pantallas, lista de control por pantalla, regresión visual, retiro del esqueleto viejo al final. Rondas de pruebas con 3 personas por rol: después del prototipo (M10-02), después del depósito (M10-03), después de Pedidos (M10-08) y al final; mismas tareas que la línea de base para comparar.
- **Criterios de aceptación.**
  - *Migración gradual pantalla por pantalla*
    1. Lista de control por pantalla aplicada y firmada en cada pantalla migrada (tokens, componentes, AA, responsive 360 px, estados vacío/error/carga, textos, prueba de usuarios, pruebas verdes).
    2. Capturas automáticas antes/después de las pantallas clave guardadas.
    3. Ninguna URL ni permiso cambia (comprobado por las pruebas actuales en cada entrega).
    4. Plan de vuelta atrás probado (volver al esqueleto viejo con un clic).
    5. El esqueleto viejo se retira solo cuando **todas** las pantallas del plan están migradas y Deutsch lo aprueba.
  - *Rondas de pruebas de usabilidad con usuarios reales*
    6. **≥ 3 rondas** hechas con **3 usuarios por rol** (o todos los disponibles).
    7. Cada ronda produce un informe corto: éxito, tiempo, errores, SEQ/SUS, hallazgos y decisiones.
    8. Cada hallazgo grave se convierte en un ticket o decisión documentada.
    9. Se compara contra la línea de base (M10-01) y se informa si mejoró, empeoró o quedó igual.
- **Prioridad.** P0. **Depende de:** transversal; las rondas arrancan con M10-01 y la migración con el interruptor de M10-05 (no se carga como bloqueo en Plane, para no frenarlo). **Fase.** Todo el módulo. **Estimación.** M + M ≈ 8 días, repartidos (más seguimiento continuo).
- *Junta los antiguos M10-27 y M10-28.*

---

## Resumen

- **Total: 13 tickets** (versión reducida del 20/11/2026; antes 31, mismo alcance).
- **P0: M10-01, 02, 03, 04, 05, 13** (6). **P1: M10-06, 07, 08, 09, 10** (5). **P2: M10-11, 12** (2). Sin P3: lo que era P3 quedó dentro de tickets con prioridad mayor (reportes, sistema y atajos de teclado en M10-11, que es baja).
- **Dependencias cargadas en Plane (bloqueado por):** 02←01 · 03←01 · 04←02 · 05←04 · 06←02, 04 · 07←04, 05 · 08←04, 05 · 09←01, 04 · 10←01, 04, 05 · 11←05, 06, 08, 09, 10 · 12←04 · 13 sin bloqueo (transversal). Tres dependencias quedan solo escritas en el ticket para no crear ciclos ni frenar el arranque: la segunda parte de M10-03 necesita M10-04/05/06; las métricas en producción de M10-01 necesitan M10-09/10; la ayuda en contexto de M10-06 necesita M10-05.
- Estimación total gruesa: sumando los rangos de cada ticket (S≈2, M≈4, L≈8, XL≈12 días) da del orden de **150 a 170 días de trabajo de una persona, unas 30 a 35 semanas-persona** (igual que antes de la fusión). Es un orden de magnitud sin compromiso: se puede paralelizar (diseño y desarrollo) y recortar si se posterga lo P2; depende de cuántas rondas de prueba se hagan y de qué tan rápido responda Deutsch a las decisiones. Un primer corte útil (Fases A y B + M10-07, M10-09 y la segunda parte de M10-03) ronda las 16 a 20 semanas-persona.
- Dependencias principales: la fase A condiciona a B y al nuevo flujo de depósito (M10-03); M10-04 es la base de casi todo; M10-05 habilita la migración; el «un solo envío» de M10-06 es prerrequisito del flujo de depósito.

---

## Equivalencia con la versión de 31

| Antiguo (versión de 31) | Nuevo (versión de 13) | En Plane |
|---|---|---|
| M10-01 Línea de base de usabilidad y de uso real | M10-01 | DDEV-68 (se conserva) |
| M10-02 Card sorting abierto y prueba de árbol | M10-02 | DDEV-69 (se conserva) |
| M10-03 Prototipo de navegación e inicio por rol | M10-02 | DDEV-70 → Cancelled |
| M10-04 Prueba en el depósito | M10-03 | DDEV-71 (se conserva) |
| M10-05 Sistema de diseño: tokens, tipografía, logo, densidad | M10-04 | DDEV-72 (se conserva) |
| M10-06 Biblioteca de componentes compartida | M10-04 | DDEV-73 → Cancelled |
| M10-07 Registro único de navegación | M10-05 | DDEV-74 (se conserva) |
| M10-08 Esqueleto nuevo con interruptor por usuario | M10-05 | DDEV-75 → Cancelled |
| M10-09 Glosario, etiquetas y guía de microcopy | M10-06 | DDEV-76 (se conserva) |
| M10-10 Inicio por rol (Hoy) | M10-07 | DDEV-77 (se conserva) |
| M10-11 Estados de pedido y semántica de color | M10-04 | DDEV-78 → Cancelled |
| M10-12 Lista de pedidos nueva | M10-08 | DDEV-79 (se conserva) |
| M10-13 Ficha de pedido | M10-08 | DDEV-80 → Cancelled |
| M10-14 Preparación, tandas y despacho mobile-first | M10-03 | DDEV-81 → Cancelled |
| M10-15 Estrategia de alertas | M10-09 | DDEV-82 (se conserva) |
| M10-16 Formularios, errores y un solo envío | M10-06 | DDEV-83 → Cancelled |
| M10-17 Accesibilidad base (WCAG 2.2 AA) | M10-10 | DDEV-84 (se conserva) |
| M10-18 Buscador global | M10-05 | DDEV-85 → Cancelled |
| M10-19 Atajos de teclado | M10-11 | DDEV-86 → Cancelled |
| M10-20 Rendimiento percibido | M10-10 | DDEV-87 → Cancelled |
| M10-21 Atención de Mercado Libre | M10-11 | DDEV-88 (se conserva) |
| M10-22 Catálogo y stock | M10-11 | DDEV-89 → Cancelled |
| M10-23 Mayoristas (administración) | M10-11 | DDEV-90 → Cancelled |
| M10-24 Reportes como tablero | M10-11 | DDEV-91 → Cancelled |
| M10-25 Pantallas de sistema | M10-11 | DDEV-92 → Cancelled |
| M10-26 Tienda mayorista: sistema común | M10-12 | DDEV-93 (se conserva) |
| M10-27 Migración gradual (transversal) | M10-13 | DDEV-94 (se conserva) |
| M10-28 Rondas de pruebas con usuarios reales | M10-13 | DDEV-95 → Cancelled |
| M10-29 Medición de uso y métricas en producción | M10-01 | DDEV-96 → Cancelled |
| M10-30 Guía para el equipo y ayuda en contexto | M10-06 | DDEV-97 → Cancelled |
| M10-31 Modo alto contraste y tamaño de letra | M10-04 | DDEV-98 → Cancelled |

Los demás documentos de `docs/ux/` ya citan los códigos de la versión de 13.
