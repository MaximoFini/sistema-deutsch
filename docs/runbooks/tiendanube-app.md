# Crear la app del sistema en Tiendanube Partners

Este paso lo hace una persona con la cuenta de socio de Kei: hay que aceptar los términos de Tiendanube. Lleva unos 10 minutos. Es una **app nueva**, distinta de la que se usó para la migración.

## 1. Crear la app

1. Entrar a <https://partners.tiendanube.com> con la cuenta de Kei.
2. **Aplicaciones → Crear aplicación**.
3. Datos básicos:
   - **Nombre:** `Sistema Deutsch`
   - **Tipo:** aplicación para una tienda (no para publicar en la tienda de apps).
   - **Email de contacto:** el de soporte de Kei.

## 2. Permisos (solo estos)

Marcar exactamente estos permisos:

| Permiso | Para qué |
|---|---|
| Productos: **lectura** (`read_products`) | Traer el catálogo. **No** marcar escritura. |
| Pedidos: **lectura y escritura** (`write_orders`) | Traer los pedidos. |
| Clientes: **lectura** (`read_customers`) | Datos del comprador para despachar. |
| Órdenes de envío / Fulfillment orders: **lectura y escritura** (`write_fulfillment_orders`) | Marcar empaquetado, enviado y entregado. |

> Si la app pide escritura de productos, el sistema la conecta igual pero muestra una advertencia. La regla de oro dice que el sistema no escribe productos, stock ni precios.

## 3. URL de redirección

- **En tu PC (ahora):** `http://localhost:8000/integraciones/tiendanube/callback/`
- **Con servidor (después):** `https://panel.deutsch.com.ar/integraciones/tiendanube/callback/`

Si el portal permite una sola URL, poner la local ahora y cambiarla al desplegar.

## 4. Webhooks de privacidad (obligatorios)

En la sección de webhooks o LGPD de la app. Hasta que haya servidor se pueden dejar con la URL de producción, que va a responder cuando despleguemos:

| Webhook | URL |
|---|---|
| Store redact | `https://panel.deutsch.com.ar/hooks/tiendanube/privacy/store_redact/` |
| Customers redact | `https://panel.deutsch.com.ar/hooks/tiendanube/privacy/customers_redact/` |
| Customers data request | `https://panel.deutsch.com.ar/hooks/tiendanube/privacy/customers_data_request/` |

Los webhooks de pedidos y productos **no** se cargan a mano: el sistema los registra solo cuando hay servidor (`TN_WEBHOOKS_BASE_URL`).

## 5. Copiar los datos al `.env`

En la app recién creada vas a ver el **App ID** y el **Client secret**. Ponelos en `sistema-deutsch/.env`. **Nunca** en Plane, en el chat ni en el repositorio.

```
TN_APP_ID=<el App ID>
TN_CLIENT_SECRET=<el Client secret>
TN_USER_AGENT=Sistema Deutsch (<email de soporte de Kei>)
```

Después reiniciá el servidor local (`runserver`) y el worker.

## 6. Conectar

1. Panel → **Integraciones** → tarjeta **Tiendanube** → **Conectar Tiendanube**.
2. Tiendanube te pide autorizar la app en la tienda de Deutsch (8434848). Aceptás.
3. Volvés al panel con el mensaje "Tiendanube conectado" y empiezan las importaciones:
   - catálogo completo;
   - pedidos de los últimos 30 días.
4. Con el worker corriendo (`uv run python manage.py procrastinate worker`), los pedidos nuevos entran cada 5 minutos.

## Si algo falla

- **"Falta configurar la app (TN_APP_ID)":** falta el paso 5 o no se reinició el servidor.
- **"La conexión no es válida o venció":** el link de autorización dura 5 minutos. Volvé a tocar Conectar.
- **"Faltan permisos":** revisá el paso 2 y reconectá.
