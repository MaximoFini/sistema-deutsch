# Investigación: qué dice la ciencia cognitiva sobre sistemas grandes (y qué no)

Fecha: 2026-11-20. Estado: borrador para revisión. Solo investigación; no se tocó código ni plantillas.

## 0. Cómo leer este documento

**Niveles de confianza** (míos, según la calidad de la fuente que pude abrir esta sesión):

| Nivel | Significa |
|---|---|
| **Alta** | Resultado replicado o norma formal (WCAG, regulación), fuente primaria o revisión seria leída/verificada. |
| **Media** | Evidencia real pero de laboratorio, de otro contexto, o consenso de expertos sin experimento fuerte; la transferencia a este panel es razonable pero no demostrada. |
| **Baja** | Opinión de expertos, evidencia vieja o indirecta, o solo la vi en fuentes secundarias. |
| **Mito / mal citado** | Idea popular que la evidencia no sostiene como se la usa. |
| **No verificado** | Lo sé de memoria o lo vi solo en un buscador; no lo pude confirmar contra la fuente. Se marca así a propósito. |

**Advertencia de honestidad.** Casi nada de lo que sigue es «neurociencia» en sentido estricto (imágenes cerebrales). Lo que sirve para diseñar pantallas viene de **psicología cognitiva**, **factores humanos** y **HCI** (interacción persona-computadora). Los estudios de «neurodiseño» o «neuromarketing» con fMRI no aportan reglas útiles para un panel de operaciones, y no los usé. Además, casi toda la evidencia es de laboratorio o de sitios públicos; **nadie estudió el panel de Deutsch**. Por eso la propuesta incluye pruebas con usuarios reales (ver `propuesta-front.md`, sección 12): la evidencia orienta, el uso real decide.

Las fuentes marcadas con URL fueron abiertas o aparecieron en búsquedas durante esta investigación (2026-11-20). Si dice «solo resumen de buscador», no leí el texto completo.

---

## 1. Carga cognitiva (Sweller)

- **Qué dice.** La memoria de trabajo es limitada; el esfuerzo mental total de una tarea se reparte entre carga *intrínseca* (la dificultad propia de la tarea), *extrínseca* (la que agrega un mal diseño) y, en la formulación posterior, *pertinente* (el esfuerzo que construye aprendizaje). El diseño debe bajar la extrínseca. Sweller publicó la base en 1988 (Cognitive Science 12(2), 257–285); la división en tres tipos se formaliza en 1998 (Sweller, van Merriënboer y Paas). Las fuentes que encontré discrepan en si 1988 ya usaba la distinción intrínseca/extrínseca; no pude abrir el artículo original.
- **Fuentes.** Resumen de buscador sobre el artículo de 1988 y su historia: https://link.springer.com/article/10.1007/s10648-019-09465-5 (revisión de la teoría, solo resumen). Traducción a UI por NN/g (Whitenton, 2013): https://www.nngroup.com/articles/minimize-cognitive-load/ (leída: evitar desorden visual, apoyarse en modelos mentales conocidos, descargar tareas de la memoria del usuario con valores por defecto y reexhibir lo ya ingresado).
- **Confianza.** Media-alta en aprendizaje; **media** al aplicarla a interfaces (la transferencia es razonable, NN/g es una guía de práctica, no un experimento).
- **Implica acá.** Cada elemento sin función (25 enlaces iguales, 3 colores de alerta usados para todo, filtros que siempre muestran 8 controles) cuesta atención. Regla de trabajo: *cada elemento visible tiene que ayudar a decidir o a actuar en esa pantalla; si no, se esconde o se mueve.*

## 2. Memoria de trabajo: Miller (7±2) vs. Cowan (4±1)

