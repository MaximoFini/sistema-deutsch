# Design: Catálogo maestro (módulo M3)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Requirements:** [requirements.md](./requirements.md)

## Overview

El maestro es la **variante** (`Variant`, SKU único), agrupada por `Product`, como hasta ahora. Cada canal se cruza con ella de una sola forma, el modelo genérico `Listing` / `ListingVariation` creado en M2:

| Canal | Cómo se representa | Ya existe |
|---|---|---|
| Tiendanube | `ExternalRef(tiendanube, Variant)` con stock y precio en `extra`. TN es la fuente del catálogo: crea las variantes | Sí (M1) |
| Mercado Libre | `Listing` + `ListingVariation` (`channel=mercadolibre`) | Sí (M2) |
| Contabilium | **`Listing` + `ListingVariation` (`channel=contabilium`)**: un `Listing` por código del archivo, con una variación | Nuevo en M3 |
| Mayorista | Reservado (M8). Cuando exista, se representa igual | — |

Así:
- "Sin vincular" es una sola consulta: `ListingVariation.variant IS NULL`, de cualquier canal;
- la vista de stock y precio lee las mismas tablas para todos los canales;
- no se crea ninguna tabla por canal (principio ERP 5).

M3 agrega a M2 dos cosas chicas:
- el origen del vínculo (`link_source`: automático o manual), para que una sincronización no pise un vínculo manual;
- el historial de importaciones de Contabilium.

## 1. Modelo

```python
# catalog.ListingVariation (cambio)
link_source = CharField(choices=[("", "sin vincular"), ("auto", "automático"), ("manual", "manual")], default="")
linked_by   = FK user null
linked_at   = DateTimeField null

# catalog.ContabiliumImport (nuevo)
ContabiliumImport: uploaded_by FK user, uploaded_at, filename, status ("preview"|"applied"|"discarded"),
                   columns JSON (mapeo detectado), rows JSON (filas normalizadas),
                   summary JSON (coinciden, sin coincidir, repetidos, errores, precios mayoristas que cambian),
                   applied_at null, applied_by FK user null
```
- **Contabilium como `Listing`:** `external_id` = código y `title` = nombre. `data` guarda `{barcode, wholesale_price, import_id}`, `price` el precio minorista y `available_quantity` el stock. Tiene una `ListingVariation` con `external_id=""`, `sku` = código, el stock y el precio, y `variant` cuando coincide.
- **Vínculo espejo:** cada vez que una `ListingVariation` queda vinculada a una variante se mantiene también un `ExternalRef(canal, Variant, "{listing}:{variación}")`, igual que en M2. Así cualquier módulo encuentra todos los IDs de una variante por una sola vía.
- **Permisos nuevos (en `catalog`):**

  | Permiso | Roles |
  |---|---|
  | `manage_links` | Administrador, Ventas |
  | `import_contabilium` | Administrador |
  | `view_channel_stock` | Administrador, Ventas |
  | `view_quality` | Administrador, Ventas |

  `view_variant` (ver el catálogo) lo tienen los cuatro roles.
- **Acciones de auditoría nuevas:** `catalog.link_changed` y `catalog.contabilium_imported`.
- **Settings:** `CATALOG_SUSPICIOUS_PRICE_MIN=1000`, `CATALOG_PRICE_DIFF_PCT=30` y `CONTABILIUM_WHOLESALE_INCLUDES_VAT=False` (la lista MAYORISTA es neta; si el archivo trae precios con IVA, se divide por 1,21).

## 2. Vinculación (US-2)

