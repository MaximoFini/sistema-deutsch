"""Funciones de Postgres que Django no trae: percentiles y duración en segundos."""

from django.db.models import Aggregate, FloatField, Func


class Percentile(Aggregate):
    """`percentile_cont(p) WITHIN GROUP (ORDER BY expr)`: p=0.5 es la mediana."""

    function = "percentile_cont"
    name = "Percentile"
    output_field = FloatField()
    template = "%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"

    def __init__(self, expression, percentile: float, **extra):
        if not 0 <= float(percentile) <= 1:
            raise ValueError("El percentil va de 0 a 1.")
        super().__init__(expression, percentile=repr(float(percentile)), **extra)


class Epoch(Func):
    """Segundos de un intervalo (p. ej. `F("answered_at") - F("asked_at")`)."""

    template = "EXTRACT(EPOCH FROM %(expressions)s)"
    output_field = FloatField()
