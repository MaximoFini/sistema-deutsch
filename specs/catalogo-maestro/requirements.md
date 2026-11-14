# Requirements: Catálogo maestro (módulo M3)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Tickets:** DDEV-24 (M3-01), DDEV-25 (M3-02), DDEV-26 (M3-03)
**Depende de:** M1 (catálogo de Tiendanube) y M2 (publicaciones de Mercado Libre), ya programados.

## Summary

Un catálogo único por SKU que cruza, para cada variante:
- la variante de Tiendanube;
- la publicación o variación de Mercado Libre;
- el código de Contabilium;
- más adelante, el producto de la tienda mayorista.

Sobre ese cruce, dos vistas de solo lectura: stock y precio por canal, y un panel de calidad de datos. Son las primeras pantallas de negocio del sistema y la base del maestro de productos del futuro ERP.

## Goals

- Encontrar cualquier producto por SKU, nombre o código de barras y ver en un lugar dónde está publicado y con qué datos.
- Que todo lo que coincide por SKU quede vinculado solo, y que lo que no coincide se pueda vincular a mano en pocos clics.
- Detectar diferencias de stock y precio entre canales antes de que generen una venta sin stock o un precio equivocado.
- Tener una lista priorizada de problemas de datos del catálogo, exportable a Excel.

## Non-goals

- Editar productos, stock o precios en los canales (regla de oro; la edición masiva de publicaciones es M6-05).
- Crear productos desde el sistema: el catálogo se alimenta de Tiendanube, Mercado Libre y Contabilium.
- Integración directa con Contabilium: no hay API. La de la tienda mayorista es M8.
- Tienda mayorista: su columna queda reservada hasta M8.

## User stories

### US-1: Buscar en el catálogo maestro (DDEV-24)

Como usuario del panel, quiero buscar un producto por SKU, nombre o código de barras y ver todos sus vínculos.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Catálogo" que lista las variantes (SKU, producto, talle/color, foto) con búsqueda por SKU, nombre o código de barras y filtros por estado de vínculo.
- WHEN se abre una variante THE SYSTEM SHALL mostrar sus vínculos:
  - Tiendanube (ID y stock/precio del canal);
  - Mercado Libre (cada publicación/variación con estado, logística, stock y precio);
  - Contabilium (código, stock y precios del último archivo importado);
  - Mayorista (reservado).
- THE SYSTEM SHALL usar la variante (`Variant`, con SKU único) como registro maestro. Cada vínculo con un canal es un `ExternalRef` o una `ListingVariation`, nunca una columna por canal (principio ERP 5).

### US-2: Vinculación automática y manual (DDEV-24)

Como Administrador o Ventas, quiero que los cruces por SKU se hagan solos y poder vincular a mano los que no coinciden.

**Acceptance criteria:**

- WHEN entra o se actualiza una publicación de Mercado Libre o un código de Contabilium THE SYSTEM SHALL vincularlo automáticamente a la variante con el mismo SKU. Para Contabilium, si no hay SKU, se busca por código de barras.
- THE SYSTEM SHALL tener una pantalla "Sin vincular" con las variaciones de Mercado Libre y los códigos de Contabilium que no tienen variante, con un buscador de variantes para vincular cada uno.
- WHEN un usuario vincula o desvincula a mano THE SYSTEM SHALL guardar el vínculo como manual (una sincronización automática posterior no lo pisa) y SHALL registrarlo en auditoría (`catalog.link_changed`).
- THE SYSTEM SHALL permitir vincular o desvincular solo a usuarios con el permiso `catalog.manage_links`, que tienen los roles Administrador y Ventas.
- IF se intenta vincular a una variante una variación de ML que ya está vinculada a otra THEN THE SYSTEM SHALL pedir confirmación y SHALL reemplazar el vínculo anterior (auditado).

### US-3: Importar el archivo de productos de Contabilium (DDEV-24)

Como Administrador, quiero subir el archivo de productos que exporta Contabilium, para cruzar sus códigos y tener su stock y sus precios en el sistema.

**Acceptance criteria:**