`apps/catalog/linking.py`:
```python
def auto_link(row: ListingVariation) -> bool
    # Si row.link_source == "manual": no toca nada.
    # Busca Variant por SKU (y por código de barras para Contabilium). Si hay → variant, link_source="auto"
    # y ExternalRef espejo. Si no → variant=None, link_source="", y borra el espejo si había.
def link_manual(row, variant, *, user) -> None      # reemplaza el vínculo anterior; audita before/after
def unlink_manual(row, *, user) -> None             # variant=None, link_source="manual" (queda desvinculado a propósito)
def relink_for_variant(variant) -> int              # filas sin vincular con ese SKU → auto_link
```
- **Mercado Libre:** `listings.upsert_item` de M2 pasa a usar `auto_link`, y respeta los vínculos manuales.
- **Tiendanube:** al terminar `catalog.upsert_product` se llama a `relink_for_variant` para cada variante nueva o con SKU cambiado. Así una publicación de ML que llegó antes que la variante se vincula sola.
- **Desvinculado a propósito:** queda con `link_source="manual"` y `variant=None`, y la sincronización lo respeta. En "Sin vincular" aparece con la marca "desvinculado a mano".
- **Ya vinculado a otra variante:** la pantalla muestra una confirmación ("Esta publicación está vinculada a SKU X. ¿Reemplazar?") y `link_manual` audita el reemplazo.

## 3. Importación de Contabilium (US-3)

`apps/catalog/contabilium_import.py`:

```mermaid
sequenceDiagram
    participant U as Admin
    participant V as Vista
    participant P as parse_file
    participant DB as Base
    U->>V: sube archivo (.xlsx / .csv)
    V->>P: leer (openpyxl / csv con detección de ; o ,)
    P->>P: detectar fila de encabezados y columnas por sinónimos
    P->>P: normalizar filas (código, nombre, barras, stock, precios AR "$ 1.234,56")
    P-->>V: filas + errores + repetidos
    V->>DB: ContabiliumImport(status=preview, rows, summary)
    V-->>U: vista previa (coinciden / sin coincidir / repetidos / errores / precios mayoristas que cambian)
    U->>V: Confirmar
    V->>DB: por fila: Listing+ListingVariation contabilium, auto_link, precio MAYORISTA (set_price si cambió)
    V->>DB: status=applied + audit catalog.contabilium_imported
```

- **Encabezados:** se busca en las primeras 10 filas la primera que tenga una columna de código. Los nombres se comparan en minúsculas, sin acentos ni puntuación.

  | Campo | Sinónimos |
  |---|---|
  | código | código, codigo, sku, cod, código interno, código producto |
  | nombre | nombre, descripción, producto, concepto |
  | código de barras | código de barras, cod barras, ean, barcode |
  | stock | stock, stock actual, cantidad, existencia |
  | precio minorista | precio, precio venta, precio final, precio minorista, lista minorista, pvp |
  | precio mayorista | precio mayorista, mayorista, lista mayorista |

  Si no se encuentra la columna de código: error que lista las columnas encontradas.
- **Números en formato argentino:** `"$ 1.234,56"` → 1234,56; `"1234.56"` → 1234,56. Celda vacía = sin dato. Si no es número, la fila va a errores.
- **Repetidos:** si un código aparece varias veces en el archivo, se usa la primera aparición y se informa.
- **Vista previa:** la coincidencia es por SKU y, si no hay, por código de barras. Calcula cuántos precios mayoristas cambian (contra el vigente) y muestra hasta 50 ejemplos de cada grupo. La vista previa **no escribe nada** salvo el registro `ContabiliumImport(status=preview)`.
- **Aplicar:**
  - se hace en una transacción;
  - por cada fila: upsert de `Listing` y `ListingVariation`, `auto_link` (respeta los manuales) y, si hay precio mayorista y la fila tiene variante, `pricing.set_price(MAYORISTA, …)`;
  - los códigos que estaban en una importación anterior y ya no vienen quedan con `Listing.status="missing"`, sin borrarse;
  - el stock **no** toca `StockLevel` mientras `STOCK_FEED_CHANNEL != "contabilium"`.
- **Confirmación única:** una importación aplicada o descartada no se puede volver a aplicar. Los archivos de más de 5 MB se rechazan.

## 4. Pantallas (US-1)

Todas bajo `/catalogo/`, con el layout del panel, HTMX y Tailwind:

