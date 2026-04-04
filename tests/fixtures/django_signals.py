"""Fixture: Django signal patterns."""


def receiver(*args, **kwargs):
    def decorator(fn):
        return fn

    return decorator


post_save = "post_save"
post_delete = "post_delete"
m2m_changed = "m2m_changed"


@receiver(post_save, sender="Equipment")
def on_equipment_save(sender, instance, **kwargs):
    """Handle equipment save."""
    update_cache(instance.id)
    notify_team(instance)


@receiver(post_delete, sender="Equipment")
def on_equipment_delete(sender, instance, **kwargs):
    """Handle equipment deletion."""
    cleanup_references(instance.id)


@receiver(m2m_changed, sender="Dashboard.shared_with")
def on_dashboard_share(sender, instance, **kwargs):
    """Handle dashboard sharing."""
    send_notification(instance)


def update_cache(equipment_id):
    pass


def notify_team(instance):
    pass


def cleanup_references(equipment_id):
    pass


def send_notification(instance):
    pass
