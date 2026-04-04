"""Fixture: processor — transform and validate logic."""

from .notifier import log_event


def validate(data):
    """Validate message data."""
    if not isinstance(data, dict):
        return False
    return "payload" in data


def transform(data):
    """Transform raw message into processed output."""
    payload = data["payload"]
    result = normalize(payload)
    log_event(f"Transformed message: {len(payload)} bytes")
    return result


def normalize(payload):
    """Normalize payload format."""
    if isinstance(payload, str):
        return payload.strip().lower()
    return str(payload)
