# Propuesta de front: panel Deutsch

Fecha: 2026-11-20. Estado: **propuesta para validar**, no decisión tomada. Nada de esto se implementó.
Base: `investigacion-neurociencia.md` (IN) y `auditoria-ui-actual.md` (AU). Cada decisión importante lleva su **principio**, su **nivel de confianza** y la **alternativa descartada**.

Convenciones: «hipótesis» = decisión razonable pero sin respaldo directo para este sistema; se valida con prueba de usuarios (sección 12). Las medidas numéricas (px, ms, porcentajes) que no vienen de una norma son **propuestas a calibrar**, no hechos.

---

## 1. Principios rectores (cinco, para decidir todo lo demás)

1. **Una pantalla, una tarea principal, una acción principal.** (IN §1, §6) Todo lo que no ayuda a decidir o actuar en esa pantalla se esconde o se mueve.
2. **Agrupar por tarea, no por módulo técnico.** (IN §3, §5) El usuario piensa «voy a preparar pedidos», no «voy a Tandas».
3. **El color de alerta es un recurso escaso.** (IN §9, §15) Rojo solo para lo que de verdad no puede esperar.
4. **Mostrar, no hacer recordar.** (IN §8) Dónde estás, qué filtros hay, a quién representás, qué sigue.
5. **Lo probado con usuarios reales de Deutsch gana a lo citado.** (IN §0, §23) La evidencia orienta; la prueba decide.

---

## 2. Manual de marca: qué se extrae y cómo se aplica

Fuente: **Manual de Identidad Corporativa Deutsch (PDF, Drive › 01 Logo e Identidad de Marca)**, que pude leer completo desde Drive (texto extraído; las páginas de colores y logos son gráficas y la extracción de texto vino parcialmente desordenada, por eso los valores de color se toman de `static/brand/tokens.css`, que ya los consigna). También existe «Logo Deutsch R 2020 Variantes.pdf» (no lo abrí de nuevo; los SVG de `static/brand/` salen de ahí).

| Tema | Lo que dice el manual | Cómo se aplica al panel |
|---|---|---|
| **Paleta** | Azul **Pantone 3005** y negro **Black 6**; escalas de 80/60/40/20/5 % de cada uno; la web usa «el color negro de la marca y color celeste relacionado con el agua». Tokens del repo: azul `#007DC5`, negro `#231F20`, agua `#CBE6F5` y `#F4FAFE`. | Barra superior en negro `#231F20` con logo negativo; fondos en blanco y agua muy claro; azul para acción. Estados con colores semánticos propios (sección 8), nunca el azul de marca para «peligro». |
| **Tipografía** | Corporativa **Myriad Pro** (Thin a Black); secundaria **Calibri** «para la página web y textos editados por la empresa». | **Source Sans 3** (ya usada en la tienda; misma familia humanista que Myriad, libre) con Calibri y sans del sistema de respaldo. Es una **decisión ya tomada en tokens.css**, no del manual; se deja asentada. |
| **Logo** | Isologo = isotipo (una «D» inclinada que sugiere un nadador) + logotipo. Área de seguridad = la altura de la «D» alrededor. **Tamaño mínimo 10 mm de ancho.** Versiones: principal, negativa para fondos oscuros, versión sobre negro. **Prohibido**: deformar, cambiar color/porcentajes, inclinar, ocultar, espaciado o tipografía incorrectos, fondos ruidosos. Siempre junto a ® cuando se usa en piezas de marca. | Encabezado: logo **negativo** (SVG de `static/brand/`) sobre negro; no recolorear. 10 mm ≈ 38 px CSS a 96 dpi: no bajar de ahí (en la práctica ≥ 96 px de ancho para que lea). Favicon: isotipo (como ya hace la tienda). El ® y las leyendas legales («Bajo Licencia Deutsch / Marca Registrada») van en pie de **tienda y documentos de cara al cliente**, no en pantallas internas de trabajo. |
| **Escritura** | «Deutsch» (no DEUTSCH ni deutsch). | Regla de copy en todo el sistema. |
| **Tono** | «Marca amiga, consejera y experta»; personalidad: trabajadora, segura, eficiente, **de confianza, honesta, cuidadosa, práctica, joven y amigable**; trata a las personas «con respeto y amabilidad». Slogan «Pasión por la natación». | Tono interno: **voseo rioplatense, directo y cálido, sin dramatizar** («Esta tanda tiene 12 pedidos. Imprimí la hoja y empezá a juntar.»). El slogan **no** se mete en pantallas de trabajo; puede ir en login y pie de la tienda. |
| **Isotipo y color** | «La letra D irá cambiando de color de acuerdo al producto que se quiera posicionar.» | Se podría usar el isotipo en estados vacíos y en el avatar del sistema, **sin deformarlo** (ver prohibiciones). Cambios de color del isotipo: solo con autorización de Deutsch (pregunta abierta). |
| **Idiomas** | «La marca habla tres idiomas: alemán, español e inglés». | El panel es solo en español rioplatense. Pregunta abierta: ¿hay usuarios que necesiten otro idioma? |