- **Qué dice.** Miller (1956) mostró que la gente recuerda unos «siete elementos» *si se agrupan en chunks*; el propio paper nació de una charla y Miller creía que lo citaban mal. Cowan (2001) revisó la literatura y argumentó que la capacidad central de la atención focal es de unos **4 chunks** (rango 3–5), no 7.
- **Fuentes.** Cowan, *The magical number 4 in short-term memory*, Behavioral and Brain Sciences 24(1), 87–114: https://pubmed.ncbi.nlm.nih.gov/11515286/ (confirmado por buscador; la página de PubMed no cargó completa, volví a confirmar en el PDF del autor: https://memory.psych.missouri.edu/assets/doc/articles/2001/cowan-bbs-2001.pdf, solo resumen de buscador). Miller 1956: https://pubmed.ncbi.nlm.nih.gov/13310704/ . Retrospectiva de Cowan sobre cómo se citó mal a Miller: https://pmc.ncbi.nlm.nih.gov/articles/PMC4486516 (solo resumen de buscador).
- **Confianza.** Alta en que «7±2» **no** es un límite de diseño; **media** en el número exacto 4 (hay debate sobre si es 3, 4 o 5, y sobre qué es un chunk).
- **Mito.** «Los menús deben tener 7±2 ítems.» Miller hablaba de recordar listas, no de leer un menú que está a la vista. Un menú visible se *reconoce*, no se recuerda.
- **Implica acá.** Lo que el usuario tiene que **retener** de una pantalla a otra (códigos, números de pedido, qué filtros aplicó) debería ser ≤ 3–4 cosas; el resto se muestra en pantalla (ver reconocer vs. recordar, punto 8).

## 3. Ley de Hick-Hyman y arquitectura de la información con muchas opciones

- **Qué dice.** El tiempo para elegir entre n alternativas equiprobables y *no ordenadas* crece con log(n+1) (Hick 1952; Hyman 1953). Cada vez que se duplican las alternativas, el tiempo sube en una cantidad constante (~150 ms en los experimentos clásicos, según una paráfrasis). **Límites:** la ley vale para respuestas arbitrarias a estímulos; con la práctica, con compatibilidad estímulo-respuesta y cuando el usuario escanea por categorías, el efecto casi desaparece. IxDF lo dice así: la aplicación al diseño de interfaces «ha sido cuestionada» porque la gente usa estrategias de escaneo.
- **Menús ancho vs. profundo.** Landauer y Nachbar (CHI 1985) encontraron ventaja de **amplitud sobre profundidad** en árboles de menús táctiles; trabajos posteriores son mixtos pero la profundidad suele agregar tiempo y errores. NN/g recomienda **navegación vertical a la izquierda** cuando hay muchas categorías principales (escala mejor, se escanea más fácil, se adapta a móvil), con costo de espacio y el riesgo de que ítems largos queden bajo el pliegue.
- **Fuentes.** https://ixdf.org/literature/article/the-hick-hyman-law-an-argument-against-complexity-in-user-interface-design (resumen de buscador) y revisión de limitaciones https://www.pubmed.gov/28434379/ (solo título/resumen de buscador). Landauer & Nachbar 1985: https://researchr.org/publication/LandauerN85 (resumen). NN/g vertical nav: https://www.nngroup.com/articles/vertical-nav/ (leída).
- **Confianza.** **Media-baja** para «menos opciones = más rápido» en navegación real; **media** para «ancho y poco profundo, con grupos claros, y barra vertical cuando son muchas secciones».
- **Mito.** «Hick demuestra que menos es siempre mejor.» No: un estudio citado por la propia búsqueda sostiene que la literatura de tiempo de reacción **no** apoya el eslogan «menos es más»; lo que baja el tiempo es que las opciones estén **agrupadas, rotuladas y ordenadas**.
- **Implica acá.** Pasar de 21 enlaces planos (administrador) a una barra lateral con **6–7 grupos** y como máximo ~5–6 ítems por grupo es una *decisión de diseño razonable*, **no un número respaldado por un estudio**; hay que validarlo con una prueba de árbol (ver tickets M10-02/03). No esconder módulos detrás de 3 niveles.

## 4. Ley de Fitts y tamaño de objetivos táctiles (depósito con celular y tablet)

