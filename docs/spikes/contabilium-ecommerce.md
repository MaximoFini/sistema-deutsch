# Spike M8-02 (DDEV-44): integración "Ecommerce" de Contabilium para la tienda mayorista

**Estado:** pendiente. Lo gestiona Kei con Deutsch (consulta a soporte y adhesión).
**Para qué:** que la tienda mayorista reciba stock y precios MAYORISTA de Contabilium solos, y que los pedidos viajen a Contabilium para facturarse sin cargarlos a mano. Es la etapa B de M8.
**Mientras tanto (etapa A, ya funcionando):**
- El precio mayorista sale de la importación del Excel de Contabilium (M3).
- El stock sale de la sincronización que ya existe.
- Cada pedido se marca "Facturado en Contabilium" a mano, con el número de comprobante. Al marcarlo se libera la reserva de stock.

## 1. Preguntas para el soporte de Contabilium (pedir la respuesta por escrito)

1. **Uso con plataforma propia.** ¿La integración "Ecommerce" (la del plugin de WooCommerce) se puede usar con una tienda propia que implemente el mismo protocolo? ¿Hay términos o restricciones?
2. **Plan.** ¿Está incluida en nuestro plan actual (Pro)? Si no, ¿qué plan hace falta y cuánto cuesta?
3. **Stock y precios hacia la tienda.**
   - ¿Contabilium llama a la tienda (push) o la tienda consulta (pull)?
   - ¿A qué URLs y con qué formato (JSON o XML, campos)?
   - ¿Cada cuánto, o solo cuando hay cambios?
   - ¿Se puede elegir que use la lista de precios **MAYORISTA** y no la general?
   - ¿Manda el precio con o sin IVA?
   - ¿Identifica los productos por SKU o código?
   - ¿Cómo maneja las variantes (talle y color)?
4. **Autenticación.** ¿Cómo se autentica cada llamada (clave, token, firma, IP fija)? ¿Cómo se renueva?
5. **Pedidos hacia Contabilium.**
   - ¿A qué endpoint se envía un pedido y con qué formato?
   - ¿Qué datos del cliente pide (CUIT, condición de IVA, domicilio)? ¿Crea el cliente si no existe?
   - ¿Qué devuelve: número de pedido, número o PDF de factura, o nada?
   - ¿Factura automáticamente o queda un pedido para facturar a mano?
   - ¿Descuenta el stock en ese momento o al facturar?
6. **Correcciones.** Si un pedido ya enviado cambia (por ejemplo, por un faltante), ¿se puede modificar o anular por la integración, o se corrige a mano en Contabilium?
7. **Límites y errores.** ¿Hay límite de llamadas? ¿Qué pasa si la tienda no responde? ¿Reintenta? ¿Hay un registro de sincronizaciones para ver errores?
8. **Entorno de prueba.** ¿Se puede probar sin afectar el stock y la facturación real (cuenta o empresa de prueba)?

## 2. Procedimiento de prueba (una vez que soporte confirme)

> **No adherir la integración en la cuenta real de Deutsch sin la decisión de Deutsch.** Si se puede, probar en una cuenta o empresa de prueba de Contabilium.

1. Levantar la tienda en un servidor con HTTPS (staging), porque Contabilium necesita una URL pública.
2. Activar en el sistema un endpoint de **registro**: guarda cada llamada de Contabilium (método, URL, encabezados sin secretos y cuerpo) y responde 200. Todavía no procesa nada.
3. Adherir la integración apuntando a staging y elegir la lista MAYORISTA.
4. Cambiar en Contabilium el precio y el stock de **un** producto de prueba y registrar qué llamada llega, cuándo y con qué datos.
5. Enviar un pedido de prueba con el formato que indique soporte, chico y de un cliente de prueba. Registrar la respuesta y qué aparece en Contabilium (¿pedido, factura, movimiento de stock?).
6. Anular el pedido de prueba y revertir los cambios del producto.

## 3. Qué registrar

| Dato | Resultado |
|---|---|
| ¿Uso con plataforma propia permitido? (respuesta escrita) | |
| Plan y costo | |
| Sentido de la sincronización de stock y precios (push/pull) y frecuencia | |
| ¿Usa la lista MAYORISTA? ¿Con o sin IVA? | |
| Formato de los datos (adjuntar un ejemplo real, sin secretos) | |
| Autenticación | |
| Endpoint y formato de pedidos; qué devuelve | |
| ¿Factura automático o a mano? ¿Cuándo descuenta stock? | |
| Correcciones de pedidos | |
| Límites, reintentos y registro de errores | |

## 4. Decisión

- **Seguir con la integración** si:
  - el uso con plataforma propia está permitido;
  - usa la lista MAYORISTA;
  - los pedidos llegan a Contabilium con el cliente y las líneas correctas.

  Con eso se programan M8-05 (recibir stock y precios) y M8-10 (enviar pedidos). La reserva de stock pasa a liberarse cuando Contabilium confirma el pedido.
- **Plan B** si alguna de esas condiciones falla: importar periódicamente el Excel de Contabilium (stock y lista MAYORISTA) con el importador de M3, y exportar los pedidos mayoristas a un archivo que Contabilium pueda importar. Si tampoco se puede, se siguen cargando a mano.