**Restricciones que se respetan:** no deformar ni recolorear el logo; no usar el azul `#007DC5` para texto normal (contraste 4,43:1, ver IN §13); no inventar tonos fuera de los tintes del manual para la marca (los colores de **estado** son un sistema aparte, funcional).

---

## 3. Arquitectura de información

### 3.1 Decisión: barra lateral izquierda agrupada + barra superior mínima

- **Qué.** Reemplazar la barra superior de hasta 21 enlaces por una **barra lateral izquierda** con **7 grupos** (los que corresponda según el rol), con el grupo del módulo actual abierto y el ítem activo marcado (`aria-current`). La barra superior queda con: logo, **buscador global** (sección 10), campana de avisos, nombre del usuario/salir.
- **Principio.** Navegación vertical para muchas categorías (IN §3, NN/g); proximidad (IN §5); reconocer en vez de recordar (IN §8). Confianza: **media**.
- **Alternativas descartadas.** (a) *Seguir con barra superior plana*: ya mide 3 líneas en escritorio y esconde ítems en celular (AU #1). (b) *Menús desplegables en la barra superior (mega-menú)*: dos niveles ocultos tras hover no funcionan en táctil y tienen mala accesibilidad. (c) *Árbol de 3 niveles*: NN/g advierte contra más de dos niveles de divulgación (IN §7). (d) *Solo buscador / paleta de comandos*: sirve a expertos pero no a quien no sabe qué existe (IN §8).
- **Límites.** La barra lateral resta ancho de contenido (menos grave en escritorio, más en tablet); en tablet vertical y celular pasa a barra inferior (sección 9).

### 3.2 Grupos propuestos (las ~25 secciones)

| Grupo | Ítems (nombre propuesto) | Hoy se llama | Permiso |
|---|---|---|---|
| **Hoy** | Inicio (por rol) | Inicio | todos |
| **Pedidos** | Pedidos · Nuevo pedido manual (botón, no ítem) · Devoluciones | Pedidos, Devoluciones | `sales.*` |
| **Preparación y envío** | Preparar · Tandas de picking · Despacho | Preparar, Tandas, Despacho | `sales.change_order_status`, `fulfillment.view_pickbatch` |
| **Mercado Libre** | Preguntas · Mensajes · Reclamos · Salud de publicaciones | idem | `conversations.*`, `catalog.view_listing_health` |
| **Catálogo y stock** | Catálogo · Productos sin vincular · Stock y precios por canal · Calidad de datos | Catálogo, Sin vincular, Stock y precios, Calidad | `catalog.*` |
| **Mayoristas** | Clientes · Invitaciones y solicitudes · Tienda (configuración) | Mayoristas | `wholesale.*` |
| **Reportes** | Reportes (un solo ítem; las pestañas Resumen, Ventas, Productos, Operación y Mayoristas quedan dentro) | Reportes | `reports.view_reports` |
| **Sistema** (solo administración) | Integraciones · Usuarios y permisos · Auditoría · Expresos (transportes) · Tipos de aviso | Integraciones, Usuarios, Auditoría, Expresos | `integrations.*`, `accounts.manage_users`, `audit.*`, `fulfillment.manage_carriers`, `alerts.change_alerttype` |

Observaciones: «Avisos» sale del menú y pasa a la **campana** (centro de avisos); «Expresos» (lista de transportes, configuración) pasa a Sistema. Los **nombres propuestos** son hipótesis a validar con el equipo (AU #8, pregunta abierta #5).

### 3.3 Cantidad de elementos por rol (antes → después)

| Rol | Hoy (enlaces en la barra) | Propuesto (grupos / ítems de barra lateral) |
|---|---|---|
| Administrador | 21 | 8 grupos / 23 ítems, pero agrupados, con los grupos plegables y el actual abierto (a la vista no hay más de ~8 a la vez) |
| Ventas | 16 | 6 grupos / 15 ítems |
| Depósito | 8 | 4 grupos (Hoy, Pedidos, Preparación y envío, Catálogo) / 7 ítems |
| Vendedor | 7 | 5 grupos (Hoy, Pedidos, Mercado Libre, Catálogo, Mayoristas) / 6 ítems |

(El número de ítems totales casi no baja; lo que baja es lo que el ojo tiene que escanear a la vez y la cantidad de decisiones al elegir primero un grupo. **Hipótesis:** se valida con prueba de árbol, M10-02.)

### 3.4 Decisión: una fuente única de navegación

- Un registro de navegación en código (`apps/core/navigation.py`, por ejemplo) que define grupo, ítem, etiqueta, ícono, URL, permiso, y que alimenta barra lateral, barra inferior móvil, buscador global y migas. Los permisos siguen siendo los de `roles.py`/`perms`; **no se tocan**.
- Una prueba automática que verifica: cada URL de módulo está en el registro; cada rol ve solo lo que puede; un permiso que no existe rompe el test.
- **Principio.** Una sola fuente evita deriva (consistencia, heurística #4). **Alternativa descartada:** seguir editando `_menu.html` a mano (duplicación en 4 lugares).

---

## 4. Qué ve cada rol al entrar (inicio por rol)

Regla: **una pantalla, 4–6 tarjetas accionables, ordenadas por urgencia, cada una con un número y un botón**. No es un reporte (los reportes son exploración, IN §16: hipótesis). Cada número lleva a la lista ya filtrada.

| Rol | Tarjetas, en este orden | Acción principal de la pantalla |
|---|---|---|
| **Depósito** | 1) **A despachar hoy** (vence antes de las 18:00; en rojo solo si ya venció) · 2) Pedidos para preparar · 3) Tandas abiertas · 4) Listos para despachar / retirar · 5) Devoluciones por recibir | **Preparar pedidos** (botón grande) |
| **Ventas** | 1) Reclamos abiertos · 2) Preguntas sin responder (con el más antiguo) · 3) Mensajes sin responder · 4) Pedidos con cobro pendiente · 5) Pedidos para preparar | **Responder** (lleva a la cola más urgente) |
| **Vendedor** | 1) Mis pedidos mayoristas en curso · 2) Preguntas para responder · 3) Clientes asignados con novedades | **Nuevo pedido para un cliente** |
| **Administrador** | 1) **Qué requiere decisión** (clientes por aprobar, ajustes por faltante, pagos por confirmar) · 2) Estado de integraciones (semáforo, solo si hay algo roto) · 3) Alertas críticas abiertas · 4) Resumen de ventas de ayer (una línea y enlace a Reportes) | **Aprobar** o **Ver lo que falla** |