- **Qué dice.** El tiempo para alcanzar un objetivo crece con la distancia y baja con el tamaño (Fitts 1954, no verificado en esta sesión). En táctil con el pulgar, Parhi, Karlson y Bederson (MobileHCI 2006) recomendaron **9,2 mm** para tareas discretas (botones, casillas) y **9,6 mm** para tareas seriales. WCAG 2.2 exige como **mínimo AA 24×24 px CSS** (criterio 2.5.8, con excepciones de espaciado, en línea, equivalentes, control del agente de usuario, esencial) y recomienda **44×44 px** (criterio 2.5.5, el mejorado; confirmé el valor y que es el más estricto, pero **no confirmé en la página su nivel AAA**, que recuerdo de memoria).
- **Guantes.** La evidencia es **débil**: un estudio militar con n=6 encontró que los guantes bajan la precisión al primer toque, y que objetivos dimensionados con MIL-STD-1472 no produjeron errores de botón equivocado con ni sin guantes; el resto es material de fabricantes y una patente. No encontré datos de legibilidad al sol para tablets de depósito. (Búsqueda del 2026-11-20.)
- **Fuentes.** https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html (leída). https://www.microsoft.com/en-us/research/?p=155150 (Parhi et al., resumen de buscador). Tamaños de Apple (44 pt) y Material (48 dp): no verificado en esta sesión.
- **Confianza.** **Alta** en el mínimo WCAG 24 px; **media** en ~9–10 mm para pulgar (estudio único, 2006, pantallas chicas); **baja** en cualquier número específico para guantes.
- **Implica acá.** El flujo de depósito ya usa casillas de 24–28 px dentro de filas de 44 px (prepare.html, dispatch.html, batch_detail.html), lo cual va por buen camino. Propuesta: objetivos de **48 px** y separación ≥ 8 px en el modo depósito, acción principal abajo (zona del pulgar), y **probar con guantes reales en el depósito** antes de fijar medidas (ticket M10-04).

## 5. Gestalt, proximidad y agrupación

- **Qué dice.** Los elementos cercanos se perciben como grupo y la proximidad puede **ganarle** al color o la forma; la región común (un borde o fondo compartido) es otro agrupador. NN/g recomienda acercar lo relacionado, separar lo no relacionado con espacio, y revisar los grupos en cada tamaño de pantalla.
- **Fuente.** https://www.nngroup.com/articles/gestalt-proximity/ (leída). Los principios son del siglo XX (Wertheimer y escuela de la Gestalt); la nota de NN/g no cita a Wertheimer, no verifiqué la atribución.
- **Confianza.** **Alta** (principio perceptivo bien establecido; el uso en UI es práctica estándar).
- **Implica acá.** Agrupar por **tarea** y no por orden alfabético o histórico de módulos; formularios en secciones con espacio claro; en la ficha de pedido, separar «qué hay que hacer ahora» de «datos de referencia».

## 6. Atención y jerarquía visual: rasgos preatentivos y patrón F

- **Rasgos preatentivos.** Ciertas diferencias (color, movimiento, orientación, tamaño) se detectan en menos de ~200–250 ms sin recorrer elemento por elemento *cuando el elemento destacado es único en su rasgo*. Sirve para destacar **una** cosa; si todo está destacado, nada lo está. Healey y Enns (IEEE TVCG 18(7), 2012) es la revisión de referencia.
- **Patrón F.** Eye-tracking de NN/g (2006) mostró que, en páginas de texto con poco formato, la gente lee arriba, baja y escanea el borde izquierdo. **Límites que NN/g mismo aclara:** rara vez es una F perfecta, **aplica al área de contenido, no a las barras de navegación**, no es el único patrón (hay layer-cake, spotted, etc.) y es el *default* cuando no hay señales que guíen la vista. NN/g recomienda lo importante primero, títulos informativos, agrupar, listas.
- **Fuentes.** https://www.csc2.ncsu.edu/faculty/healey/download/tvcg.12a.pdf (resumen de buscador). https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content/ (leída; publicada 2017, referencia 2006).
- **Confianza.** **Alta** para preatentivos y para «una cosa destacada por pantalla»; **media** para el patrón F (hallazgo real, pero no es ley; en un panel con tablas y botones **no** debe usarse para ubicar cosas por reflejo).
- **Mito / mal usado.** «Hay que poner todo en forma de F / Z.» No hay base para aplicar esos patrones a pantallas de operación, que se leen por tarea y por jerarquía visual.
- **Implica acá.** Una sola acción principal por pantalla; el dato más importante de cada fila (límite de despacho) con peso tipográfico, no con el rojo de uso general.