- THE SYSTEM SHALL aceptar archivos Excel (`.xlsx`) y CSV, y detectar las columnas por nombre: código o SKU, nombre, código de barras, stock, precio minorista y precio mayorista, con variantes de nombre habituales.
- IF el archivo no tiene una columna de código reconocible THEN THE SYSTEM SHALL rechazarlo explicando qué columnas encontró.
- WHEN se sube un archivo THE SYSTEM SHALL mostrar una vista previa antes de aplicar nada:
  - cuántos códigos coinciden con una variante (por SKU o por código de barras);
  - cuántos no coinciden;
  - códigos repetidos en el archivo;
  - filas con errores (precio o stock no numérico);
  - cuántos precios mayoristas cambian.
- WHEN el usuario confirma THE SYSTEM SHALL:
  - vincular los códigos (salvo los vínculos manuales existentes);
  - guardar stock y precios de Contabilium como dato del canal;
  - si el archivo trae precio mayorista, cargarlo en la lista MAYORISTA con vigencia desde la importación, solo si cambió.
- THE SYSTEM SHALL guardar cada importación (fecha, usuario, archivo, resumen) y registrarla en auditoría (`catalog.contabilium_imported`).
- THE SYSTEM SHALL NOT modificar el stock del sistema con este archivo mientras el canal que alimenta el stock sea Tiendanube (`STOCK_FEED_CHANNEL`).

### US-4: Stock y precio por canal (DDEV-25)

Como Administrador, quiero ver para cada SKU el stock y el precio en cada canal, para detectar diferencias.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una vista de solo lectura con una fila por SKU y estas columnas:
  - **stock:** Contabilium, Tiendanube, Mercado Libre propio y Mercado Libre Full (por separado), y Mayorista (reservado);
  - **precio:** lista minorista, lista mayorista, Tiendanube y Mercado Libre.
- THE SYSTEM SHALL tener un filtro "solo con diferencias" que muestre los SKU donde:
  - el stock no Full difiere entre los canales que lo informan;
  - o el precio de un canal difiere del precio minorista vigente.
- THE SYSTEM SHALL resaltar la celda que difiere y mostrar cuándo se actualizó por última vez el dato de cada canal.
- THE SYSTEM SHALL ser solo lectura: no tiene acciones de escritura.
- THE SYSTEM SHALL poder buscar y filtrar por producto, y exportar la vista a Excel.

### US-5: Panel de calidad de datos (DDEV-26)

Como Administrador, quiero una lista de los problemas de datos del catálogo con su gravedad, para corregirlos en el origen.

**Acceptance criteria:**

- THE SYSTEM SHALL detectar estos problemas:
  - sin SKU;
  - SKU duplicado (en Tiendanube o en el archivo de Contabilium);
  - sin código de barras;
  - sin foto;
  - precio $0 o sospechoso (por debajo de un mínimo configurable, o muy distinto entre canales);
  - sin peso o sin medidas;
  - publicado en un canal y no en el otro (Tiendanube y no ML, o una variación de ML sin vincular);
  - stock distinto entre canales.
- THE SYSTEM SHALL asignar a cada problema una severidad: **crítico** o **aviso**. Son críticos: sin SKU, SKU duplicado, precio $0 y stock distinto. El resto son avisos.
- THE SYSTEM SHALL mostrar cada problema con un enlace a la variante, el producto o la publicación, y SHALL permitir filtrar por tipo y severidad.
- THE SYSTEM SHALL permitir exportar la lista a Excel.
- THE SYSTEM SHALL calcular la lista al momento, y SHALL responder en menos de 5 segundos con el tamaño actual del catálogo (~720 variantes).

## Constraints

- Regla de oro: todo es lectura respecto de los canales. Las únicas escrituras son internas (vínculos, lista MAYORISTA, datos del canal Contabilium).
- El SKU es la clave de cruce. Hoy los SKU de Tiendanube son los de Contabilium (así se cargaron en la migración).
- Volumen: unas 280 publicaciones de Tiendanube y 720 variantes. Mercado Libre puede tener varias publicaciones por SKU.
- Nueva dependencia: `openpyxl` (MIT) para leer y escribir Excel.

## Open questions

Ninguna bloqueante. Decisiones del 2026-11-14:

- **Vinculación manual:** Administrador y Ventas.
- **Precio mayorista:** si el archivo de Contabilium lo trae, se carga en la lista MAYORISTA (con vista previa).
- **Columnas del archivo de Contabilium:** el importador detecta columnas por nombre. Se ajusta cuando haya un export real.
- **Mínimo de "precio sospechoso":** valor por defecto $1.000, configurable (`CATALOG_SUSPICIOUS_PRICE_MIN`). Diferencia entre canales mayor a 30 % (configurable).