- **Principio.** Visibilidad del estado + tablero de una pantalla (IN §16, baja-media) + efecto de una acción principal (IN §6).
- **Alternativa descartada.** *Inicio con gráficos y KPIs de ventas para todos*: es el rol del dueño, no del que prepara pedidos; ocupa atención sin función. Los reportes quedan en su sección.
- **Antes de construir:** prototipar las 4 pantallas y probar con **una persona por rol** (M10-03).

---

## 5. Flujos clave: ubicación y orden de las acciones

Para cada flujo: pasos, dónde vive la acción principal, qué se muestra, principio, alternativa descartada. (Los flujos actuales están en `sales`, `fulfillment`, `conversations`, `wholesale`.)

### 5.1 Tomar un pedido (manual, o a nombre de un cliente mayorista)
1. Desde **Pedidos › Nuevo pedido** (botón principal arriba a la derecha en la lista) o desde la **ficha del cliente** («Armar pedido para este cliente»).
2. Un formulario de **una columna**: Cliente (búsqueda con sugerencias) → Productos (búsqueda por SKU/nombre, cantidad) → Envío y cobro → **Resumen fijo abajo** con total y botón «Guardar pedido».
3. Antes de guardar, el resumen repite lo esencial (cliente, cantidad de unidades, total) — es la última barrera.
4. Después de guardar: pantalla de confirmación **con el siguiente paso** («Pedido PM-1042 guardado. Ver pedido / Cargar otro»).
- **Principios.** Proximidad y chunking de campos (IN §5); validación en línea y errores constructivos (IN §14); final claro (IN §11, media). **Descartado:** formulario en varias pestañas (esconde lo que falta, el usuario no sabe qué completó) y asistente de 5 pasos para un pedido simple (agrega clics sin aportar claridad; la «regla de 3 clics» es mito, pero cada paso extra igual cuesta).

