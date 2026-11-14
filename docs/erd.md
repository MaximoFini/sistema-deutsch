# Diagrama de entidades (núcleo M0)

Fuente: modelos en `apps/*/models.py`. Convenciones y razones en [`specs/base-sistema/design.md` §3](../specs/base-sistema/design.md).

```mermaid
erDiagram
    Product ||--o{ Variant : "tiene"
    Variant ||--o{ StockLevel : "stock en"
    Warehouse ||--o{ StockLevel : "contiene"
    Variant ||--o{ StockMovement : "mueve"
    Warehouse ||--o{ StockMovement : "en"
    PriceList ||--o{ PriceListItem : "contiene"
    Variant ||--o{ PriceListItem : "precio con vigencia"
    PriceList |o--o{ Customer : "lista asignada"
    Customer ||--o{ Address : "domicilios"
    Customer |o--o{ SalesDocument : "compra"
    Channel ||--o{ SalesDocument : "origen"
    SalesDocument ||--o{ SalesLine : "líneas"
    Variant |o--o{ SalesLine : "vende"
    SalesDocument ||--o{ Payment : "pagos"
    SalesDocument ||--o{ Shipment : "envíos"
    SalesDocument |o--o{ SalesDocument : "relacionado (devolución, futura factura)"
    Channel ||--o{ ExternalRef : "IDs externos de cualquier entidad"
    Channel ||--o| ChannelCredential : "credencial cifrada"
    Channel ||--o{ ChannelWriteSwitch : "interruptor stock / precio"
    Channel ||--o{ InboundEvent : "eventos recibidos"
    Channel ||--o{ SyncRun : "conciliaciones"
    User ||--o{ AuditLog : "acciones"
    AlertType ||--o{ Alert : "alertas"
    Alert ||--o{ AlertReceipt : "por usuario"
    User ||--o{ AlertReceipt : "recibe"

    Product { string name  string category  bool is_active }
    Variant { string sku UK  string barcode UK  json attributes  int weight_g }
    StockLevel { decimal on_hand  decimal reserved }
    StockMovement { string kind  decimal quantity  string affects  string source }
    PriceListItem { decimal price  decimal vat_rate  datetime valid_from }
    Customer { string kind  string tax_id  string vat_condition  bool credit_enabled }
    SalesDocument { string doc_type  int number  string status  decimal total  json fiscal }
    ExternalRef { string external_id  int object_id }
    InboundEvent { string topic  string dedupe_key UK  string status  int attempts }
    DataSource { string data_type UK  string source }
```

`DataSource` (fuente de verdad por tipo de dato) no tiene relaciones: la consultan los servicios antes de escribir.