## 7. Divulgación progresiva

- **Qué dice.** Mostrar primero las pocas opciones importantes y revelar las especializadas a pedido mejora aprendizaje, eficiencia y tasa de error. **Límites:** más de **dos** niveles de revelado suele ser mala usabilidad; si el reparto inicial es malo (se esconde lo frecuente) empeora.
- **Fuente.** https://www.nngroup.com/articles/progressive-disclosure/ (leída; la nota no atribuye el origen del concepto).
- **Confianza.** **Media-alta** (consenso de práctica, respaldo experimental indirecto).
- **Implica acá.** Filtros de pedidos: dejar visibles 2–3 (canal, estado, búsqueda) y el resto en «Más filtros». Menú: grupos plegables pero con el grupo del módulo actual siempre abierto. No más de dos niveles.

## 8. Reconocer antes que recordar

- **Qué dice.** Es la heurística #6 de Nielsen (1994, revisada 2024): hacer visibles opciones, acciones e información para no obligar a recordar. Se apoya en la diferencia entre recuerdo libre y reconocimiento, un hallazgo básico de memoria.
- **Fuente.** https://www.nngroup.com/articles/ten-usability-heuristics/ (leída).
- **Confianza.** **Media-alta**. Las 10 heurísticas son un consenso de expertos derivado de análisis de problemas de usabilidad, no un conjunto de leyes experimentales.
- **Implica acá.** Mostrar en pantalla el estado y el contexto (en qué módulo estás, qué filtros están aplicados, a qué cliente representás); hoy el menú no marca la página activa y los filtros aplicados no se resumen (ver auditoría).

## 9. Efecto Von Restorff (aislamiento)

- **Qué dice.** En una lista homogénea, el ítem distinto se recuerda mejor (von Restorff 1933). Hunt (1995) matiza qué se probó realmente: distintividad *respecto del resto de la lista*, no «destacar por destacar».
- **Fuente.** Hunt 1995, *The subtlety of distinctiveness: what von Restorff really did*, Psychonomic Bulletin & Review 2, 105–112 (existe; solo referencia de buscador).
- **Confianza.** **Media** en laboratorio (memoria de listas); **baja-media** al transferirlo a UI (extrapolación).
- **Implica acá.** Si el rojo aparece en 56 lugares de las plantillas, ningún rojo es distintivo. La regla propuesta: **el rojo solo para 3 situaciones críticas** (ver propuesta, sección 8). Es el mismo razonamiento de la aviación (punto 15): el color de alerta se reserva.

## 10. Efecto Zeigarnik

- **Qué dice la versión popular.** «Las tareas incompletas se recuerdan mejor, por eso las barras de progreso enganchan.» **Qué dice la evidencia reciente.** Un metaanálisis de 2025 (Ghibellini y Meier, revista de la serie Palgrave/Humanities and Social Sciences Communications, DOI s41599-025-05000-w) **no encontró ventaja de memoria** para tareas interrumpidas; sí encontró la tendencia a **retomar** tareas interrumpidas (efecto Ovsiankina). La ventaja de memoria es famosa por ser difícil de replicar.
- **Fuente.** https://ideas.repec.org/a/pal/palcom/v12y2025i1d10.1057_s41599-025-05000-w.html (solo resumen; no vi tamaños de efecto).
- **Confianza.** Que el efecto de memoria **no se sostiene como regla general**: **media-alta**. Que las personas tienden a retomar lo interrumpido: **media**.
- **Mito / mal citado.** Citar Zeigarnik para justificar barras de progreso, tareas pendientes o «gamificación».
- **Implica acá.** Igual conviene mostrar «pedidos que quedaron a medio preparar» por **razones de usabilidad** (recuperar interrupciones, reducir recordar), no por Zeigarnik. No invertir en trucos de «progreso que engancha».

## 11. Regla pico-final

