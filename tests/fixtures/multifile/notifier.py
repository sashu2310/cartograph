"""Fixture: notifier — logging and alerting."""


def log_event(message):
    """Log an event."""
    print(f"[LOG] {message}")


def send_alert(message):
    """Send an alert notification."""
    log_event(f"[ALERT] {message}")
    dispatch_webhook(message)


def dispatch_webhook(message):
    """Dispatch a webhook notification."""
    pass
