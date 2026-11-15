"""Emails a clientes: plantillas editables y cola de envío (US-6).

`enqueue` arma el email con el texto de la `EmailTemplate`, dentro del layout HTML de marca, y lo deja
en `OutboundEmail` como "pendiente de envío". La tarea `send_pending_emails` los manda cuando hay
correo saliente configurado (`STORE_EMAILS_ENABLED`); mientras tanto quedan en la cola, visibles en el
panel.

M8a (T2): al enviar, un email con más de `STORE_EMAIL_MAX_AGE_HOURS` (72 h) en la cola ya no sirve ("tu
pago vence mañana" de hace semanas): queda "Vencido, no enviado". La aprobación o el rechazo del registro
no vencen nunca (siguen siendo útiles).
"""

import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape, linebreaks

from apps.alerts import services as alerts

from .models import EmailTemplate, OutboundEmail

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
NEVER_EXPIRE = ("registration_approved", "registration_rejected")
EXPIRED_NOTE = "No se mandó: quedó más de {hours} h en la cola y el aviso ya no sirve."
VARIABLE = re.compile(r"\{(\w+)\}")
# Variables que se pueden usar en los textos (se muestran como ayuda en el panel).
VARIABLES = {
    "cliente": "Nombre del cliente",
    "pedido": "Número de pedido",
    "total": "Total del pedido",
    "enlace": "Enlace a la tienda o al pedido",
    "motivo": "Motivo (rechazo)",
    "proximos_pasos": "Próximos pasos según el medio de pago",
    "datos_bancarios": "Datos para transferir",
    "vence": "Fecha de vencimiento del pago",
    "detalle": "Detalle de lo que falta",
    "transporte": "Transporte",
    "seguimiento": "Código de seguimiento",
    "cobro": "Cobro en el local (efectivo)",
}


def render_text(template: str, context: dict) -> str:
    """Reemplaza {variable} por su valor. Solo nombres simples: nada de atributos ni índices.

    Una variable desconocida queda tal cual (así un error de tipeo en el panel no rompe el envío).
    """
    return VARIABLE.sub(lambda m: str(context.get(m.group(1), m.group(0))), template or "")


def render(code: str, context: dict) -> tuple[str, str, str]:
    """Devuelve (asunto, texto, html) de una plantilla."""
    template = EmailTemplate.objects.get(code=code)
    subject = " ".join(render_text(template.subject, context).split())[:200]
    text = render_text(template.body, context)
    html = render_to_string(
        "store/email/layout.html",
        {"subject": subject, "body_html": linebreaks(escape(text), autoescape=False)},
    )
    footer = "\n\n--\nDeutsch · Pasión por la natación"
    return subject, text + footer, html


def enqueue(code: str, to: str, context: dict | None = None) -> OutboundEmail | None:
    """Encola un email. Si falta la plantilla o el destinatario, lo registra en el log y no falla."""
    if not to:
        return None
    try:
        subject, text, html = render(code, context or {})
    except EmailTemplate.DoesNotExist:
        logger.error("Plantilla de email inexistente: %s", code)
        return None
    email = OutboundEmail.objects.create(
        to=to, template_code=code, subject=subject, body_text=text, body_html=html
    )
    if settings.STORE_EMAILS_ENABLED:
        from .tasks import send_email

        email_id = email.pk
        transaction.on_commit(lambda: send_email.defer(email_id=email_id))
    return email


def max_age() -> timedelta:
    return timedelta(hours=settings.STORE_EMAIL_MAX_AGE_HOURS)


def is_stale(email: OutboundEmail, now=None) -> bool:
    """Viejo para mandarlo: más de `STORE_EMAIL_MAX_AGE_HOURS` en la cola (salvo los que no vencen)."""
    if email.template_code in NEVER_EXPIRE:
        return False
    return email.created_at <= (now or timezone.now()) - max_age()


def expire_stale(now=None) -> int:
    """Marca "Vencido, no enviado" todos los pendientes viejos (una sola consulta)."""
    now = now or timezone.now()
    return (
        OutboundEmail.objects.filter(status=OutboundEmail.Status.PENDING, created_at__lte=now - max_age())
        .exclude(template_code__in=NEVER_EXPIRE)
        .update(
            status=OutboundEmail.Status.EXPIRED,
            last_error=EXPIRED_NOTE.format(hours=settings.STORE_EMAIL_MAX_AGE_HOURS),
            updated_at=now,
        )
    )


def send(email: OutboundEmail) -> bool:
    """Intenta mandar un email de la cola. Devuelve True si salió."""
    if email.status != OutboundEmail.Status.PENDING:
        return email.status == OutboundEmail.Status.SENT
    if is_stale(email):
        email.status = OutboundEmail.Status.EXPIRED
        email.last_error = EXPIRED_NOTE.format(hours=settings.STORE_EMAIL_MAX_AGE_HOURS)
        email.save(update_fields=["status", "last_error", "updated_at"])
        logger.info("Email %s a %s vencido en la cola: no se manda", email.pk, email.to)
        return False
    email.attempts += 1
    try:
        message = EmailMultiAlternatives(
            subject=email.subject, body=email.body_text, from_email=None, to=[email.to]
        )
        message.attach_alternative(email.body_html, "text/html")
        message.send()
    except Exception as exc:  # noqa: BLE001 - cualquier error del servidor de correo
        email.last_error = str(exc)[:500]
        if email.attempts >= MAX_ATTEMPTS:
            email.status = OutboundEmail.Status.FAILED
        email.save(update_fields=["attempts", "last_error", "status", "updated_at"])
        logger.warning("Falló el email %s a %s (intento %s)", email.pk, email.to, email.attempts)
        if email.status == OutboundEmail.Status.FAILED:
            alerts.emit(
                "wholesale.email_failed",
                title=f"No pudimos mandar «{email.subject}» a {email.to}",
                body=f"Último error: {email.last_error}",
                link_url="/tienda-mayorista/emails/?estado=failed",
                dedupe_key=f"email:{email.pk}",
            )
        return False
    email.status = OutboundEmail.Status.SENT
    email.sent_at = timezone.now()
    email.last_error = ""
    email.save(update_fields=["attempts", "last_error", "status", "sent_at", "updated_at"])
    return True


def send_pending(limit: int = 100) -> int:
    """Manda los pendientes (los más viejos primero). No hace nada si no hay correo saliente."""
    if not settings.STORE_EMAILS_ENABLED:
        return 0
    expire_stale()  # primero se descartan los viejos, así no ocupan el lote
    sent = 0
    ids = list(
        OutboundEmail.objects.filter(status=OutboundEmail.Status.PENDING)
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    for pk in ids:
        with transaction.atomic():
            email = OutboundEmail.objects.select_for_update(skip_locked=True).filter(pk=pk).first()
            if email is not None and send(email):
                sent += 1
    return sent


def pending_count() -> int:
    return OutboundEmail.objects.filter(status=OutboundEmail.Status.PENDING).count()


def expired_count() -> int:
    return OutboundEmail.objects.filter(status=OutboundEmail.Status.EXPIRED).count()
