import re

import pytest
from django.contrib.auth.models import Permission
from django.core import mail
from django.urls import reverse

from apps.accounts.models import User, UserPermissionDenial
from apps.accounts.roles import ADMIN, DEPOSITO, VENTAS
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def perm(name):
    app_label, codename = name.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


# ── Login, recuperación, desactivación ─────────────────────────────────────


def test_login_ok_and_wrong_password(client, admin_user):
    url = reverse("accounts:login")
    bad = client.post(url, {"username": admin_user.email, "password": "incorrecta"})
    assert bad.status_code == 200 and "_auth_user_id" not in client.session
    ok = client.post(url, {"username": admin_user.email.upper(), "password": "clave-de-test-123"})
    assert ok.status_code == 302 and client.session["_auth_user_id"] == str(admin_user.pk)


def test_no_signup_url_exists(client):
    for path in ["/cuenta/registro/", "/cuenta/signup/", "/registro/", "/signup/"]:
        assert client.get(path).status_code in (302, 404)  # 302 = home pide login, nunca un formulario


def test_password_reset_single_use(client, admin_user):
    client.post(reverse("accounts:password_reset"), {"email": admin_user.email})
    assert len(mail.outbox) == 1
    link = re.search(r"http://testserver(/cuenta/recuperar/[^\s]+)", mail.outbox[0].body).group(1)
    form_page = client.get(link, follow=True)
    set_url = form_page.redirect_chain[-1][0]
    data = {"new_password1": "OtraClave-Segura-2026", "new_password2": "OtraClave-Segura-2026"}
    assert client.post(set_url, data).status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.check_password("OtraClave-Segura-2026")
    reused = client.get(link, follow=True)
    assert reused.context["validlink"] is False


def test_inactive_user_cannot_login_and_session_is_cut(client, admin_user):
    client.force_login(admin_user)
    assert client.get(reverse("core:home")).status_code == 200
    User.objects.filter(pk=admin_user.pk).update(is_active=False)
    assert client.get(reverse("core:home")).status_code == 302  # sesión cortada
    client.logout()
    client.post(reverse("accounts:login"), {"username": admin_user.email, "password": "clave-de-test-123"})
    assert "_auth_user_id" not in client.session


# ── Roles y permisos ─────────────────────────────────────────────────────


def test_roles_exist_with_permissions(roles):
    assert set(roles) >= {ADMIN, DEPOSITO, VENTAS, "Vendedor"}
    assert roles[ADMIN].permissions.filter(codename="manage_users").exists()
    assert not roles[DEPOSITO].permissions.filter(codename="manage_users").exists()


def test_extra_permission_adds_without_changing_role(make_user):
    user = make_user("dep@test.local", DEPOSITO)
    assert not user.has_perm("audit.view_auditlog")
    user.user_permissions.add(perm("audit.view_auditlog"))
    user = User.objects.get(pk=user.pk)
    assert user.has_perm("audit.view_auditlog")
    assert user.groups.get().name == DEPOSITO


def test_denial_removes_role_permission(make_user):
    user = make_user("adm2@test.local", ADMIN)
    assert user.has_perm("accounts.manage_users")
    UserPermissionDenial.objects.create(user=user, permission=perm("accounts.manage_users"))
    user = User.objects.get(pk=user.pk)
    assert not user.has_perm("accounts.manage_users")
    assert user.has_perm("audit.view_auditlog")  # el resto del rol sigue


def test_forbidden_screen_returns_403_without_data(client, users_by_role):
    client.force_login(users_by_role[DEPOSITO])
    response = client.get(reverse("accounts:user_list"))
    assert response.status_code == 403
    assert users_by_role[ADMIN].email.encode() not in response.content


def test_anonymous_is_sent_to_login(client):
    response = client.get(reverse("accounts:user_list"))
    assert response.status_code == 302 and reverse("accounts:login") in response["Location"]


@pytest.mark.parametrize(
    "url_name,allowed",
    [
        ("accounts:user_list", {ADMIN}),
        ("audit:list", {ADMIN}),
        ("integrations:status", {ADMIN}),
        ("alerts:list", {ADMIN, DEPOSITO, VENTAS, "Vendedor"}),
        ("core:home", {ADMIN, DEPOSITO, VENTAS, "Vendedor"}),
    ],
)
def test_each_role_sees_only_what_it_should(client, users_by_role, url_name, allowed):
    for role, user in users_by_role.items():
        client.force_login(user)
        status = client.get(reverse(url_name)).status_code
        assert status == (200 if role in allowed else 403), f"{role} en {url_name}: {status}"


# ── Pantallas de usuarios ────────────────────────────────────────────────


def test_admin_creates_user_sends_email_and_audits(admin_client, roles, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("accounts:user_create"),
            {"full_name": "Sergio Depósito", "email": "Sergio@Deutsch.test", "role": roles[DEPOSITO].pk},
        )
    assert response.status_code == 302
    user = User.objects.get(email="sergio@deutsch.test")
    assert user.groups.get().name == DEPOSITO
    assert not user.has_usable_password()
    assert len(mail.outbox) == 1 and "/cuenta/recuperar/" in mail.outbox[0].body
    log = AuditLog.objects.get(action="user.created")
    assert log.after["role"] == DEPOSITO and log.actor.email == "admin@test.local"


def test_admin_edits_permissions_and_audits_before_after(admin_client, make_user, roles):
    user = make_user("ventas2@test.local", VENTAS)
    extra = perm("integrations.view_status")
    response = admin_client.post(
        reverse("accounts:user_edit", args=[user.pk]),
        {
            "full_name": user.full_name,
            "email": user.email,
            "role": roles[VENTAS].pk,
            "extra_permissions": [extra.pk],
        },
    )
    assert response.status_code == 302
    assert User.objects.get(pk=user.pk).has_perm("integrations.view_status")
    log = AuditLog.objects.get(action="user.updated")
    assert log.before["extra_permissions"] == [] and log.after["extra_permissions"] == [
        "integrations.view_status"
    ]


def test_cannot_add_and_deny_same_permission(admin_client, make_user, roles):
    user = make_user("x@test.local", VENTAS)
    p = perm("alerts.view_alert")
    response = admin_client.post(
        reverse("accounts:user_edit", args=[user.pk]),
        {
            "full_name": "X",
            "email": user.email,
            "role": roles[VENTAS].pk,
            "extra_permissions": [p.pk],
            "denied_permissions": [p.pk],
        },
    )
    assert response.status_code == 200 and "a la vez" in response.content.decode()


def test_deactivate_and_reactivate(admin_client, make_user):
    user = make_user("baja@test.local", VENTAS)
    admin_client.post(reverse("accounts:user_toggle_active", args=[user.pk]))
    user.refresh_from_db()
    assert not user.is_active
    admin_client.post(reverse("accounts:user_toggle_active", args=[user.pk]))
    user.refresh_from_db()
    assert user.is_active
    assert list(AuditLog.objects.order_by("id").values_list("action", flat=True)) == [
        "user.deactivated",
        "user.reactivated",
    ]


def test_admin_cannot_deactivate_self(admin_client, admin_user):
    admin_client.post(reverse("accounts:user_toggle_active", args=[admin_user.pk]))
    admin_user.refresh_from_db()
    assert admin_user.is_active


def test_every_role_permission_has_spanish_label():
    from apps.accounts.roles import PERMISSION_LABELS, ROLE_PERMISSIONS

    used = {p for perms in ROLE_PERMISSIONS.values() for p in perms}
    assert used <= set(PERMISSION_LABELS), f"Faltan etiquetas: {used - set(PERMISSION_LABELS)}"
