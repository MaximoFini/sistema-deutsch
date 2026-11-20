# Preguntas abiertas y decisiones pendientes (módulo M10 · Front y experiencia de uso)

Fecha: 2026-11-20. Cada pregunta dice **a quién** hay que hacérsela, **por qué importa** y **qué ticket/decisión destraba**. Las marcadas **[bloqueante]** impiden empezar algo; el resto se puede decidir sobre la marcha.

## A. Alcance y prioridad (decide Deutsch / el dueño)

1. **[bloqueante] ¿Quieren que se haga este módulo ahora, y en qué orden frente a lo que está pendiente de otros módulos?** Un primer corte útil (pruebas + cimientos + inicio + depósito + alertas + formularios + accesibilidad) son del orden de 16–20 semanas-persona; el módulo completo, unas 30–35. Destraba: todo (tickets-propuestos.md).
2. **¿Cuánto del panel es «de cara al dueño» y cuánto es del equipo que opera?** Si el dueño usa mucho Reportes, el tablero (M10-24) sube de prioridad; si no, queda P3.
3. **¿Se prefiere un cambio gradual con interruptor por usuario (propuesto) o un solo cambio en una fecha?** Afecta el riesgo y la capacitación (M10-08, M10-27).

## B. Personas y uso real (decide Deutsch; las respuestas dan la línea de base)

