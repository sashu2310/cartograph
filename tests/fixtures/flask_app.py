"""Fixture: Flask application patterns."""

from flask import Blueprint, Flask

app = Flask(__name__)
bp = Blueprint("users", __name__, url_prefix="/api/users")


# ── App-level routes (classic @app.route) ─────────────────


@app.route("/")
def index():
    """Home page."""
    return render_home()


@app.route("/health")
def healthcheck():
    """Health check endpoint."""
    return {"status": "ok"}


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page — handles both GET (form) and POST (submit)."""
    return handle_login()


# ── App-level routes (Flask 2.0+ shorthand) ───────────────


@app.get("/items")
def list_items():
    """List all items."""
    return get_all_items()


@app.post("/items")
def create_item(payload):
    """Create a new item."""
    return save_item(payload)


@app.delete("/items/<int:item_id>")
def delete_item(item_id):
    """Delete an item."""
    remove_item(item_id)


# ── Blueprint routes ──────────────────────────────────────


@bp.route("/")
def list_users():
    """List users in this blueprint."""
    return get_all_users()


@bp.get("/<int:user_id>")
def get_user(user_id):
    """Get a single user."""
    return find_user(user_id)


@bp.post("/")
def create_user(payload):
    """Create a user."""
    return save_user(payload)


@bp.put("/<int:user_id>")
def update_user(user_id, payload):
    """Update a user."""
    return modify_user(user_id, payload)


# ── Error handlers ────────────────────────────────────────


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return {"error": "not found"}


@app.errorhandler(500)
def server_error(error):
    """Handle 500 errors."""
    return {"error": "internal server error"}


# ── Helper functions ──────────────────────────────────────


def render_home():
    return "<h1>Home</h1>"


def handle_login():
    return {}


def get_all_items():
    return []


def save_item(payload):
    return {}


def remove_item(item_id):
    pass


def get_all_users():
    return []


def find_user(user_id):
    return {}


def save_user(payload):
    return {}


def modify_user(user_id, payload):
    return {}
