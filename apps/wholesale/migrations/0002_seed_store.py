"""Fila inicial de la configuración de la tienda y textos propuestos de los emails (Deutsch los revisa
y los edita desde el panel)."""

from django.db import migrations

TEMPLATES = [
    (
        "registration_received",
        "Registro recibido",
        "Recibimos tu registro en la tienda mayorista de Deutsch",
        "Hola, {cliente}:\n\n"
        "Gracias por registrarte en la tienda mayorista de Deutsch. Vamos a revisar tus datos y te "
        "avisamos por este medio cuando aprobemos tu cuenta.\n\n"
        "Si tenés alguna duda, respondé este email.",
    ),
    (
        "registration_approved",
        "Registro aprobado",
        "¡Tu cuenta mayorista de Deutsch ya está activa!",
        "Hola, {cliente}:\n\n"
        "Aprobamos tu cuenta. Ya podés ingresar a la tienda mayorista con tu email y tu contraseña, ver "
        "los precios mayoristas y hacer tu pedido.\n\n"
        "Ingresá acá: {enlace}",
    ),
    (
        "registration_rejected",
        "Registro rechazado",
        "Sobre tu registro en la tienda mayorista de Deutsch",
        "Hola, {cliente}:\n\n"
        "Revisamos tu registro y por ahora no lo pudimos aprobar.\n\n"
        "Motivo: {motivo}\n\n"
        "Si creés que es un error o querés darnos más datos, respondé este email.",
    ),
    (
        "order_received",
        "Pedido recibido",
        "Recibimos tu pedido {pedido}",
        "Hola, {cliente}:\n\n"
        "Recibimos tu pedido {pedido} por {total}.\n\n"
        "{proximos_pasos}\n\n"
        "Podés ver el detalle cuando quieras desde tu cuenta: {enlace}",
    ),
    (
        "payment_confirmed",
        "Pago confirmado",
        "Confirmamos el pago de tu pedido {pedido}",
        "Hola, {cliente}:\n\n"
        "Confirmamos el pago de tu pedido {pedido}. Ya lo estamos preparando y te avisamos cuando salga.",
    ),
    (
        "payment_reminder",
        "Recordatorio de pago",
        "Tu pedido {pedido} vence mañana",
        "Hola, {cliente}:\n\n"
        "Todavía no recibimos el comprobante de la transferencia de tu pedido {pedido} por {total}. "
        "Si no lo recibimos antes del {vence}, el pedido se cancela y liberamos la mercadería.\n\n"
        "Subí el comprobante desde tu cuenta: {enlace}\n\n"
        "Datos para transferir:\n{datos_bancarios}",
    ),
    (
        "order_expired",
        "Pedido vencido",
        "Cancelamos tu pedido {pedido} por falta de pago",
        "Hola, {cliente}:\n\n"
        "Como no recibimos el pago, cancelamos tu pedido {pedido} y liberamos la mercadería.\n\n"
        "Si todavía lo querés, podés repetirlo desde tu cuenta en un par de clics: {enlace}",
    ),
    (
        "shortage_query",
        "Consulta por faltante",
        "Te falta algo en el pedido {pedido}: necesitamos tu respuesta",
        "Hola, {cliente}:\n\n"
        "Mientras preparábamos tu pedido {pedido} nos dimos cuenta de que nos falta:\n\n"
        "{detalle}\n\n"
        "Respondé este email o escribinos para decirnos si querés quitarlo, pedir menos unidades o "
        "cambiarlo por otro talle o color. Apenas nos contestes seguimos con el pedido.",
    ),
    (
        "dispatched",
        "Pedido despachado",
        "Tu pedido {pedido} ya salió",
        "Hola, {cliente}:\n\n"
        "Despachamos tu pedido {pedido} por {transporte}.\n\n"
        "Seguimiento: {seguimiento}\n\n"
        "La factura te llega por email desde Contabilium.",
    ),
    (
        "ready_for_pickup",
        "Listo para retirar",
        "Tu pedido {pedido} está listo para retirar",
        "Hola, {cliente}:\n\n"
        "Tu pedido {pedido} ya está listo. Podés pasar a retirarlo por el local en el horario de atención.\n\n"
        "{cobro}",
    ),
]


def seed(apps, schema_editor):
    StoreSettings = apps.get_model("wholesale", "StoreSettings")
    EmailTemplate = apps.get_model("wholesale", "EmailTemplate")
    StoreSettings.objects.get_or_create(pk=1)
    for code, name, subject, body in TEMPLATES:
        EmailTemplate.objects.get_or_create(code=code, defaults={"name": name, "subject": subject, "body": body})


class Migration(migrations.Migration):
    dependencies = [("wholesale", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
