"""Fixture: FastAPI application patterns."""

from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter(prefix="/api/v1")


# ── App-level routes ──────────────────────────────────────


@app.get("/users")
def list_users():
    """List all users."""
    return get_all_users()


@app.post("/users")
def create_user(payload):
    """Create a new user."""
    user = save_user(payload)
    return user


@app.get("/users/{user_id}")
def get_user(user_id: int):
    """Get a single user."""
    return find_user(user_id)


@app.put("/users/{user_id}")
def update_user(user_id: int, payload):
    """Update a user."""
    return modify_user(user_id, payload)


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    """Delete a user."""
    remove_user(user_id)


# ── Router-level routes ───────────────────────────────────


@router.get("/products")
def list_products():
    """List products."""
    return get_all_products()


@router.post("/products")
def create_product(payload):
    """Create a product."""
    return save_product(payload)


@router.patch("/products/{product_id}")
def patch_product(product_id: int, payload):
    """Partially update a product."""
    return modify_product(product_id, payload)


# ── WebSocket ─────────────────────────────────────────────


@app.websocket("/ws/notifications")
async def notification_stream(websocket):
    """WebSocket for live notifications."""
    pass


# ── Helper functions ──────────────────────────────────────


def get_all_users():
    return []


def save_user(payload):
    return {}


def find_user(user_id):
    return {}


def modify_user(user_id, payload):
    return {}


def remove_user(user_id):
    pass


def get_all_products():
    return []


def save_product(payload):
    return {}


def modify_product(product_id, payload):
    return {}