4. **[bloqueante] ¿Cuántas personas usan hoy el panel, con qué rol cada una y cuántas por día?** Define si el card sorting y las pruebas de 3 por rol son posibles (M10-01, M10-02, M10-28). Si hay 1–2 personas por rol, las pruebas serán con ellas y se leen como casos, no como muestra.
5. **¿Qué palabras usa el equipo?** ¿Dicen «tanda», «expreso», «picking», «despacho», «sin vincular», «calidad», «salud»? ¿Cómo llaman a cada paso? (M10-02, M10-09; auditoría #8).
6. **¿Qué tareas hacen todos los días, en qué orden, y cuáles les resultan más molestas hoy?** Sin esto, las tareas de prueba son supuestas (M10-01).
7. **¿Quién hace qué en un día de mucho volumen?** ¿Una misma persona prepara, despacha y responde? Si es así, el menú por rol puede no ajustarse y conviene permitir «atajos personales».
8. **¿Hay usuarios con baja visión, daltonismo o que usen lupa/lector de pantalla?** Cambia la prioridad de accesibilidad reforzada y del modo alto contraste (M10-17, M10-31).
9. **¿Alguien necesita el panel en otro idioma?** El manual dice que la marca habla alemán, español e inglés; el panel hoy es solo en español.

## C. Depósito (decide Deutsch + el encargado del local; **hay que ir al lugar**)

10. **[bloqueante para M10-04/14] ¿Qué dispositivos se usan (marca, tamaño de pantalla), con qué sistema y navegador, y quién los provee?** Define tamaños y pruebas.
11. **¿Se trabaja con guantes? ¿De qué tipo? ¿Con qué luz (interior, patio, sol directo)? ¿Con mucho ruido?** Sin esto, lo de guantes y sonido es hipótesis (IN §4, §20).
12. **¿Hay conexión estable en todo el depósito o se corta?** Define si hace falta cola de envío offline (propuesta §9).
13. **¿Tienen lector de códigos de barras o se aceptaría escanear con la cámara del celular?** Cambia el flujo de preparación (propuesta §5.2; hoy se descartó como obligatorio).
14. **¿Se imprime en el depósito? ¿En qué impresora y desde qué dispositivo?** Impacta el flujo de hojas de picking, etiquetas y rótulos.
15. **¿Qué se puede deshacer en la práctica?** (p. ej. un pedido ya marcado «Despachado» en Tiendanube/Mercado Libre). Define dónde se ofrece «Deshacer» (propuesta §5.3; pregunta técnica también).

## D. Marca (decide Deutsch / quien cuide la marca)

16. **¿Puede el panel interno usar el logo y los colores de marca, o el uso está limitado a piezas de cara al público?** El manual no lo dice. Destraba M10-05.
17. **El manual pide Myriad Pro y, para web, Calibri. Estamos usando Source Sans 3 (libre, parecida a Myriad). ¿Lo aprueban, o prefieren Calibri en el panel?** Source Sans 3 se decidió en `static/brand/tokens.css`; falta la aprobación expresa.
18. **¿Se puede cambiar el color de la «D» (isotipo) en el panel (por ejemplo, un color por área)?** El manual dice que cambia «según el producto», pero no para software. Por ahora no se cambia.
19. **¿Qué azul exacto es el de marca en pantalla?** El PDF muestra el Pantone 3005; en `tokens.css` está como `#007DC5`; la página de colores del manual está en gráfico y no pude comprobar RGB/CMYK. Que alguien con el original lo confirme.
20. **¿Usamos el slogan «Pasión por la natación» en alguna parte del panel (login, pie)?** Propuesta: solo login y pie de la tienda.
21. **El manual pide el ® junto al logo. ¿En el panel interno hace falta?** Propuesta: no; sí en la tienda y en documentos de cara al cliente.

## E. Navegación y estructura (decide Deutsch con el equipo, con prueba)

22. **¿Los 7–8 grupos propuestos les cierran? ¿Falta alguno o sobra alguno?** Ver propuesta §3.2; se valida en M10-02.
23. **¿«Avisos» como campana (en vez de un ítem de menú) les parece bien?**
24. **¿Quién debe ver «Sin vincular» y «Calidad»?** Hoy los ven Administrador y Ventas; en el nuevo menú quedan en «Catálogo y stock» y no cambia, pero conviene confirmar.
25. **¿«Expresos» (transportes) es configuración de administrador o lo toca Depósito?** Hoy es `fulfillment.manage_carriers` solo para el administrador; la propuesta lo manda a «Sistema».

## F. Alertas (decide Deutsch + quien reciba los avisos)

26. **[bloqueante para M10-15] ¿Cuáles son hoy las 5 alertas que *no* pueden perderse?** (¿despacho vencido, reclamo, falla de integración, pago rechazado?). Sirve para fijar el nivel «crítico» (propuesta §8).
27. **¿Cuántos avisos reciben por día y cuántos terminan en una acción?** Si el sistema no lo registra, se empieza a registrar (M10-01, M10-15).
28. **¿Quieren sonido en alguna situación? ¿Mails de avisos críticos?** Hoy hay email configurable por tipo; confirmar qué roles lo quieren.
29. **¿Quién es dueño de cada tipo de aviso (quién hace algo cuando llega)?** Si nadie, el aviso sobra.

## G. Datos y técnica (decide el equipo técnico / Maico)

30. **¿Qué tiempos de respuesta tiene hoy el sistema en producción (no en la PC del desarrollo)?** Define metas realistas (M10-01, M10-20).
31. **¿Se puede servir HTMX y fuentes desde el propio sitio** (hoy HTMX se carga desde un CDN externo y Source Sans 3 desde Google Fonts en la tienda)? Resuelve dependencia externa y privacidad.
32. **¿Qué herramienta de regresión visual / pruebas de accesibilidad se puede usar** en el entorno de integración continua? (M10-17, M10-27).
33. **¿Qué datos de uso se pueden registrar sin problemas de privacidad?** (M10-29).

## H. Tienda mayorista (decide Deutsch)

34. **¿Hay 2–3 clientes mayoristas dispuestos a una prueba de 30 minutos del flujo de pedido?** Sin eso, la tienda se audita solo con criterios (M10-26).
35. **¿Qué porcentaje de pedidos mayoristas llega desde celular?** Define prioridad del diseño móvil de la tienda.

## I. Qué NO sé y conviene no afirmar (resumen de lo no verificado)

- Cómo funcionan las pantallas del depósito con guantes y sol (evidencia débil, IN §4, §20).
- Tamaños exactos de Apple y Material (mencionados de memoria).
- Los textos originales de Doherty y Thadani (1982), Kahneman y col. (1993), Fitts (1954), Sendelbach y Funk (2013).
- La prevalencia de daltonismo en Argentina (la cifra que tengo es de ascendencia norte-europea).
- Evidencia primaria sobre diseño de tablas densas (la fuente de NN/g no cargó).
- Si «una pantalla por rol» es lo mejor para cada rol de Deutsch (hipótesis de Few; se prueba).
- Cuántas personas hay de cada rol: sin ese dato, las rondas de prueba son un compromiso hasta saberlo.
