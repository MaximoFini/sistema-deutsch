# Auditoría de la UI actual (solo lectura)

Fecha: 2026-11-20. Método: lectura de `templates/`, `apps/accounts/roles.py`, `apps/sales/templatetags/orders.py`, `assets/css/source.css`, `static/brand/tokens.css`. **No se ejecutó la app ni se probó en dispositivos**: los problemas de tamaño/densidad son inferidos del código (clases Tailwind) y hay que confirmarlos con la línea de base (ticket M10-01). Los principios citados están desarrollados en `investigacion-neurociencia.md` (IN §n).

## Resumen en 30 segundos

El panel funciona y ya tiene aciertos importantes en el flujo de depósito (casillas grandes, tarjetas en celular, barra de acción fija, anti doble envío en Preparar). Los problemas graves son **estructurales**: una barra superior plana con hasta 21 enlaces, un inicio vacío, alertas sin jerarquía (el rojo se usa para todo), cero señales de accesibilidad en el esqueleto y un panel que no usa la marca que la tienda mayorista sí tiene.

### Cantidad de ítems en la barra superior por rol (calculada desde `_menu.html` + `roles.py`)

| Rol | Enlaces visibles | Detalle |
|---|---|---|
| Administrador | **21** | Inicio, Pedidos, Preparar, Tandas, Despacho, Expresos, Devoluciones, Catálogo, Sin vincular, Stock y precios, Calidad, Preguntas, Mensajes, Reclamos, Salud, Mayoristas, Reportes, Avisos, Integraciones, Usuarios, Auditoría |
| Ventas | **16** | Todo lo anterior salvo Expresos, Reportes, Integraciones, Usuarios, Auditoría |
| Depósito | **8** | Inicio, Pedidos, Preparar, Tandas, Despacho, Devoluciones, Catálogo, Avisos |
| Vendedor | **7** | Inicio, Pedidos, Catálogo, Preguntas, Mensajes, Mayoristas, Avisos |

(Más la etiqueta de grupo «Mercado Libre», que es texto gris `stone-400` y no un enlace.)

---

## Problemas ordenados por impacto

Escala de impacto: **Crítico** (afecta tareas diarias de varios roles o seguridad operativa), **Alto**, **Medio**, **Bajo**.

### 1. [Crítico] Navegación plana de hasta 21 enlaces, sin agrupar y sin marcar dónde estás
- **Evidencia.** `templates/_menu.html` lista todos los enlaces con la misma clase `hover:underline`; `base.html` los pone en una `nav` que en escritorio hace `flex-wrap` (se parte en 2–3 líneas) y en celular es una tira de scroll horizontal (`overflow-x-auto`) donde los ítems 8 a 21 quedan **fuera de pantalla sin pista**. No hay estado «activo» (`aria-current` ni estilo): el usuario **no ve en qué módulo está**. Tareas diarias (Pedidos, Preparar, Despacho) comparten el mismo nivel visual que configuración rara (Usuarios, Auditoría, Integraciones). El único agrupamiento es «Mercado Libre», hecho con un `<span>` de texto.
- **Principios.** Carga extrínseca (IN §1), proximidad/agrupación (IN §5), reconocer antes que recordar (IN §8), navegación vertical para muchas secciones (IN §3). Preparar → Tandas → Despacho es **un solo flujo** repartido en tres enlaces dispersos.
- **Impacto.** Todos los roles; peor en Administrador y Ventas (16–21 ítems) y en celular.

