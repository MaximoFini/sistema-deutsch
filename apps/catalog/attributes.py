"""Orden de los atributos de una variante (talle, color…) para mostrarlos siempre igual.

Postgres (jsonb) no conserva el orden de las claves, así que "M / Negro" podía salir "Negro / M".
Lo usan la lista de picking (M5) y la ficha de una pregunta de Mercado Libre (M6).
"""

ATTRIBUTE_ORDER = ("talle", "color")


def _key(name) -> tuple:
    lower = str(name or "").lower()
    position = ATTRIBUTE_ORDER.index(lower) if lower in ATTRIBUTE_ORDER else len(ATTRIBUTE_ORDER)
    return position, lower


def ordered_values(attributes: dict | None) -> list[str]:
    """Valores no vacíos en orden: talle primero, después color y el resto alfabético."""
    items = sorted((attributes or {}).items(), key=lambda kv: _key(kv[0]))
    return [str(v) for _, v in items if v]


def attributes_text(attributes: dict | None, separator: str = " / ") -> str:
    """Texto tipo «M / Negro» (vacío si no hay atributos)."""
    return separator.join(ordered_values(attributes))
