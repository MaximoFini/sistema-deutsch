"""Textos en castellano para los códigos de Mercado Libre (reclamos y salud de publicaciones).

Los códigos que no están acá se muestran tal cual: el texto exacto se confirma con la cuenta real.
"""

CLAIM_TYPES = {
    "mediations": "Reclamo",
    "return": "Devolución",
    "returns": "Devolución",
    "change": "Cambio",
    "cancel_sale": "Cancelación de la venta",
    "cancel_purchase": "Cancelación de la compra",
    "fulfillment": "Reclamo de Full",
    "ml_case": "Caso abierto por Mercado Libre",
    "service": "Reclamo de servicio",
}

CLAIM_STAGES = {
    "claim": "Reclamo (entre comprador y vendedor)",
    "dispute": "Mediación de Mercado Libre",
    "recontact": "Recontacto",
    "stale": "Sin actividad",
    "none": "—",
}

# Motivos: ML usa códigos con prefijo por familia (PNR, PDD, CS…). Primero el código exacto,
# después el prefijo.
CLAIM_REASONS = {}
CLAIM_REASON_PREFIXES = {
    "PNR": "Producto no recibido",
    "PDD": "Producto distinto o defectuoso",
    "CS": "Compra cancelada",
}

RETURN_STATUSES = {
    "pending": "pendiente",
    "label_generated": "etiqueta generada",
    "ready_to_ship": "lista para enviar",
    "shipped": "en camino",
    "delivered": "entregada al vendedor",
    "not_delivered": "no entregada",
    "cancelled": "cancelada",
    "closed": "cerrada",
    "expired": "vencida",
    "failed": "con error",
    "opened": "abierta",
}

CLAIM_STATUSES = {"opened": "Abierto", "closed": "Cerrado"}

# Salud de publicaciones: sub_status, tags y códigos de advertencia de ML.
HEALTH_REASONS = {
    # sub_status
    "out_of_stock": "sin stock",
    "paused": "pausada por el vendedor",
    "deleted": "borrada",
    "expired": "vencida",
    "forbidden": "prohibida por Mercado Libre (infracción)",
    "suspended": "suspendida por Mercado Libre",
    "freezed": "congelada por Mercado Libre",
    "held": "retenida por Mercado Libre",
    "under_review": "en revisión de Mercado Libre",
    "waiting_for_patch": "Mercado Libre pide corregir datos",
    "pending_documentation": "Mercado Libre pide documentación",
    "picture_download_pending": "fotos procesándose",
    "warning": "con advertencia de Mercado Libre",
    # tags
    "moderation_penalty": "penalizada por moderación",
    "poor_quality_picture": "fotos de baja calidad",
    "poor_quality_thumbnail": "foto principal de baja calidad",
    "incomplete_technical_specs": "ficha técnica incompleta",
    # warnings
    "item.attributes.missing_required": "faltan atributos obligatorios",
    "item.attributes.missing_conditional_required": "faltan atributos obligatorios para esta categoría",
    "item.attribute.missing_catalog_required": "faltan atributos que pide el catálogo",
}


def _get(table: dict, code: str) -> str:
    code = code or ""
    return table.get(code, code)


def claim_type(code: str) -> str:
    return _get(CLAIM_TYPES, code)


def claim_stage(code: str) -> str:
    return _get(CLAIM_STAGES, code)


def claim_status(code: str) -> str:
    return _get(CLAIM_STATUSES, code)


def claim_reason(code: str) -> str:
    code = code or ""
    if code in CLAIM_REASONS:
        return CLAIM_REASONS[code]
    for prefix, text in CLAIM_REASON_PREFIXES.items():
        if code.upper().startswith(prefix):
            return f"{text} ({code})"
    return code


def return_status(code: str) -> str:
    return _get(RETURN_STATUSES, code)


def health_reason(code: str) -> str:
    return _get(HEALTH_REASONS, code)


LISTING_STATUSES = {
    "active": "activa",
    "paused": "pausada",
    "closed": "finalizada",
    "under_review": "en revisión",
    "inactive": "inactiva",
    "payment_required": "pago pendiente",
}


def listing_status(code: str) -> str:
    return _get(LISTING_STATUSES, code)
