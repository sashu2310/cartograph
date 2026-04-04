"""Fixture: Multi-level call chains for call tree testing."""


def entry_point():
    """The top-level entry point."""
    result = step_one()
    if result:
        step_two(result)
    else:
        handle_failure()


def step_one():
    data = fetch_from_db()
    return validate(data)


def step_two(data):
    transformed = transform(data)
    store(transformed)
    notify(transformed)


def fetch_from_db():
    return {"key": "value"}


def validate(data):
    if not data:
        return None
    return data


def transform(data):
    return {k: v.upper() for k, v in data.items()}


def store(data):
    pass


def notify(data):
    send_email(data)
    send_slack(data)


def send_email(data):
    pass


def send_slack(data):
    pass


def handle_failure():
    log_error()
    alert_team()


def log_error():
    pass


def alert_team():
    pass