### 5.2 Preparar (Depósito)
1. **Preparar** muestra pedidos nuevos **ordenados por límite de despacho** (el más urgente arriba, con tiempo restante en texto grande).
2. Marcar → barra inferior fija «Armar tanda (N)».
3. La **hoja de picking** de la tanda es la pantalla de trabajo en el celular: un producto por tarjeta, cantidad en grande, tilde grande; el avance de la tanda arriba («8 de 12 productos»).
4. Al terminar: «Tanda lista. Ahora: Despacho».
- **Principios.** Objetivos táctiles ≥ 44–48 px y acción en la zona del pulgar (IN §4); una acción principal (IN §6); reducir lo que hay que recordar (IN §2). **Descartado:** escaneo de códigos de barras obligatorio (no sabemos si el depósito tiene lector/cámara y cambiaría el proceso; queda como pregunta y posible mejora, ticket futuro).

### 5.3 Despachar
1. **Despacho** agrupa por «Preparando → Listo → Listo para retirar» como hoy, pero con **un botón de avance por grupo** destacado («Marcar 8 como despachados») y el resto de acciones (rótulo, etiqueta, faltante) como **acciones secundarias de al menos 44 px**.
2. Efectivo a cobrar: bloque propio con importe grande y confirmación («Cobré $12.300»), nunca una casilla escondida.
3. **Confirmación** de acciones difíciles de deshacer: nombra la consecuencia («Se avisa a Tiendanube y el cliente recibe el aviso») y muestra «Deshacer» durante unos minutos cuando el sistema lo permita (hipótesis: depende de qué se pueda revertir en cada canal; pregunta técnica).
- **Principios.** Prevención y recuperación de errores (IN §14). **Descartado:** diálogo «¿Estás seguro?» genérico en todo (la gente aprende a pulsar Aceptar sin leer: no tengo estudio verificado para citar, es una regla de práctica; por eso solo se confirman acciones con consecuencia externa).

### 5.4 Responder (Preguntas, Mensajes y Reclamos de Mercado Libre)
1. Cola ordenada por **antigüedad** (la más vieja primero) con el tiempo transcurrido, no por canal.
2. En la ficha: la pregunta arriba, **respuestas guardadas** sugeridas a un toque, caja de respuesta y botón «Enviar respuesta» (único primario).
3. Al enviar, pasa **a la siguiente de la cola** (flujo continuo), con «Volver a la lista».
- **Principios.** Una acción principal (IN §6); reducir carga (IN §1). **Descartado:** vista tipo bandeja de mail con panel dividido en celular (no cabe); en escritorio sí se puede evaluar.

### 5.5 Cobrar (confirmar pagos y efectivo)
1. El cobro se ve **en la tarjeta del pedido** como un estado claro: «Cobrado» / «Pendiente de cobro» con ícono y texto.
2. Confirmar pago (mayoristas, transferencia): acción **única y visible** en la ficha, con importe, medio y referencia; efectivo: en Despacho, ver 5.3.
- **Principios.** Prevención de errores, no depender solo del color (IN §13, §14). **Descartado:** casilla «Cobrado» + «Guardar» escondida abajo (hoy en `order_detail.html`).

