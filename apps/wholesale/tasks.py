"""Tareas de la tienda mayorista."""

from django.db import transaction
from procrastinate.contrib.django import app

from . import mail
from .models import OutboundEmail


@app.task(queue="email")
def send_email(email_id: int):
    """Manda un email recién encolado (si falla, lo reintenta la tarea periódica)."""
    with transaction.atomic():
        email = OutboundEmail.objects.select_for_update(skip_locked=True).filter(pk=email_id).first()
        if email is not None:
            mail.send(email)


@app.periodic(cron="*/5 * * * *")
@app.task(queue="email", queueing_lock="store_send_pending_emails")
def send_pending_emails(timestamp: int):
    """Cada 5 minutos: manda los emails pendientes (hasta 5 intentos cada uno; después, alerta)."""
    return mail.send_pending()


@app.periodic(cron="*/15 * * * *")
@app.task(queue="default", queueing_lock="store_payment_deadlines")
def payment_deadlines(timestamp: int):
    """Cada 15 minutos: recordatorio 24 h antes y cancelación de transferencias vencidas sin pago."""
    from . import payments

    reminders = payments.send_reminders()
    result = payments.expire_orders()
    return {"reminders": reminders, **result}
