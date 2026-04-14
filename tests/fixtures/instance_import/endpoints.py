"""Fixture: Endpoints importing a service instance — mirrors Polar's pattern."""

from .service import user_service


def get_user_endpoint(user_id):
    """Get a user by ID."""
    return user_service.get_user(user_id)


def create_user_endpoint(data):
    """Create a new user."""
    return user_service.create_user(data)


def delete_user_endpoint(user_id):
    """Delete a user."""
    user_service.delete_user(user_id)
