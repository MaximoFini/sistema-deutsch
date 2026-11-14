"""Credenciales de canales, cifradas con Fernet. La clave viene de FIELD_ENCRYPTION_KEY
(admite varias separadas por coma: la primera cifra, todas descifran → rotación)."""

import json

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings

from .models import Channel, ChannelCredential


class CredentialsMissing(Exception):
    pass


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings.FIELD_ENCRYPTION_KEYS if k.strip()]
    if not keys:
        raise RuntimeError("Falta FIELD_ENCRYPTION_KEY")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt(token: bytes) -> dict:
    return json.loads(_fernet().decrypt(bytes(token)).decode())


def save(channel: Channel | str, data: dict, expires_at=None) -> None:
    if isinstance(channel, str):
        channel = Channel.objects.get(code=channel)
    ChannelCredential.objects.update_or_create(
        channel=channel, defaults={"data_encrypted": encrypt(data), "expires_at": expires_at}
    )


def get(channel: Channel | str) -> dict:
    code = channel if isinstance(channel, str) else channel.code
    cred = ChannelCredential.objects.filter(channel__code=code).first()
    if cred is None:
        raise CredentialsMissing(f"El canal {code} no tiene credenciales cargadas.")
    return decrypt(cred.data_encrypted)


def rotate_all() -> int:
    """Re-cifra todas las credenciales con la clave principal actual."""
    count = 0
    for cred in ChannelCredential.objects.all():
        cred.data_encrypted = _fernet().rotate(bytes(cred.data_encrypted))
        cred.save(update_fields=["data_encrypted", "updated_at"])
        count += 1
    return count
