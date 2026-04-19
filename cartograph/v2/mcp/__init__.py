"""MCP server — agent-native access to the cartograph pipeline."""

from cartograph.v2.mcp.server import build_server, serve

__all__ = ["build_server", "serve"]