| URL | Pantalla | Permiso |
|---|---|---|
| `/catalogo/` | Lista de variantes: búsqueda `q` (SKU, nombre o código de barras), filtros (sin ML, sin Contabilium, para revisar, inactivas), paginada de a 50 | `catalog.view_variant` |
| `/catalogo/<id>/` | Ficha: producto, fotos, atributos, peso y medidas, precios vigentes (minorista y mayorista) y un bloque por canal con sus vínculos | `catalog.view_variant` |
| `/catalogo/sin-vincular/` | Variaciones de ML y códigos de Contabilium sin variante, filtro por canal, con un buscador de variantes (HTMX) por fila | `catalog.manage_links` |
| `/catalogo/vincular/<row>/` (POST) | Vincular, reemplazar o desvincular | `catalog.manage_links` |
| `/catalogo/buscar-variantes/` | Fragmento HTMX con hasta 10 variantes que coinciden | `catalog.manage_links` |
| `/catalogo/contabilium/` | Subir archivo, historial de importaciones | `catalog.import_contabilium` |
| `/catalogo/contabilium/<id>/` | Vista previa, botones Confirmar y Descartar | `catalog.import_contabilium` |
| `/catalogo/stock-precios/` | Vista por canal (§5), `?diferencias=1`, `?formato=xlsx` | `catalog.view_channel_stock` |
| `/catalogo/calidad/` | Panel de calidad (§6), filtros, `?formato=xlsx` | `catalog.view_quality` |

El menú del panel suma "Catálogo", y debajo "Sin vincular", "Stock y precios" y "Calidad", cada uno según el permiso.

## 5. Stock y precio por canal (US-4)

`apps/catalog/channel_view.py` → `build_rows(queryset) -> list[ChannelRow]`, armado con pocas consultas, sin N+1:
1. variantes, con su producto;
2. `ExternalRef` de Tiendanube por `object_id`, para el stock y el precio de `extra`;
3. `ListingVariation` vinculadas (ML y Contabilium) con su `Listing` (`channel`, `logistic_type`, `status`, `last_synced_at`);
4. precios vigentes de MINORISTA y MAYORISTA: todos los `PriceListItem` con `valid_from <= ahora`, ordenados, quedándose con el último por variante y lista.

```python
ChannelRow: variant, product_name, sku,
            stock = {"contabilium": int|None, "tiendanube": int|None, "ml_own": int|None, "ml_full": int|None, "mayorista": None},
            price = {"minorista": Decimal|None, "mayorista": Decimal|None, "tiendanube": Decimal|None, "mercadolibre": Decimal|None},
            updated = {canal: datetime|None},
            stock_diff: bool, price_diff: set[str]   # canales cuyo precio difiere del minorista
```
- **ML propio y Full:** se suman las `available_quantity` de las publicaciones activas del SKU, separando `logistic_type=fulfillment` (Full) del resto (propio).
- **Diferencia de stock:** los valores no nulos entre Contabilium, Tiendanube y ML propio no son todos iguales. Full no entra, porque es otro depósito.
- **Diferencia de precio:** el precio de Tiendanube o de alguna publicación activa de ML es distinto del minorista vigente. La comparación es exacta a 2 decimales y se considera el precio promocional de TN si existe.
- **Exportación:** con `?formato=xlsx` se genera un Excel con las mismas columnas (`openpyxl`, en memoria) y nombre `stock-precios-AAAAMMDD.xlsx`.

## 6. Calidad de datos (US-5)

`apps/catalog/quality.py` → `find_issues() -> list[Issue]`, calculado al momento:

```python
Issue: code, severity ("critical"|"warning"), title, detail, sku, url  # url a la ficha o a "sin vincular"
```

| Código | Detección | Severidad |
|---|---|---|
| `no_sku` | Variante con nota "Sin SKU" (TN) o `ListingVariation` de ML con `sku` vacío | crítico |
| `dup_sku` | Variante con nota de SKU o barras repetido (TN), o código repetido en la última importación de Contabilium | crítico |
| `no_barcode` | Variante activa sin `barcode` | aviso |
| `no_photo` | Producto activo sin `images` | aviso |
| `price_zero` | Precio minorista vigente ≤ 0 | crítico |
| `price_suspicious` | Minorista < `CATALOG_SUSPICIOUS_PRICE_MIN`, o un canal difiere más de `CATALOG_PRICE_DIFF_PCT` % del minorista | aviso |
| `no_weight` / `no_dimensions` | Variante activa sin peso / sin alguna medida | aviso |
| `missing_in_ml` | Variante activa con vínculo de TN y sin publicación activa de ML | aviso |
| `unlinked` | `ListingVariation` de ML o Contabilium sin variante (excepto las desvinculadas a mano) | aviso |
| `stock_diff` | `stock_diff` de §5 | crítico |

