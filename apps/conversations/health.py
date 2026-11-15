"""Salud de publicaciones de Mercado Libre y guía de talles (M6). Solo lectura: nunca escribe en ML.

Los problemas se calculan en Python sobre las publicaciones no cerradas (unos pocos miles), igual que
el panel de Calidad de M3.
"""

import io
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.catalog.models import Listing, ListingVariation

from .labels import HEALTH_REASONS, health_reason

logger = logging.getLogger(__name__)
CHANNEL = "mercadolibre"

PROBLEMS = {
    "paused": "Pausada",
    "under_review": "En revisión / infracción",
    "incomplete": "Ficha técnica incompleta",
    "low_quality": "Calidad baja",
    "needs_review": "Revisar datos (sistema)",
}
MODERATION_SUB_STATUS = {
    "forbidden",
    "suspended",
    "freezed",
    "held",
    "under_review",
    "waiting_for_patch",
    "pending_documentation",
}
MODERATION_TAGS = {"moderation_penalty"}
INCOMPLETE_TAGS = {"incomplete_technical_specs"}
POOR_QUALITY_TAGS = {"poor_quality_picture", "poor_quality_thumbnail"}
OPEN_STATUSES_EXCLUDED = ["closed", "missing", "inactive"]


@dataclass
class Problem:
    code: str
    reason: str

    @property
    def title(self) -> str:
        return PROBLEMS[self.code]


@dataclass
class HealthRow:
    listing: Listing
    problems: list[Problem]
    skus: list[str] = field(default_factory=list)

    @property
    def picture(self) -> str:
        pictures = (self.listing.data or {}).get("pictures") or []
        return pictures[0] if pictures else ""

    @property
    def edit_url(self) -> str:
        return listing_edit_url(self.listing)

    @property
    def codes(self) -> set[str]:
        return {p.code for p in self.problems}


def listing_edit_url(listing: Listing) -> str:
    return settings.ML_LISTING_EDIT_URL.format(id=listing.external_id)


def _as_list(value) -> list:
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def _warning_code(w) -> str:
    if isinstance(w, dict):
        return str(w.get("code") or w.get("cause_id") or "")
    return str(w)


def _warning_text(w) -> str:
    code = _warning_code(w)
    if code in HEALTH_REASONS:
        return health_reason(code)
    if isinstance(w, dict) and w.get("message"):
        return str(w["message"])
    return code


def _is_attribute_warning(w) -> bool:
    code = _warning_code(w).lower()
    return "attribute" in code and ("missing" in code or "required" in code)


def problems_for(listing: Listing) -> list[Problem]:
    data = listing.data or {}
    sub_status = [str(s) for s in _as_list(data.get("sub_status"))]
    tags = {str(t) for t in _as_list(data.get("tags"))}
    warnings = _as_list(data.get("warnings"))
    problems: list[Problem] = []

    if listing.status == "paused":
        reasons = [health_reason(s) for s in sub_status if s not in MODERATION_SUB_STATUS]
        problems.append(Problem("paused", ", ".join(reasons) or "sin motivo informado por Mercado Libre"))

    moderation = [s for s in sub_status if s in MODERATION_SUB_STATUS] + sorted(tags & MODERATION_TAGS)
    if listing.status == "under_review" or moderation:
        reasons = [health_reason(s) for s in moderation] or [health_reason("under_review")]
        problems.append(Problem("under_review", ", ".join(dict.fromkeys(reasons))))

    attr_warnings = [w for w in warnings if _is_attribute_warning(w)]
    if tags & INCOMPLETE_TAGS or attr_warnings:
        reasons = [health_reason(t) for t in sorted(tags & INCOMPLETE_TAGS)] + [
            _warning_text(w) for w in attr_warnings
        ]
        problems.append(Problem("incomplete", ", ".join(dict.fromkeys(reasons))))

    min_score = Decimal(str(settings.ML_HEALTH_MIN_SCORE))
    low_reasons = []
    if listing.health is not None and listing.health < min_score:
        low_reasons.append(f"puntaje de salud {int(listing.health * 100)}% (mínimo {int(min_score * 100)}%)")
    low_reasons += [health_reason(t) for t in sorted(tags & POOR_QUALITY_TAGS)]
    if low_reasons:
        problems.append(Problem("low_quality", ", ".join(low_reasons)))

    if listing.needs_review:
        problems.append(Problem("needs_review", listing.review_notes or "revisar datos de la publicación"))
    return problems


