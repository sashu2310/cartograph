"""Fixture: Django Ninja controller patterns.

Statically parsed only; the ninja import below makes our annotator's
import gate pass. Local stubs below shadow at runtime.
"""

from ninja import Router as _Router  # noqa: F401


def api_controller(path, **kwargs):
    def decorator(cls):
        return cls

    return decorator


class route:  # noqa: N801
    @staticmethod
    def get(path="", **kwargs):
        def decorator(fn):
            return fn

        return decorator

    @staticmethod
    def post(path="", **kwargs):
        def decorator(fn):
            return fn

        return decorator

    @staticmethod
    def patch(path="", **kwargs):
        def decorator(fn):
            return fn

        return decorator

    @staticmethod
    def delete(path="", **kwargs):
        def decorator(fn):
            return fn

        return decorator


@api_controller("/equipments", auth="JWTAuth()", permissions=["READ_EQUIPMENT"])
class EquipmentApiController:
    @route.get("", response="ListSchema")
    def list_equipments(self, filters=None):
        """List all equipments."""
        return get_equipments(filters)

    @route.get("/{equipment_id}", response="DetailSchema")
    def get_equipment(self, equipment_id):
        """Get a single equipment."""
        return find_equipment(equipment_id)

    @route.post("", response="DetailSchema")
    def create_equipment(self, payload):
        """Create a new equipment."""
        equipment = save_equipment(payload)
        return equipment

    @route.delete("/{equipment_id}")
    def delete_equipment(self, equipment_id):
        """Delete an equipment."""
        remove_equipment(equipment_id)


@api_controller("/sensors")
class SensorApiController:
    @route.get("")
    def list_sensors(self):
        return get_all_sensors()


def get_equipments(filters):
    return []


def find_equipment(equipment_id):
    return {}


def save_equipment(payload):
    return {}


def remove_equipment(equipment_id):
    pass


def get_all_sensors():
    return []