- **Qué dice.** Los recuerdos de una experiencia se parecen más a su momento más intenso y a su final que al promedio o la duración (Kahneman y colaboradores, 1993, **no verificado**). Un metaanálisis de 2022 (Alaybek, Dalal y otros, OBHDP 170, 174 tamaños de efecto) halló que el efecto pico-final sobre la **evaluación retrospectiva** es grande (r ≈ 0,58) y robusto; pero el promedio de toda la experiencia predijo casi igual de bien según un resumen secundario (no verificado).
- **Fuente.** https://ideas.repec.org/a/eee/jobhdp/v170y2022ics0749597822000334.html (solo resumen).
- **Confianza.** **Media-alta** para evaluación retrospectiva; **baja** para decir qué tan útil es en software de trabajo repetitivo.
- **Implica acá.** Cuidar el **final** de las tareas (confirmación clara: «Tanda 214 armada, 12 pedidos. Siguiente: imprimir la hoja») y evitar picos negativos (error confuso al final de un envío). Es una razón más, no la principal; la principal es reducir errores y tiempo.

## 12. Umbral de Doherty y percepción de la espera

- **Qué dice.** Doherty y Thadani (IBM Systems Journal, 1982) reportaron que la productividad sube marcadamente con respuestas por debajo de ~400 ms; Laws of UX lo popularizó como «umbral de Doherty». **El original no lo pude abrir** (hay una reproducción en el archivo del Computer History Museum, solo resumen de buscador) y es de la época de terminales de mainframe. Los límites más citados y mejor fundados son los de **0,1 s / 1 s / 10 s**: ≤0,1 s se siente instantáneo; ≤1 s mantiene el hilo de pensamiento; hasta 10 s se mantiene la atención, y más allá hay que mostrar **progreso** y permitir cancelar. NN/g los toma de Miller (1968) y Card et al. (1991), y la barra de progreso de Myers (1985).
- **Fuentes.** https://www.nngroup.com/articles/response-times-3-important-limits/ (leída). https://archive.computerhistory.org/resources/access/text/2024/03/102751398-05-01-acc.pdf (resumen de buscador). https://lawsofux.com/doherty-threshold/ (secundaria).
- **Confianza.** **Media-alta** en 0,1/1/10 s; **media-baja** en «400 ms» como umbral duro.
- **Implica acá.** Metas de rendimiento percibido: respuesta visible a un toque en ≤100 ms, páginas de lista en ≤1 s, indicador si pasa de 1 s, barra de progreso con cancelar si pasa de 10 s. Ya existe `tests/test_rendimiento.py`; sumar medición en dispositivos reales del depósito.

## 13. Color, contraste y daltonismo (WCAG 2.2)

- **Qué dice.** 1.4.1 (nivel A): el color no puede ser el **único** medio para transmitir información. 1.4.3 (AA): contraste mínimo **4,5:1** para texto normal y **3:1** para texto grande (≥18 pt o 14 pt negrita). 1.4.11: componentes de interfaz y gráficos a **3:1**. Daltonismo rojo-verde: ~1 de cada 12 varones y 1 de cada 200 mujeres **en poblaciones de ascendencia del norte de Europa**; menor en casi todas las otras (MedlinePlus). No tengo la cifra para Argentina.
- **Fuentes.** https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html y https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html (leídas). https://medlineplus.gov/genetics/condition/color-vision-deficiency/ (resumen de buscador).
- **Confianza.** **Alta** (normas). La prevalencia local: **baja** (extrapolada).
- **Implica acá.** Cada estado se dice con **texto + ícono + color**, nunca solo color; el verde y el rojo de marca (`#1E6B3C` y `#A3221A`) tienen contraste entre sí de apenas 1,15:1, así que se separan por ícono/texto, no por tono. Detalle: el azul de marca `#007DC5` da **4,43:1** contra blanco: **no alcanza AA para texto normal**; se usa `#00659F` para texto y botones, y `#007DC5` solo para logo, bordes y texto grande (el manual de tokens del repo ya lo advierte, pero la frase «blanco sobre azul botón 6,3» solo es cierta con `#00659F`, no con `#007DC5`).

