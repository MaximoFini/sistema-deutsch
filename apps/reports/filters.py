"""Filtros de los reportes: período (atajos o rango libre) y canal. Viajan en la URL."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

TZ = ZoneInfo(settings.TIME_ZONE)
MAX_DAYS = 730  # 2 años

PRESETS = {
    "hoy": "Hoy",
    "7d": "Últimos 7 días",
    "30d": "Últimos 30 días",
    "mes": "Este mes",
    "mes_anterior": "Mes anterior",
    "rango": "Rango libre",
}
DEFAULT_PRESET = "30d"
CHANNELS = {
    "": "Todos los canales",
    "tiendanube": "Tiendanube",
    "mercadolibre": "Mercado Libre",
    "manual": "Manual",
}


@dataclass
class Filters:
    start: date  # primer día incluido (hora Argentina)
    end: date  # último día incluido
    channel: str = ""
    preset: str = DEFAULT_PRESET
    warnings: list[str] = field(default_factory=list)

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=TZ)

    @property
    def end_dt(self) -> datetime:
        """Exclusivo: medianoche del día siguiente al último."""
        return datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=TZ)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "Filters":
        """Mismo largo, inmediatamente antes."""
        end = self.start - timedelta(days=1)
        return Filters(
            start=end - timedelta(days=self.days - 1), end=end, channel=self.channel, preset="rango"
        )

    @property
    def channel_label(self) -> str:
        return CHANNELS.get(self.channel, self.channel)

    @property
    def label(self) -> str:
        if self.start == self.end:
            return f"{self.start:%d/%m/%Y}"
        return f"{self.start:%d/%m/%Y} al {self.end:%d/%m/%Y}"

    def params(self) -> dict:
        data = {"periodo": self.preset}
        if self.preset == "rango":
            data.update(desde=self.start.isoformat(), hasta=self.end.isoformat())
        if self.channel:
            data["canal"] = self.channel
        return data

    def querystring(self) -> str:
        return urlencode(self.params())


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def preset_range(preset: str, today: date) -> tuple[date, date]:
    if preset == "hoy":
        return today, today
    if preset == "7d":
        return today - timedelta(days=6), today
    if preset == "mes":
        return today.replace(day=1), today
    if preset == "mes_anterior":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    return today - timedelta(days=29), today  # 30d


def from_request(get, today: date | None = None) -> Filters:
    """Arma los filtros desde `request.GET`. Nunca falla: lo inválido se corrige y se avisa."""
    today = today or timezone.localdate()
    warnings: list[str] = []
    channel = get.get("canal", "") or ""
    if channel not in CHANNELS:
        warnings.append("Ese canal no existe: se muestran todos.")
        channel = ""
    preset = get.get("periodo") or ("rango" if get.get("desde") or get.get("hasta") else DEFAULT_PRESET)
    if preset not in PRESETS:
        warnings.append("Ese período no existe: se muestran los últimos 30 días.")
        preset = DEFAULT_PRESET
    if preset != "rango":
        start, end = preset_range(preset, today)
        return Filters(start, end, channel, preset, warnings)

    start, end = _parse_date(get.get("desde")), _parse_date(get.get("hasta"))
    if start is None and end is None:
        warnings.append("Las fechas no son válidas: se muestran los últimos 30 días.")
        start, end = preset_range(DEFAULT_PRESET, today)
        return Filters(start, end, channel, DEFAULT_PRESET, warnings)
    if end is None:
        end = today
    if start is None:
        start = end - timedelta(days=29)
    if start > end:
        start, end = end, start
        warnings.append("La fecha «desde» era posterior a «hasta»: se invirtieron.")
    if (end - start).days + 1 > MAX_DAYS:
        start = end - timedelta(days=MAX_DAYS - 1)
        warnings.append(f"El rango máximo es de 2 años: se muestra desde el {start:%d/%m/%Y}.")
    return Filters(start, end, channel, "rango", warnings)
