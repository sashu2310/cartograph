"""Shared HTTP pattern utilities — cross-language helpers for REST/API detection."""

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def normalize_url_pattern(url: str) -> str:
    """Normalize a URL pattern for consistent matching across frameworks."""
    url = url.strip("/")
    if not url.startswith("/"):
        url = f"/{url}"
    return url
