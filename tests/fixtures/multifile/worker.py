"""Fixture: worker — async task definitions that call other modules."""

from .notifier import send_alert
from .processor import transform, validate
from .store import Store

celery_app = type("FakeCelery", (), {"task": lambda **kw: lambda f: f})()
store = Store()


@celery_app.task(queue="default")
def handle_message(message_id):
    """Handle an incoming message — entry point."""
    raw = store.get(message_id)
    if not raw:
        return {"status": "not_found"}

    if not validate(raw):
        send_alert(f"Invalid message: {message_id}")
        return {"status": "invalid"}

    result = transform(raw)
    persist_result.delay(message_id, result)
    return {"status": "ok"}


@celery_app.task(queue="default")
def persist_result(message_id, result):
    """Persist a processed result."""
    store.put(f"result:{message_id}", result)


@celery_app.task(queue="batch")
def handle_batch(message_ids):
    """Process a batch of messages."""
    for mid in message_ids:
        handle_message.delay(mid)
