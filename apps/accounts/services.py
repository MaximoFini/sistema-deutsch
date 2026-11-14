"""Alta, edición y baja de usuarios. Cada cambio queda auditado."""

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.audit import services as audit

from .models import User, UserPermissionDenial


def snapshot(user: User) -> dict:
    return {
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "role": user.groups.first().name if user.groups.exists() else None,
        "extra_permissions": sorted(
            f"{p.content_type.app_label}.{p.codename}"
            for p in user.user_permissions.select_related("content_type")
        ),
        "denied_permissions": sorted(
            f"{d.permission.content_type.app_label}.{d.permission.codename}"
            for d in user.permission_denials.select_related("permission__content_type")
        ),
    }


def _apply_permissions(user, role, extra, denied):
    user.groups.set([role])
    user.user_permissions.set(extra)
    user.permission_denials.exclude(permission__in=denied).delete()
    for perm in denied:
        UserPermissionDenial.objects.get_or_create(user=user, permission=perm)


@transaction.atomic
def create_user(*, actor, request, full_name, email, role, extra=(), denied=()) -> User:
    user = User.objects.create_user(email=email, full_name=full_name)  # sin contraseña usable
    _apply_permissions(user, role, extra, denied)
    audit.record(actor, "user.created", user, after=snapshot(user), request=request)
    transaction.on_commit(lambda: send_set_password_email(user, request))
    return user


@transaction.atomic
def update_user(*, actor, request, user, full_name, email, role, extra=(), denied=()) -> User:
    before = snapshot(user)
    user.full_name = full_name
    user.email = email
    user.save(update_fields=["full_name", "email"])
    _apply_permissions(user, role, extra, denied)
    audit.record(actor, "user.updated", user, before=before, after=snapshot(user), request=request)
    return user


@transaction.atomic
def set_active(*, actor, request, user, active: bool) -> User:
    if user.is_active == active:
        return user
    before = snapshot(user)
    user.is_active = active
    user.save(update_fields=["is_active"])
    # Las sesiones abiertas se cortan solas: ModelBackend.get_user rechaza usuarios inactivos.
    audit.record(
        actor,
        "user.reactivated" if active else "user.deactivated",
        user,
        before=before,
        after=snapshot(user),
        request=request,
    )
    return user


def send_set_password_email(user: User, request) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    url = request.build_absolute_uri(path) if request else path
    context = {"user": user, "url": url, "hours": settings.PASSWORD_RESET_TIMEOUT // 3600}
    send_mail(
        subject="Tu usuario en el Sistema Deutsch",
        message=render_to_string("accounts/email/welcome.txt", context),
        from_email=None,
        recipient_list=[user.email],
    )
