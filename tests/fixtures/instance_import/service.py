"""Fixture: Service layer with module-level instance — mirrors Polar's pattern."""


class UserService:
    def get_user(self, user_id):
        return find_user(user_id)

    def create_user(self, data):
        validated = validate_data(data)
        return save_user(validated)

    def delete_user(self, user_id):
        remove_user(user_id)


user_service = UserService()


def find_user(user_id):
    return {}


def validate_data(data):
    return data


def save_user(data):
    return {}


def remove_user(user_id):
    pass
