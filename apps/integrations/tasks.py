from procrastinate.contrib.django import app

from . import registry, services


@app.task(queue="integrations")
def process_event(event_id: int):
    services.process(event_id)


@app.task(queue="integrations", queueing_lock="reconcile_channel")
def reconcile_channel(channel_code: str):
    services.run_reconciliation(channel_code)


@app.periodic(cron="*/15 * * * *")
@app.task(queue="integrations", queueing_lock="reconcile_all")
def reconcile_all(timestamp: int):
    """Cada 15 minutos concilia todos los canales con adaptador registrado."""
    for adapter in registry.all_adapters():
        if getattr(adapter, "own_schedule", False):
            continue  # el canal tiene sus propias tareas periódicas
        reconcile_channel.configure(queueing_lock=f"reconcile:{adapter.code}").defer(
            channel_code=adapter.code
        )


@app.periodic(cron="*/5 * * * *")
@app.task(queue="integrations", queueing_lock="requeue_stuck_events")
def requeue_stuck_events(timestamp: int):
    """Red de seguridad: reencola eventos trabados en procesando/pendiente hace más de 15 min."""
    services.requeue_stuck()
