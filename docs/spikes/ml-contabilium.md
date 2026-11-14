# Spike DDEV-23: convivencia con la integración Mercado Libre ↔ Contabilium

**Estado:** pendiente. Requiere que Deutsch active la integración de Contabilium con Mercado Libre (proyecto DEUSTCH).

## Pregunta

¿La sincronización de Contabilium pisa títulos, descripciones, atributos o fotos editados desde el sistema? Esto define qué campos son seguros para la edición masiva (M6-05).

## Procedimiento

1. Elegir una publicación de prueba, idealmente pausada o con poco movimiento. Anotar su `ITEM_ID`.
2. Foto inicial:
   ```bash
   uv run python manage.py ml_spike_snapshot ITEM_ID
   ```
3. Editar desde la API:
   - título;
   - descripción;
   - un atributo no obligatorio;
   - el orden de las fotos.

   **No** tocar precio ni stock.
4. Esperar al menos un ciclo de sincronización de Contabilium (preguntar a Contabilium cada cuánto corre).
5. Foto final con el mismo comando y comparar los dos JSON que quedan en `local/spikes/`.
6. Revertir los cambios de la publicación.

## Resultado (completar)

| Campo | ¿Contabilium lo pisa? | ¿Seguro para M6-05? |
|---|---|---|
| Título | | |
| Descripción | | |
| Atributos | | |
| Fotos | | |
| Precio / stock | Sí (es su función) | **No** (regla de oro) |
