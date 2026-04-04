"""Fixture: Celery task patterns."""

from celery import chain, chord, group, shared_task

celery_app = type("FakeCelery", (), {"task": lambda **kw: lambda f: f})()


@celery_app.task(queue="server")
def process_sensor_data(sensor_ids):
    """Process sensor data for given IDs."""
    results = fetch_data(sensor_ids)
    if not results:
        return {"status": "no_data"}
    trigger_analysis.delay(sensor_ids)
    return {"status": "ok", "count": len(results)}


@celery_app.task(queue="priority")
def trigger_analysis(sensor_ids):
    """Trigger analysis pipeline."""
    workflow = chain(
        validate_data.s(sensor_ids),
        run_diagnostics.s(),
        store_results.s(),
    )
    workflow.apply_async()


@shared_task
def validate_data(sensor_ids):
    return sensor_ids


@celery_app.task
def run_diagnostics(data):
    job = group(analyze_sensor.s(s) for s in data)
    callback = notify_complete.si()
    chord(job, callback).apply_async()


@celery_app.task
def analyze_sensor(sensor_id):
    return {"sensor": sensor_id, "result": "ok"}


@celery_app.task
def store_results(results):
    pass


@celery_app.task
def notify_complete():
    pass


def fetch_data(sensor_ids):
    return sensor_ids
