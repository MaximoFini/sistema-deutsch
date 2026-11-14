# Crear la app del sistema en Mercado Libre Developers

Son dos pasos de personas distintas:
1. **Kei** crea la app en <https://developers.mercadolibre.com.ar> (unos 10 min).
2. **El dueño de la cuenta vendedora de Deutsch** autoriza la app iniciando sesión con esa cuenta. Sin esto, el sistema no puede leer ventas.

## 1. Crear la app (Kei)

1. Entrar a <https://developers.mercadolibre.com.ar> → **Mis aplicaciones → Crear nueva aplicación**.
2. Datos:
   - **Nombre:** `Sistema Deutsch`
   - **Descripción corta:** centro de pedidos interno de Deutsch.
   - **URI de redirect:**
     - **Sin servidor (ahora):** una URL `https` cualquiera que controle Kei, por ejemplo `https://keisoftware.com.ar/ml-callback`. Mercado Libre no acepta `localhost`. La página puede no existir: lo único que importa es la URL a la que vuelve el navegador.
     - **Con servidor (después):** `https://panel.deutsch.com.ar/integraciones/mercadolibre/callback/`
   - **Scopes:** lectura, escritura y `offline_access` (este último es necesario para que el token se renueve solo).
3. **Tópicos de notificaciones:** `orders_v2`, `shipments`, `questions`, `messages`, `claims` e `items`.
4. **URL de notificaciones:** `https://panel.deutsch.com.ar/hooks/mercadolibre/`. Hasta que haya servidor, el sistema consulta cada 5 minutos y no necesita esta URL.

## 2. Copiar los datos al `.env`

Copiar el **App ID** y la **Secret Key** a `sistema-deutsch/.env`. **Nunca** en Plane, en el chat ni en el repositorio.

```
ML_APP_ID=<App ID>
ML_CLIENT_SECRET=<Secret Key>
ML_REDIRECT_URI=<la misma URI de redirect que cargaste en la app>
ML_LABEL_FORMAT=pdf        # cambiar a zpl2 si la térmica es Zebra
```

Reiniciar el servidor local y el worker.

## 3. Autorizar (dueño de la cuenta de Deutsch)

1. En el panel: **Integraciones → tarjeta Mercado Libre → Conectar Mercado Libre**.
2. Mercado Libre pide iniciar sesión: tiene que ser **la cuenta vendedora de Deutsch** (no una personal) y aceptar.
3. **Sin servidor:** el navegador vuelve a la URL `https` de la app, con algo como `?code=TG-...&state=...` al final. Copiar **la URL completa** de la barra de direcciones, pegarla en el campo **"Pegá la URL de vuelta"** de la tarjeta y tocar **Terminar conexión**. El código vence en pocos minutos, así que conviene hacerlo enseguida.
4. **Con servidor:** vuelve solo al panel.
5. Arrancan las importaciones de publicaciones y de las ventas de los últimos 30 días. El token se renueva solo cada pocas horas.

## Usuarios de prueba (opcional)

Para probar sin tocar la cuenta real, con la app conectada:

```bash
uv run python manage.py ml_test_user
```

Muestra el usuario y la contraseña **una sola vez**. Guardala en tu gestor de contraseñas, no en el repo ni en Plane.

## Si algo falla

- **"Faltan ML_APP_ID o ML_REDIRECT_URI":** falta el paso 2 o no se reinició el servidor.
- **"No es válida o venció":** el `state` no coincide o pasó mucho tiempo. Tocá Conectar de nuevo.
- **"Mercado Libre se desconectó"** (alerta): el token no se pudo renovar (permiso revocado o vencido). Hay que repetir el paso 3 con el dueño de la cuenta.