## 14. Prevención y recuperación de errores

- **Qué dice.** Reason (BMJ 2000) distingue el enfoque *persona* (culpar al individuo) del enfoque *sistema* (cambiar las condiciones y las defensas); propone **tolerar** los errores y **contener** su daño, no solo reducirlos. Nielsen: heurística #5 (prevenir: restricciones, valores por defecto, confirmación antes de actuar) y #9 (mensajes en lenguaje claro que dicen el problema y la solución). NN/g sobre formularios: validación **en línea** cuando se pueda, mensajes explícitos, legibles, corteses, precisos y constructivos; un resumen de errores **no alcanza** como único indicador; evitar errores *prematuros* (antes de que el usuario se equivoque). Baymard coincide en no mostrar mensajes prematuros y confirmar positivamente.
- **Fuentes.** https://pmc.ncbi.nlm.nih.gov/articles/PMC1117770 (Reason, resumen de buscador). https://www.nngroup.com/articles/errors-forms-design-guidelines/ , https://www.nngroup.com/articles/hostile-error-messages/ , https://baymard.com/research-articles/inline-form-validation (solo resúmenes de buscador; no abrí los textos). El dato «validación 500 ms después de dejar de tipear» lo vi atribuido a NN/g solo en una guía gubernamental: **no verificado**.
- **Confianza.** **Media-alta** (Reason es un marco teórico muy aceptado, aunque se lo critica por llevar a análisis demasiado lineales; las guías NN/g/Baymard se basan en pruebas con usuarios).
- **Implica acá.** Acciones difíciles de deshacer (armar tanda, despachar, cancelar, confirmar pago, ajustar por faltante) deben nombrar la **consecuencia** y ofrecer deshacer cuando sea posible. Un único mecanismo global de «un solo envío por formulario» (hoy solo existe en Preparar y en la tienda). Mensajes con plantilla «qué pasó + qué hacer».

## 15. Fatiga de alertas (salud y aviación)

