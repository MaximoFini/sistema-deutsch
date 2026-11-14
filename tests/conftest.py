import pytest
from django.contrib.auth.models import Group
from procrastinate import testing
from procrastinate.contrib.django import app as procrastinate_app

from apps.accounts.models import User
from apps.accounts.roles import ADMIN, DEPOSITO, VENDEDOR, VENTAS, sync_roles


@pytest.fixture(autouse=True)
def in_memory_queue():
    """Cola en memoria: los tests ven qué tareas se encolaron sin worker real."""
    connector = testing.InMemoryConnector()
    with procrastinate_app.replace_connector(connector):
        yield connector


@pytest.fixture
def roles(db):
    sync_roles()
    return {g.name: g for g in Group.objects.all()}


def _make_user(email, role_name, roles):
    user = User.objects.create_user(
        email=email, full_name=email.split("@")[0].title(), password="clave-de-test-123"
    )
    if role_name:
        user.groups.add(roles[role_name])
    return user


@pytest.fixture
def make_user(roles):
    def factory(email="usuario@test.local", role=None):
        return _make_user(email, role, roles)

    return factory


@pytest.fixture
def admin_user(make_user):
    return make_user("admin@test.local", ADMIN)


@pytest.fixture
def users_by_role(make_user):
    return {
        ADMIN: make_user("admin@test.local", ADMIN),
        DEPOSITO: make_user("deposito@test.local", DEPOSITO),
        VENTAS: make_user("ventas@test.local", VENTAS),
        VENDEDOR: make_user("vendedor@test.local", VENDEDOR),
    }


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client