def ml_listings():
    return (
        Listing.objects.filter(channel__code=CHANNEL)
        .exclude(status__in=OPEN_STATUSES_EXCLUDED)
        .prefetch_related(Prefetch("variations", queryset=ListingVariation.objects.only("listing_id", "sku")))
        .order_by("title", "pk")
    )


def listings_with_problems(q: str = "", code: str = "") -> tuple[list[HealthRow], dict[str, int]]:
    """Publicaciones con al menos un problema (filtradas por búsqueda y tipo) y el contador por tipo.

    El contador se calcula con la búsqueda aplicada pero sin el filtro de tipo, para que los chips
    muestren cuántas hay de cada uno.
    """
    qs = ml_listings()
    q = (q or "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(external_id__icontains=q) | Q(variations__sku__icontains=q)
        ).distinct()
    rows: list[HealthRow] = []
    counts = dict.fromkeys(PROBLEMS, 0)
    for listing in qs:
        problems = problems_for(listing)
        if not problems:
            continue
        for p in problems:
            counts[p.code] += 1
        skus = sorted({v.sku for v in listing.variations.all() if v.sku})
        rows.append(HealthRow(listing, problems, skus))
    if code:
        rows = [r for r in rows if code in r.codes]
    return rows, counts


def export_xlsx(rows: list[HealthRow]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Salud de publicaciones"
    ws.append(["Publicación", "Título", "SKU", "Estado", "Problemas", "Motivos", "Editar en ML"])
    for r in rows:
        ws.append(
            [
                r.listing.external_id,
                r.listing.title,
                ", ".join(r.skus),
                r.listing.status,
                ", ".join(p.title for p in r.problems),
                " | ".join(f"{p.title}: {p.reason}" for p in r.problems),
                r.edit_url,
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Guía de talles ───────────────────────────────────────────────────────


def _value_name(attr: dict) -> str:
    values = attr.get("values") or []
    if values and isinstance(values[0], dict):
        return str(values[0].get("name") or "")
    return str(attr.get("value_name") or "")


def normalize_chart(chart: dict) -> dict:
    """Convierte la respuesta de /catalog/charts/{id} en columnas y filas {talle, medidas}."""
    main_ids = {
        a.get("id") for a in ((chart.get("main_attribute") or {}).get("attributes") or []) if a.get("id")
    } or {"SIZE"}
    columns: list[str] = []
    rows = []
    for row in chart.get("rows") or []:
        size, values = "", {}
        for attr in row.get("attributes") or []:
            name = attr.get("name") or attr.get("id") or ""
            if attr.get("id") in main_ids and not size:
                size = _value_name(attr)
                continue
            if attr.get("id") in ("FILTRABLE_SIZE",):
                continue
            values[name] = _value_name(attr)
            if name not in columns:
                columns.append(name)
        if size:
            rows.append({"size": size, "measures": values})
    for row in rows:
        row["cells"] = [row["measures"].get(c, "") for c in columns]
    return {"columns": columns, "rows": rows}


def _fresh(chart: dict | None, grid_id: str) -> bool:
    if not chart or chart.get("grid_id") != grid_id:
        return False
    fetched = parse_datetime(chart.get("fetched_at") or "")
    return bool(fetched and timezone.now() - fetched < timedelta(hours=settings.ML_SIZE_CHART_TTL_HOURS))


def size_chart(listing: Listing | None, client=None) -> dict | None:
    """Guía de talles de la publicación en ML, cacheada en `Listing.data["size_chart"]`.

    Devuelve None si la publicación no tiene guía o si ML falla (la pantalla no se rompe).
    """
    if listing is None:
        return None
    data = listing.data or {}
    grid_id = str(data.get("size_grid_id") or "")
    if not grid_id:
        return None
    cached = data.get("size_chart")
    if _fresh(cached, grid_id):
        return cached
    try:
        if client is None:
            from apps.integrations.adapters.mercadolibre.client import MLClient

            client = MLClient()
        chart = normalize_chart(client.get(f"/catalog/charts/{grid_id}"))
    except Exception:  # noqa: BLE001 — la guía es un extra: si ML falla, se usa la vieja o nada
        logger.warning("No se pudo traer la guía de talles %s de ML", grid_id, exc_info=True)
        return cached if cached and cached.get("grid_id") == grid_id else None
    chart.update(grid_id=grid_id, fetched_at=timezone.now().isoformat())
    listing.data = {**data, "size_chart": chart}
    Listing.objects.filter(pk=listing.pk).update(data=listing.data)
    return chart
