import logging

from django.core.mail import send_mail
from django.utils import timezone
from procrastinate.contrib.django import app

from .models import AlertReceipt

logger = logging.getLogger(__name__)

MAX_EMAIL_ATTEMPTS = 5
BACKOFF_SECONDS = [60, 300, 1500, 7200]  # 1 min, 5 min, 25 min, 2 h


@app.task(queue="email")
def send_alert_email(receipt_id: int):
    """Envía el email de una alerta. Si falla, reintenta con espera creciente; la alerta
    sigue visible en el panel aunque el email no salga."""
    receipt = AlertReceipt.objects.select_related("alert", "user").filter(pk=receipt_id).first()
    if receipt is None or receipt.emailed_at:
        return
    alert = receipt.alert
    body = alert.body
    if alert.link_url:
        body += f"\n\nVer en el sistema: {alert.link_url}"
    receipt.email_attempts += 1
    try:
        send_mail(
            subject=f"[Sistema Deutsch] {alert.title}",
            message=body,
            from_email=None,
            recipient_list=[receipt.user.email],
        )
    except Exception as exc:  # noqa: BLE001
        receipt.email_error = str(exc)[:1000]
        receipt.save(update_fields=["email_attempts", "email_error"])
        logger.warning("Falló email de alerta %s (intento %s)", alert.pk, receipt.email_attempts)
        if receipt.email_attempts < MAX_EMAIL_ATTEMPTS:
            wait = BACKOFF_SECONDS[min(receipt.email_attempts - 1, len(BACKOFF_SECONDS) - 1)]
            send_alert_email.configure(schedule_in={"seconds": wait}).defer(receipt_id=receipt_id)
        return
    receipt.emailed_at = timezone.now()
    receipt.email_error = ""
    receipt.save(update_fields=["email_attempts", "email_error", "emailed_at"])