- **Qué dice.** En salud, la **fatiga de alarmas** (insensibilización por exceso de alarmas, la mayoría sin necesidad de intervención) es un problema de seguridad: Sendelbach y Funk (AACN Adv Crit Care 2013;24(4):378–86) y el *Sentinel Event Alert 50* de la Joint Commission (8 de abril de 2013): **98 eventos** relacionados con alarmas entre 2009 y junio de 2012, **80 con muerte**; **pero** la propia alerta advierte que no es un conjunto epidemiológico y que no deben sacarse conclusiones sobre frecuencias ni tendencias (notificación voluntaria). Una nota de prensa secundaria (Becker's) afirma que entre el 85 % y el 99 % de las señales no requieren intervención clínica: **no verificado** en la fuente. En **aviación**, 14 CFR 25.1322 y la AC 25.1322-1 definen tres niveles (**advertencia** = conciencia y respuesta inmediatas; **precaución** = conciencia inmediata, respuesta posterior; **aviso** = conciencia, posible respuesta posterior), con **rojo reservado a advertencias**, ámbar/amarillo para precauciones, cualquier color menos rojo o verde para avisos; el uso de rojo/ámbar/amarillo para funciones que **no** son alertas debe ser **limitado**; las advertencias y precauciones usan al menos **dos sentidos**.
- **Fuentes.** https://psnet.ahrq.gov/issue/medical-device-alarm-safety-hospitals y https://jointcommission.org/sea_issue_50 (resúmenes de buscador; la página de la Joint Commission me dio 403 al intentar abrirla). Sendelbach y Funk: referencia confirmada por buscador (PubMed 24153215), **no leí el texto**. https://www.law.cornell.edu/cfr/text/14/25.1322 y https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC_25.1322-1.pdf (resúmenes de buscador).
- **Confianza.** **Alta** en el mecanismo (habituación ante señales frecuentes y poco accionables) y en la jerarquía de colores de aviación como norma formal; **media** en cuánto se transfiere a un ERP donde el riesgo es plata y plazos, no vidas; **baja** en cualquier porcentaje.
- **Implica acá.** El panel hoy usa un badge rojo para un conteo de trabajo normal (preguntas sin responder) y el mismo rojo para errores y vencimientos: es la receta de la habituación. Propuesta: 3 niveles (crítico / atención / informativo), rojo reservado, contadores de cola en neutro, medir **tasa de acción por alerta** y retirar los tipos que nadie accione (ver propuesta, sección 8).

## 16. Diseño de tableros (Few)

- **Qué dice.** Few define el tablero como una pantalla única con lo más importante para hacer un trabajo, que se puede monitorear de un vistazo; no es una herramienta de exploración. «Lo fundamental es mostrar todo lo necesario en una sola pantalla sin desplazar.»
- **Fuente.** Few, *Information Dashboard Design* (O'Reilly, 2006) y notas de Perceptual Edge; **solo la conocí por citas secundarias** (no abrí Perceptual Edge). https://blogs.ischool.berkeley.edu/i247s13/files/2013/02/WhyMostDashboardsFail.pdf (resumen de buscador).
- **Confianza.** **Baja-media**: es doctrina experta influyente, **no** un resultado experimental; el propio comentarista señala que lo de «una pantalla» es discutible en móviles.
- **Implica acá.** Cada inicio por rol = una pantalla con 4–6 indicadores accionables ordenados por urgencia; los reportes (exploración) van aparte.

## 17. Tablas de datos densas

- **Qué dice.** No pude abrir la nota de NN/g sobre tablas (URL 404), así que **no tengo evidencia primaria verificada** para tablas. Lo que sigue es práctica estándar derivada de los principios anteriores (proximidad, jerarquía, reconocimiento), **sin respaldo experimental propio acá**: encabezados fijos, alineación a la derecha de números con cifras tabulares, columnas ordenables, 5–7 columnas visibles por defecto con selector, fila entera clickeable, acciones masivas al seleccionar.
- **Confianza.** **Baja** como evidencia; tratar como hipótesis a probar con usuarios.
- **Implica acá.** Hoy la tabla de pedidos tiene 9 columnas visibles a partir de 768 px (ver auditoría).

## 18. Atajos de teclado para expertos

- **Qué dice.** Los atajos son más rápidos que menús y barras de íconos, pero la gente casi no hace la transición porque no los ve (falta de señal visual). Lane, Napier, Peres y Sándor (IJHCI 18(2), 2005) lo documentan; solo lo vi por referencias secundarias y la cifra de «7 % usa Ctrl+S» es de una discusión de lista de correo con encuesta, **no verificada**. Heurística #7 de Nielsen.
- **Fuentes.** https://dblp.dagstuhl.de/rec/journals/ijhci/LaneNPS05.html (referencia). https://www.nngroup.com/articles/ten-usability-heuristics/ (leída).
- **Confianza.** **Media** (resultado coherente con la literatura, pero no leí el estudio).
- **Implica acá.** Si hay atajos, **mostrarlos donde el usuario ya mira** (en el menú, en el placeholder del buscador, con `?` para ayuda). Pocos y consistentes: buscador global y moverse entre listas. No hacer un sistema de 40 atajos.

## 19. Navegación para decenas de módulos, card sorting y árboles

- **Qué dice.** NN/g: barra vertical a la izquierda cuando hay muchas categorías (ver punto 3). **Card sorting abierto** para descubrir los grupos que la gente espera: NN/g recomienda **≥15 participantes** para cualitativo y **30–50** para cuantitativo; el **tree testing** sirve para evaluar la jerarquía propuesta. **El negocio no tiene 15 personas por rol**: es una limitación real. Adaptación honesta: un card sorting *abierto con todo el personal que usa el panel* (hoy pocos usuarios) y un tree test con las mismas personas, leyendo los resultados como **evidencia cualitativa**, no estadística.
- **Fuente.** https://www.nngroup.com/articles/card-sorting-definition/ (leída).
- **Confianza.** **Media** para el método; **baja** para sus números si se aplican a un equipo muy chico.

## 20. Uso en depósito (guantes, luz, celular)

- **Qué dice la evidencia.** Poca y débil (ver punto 4). No encontré estudios sobre legibilidad al sol en tablets de depósito ni sobre guantes y tamaño de objetivo con muestras decentes. Lo que hay es sentido común de ingeniería y consejos de fabricantes (guantes finos funcionan mejor; usar la yema, no la punta).
- **Confianza.** **Baja**. Todo lo de depósito se decide con **prueba en el lugar**, con los dispositivos y los guantes reales.

## 21. Cuántos usuarios hacen falta para probar

- **Qué dice.** Nielsen (2000): con ~5 usuarios se encuentran ~85 % de los problemas **si** un usuario individual tropieza con el 31 % de los problemas (modelo N·[1−(1−L)^n]); recomienda **varias rondas chicas** con rediseño entre ellas y **3 usuarios por grupo** cuando hay grupos distintos. El modelo tiene críticas en la literatura (que no verifiqué) y asume problemas igual de fáciles de encontrar.
- **Fuente.** https://www.nngroup.com/articles/why-you-only-need-to-test-with-5-users/ (leída; 2000).
- **Confianza.** **Media**. Es un modelo, no una garantía.
- **Implica acá.** 4 roles → **3 usuarios por rol** por ronda, 3 rondas.

---

## 22. Mitos que NO usamos para decidir

| Mito | Qué pasa realmente | Fuente |
|---|---|---|
| «Un menú debe tener 7±2 ítems.» | Miller hablaba de recordar listas con chunks; un menú visible se reconoce. Cowan sugiere ~4 como capacidad de atención focal. No hay regla de 7 para menús. | Miller 1956; Cowan 2001 (ver punto 2) |
| «Regla de 3 clics.» | Porter (2003): los usuarios seguían hasta 25 clics y la cantidad de clics **no predijo** éxito ni satisfacción; NN/g: no tiene respaldo en datos publicados. Importa si cada paso es **claro**, no cuántos son. | https://www.nngroup.com/articles/3-click-rule/ ; https://articles.centercentre.com/?p=17 (el dato «44 usuarios, 620 tareas» viene de fuentes secundarias, no verificado) |
| «Estilos de aprendizaje (visual/auditivo/kinestésico).» | Pashler et al. (2008): hay preferencias, pero **no hay evidencia adecuada** de que enseñar según el «estilo» mejore resultados. No diseñamos «un modo para visuales». | https://pubmed.ncbi.nlm.nih.gov/26162104/ |
| «Todo sigue un patrón en F.» | NN/g: aplica al contenido de texto con poco formato, no a barras de navegación ni a pantallas de operación. | punto 6 |
| «Zeigarnik: lo incompleto se recuerda más.» | Metaanálisis 2025: sin ventaja de memoria; sí tendencia a retomar. | punto 10 |
| «Hick: menos opciones siempre es mejor.» | Funciona para elecciones no ordenadas; con categorías claras y práctica el efecto casi desaparece. | punto 3 |
| «400 ms es una frontera mágica.» | Dato de 1982 en mainframes; los límites sólidos son 0,1/1/10 s. | punto 12 |
| «El azul transmite confianza, el rojo urgencia (psicología del color universal).» | No encontré evidencia sólida para reglas universales; las convenciones de alerta (rojo/ámbar) vienen de **normas** como las de aviación, no de «neurociencia del color». **No verificado**: no busqué estudios específicos. | punto 15 |
| «5 usuarios alcanzan siempre.» | Es un modelo que supone problemas igual de detectables; Nielsen mismo pide rondas repetidas y grupos por separado. | punto 21 |

## 23. Qué NO sé (y conviene no afirmar)

- Cómo funcionan los guantes del depósito de Deutsch con las pantallas que tengan; cuánta luz hay; qué dispositivos son.
- Tamaños exactos de Apple HIG y Material (mencionados de memoria).
- El texto original de Doherty & Thadani (1982), Kahneman et al. (1993), Fitts (1954), Sendelbach & Funk (2013).
- Cuántos usuarios de Deutsch tienen deficiencia de color.
- Si un tablero «de una pantalla» es lo mejor para cada rol de Deutsch (hipótesis de Few, no probada acá).
- Evidencia primaria sobre tablas densas (la nota de NN/g no cargó).
