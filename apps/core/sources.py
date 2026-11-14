"""Consulta de la fuente de verdad. Todo formulario o servicio que edite stock, precio,
producto, cliente o factura debe llamar a `ensure_system_owned` antes de escribir."""

from .models import DataSource


class SourceOfTruthViolation(Exception):
    """Se intentó editar en el sistema un dato cuya fuente de verdad es externa."""


def source_of(data_type: str) -> str:
    try:
        return DataSource.objects.only("source").get(data_type=data_type).source
    except DataSource.DoesNotExist:
        # Sin configuración explícita, el dato es de Contabilium (valor seguro).
        return DataSource.Source.CONTABILIUM


def is_owned_by_system(data_type: str) -> bool:
    return source_of(data_type) == DataSource.Source.SYSTEM


def ensure_system_owned(data_type: str) -> None:
    if not is_owned_by_system(data_type):
        raise SourceOfTruthViolation(
            f"El dato '{data_type}' se edita en {source_of(data_type)}, no en el sistema."
        )


def set_source(data_type: str, source: str, user=None) -> DataSource:
    obj, _ = DataSource.objects.update_or_create(
        data_type=data_type, defaults={"source": source, "changed_by": user}
    )
    return obj
