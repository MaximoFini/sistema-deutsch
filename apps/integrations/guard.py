"""Regla de oro: el sistema NO escribe stock ni precio en los canales mientras Contabilium
sea la fuente de verdad. Todo `write_stock` / `write_price` de un adaptador debe llamar a
`ensure_write_allowed` en su primera línea."""

import logging
from typing import Literal

from django.conf import settings

from apps.audit import services as audit

from .models import ChannelWriteSwitch

logger = logging.getLogger(__name__)


class WriteBlocked(Exception):
    pass


def is_write_allowed(channel_code: str, kind: Literal["stock", "price"]) -> bool:
    if not settings.ALLOW_CHANNEL_WRITES:  # llave 1: el servidor
        return False
    return ChannelWriteSwitch.objects.filter(  # llave 2: el interruptor del panel
        channel__code=channel_code, kind=kind, enabled=True
    ).exists()


def ensure_write_allowed(
    channel_code: str, kind: Literal["stock", "price"], detail: dict | None = None
) -> None:
    if is_write_allowed(channel_code, kind):
        return
    logger.warning("Escritura de %s a %s bloqueada por la regla de oro", kind, channel_code)
    audit.record(
        None,
        "integration.write_blocked",
        None,
        after={"channel": channel_code, "kind": kind, **(detail or {})},
    )
    raise WriteBlocked(f"Escritura de {kind} a {channel_code} bloqueada (interruptor apagado).")


def set_switch(*, actor, request, channel, kind: str, enabled: bool) -> ChannelWriteSwitch:
    switch, _ = ChannelWriteSwitch.objects.get_or_create(channel=channel, kind=kind)
    before = {"enabled": switch.enabled}
    switch.enabled = enabled
    switch.changed_by = actor
    switch.save()
    audit.record(
        actor,
        "integration.write_switch_changed",
        switch,
        before=before,
        after={"enabled": enabled},
        request=request,
    )
    return switch