### 2. [Crítico] El inicio no sirve para trabajar
- **Evidencia.** `templates/core/home.html` (6 líneas): «Hola, {nombre}. Centro de pedidos Deutsch. **Los módulos de pedidos, catálogo y preparación se suman en las próximas etapas.**» El texto está obsoleto (los módulos ya existen) y no muestra nada accionable. La única señal de pendientes es la campana y los contadores de Mercado Libre en la barra.
- **Principios.** Visibilidad del estado del sistema (heurística #1), tablero de una pantalla por rol (IN §16), reducir recordar (IN §8).
- **Impacto.** Todos los roles al entrar; obliga a recorrer el menú para saber qué hacer.

### 3. [Crítico] Alertas sin jerarquía: el rojo significa 10 cosas distintas
- **Evidencia (conteos sobre `templates/`, excluyendo `store/`).** `text-red-700` aparece **56 veces**, `bg-red-50` 13, `border-red-300` 9, `bg-red-600` 4. Se usa rojo para: plazo de despacho vencido (`order_list.html`, `prepare.html`, `dispatch.html`), «Etiqueta sin imprimir», estado Cancelado (`orders.py: status_classes`), errores, «no está en el catálogo» (`order_detail.html`, `batch_detail.html`), cambios negativos en reportes (`reports/summary.html`), botón Cancelar, y **la insignia de conteo de trabajo normal** (`conversations/_menu_links.html`: cada cola de preguntas/mensajes/reclamos con items pendientes se pinta de rojo sólido `bg-red-600`). El ámbar es igual de promiscuo: 31 `text-amber-900`, 22 `bg-amber-50`, 13 `bg-amber-100` (cobro pendiente, aviso de lista truncada, pedido histórico, efectivo a cobrar, entorno de prueba). Además, el estado de pedido «especial» comparte ámbar con las advertencias (`FAMILY_CLASSES`).
- **Principios.** Fatiga de alertas y jerarquía de color reservada (IN §15), efecto de aislamiento (IN §9), preatentivos: si todo se destaca nada se destaca (IN §6).
- **Impacto.** Todos los roles; riesgo de que se ignore lo que de verdad vence (plazos de despacho, reclamos). **Medir antes de afirmar**: no tengo datos de cuántos avisos reciben ni cuántos se accionan.

### 4. [Alto] Accesibilidad base ausente en el esqueleto
- **Evidencia.** Búsqueda de `focus|sr-only|aria-|skip` en `base.html` y `_menu.html`: **0 resultados**. No hay *skip link*; la `nav` no tiene `aria-label`; los mensajes de Django (`base.html`) no tienen `role="status"` ni `aria-live` (la tienda mayorista sí: `store/base.html` usa `role="status"`); la campana es un emoji 🔔 con solo `title` (`alerts/_bell.html`), sin nombre accesible; no se definió un estilo de foco propio (el foco depende del navegador); los atajos de teclado no existen. Los 11 px (`text-[11px]` ×2) y los `text-xs` (228 usos) en información útil complican la lectura.
- **Contrastes calculados.** `text-stone-400` sobre blanco: **2,52:1** (falla AA; se usa para la etiqueta «Mercado Libre»). `text-stone-500` sobre blanco: 4,80:1 (pasa justo, pero sobre `stone-50`, el fondo de la página, baja a 4,59:1). `bg-red-600` con texto blanco: 4,83:1 (pasa). Rojo/ámbar/verde de los textos de estado: pasan (5,0–6,5:1).
- **Principios.** WCAG 2.2: 1.4.3 contraste (AA 4,5:1), 1.4.1 no depender solo del color, 2.4.1 saltar bloques, 4.1.3 mensajes de estado (IN §13). **Nota:** las referencias a 2.4.1 y 4.1.3 las cito de memoria (no abrí esas páginas).
- **Impacto.** Usuarios con teclado, lector de pantalla, baja visión o luz fuerte; también calidad general.

### 5. [Alto] El panel no usa la identidad de marca
- **Evidencia.** `base.html`: fondo `bg-stone-50`, texto `text-stone-900`, botones `bg-stone-900` (negro cálido de Tailwind, no `#231F20`), cabecera con la palabra «Deutsch» en texto (`font-semibold tracking-tight`), **sin logo, sin favicon, sin Source Sans 3** (la tienda mayorista sí carga la fuente y el favicon desde `store/base.html`). `assets/css/source.css` lo dice expresamente: «El panel no los usa todavía». Resultado: dos productos con aspecto distinto, y el manual pide «negro de la marca y celeste relacionado con el agua» para web.
- **Principios.** Consistencia y estándares (heurística #4); el manual de marca (Drive › 01 Logo e Identidad de Marca) manda usar la marca de forma disciplinada.
- **Impacto.** Percepción de calidad y confianza del dueño y del equipo; no afecta tareas, pero es lo más visible.

### 6. [Alto] Densidad y tamaño de texto de la información crítica
- **Evidencia.** `text-sm` 390 veces y `text-xs` 228. El **límite de despacho**, dato crítico para Depósito, va en `text-xs` (`order_list.html`, `prepare.html`, `dispatch.html`); método de envío, productos (`font-mono text-xs`) y fecha también. `order_list.html` muestra **9 columnas** (Pedido, Fecha, Comprador, Productos, Total, Cobro, Envío, Límite, Estado) desde `md` (768 px), es decir, **en una tablet vertical** se ve la tabla densa con scroll horizontal (`overflow-x-auto`). La ficha de pedido (`order_detail.html`) apila 4–6 secciones con `text-sm` y subtítulos `text-xs` sin jerarquía de «qué hago ahora».
- **Principios.** Jerarquía visual y atención (IN §6), carga cognitiva (IN §1), tablas densas (IN §17, evidencia baja: hipótesis).
- **Impacto.** Ventas y Depósito (lectura rápida repetida durante el día). **A confirmar** con mediciones en pantalla real.

### 7. [Alto] Filtros siempre abiertos y sin resumen de lo aplicado
- **Evidencia.** `order_list.html`: 8 controles a la vista (canal, estado, cobro, comprador, SKU, desde, hasta, históricos) + botón; son `<select>` y campos sin chips de filtros aplicados, sin vistas guardadas. Hay dos cajas de búsqueda con significados distintos («Comprador o n.º» y «SKU») y **no hay buscador global**. `reports/_layout.html` repite el patrón (período, canal, rangos). Una búsqueda de un pedido por cualquier dato (nombre, número, SKU, cliente mayorista) obliga a elegir antes el módulo.
- **Principios.** Divulgación progresiva (IN §7), reconocer vs. recordar (IN §8), carga cognitiva (IN §1).
- **Impacto.** Ventas y Vendedor, especialmente.

### 8. [Alto] Etiquetas del menú con vocabulario interno o ambiguo
- **Evidencia.** `_menu.html` y `roles.py`: «Tandas», «Expresos», «Sin vincular», «Calidad» (en `roles.py` se explica como «panel de calidad de datos»), «Salud» (= salud de las publicaciones de Mercado Libre), «Avisos», «Preparar» vs «Despacho». «Mayoristas» es el nombre del módulo de clientes mayoristas pero también el de la tienda. Algunas ya se explican en frases largas dentro de las pantallas (p. ej. el párrafo de `prepare.html`) porque el nombre solo no alcanza.
- **Principios.** Coincidencia con el mundo real y el lenguaje del usuario (heurística #2). **No verifiqué qué palabras usa el equipo de Deutsch**: puede que «tanda» sí sea su palabra. Pregunta abierta, ver `preguntas-abiertas.md`.
- **Impacto.** Usuarios nuevos y roles que usan módulos poco.

### 9. [Medio] Acciones principales sin jerarquía clara en la ficha de pedido
- **Evidencia.** `order_detail.html`, bloque «Pasar a:» — cada transición posible es un formulario con su propio botón; todos con `bg-stone-900` salvo Cancelar (borde rojo). El siguiente paso «natural» y las alternativas se ven igual de importantes. Las acciones de cobro (casilla + select + enlace «Guardar» subrayado) están en otra tarjeta más abajo. En `dispatch.html` las acciones de cada pedido son enlaces `text-xs` subrayados («Ver pedido», «Rótulo», «Marcar faltante»).
- **Principios.** Jerarquía/una acción principal (IN §6), prevención de errores (IN §14): botones iguales para acciones muy distintas.
- **Impacto.** Ventas y Depósito.

### 10. [Medio] Retroalimentación y rendimiento percibido desparejos
- **Evidencia.** El anti doble envío existe solo en `fulfillment/prepare.html` (script propio, inline) y en la tienda (`store/base.html`, genérico); `base.html` del panel **no tiene** un mecanismo común, así que los demás formularios (cambio de estado, pedido manual, cobro, respuestas de ML) no tienen ese resguardo. HTMX se carga desde `cdnjs.cloudflare.com` (dependencia externa en el camino de carga). El menú se rellena con un `hx-get` al cargar (`_menu.html`: contadores de Mercado Libre); los números aparecen **después** y pueden mover el layout. Hay dos sondeos a 60 s (campana y contadores). No hay indicadores de carga en lo que tarda (etiquetas PDF, armado de tandas, reportes).
- **Principios.** Respuesta en 0,1/1/10 s (IN §12), visibilidad del estado (heurística #1), prevención de errores (IN §14).
- **Impacto.** Todos; más visible con conexión lenta del depósito (no medido).

### 11. [Medio] Mobile y tablet del depósito: lo hecho está bien, faltan piezas
- **Lo que está bien (conservar).** `prepare.html`, `dispatch.html`, `batch_detail.html`: casillas de 24–28 px dentro de filas de ≥44 px, tarjetas en lugar de tabla en celular, barra de acción fija abajo (`fixed inset-x-0 bottom-0`) con relleno para que no tape contenido, `role="alert"` en el tope por tanda, recarga al volver con «Atrás» (`pageshow`).
- **Lo que falta.** (a) La navegación del celular es la misma tira horizontal de hasta 21 enlaces (Depósito tiene 8, razonable, pero Ventas 16); no hay barra inferior de tareas. (b) A partir de 768 px se pasa a la tabla (`md:block`), así que la tablet vertical pierde el diseño por tarjetas. (c) Los controles de los filtros tienen `py-2` (≈36–40 px); varios enlaces de acción son `text-xs` sin área táctil ampliada. (d) Las tildes de la lista de picking solo se guardan en el navegador de ese teléfono (lo dice la pantalla; es una decisión conocida de M6). (e) No se contempló luz fuerte (alto contraste) ni guantes; **no hay datos reales**.
- **Principios.** Fitts/objetivos táctiles (IN §4), WCAG 2.5.8 (24 px AA) / 2.5.5 (44 px).
- **Impacto.** Depósito.

### 12. [Medio] Pantallas con estructura distinta entre módulos
- **Evidencia.** Títulos `text-xl font-semibold` en el panel (la tienda usa `text-3xl font-bold`); filtros como grilla de selects en pedidos, pestañas + formulario en reportes, enlaces sueltos en Despacho; botones con distintos tamaños (`py-2`, `py-2.5`, `min-h-[44px]`, `py-1.5`). Cada plantilla repite sus clases Tailwind (no hay componentes en el panel; la tienda sí tiene `templates/store/components/`: `alert`, `button`, `field`, `table`, `status_badge`, `paginator`).
- **Principios.** Consistencia (heurística #4), carga extrínseca (IN §1).
- **Impacto.** Todos, de forma acumulativa; encarece cualquier cambio de diseño (hay que tocar ~60 plantillas).

### 13. [Medio] Mensajes del sistema y errores
- **Evidencia.** `base.html`: mensajes con colores por etiqueta (rojo/ámbar/verde) pero sin ícono, sin cierre, sin `aria-live`. Existen páginas 403/404/500 propias (`_error_base.html`) y textos en español claro en muchas validaciones (ej. «Máximo N por tanda. Desmarcá algunos.», «Se muestran los primeros X de Y. Usá los filtros.»: buen tono). Falta una **plantilla única** «qué pasó + qué hacer» y un resumen de errores en formularios largos (`manual_form.html`).
- **Principios.** Heurísticas #5 y #9, formularios (IN §14).
- **Impacto.** Ventas y Vendedor al cargar pedidos manuales.

### 14. [Bajo] Detalles de pulido
- Paginación con enlaces de texto «Anterior/Siguiente» pequeños (`_pagination.html`; en `order_list.html` además se repite inline): no salta a página, objetivo táctil chico.
- El badge de entorno («staging», etc.) es ámbar, igual que las advertencias reales.
- Tarjetas KPI de `reports/summary.html` con dos líneas `text-xs` de comparación (período anterior y año anterior) que repiten la misma estructura 4 veces; la lectura rápida pide un solo comparativo destacado y el otro en detalle.
- La paleta de canales (`apps/reports/queries.py: color`): `mayorista = #7c3aed` (violeta) ajeno a la marca; sirve para distinguir series, pero habría que revisar contraste y que no dependa solo del color (hoy el punto lleva `aria-hidden` y el nombre del canal al lado: bien).
- Gráficos (`reports/summary.html`) con `canvas` + `aria-label`: ok, pero sin tabla alternativa.

---

## Lo que está bien y se debe conservar

1. **Menú por permisos:** cada ítem depende de permisos reales (`perms.*`), lo que permite derivar menús por rol sin duplicar reglas.
2. **Diseño en dos modos de la lista de pedidos** (tabla en escritorio, tarjetas en celular) y la lógica de barra fija en Preparar/Despacho.
3. **Casillas grandes, mensajes en voseo claro, protección contra doble envío en Preparar, `role="alert"`.**
4. **Tokens de marca ya definidos y verificados** (`static/brand/tokens.css`, contrastes documentados) y **componentes de la tienda** (`templates/store/components/*`): hay base para un sistema de diseño sin empezar de cero.
5. **Páginas de error propias y página `/mayorista/estilo/`** como guía de estilo vivo.
6. **Pruebas automáticas** (`tests/test_url_permissions.py`, `tests/test_rendimiento.py`): permiten cambiar la presentación con red de seguridad.

## Qué no pude evaluar con el código solo

- Tiempos reales de carga y de respuesta en el celular/tablet del depósito.
- Cuántos avisos llegan por día por rol y cuántos se accionan.
- Cómo usan realmente el panel (qué módulos, en qué orden, qué errores cometen).
- Legibilidad al sol y con guantes.
- Estado de la tienda mayorista contra los mismos criterios (se audita en M10-26).