- La lista se ordena por severidad, código y SKU.
- **Filtros:** por código y por severidad. Arriba de la lista, un contador por tipo.
- **Exportación:** Excel con severidad, problema, SKU, producto, detalle y link.
- **Rendimiento:** reusa `build_rows` de §5 y hace unas pocas consultas en total. La meta es menos de 5 s con 720 variantes (hay un test de cantidad de consultas).

## 7. Trade-offs

| Decisión | Elegido | Alternativa | Por qué |
|---|---|---|---|
| Contabilium | Como `Listing` del canal contabilium | Tabla `ContabiliumProduct` | Un solo mecanismo de vínculo, de "sin vincular" y de vista por canal; sin tablas por canal |
| Vínculo manual | `link_source` en `ListingVariation` | Tabla de excepciones | Una columna alcanza y queda junto al dato |
| Calidad | Calculada al momento | Tabla de problemas actualizada por tareas | Con ~720 variantes calcular es rápido y nunca muestra datos viejos |
| Columnas del archivo | Detección por sinónimos con vista previa | Formato fijo | Todavía no hay un export real; la vista previa evita importar mal |
| Excel | `openpyxl` | CSV | Lo pide el ticket ("exportable a Excel"), y Deutsch usa Excel |

## 8. Tests

- **Vinculación:**
  - automática por SKU;
  - por código de barras (Contabilium);
  - el vínculo manual no se pisa en la siguiente sync;
  - desvincular a mano queda respetado;
  - reemplazo auditado;
  - relink cuando aparece la variante después;
  - permisos (Depósito no puede vincular).
- **Importador:**
  - xlsx y csv (con `;` y con `,`);
  - encabezado en la fila 3;
  - sinónimos y acentos;
  - números argentinos;
  - sin columna de código → error;
  - repetidos;
  - filas con error;
  - la vista previa no escribe;
  - aplicar vincula, carga MAYORISTA solo si cambió y respeta los manuales;
  - los códigos que desaparecen quedan `missing`;
  - no se puede aplicar dos veces;
  - el IVA incluido se divide por 1,21;
  - no toca `StockLevel`.
- **Vista por canal:** columnas correctas con datos de los 3 canales, ML propio y Full separados, filtro de diferencias (stock y precio), Excel descargable con encabezados, solo lectura (no hay POST).
- **Calidad:** un caso por cada código de problema, severidades, filtros, Excel, cantidad de consultas acotada.
- **Pantallas:** búsqueda por SKU, nombre y código de barras; la ficha muestra los vínculos de cada canal; permisos por rol.

## 9. Trazabilidad

| Requirement | Dónde |
|---|---|
| US-1 búsqueda, ficha con vínculos, Variant como maestro | §1, §4 |
| US-2 automática por SKU/barras, sin vincular, manual que no se pisa, auditoría, permisos, reemplazo | §1, §2, §4 |
| US-3 xlsx/csv, columnas, vista previa, aplicar, MAYORISTA, historial, no tocar stock | §1, §3 |
| US-4 columnas, diferencias, resaltado, solo lectura, Excel | §5 |
| US-5 problemas, severidad, enlace, filtros, Excel, rendimiento | §6 |

## Riesgos

- **Formato real del export de Contabilium:** puede usar otros nombres de columna o varias listas de precio. La detección por sinónimos y la vista previa lo absorben; si hace falta, se agregan sinónimos con el archivo real.
- **IVA en el precio mayorista del archivo:** se asume neto, con un setting para cambiarlo. Se confirma con el archivo real.
- **Varias publicaciones de ML por SKU:** se suman para el stock propio, y cada una aparece en la ficha y en las diferencias de precio.