### 5.6 Aprobar cliente mayorista
1. El administrador entra a **Hoy › Clientes por aprobar** (tarjeta con número) o a Mayoristas › Clientes.
2. La ficha muestra: quién es, qué pidió (CUIT, condición IVA, rubro), **un botón Aprobar y un botón Rechazar** con motivo obligatorio, y una línea «Qué pasa después» («el cliente recibe un email y puede comprar»).
- **Principios.** Visibilidad (heurística #1) y prevención de errores. **Descartado:** aprobación masiva de entrada (riesgo de aprobar sin leer; evaluar más adelante si el volumen lo pide).

---

## 6. Sistema visual

### 6.1 Colores
- **Marca:** negro `#231F20` (barra superior, texto principal), azul `#00659F` (acción primaria, enlaces; contraste 6,3:1 con blanco), azul oscuro `#004F7C` (hover/activo), agua `#CBE6F5` y `#F4FAFE` (fondos, selección, grupo activo), `#007DC5` solo para logo, bordes y texto grande.
- **Neutros:** blanco, grises `#F6F7F8`, `#E3E7EA`, texto secundario `#5B6670` (5,9:1), **nada de gris más claro que `#5B6670` para texto**.
- **Estados** (sección 8).
- **Principio.** Contrastes WCAG (IN §13). **Alternativa descartada:** adoptar las escalas `stone/red/amber/emerald` de Tailwind del panel actual: no son marca (AU #5).

### 6.2 Tipografía y escala
- Source Sans 3; base **16 px** (hoy 14 px `text-sm` predominante).
- Escala: 12 (solo etiquetas auxiliares, nunca información crítica) · 14 (tablas en modo compacto) · **16 (base)** · 18 (destacados) · 24 (títulos de pantalla) · 32+ (números de inicio y de depósito).
- Cifras **tabulares** para importes y cantidades; negrita de 600 como máximo énfasis (no se usan 900/Black en datos).
- **Principio.** Jerarquía (IN §6). **Descartado:** reducir aún más el tamaño para «ganar densidad»: la densidad se gana quitando elementos, no achicando.

### 6.3 Espaciado y densidad
- Grilla de 4/8 px; separación entre grupos ≥ 24 px, entre campos ≥ 16 px (proximidad, IN §5).
- **Tres densidades** (preferencia por usuario, con valor por defecto según rol): **cómoda** (filas de ~56 px; depósito y celular), **normal** (~44 px), **compacta** (~36 px; solo administración en escritorio). Objetivo táctil mínimo siempre ≥ 24 px (WCAG 2.5.8) y ≥ 44–48 px en modo cómodo.
- **Principio.** Fitts (IN §4). **Descartado:** una sola densidad para todos (el depósito con guantes y el que carga 200 filas de auditoría tienen necesidades opuestas; hipótesis a probar).

### 6.4 Componentes (inventario a construir, partiendo de `templates/store/components/*`)
1. **Botón** (primario azul `#00659F`; secundario con borde; peligro con ícono y texto; deshabilitado con motivo). **Una primaria por pantalla.**
2. **Chip de estado** (ícono + texto + color; 5 familias, ver §8).
3. **Tabla:** encabezado fijo; hasta 6–7 columnas visibles por defecto con «Columnas»; números a la derecha; fila entera enlazable; columna «Límite» con tiempo relativo («vence en 2 h» / «venció hace 40 min») y fecha absoluta en `title`; selección múltiple con barra de acciones; en celular se transforma en tarjetas **desde 1024 px hacia abajo** (no 768, para cubrir tablet vertical). *Evidencia de tablas: baja, tratar como hipótesis (IN §17).*
4. **Ficha** (detalle): cabecera con estado + **siguiente paso** como botón primario; debajo, secciones en orden «qué hacer → qué es → plata → historial»; panel lateral opcional en escritorio.
5. **Formulario:** una columna, etiqueta arriba, ayuda breve bajo el campo, secciones separadas por espacio, validación en línea al salir del campo (no antes), resumen de errores arriba con enlaces a cada campo, datos conservados al fallar.
6. **Estado vacío:** qué pasa («No hay pedidos para preparar») + qué se puede hacer («Ver pedidos de ayer»), con el isotipo opcional.
7. **Mensajes** (éxito, info, advertencia, error): ícono + texto, `aria-live`, errores sin cierre automático, éxitos que se cierran solos.
8. **Aviso en barra** y **centro de avisos** (sección 8).
9. **Filtros:** 2–3 visibles + «Más filtros»; chips de los aplicados con «x» y «Limpiar todo».
10. **Carga:** esqueleto o barra delgada; indicador con texto si pasa de 1 s (sección 11).

### 6.5 Mensajes de error en castellano simple
Plantilla: **qué pasó + qué hacer + (si corresponde) qué se conserva.** Voseo, sin códigos ni «ha ocurrido».

| En vez de | Decir |
|---|---|
| «Error 500» | «No pudimos guardar el pedido. No se perdió nada: probá de nuevo en un momento. Si sigue, avisale a Maico con este código: 8F2A.» |
| «Campo obligatorio» | «Falta el CUIT. Sin él no podemos facturar.» |
| «Valor inválido» | «El mínimo de compra mayorista es $120.000. Este pedido llega a $98.500.» |
| «Permiso denegado» | «Tu usuario no puede aprobar clientes. Pedíselo a un administrador.» |
| «Error de conexión con Mercado Libre» | «Mercado Libre no respondió. Probá de nuevo en un minuto; la pregunta sigue sin responder.» |

Los ejemplos de plata y de códigos son ilustrativos; las cifras reales las pone el sistema.
- **Principio.** Heurística #9 y NN/g sobre errores constructivos (IN §14, media-alta).

---

## 7. Accesibilidad

Objetivo: **WCAG 2.2 nivel AA** en todo el panel y la tienda (norma, confianza alta), con estas reglas operativas:
1. Contraste de texto ≥ 4,5:1 (3:1 en texto grande y en bordes/íconos de controles); verificación automática de tokens.
2. **No depender solo del color:** todo estado = ícono + texto + color (1.4.1).
3. Foco visible propio (anillo de 2 px azul oscuro con separación), orden de tabulación lógico, **enlace «Saltar al contenido»**, `nav` con `aria-label`, página activa con `aria-current`.
4. Mensajes y alertas con `aria-live` adecuado (`status`/`alert`).
5. Objetivos ≥ 24 px (mínimo AA) y ≥ 44–48 px en depósito.
6. Texto escalable: probar al 200 %; nada fijo en px para tipografía de lectura.
7. Gráficos con **tabla alternativa**.
8. Revisión con lector de pantalla de los 6 flujos del punto 5 y prueba automática (axe) en CI.
- **Alternativa descartada:** «hacer accesibilidad al final»: sale más caro y se rompe con cada pantalla nueva; se define en el sistema de diseño desde el principio.

---

## 8. Estrategia de alertas

### 8.1 Tres niveles, modelo tomado de la aviación (IN §15)

| Nivel | Cuándo | Color/ícono | Dónde aparece | Ejemplos de Deutsch (a validar) |
|---|---|---|---|---|
| **Crítico** (rojo, ícono de triángulo/stop) | Algo ya falló o vence **ahora** y hay plata o plazo en juego | Rojo `#A3221A` sobre `#FDEBE9` + texto | Banner persistente + campana con punto + (solo para Administrador/Ventas) email | Despacho vencido, reclamo abierto, integración caída con escritura activa, pago rechazado |
| **Atención** (ámbar, ícono de exclamación) | Hay que hacer algo **hoy** pero no es urgente | Ámbar `#7A4D00` sobre `#FFF3D1` + texto | Campana, tarjeta en Hoy | Pedido sin cobrar de más de 24 h, publicación con problemas, cliente por aprobar |
| **Informativo** (azul agua, ícono i) | Hay novedad, no hace falta actuar | Azul `#00659F` sobre agua + texto | Centro de avisos, sin insignia roja | Pedido nuevo, respuesta recibida |

- **Regla de oro:** **el rojo se reserva a lo crítico.** Los **contadores de trabajo** (preguntas pendientes, pedidos para preparar) van en **neutro** (negro o azul) y nunca rojos, porque son carga normal, no alarma. Un estado de pedido como «Cancelado» tampoco es una alerta: va en gris con ícono.
- **Dos canales para lo crítico** (en aviación: al menos dos sentidos; acá: color+texto+ícono y además campana o email).
- **Sin sonido por defecto** (en un depósito con ruido no se oye y en una oficina molesta; sonido = decisión a validar con el equipo).
- **Principios.** Fatiga de alarmas y jerarquía (IN §15, alta en el mecanismo/media en la transferencia), aislamiento (IN §9). **Alternativa descartada:** «Más avisos para que no se pierda nada»: es exactamente el patrón que lleva a ignorarlos.

### 8.2 Higiene de alertas
- Cada tipo de aviso tiene **dueño, nivel, destinatario y acción esperada** (se agrega el campo `nivel` en la configuración de tipos de alerta; hoy se gestiona desde `alerts.change_alerttype`).
- **Agrupar:** 8 preguntas nuevas = un aviso («8 preguntas sin responder»), no 8.
- **Medir:** por tipo de aviso, la **tasa de acción** (¿alguien hizo lo esperado en X horas?) y la **tasa de «marcar leído sin actuar»**. Objetivo a calibrar: si un tipo no se acciona, se rebaja de nivel o se elimina. Revisión mensual.
- **Silencio inteligente:** no volver a avisar lo mismo (ya existe `dedupe_key` en el modelo de alertas, ver `alerts/migrations/0001_initial.py`).

---

## 9. Mobile y tablet para el depósito

Evidencia **débil** para guantes y luz (IN §4, §20): lo que sigue son **hipótesis a probar en el depósito real** antes de fijar medidas (M10-04).

- **Barra inferior de 4 tareas** en celular/tablet vertical: *Preparar · Tandas · Despacho · Buscar*, más «Más» para el resto. Desaparece la tira horizontal de enlaces.
- **Tabla → tarjetas hasta 1024 px** (cubre tablet vertical).
- **Objetivos de 48 px**, separación ≥ 8 px, acción principal **abajo** (zona del pulgar; Parhi et al. 9,2–9,6 mm como mínimo para pulgar, IN §4).
- **Alto contraste y tamaño grande**: números de cantidad en 24–32 px, negrita; sin grises claros; **modo alto contraste** manual (sol directo). Evidencia de legibilidad al sol: no encontrada (IN §4).
- **Sin gestos finos:** nada de deslizar para borrar ni arrastrar; todo con toque simple.
- **Tolerancia a conexión:** tildes de picking guardadas en el dispositivo (ya existe) y **cola de envío con reintento visible** («Se enviará cuando haya conexión»), a evaluar con el equipo técnico.
- **Retroalimentación háptica/visual al tildar** (cambio de color fuerte + vibración si el dispositivo lo permite).
- **Alternativa descartada:** una app nativa o PWA instalada (costo y mantenimiento altos; evaluar solo si la prueba muestra que el navegador no alcanza).

---

## 10. Atajos y buscador global

- **Buscador global** en la barra superior (`/` o `Ctrl+K` / `⌘+K`): busca por **número de pedido, nombre o CUIT de comprador/cliente, SKU, nombre de producto**; resultados agrupados por tipo (Pedidos, Clientes, Productos, Preguntas), filtrados por permisos; los más recientes primero; en celular, ícono de lupa en la barra inferior.
- **Atajos mínimos:** `/` buscar · `?` ayuda con la lista · `g` luego `p` (ir a Pedidos), `g` luego `r` (Preparar), `g` luego `d` (Despacho) · `j`/`k` bajar/subir en listas (opcional, solo administración). **Siempre mostrados** en el buscador (placeholder «Buscá pedido, cliente o SKU — `/`») y en la ayuda, porque los atajos que no se ven casi nunca se usan (IN §18, media).
- **Principios.** Heurística #7, reconocer vs. recordar (IN §8). **Descartado:** conjunto grande de atajos tipo editor de código (curva de aprendizaje alta y poco uso; el equipo no pidió esto, pregunta abierta).
- **Esfuerzo técnico:** la búsqueda en servidor con índices existentes; objetivo de respuesta en ≤ 300 ms (propuesta a calibrar).

---

## 11. Metas de rendimiento percibido

Basadas en los límites 0,1 / 1 / 10 s (IN §12, media-alta; el «400 ms» de Doherty se toma como **aspiración**, no umbral duro).

| Situación | Meta (propuesta) | Cómo |
|---|---|---|
| Respuesta a un toque/clic | **≤ 100 ms** de retroalimentación visual (estado «presionado», botón «Enviando…») | CSS inmediato + deshabilitar al enviar (un mecanismo común) |
| Cambio de pantalla / lista | **≤ 1 s** en red normal | `hx-boost`/navegación parcial, paginación en servidor, índices; presupuesto por pantalla en `tests/test_rendimiento.py` |
| Operación de 1–10 s (imprimir hoja de tanda, etiquetas) | Indicador con texto («Preparando etiquetas…») | Estado de carga visible |
| Operación > 10 s (lotes, reportes grandes, exportar) | Barra de progreso con **Cancelar** y permitir seguir trabajando | Tarea en segundo plano con aviso al terminar |
| Sin saltos de diseño | Los contadores de menú no deben mover el contenido | Reservar el espacio o renderizar el número en el servidor |

- Medir con **datos de campo** (el celular del depósito, la red del local), no solo en la computadora del desarrollador.
- Dependencias externas en el camino crítico (HTMX desde CDN): servirlas desde el propio sitio.
- **Alternativa descartada:** «mejorar rendimiento optimizando todo»: sin línea de base es adivinar; se mide primero (M10-01).

---

## 12. Cómo se mide la usabilidad

### 12.1 Pruebas con usuarios reales de Deutsch
- **Quiénes:** 3 personas por rol (Administrador, Ventas, Depósito, Vendedor), según el criterio de rondas chicas repetidas (NN/g, IN §21, media). Si hay menos personas que eso en un rol, probar con las que haya y decirlo en el informe.
- **Cuándo:** (1) **línea de base** del sistema actual, (2) **prototipo** de navegación e inicio, (3) **prototipo de depósito en el lugar**, (4) después de construir cada pantalla migrada.
- **Tareas por rol** (ejemplos; ajustar con el equipo): Depósito: «armá una tanda con los pedidos más urgentes y marcá lo juntado», «despachá 3 pedidos y cobrá el efectivo». Ventas: «respondé la pregunta más antigua», «buscá el pedido de la clienta X y decime cuándo se despacha». Vendedor: «cargá un pedido para el cliente Y». Admin: «aprobá un cliente», «encontrá por qué falló la integración con Tiendanube».
- **Cómo:** pensar en voz alta, sin ayuda, con cronómetro; observar errores y dudas; tomar notas y, si el equipo acepta, grabar pantalla.
- **Pruebas de navegación:** card sorting abierto (con todo el personal que usa el panel) y tree test de la barra lateral (IN §19; con muestras chicas, se lee como cualitativo).

### 12.2 Métricas
| Métrica | Qué mide | Cómo | Meta inicial (a calibrar con la línea de base) |
|---|---|---|---|
| Éxito en la tarea | ¿Pudo hacerla sin ayuda? | Observación | ≥ 90 % de los participantes en tareas diarias |
| Tiempo en tarea | Eficiencia | Cronómetro y registro de eventos | ≥ 20 % mejor que la línea de base (cifra arbitraria: se fija después de medir) |
| Errores y reintentos | Calidad del flujo | Observación + registro | Bajar vs. línea de base |
| **Primer clic correcto** en navegación | ¿Entiende dónde está cada cosa? | Tree test | ≥ 80 % (cifra de práctica, no verificada) |
| Facilidad percibida | Opinión | SEQ (una pregunta por tarea) y **SUS** al final | SUS: referencia habitual ~68 de media (no verificado en esta sesión); apuntar a superarla |
| Alertas: tasa de acción | Fatiga | Registro de avisos (§8.2) | Subir; rebajar o retirar los de baja tasa |
| Uso de buscador/atajos | Adopción | Telemetría simple, sin datos personales sensibles | Crece mes a mes |
| Rendimiento percibido | Esperas | Registro de tiempos de campo | Cumplir §11 |

Reglas de honestidad: **todo número «meta» es una propuesta**; se fija con la línea de base de Deutsch y con el equipo, no con un estándar importado.

---

## 13. Migración gradual, sin romper nada

1. **No se cambian URLs, permisos ni modelos.** Es una capa de presentación. Las pruebas actuales (`tests/test_url_permissions.py`, etc.) deben seguir verdes en cada paso.
2. **Primero los cimientos, sin cambiar el aspecto:** tokens de marca, tipografía y componentes en paralelo a lo existente (los componentes nuevos conviven con las clases actuales).
3. **Esqueleto nuevo detrás de un interruptor por usuario** (`UI_V2`): Maico y una persona por rol lo prueban; el resto sigue con el esqueleto actual. Un clic para volver al anterior.
4. **Pantalla por pantalla**, en este orden (por impacto y riesgo): Hoy (inicio por rol) → Preparar/Tandas/Despacho (depósito) → Pedidos (lista y ficha) → Atención de Mercado Libre → Catálogo y stock → Mayoristas (administración) → Reportes → Sistema.
5. **Lista de control por pantalla migrada:** tokens aplicados · componentes del sistema · AA verificado · responsive hasta 360 px · estados vacío/error/carga · textos revisados · prueba de usuarios hecha · pruebas automáticas verdes.
6. **Cuando todas las pantallas estén migradas**, se quita el esqueleto viejo; no antes.
7. **Regresión visual:** capturas automáticas de las pantallas clave antes/después (herramienta a elegir; ver ticket M10-27).
- **Principio.** Reducir riesgo con cambios chicos y reversibles (reversibilidad, Reason: tolerar y contener errores, IN §14). **Alternativa descartada:** «gran rediseño de una vez»: 60+ plantillas, riesgo de romper flujos del depósito en día de despacho, y sin forma de aprender entre pasos.

---

## 14. Tienda mayorista

Ya tiene identidad de marca (tokens, Source Sans 3, componentes, página `/mayorista/estilo/`). Propuesta: **no rehacerla**, sino:
1. Convertir `/mayorista/estilo/` en la **guía de estilo común** del panel y la tienda (una sola fuente de tokens y componentes).
2. **Auditarla con los mismos criterios** (AA, objetivos táctiles, errores en castellano simple, rendimiento en celular).
3. Mantener el aviso visible «Estás armando un pedido para…» (heurística #1) y revisarlo con vendedores reales.
4. Pruebas con 2–3 clientes mayoristas reales en el flujo de pedido (cuando se pueda).
- **Descartado:** unificar la tienda al panel (son públicos distintos: cliente que compra vs. equipo que opera; comparten sistema de diseño, no pantallas).

---

## 15. Riesgos y límites de esta propuesta

- **Pocos usuarios para pruebas estadísticas:** los resultados serán cualitativos.
- **Evidencia indirecta:** la ciencia cognitiva respalda los principios, no la configuración exacta de Deutsch.
- **Costo de capacitación:** cambiar de menú obliga a reaprender; se mitiga con migración gradual, el interruptor por usuario y la guía para Maico.
- **No se verificó el dispositivo del depósito:** medidas de táctil y contraste son hipótesis.
- **Algunas decisiones técnicas** (deshacer en canales externos, escaneo, cola offline) dependen de qué permiten Tiendanube y Mercado Libre: se confirman con el equipo técnico.
