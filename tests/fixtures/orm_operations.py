"""Fixture: Django ORM operation patterns."""


class Sensor:
    class objects:  # noqa: N801
        @staticmethod
        def filter(**kwargs):
            return []

        @staticmethod
        def create(**kwargs):
            return {}

        @staticmethod
        def all():
            return []


class Equipment:
    class objects:  # noqa: N801
        @staticmethod
        def get(id=None):
            return {}

        @staticmethod
        def bulk_create(items):
            return items


def read_sensors(facility_id):
    """Read sensors with various ORM patterns."""
    sensors = Sensor.objects.filter(facility_id=facility_id)
    _ = Sensor.objects.all()
    return sensors


def create_sensor(data):
    """Create a sensor."""
    sensor = Sensor.objects.create(**data)
    sensor.save()
    return sensor


def bulk_import(items):
    """Bulk create sensors."""
    Equipment.objects.bulk_create(items)


def get_equipment(equipment_id):
    """Get single equipment."""
    return Equipment.objects.get(id=equipment_id)


def delete_sensor(sensor):
    """Delete a sensor."""
    sensor.delete()
