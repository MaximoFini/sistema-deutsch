"""Almacenamiento privado: comprobantes de pago y otros archivos de clientes.

Va fuera de MEDIA_ROOT y sin URL pública: los archivos se sirven solo desde una vista que controla
el permiso. Si `STORAGES["private"]` está configurado (prod, tests) se usa ese; si no, una carpeta
local `PRIVATE_MEDIA_ROOT`.
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage, InvalidStorageError, storages


def private_storage():
    try:
        return storages["private"]
    except InvalidStorageError:
        return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)
