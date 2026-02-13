"""MCP server for OpenClaw Agent Dashboard.

Exposes dashboard REST endpoints as MCP tools so AI clients can inspect
status, insights, drilldowns, and docs using a standard MCP interface.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("OPENCLAW_DASHBOARD_BASE_URL", "http://127.0.0.1:5050").rstrip("/")
REQUEST_TIMEOUT_SEC = float(os.environ.get("OPENCLAW_MCP_TIMEOUT_SEC", "10"))

mcp = FastMCP("openclaw-observatory")


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    query = urlencode(params or {}, doseq=True)
    return f"{BASE_URL}{path}{'?' + query if query else ''}"


def _http_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = _build_url(path, params)
    request = Request(url=url, method="GET")

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SEC) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset)
            return {
                "ok": True,
                "base_url": BASE_URL,
                "status_code": int(response.status),
                "data": json.loads(body) if body else {},
            }
    except HTTPError as exc:
        details = ""
        try:
            details = exc.read().decode("utf-8", errors="replace")
        except Exception:
            details = ""
        return {
            "ok": False,
            "base_url": BASE_URL,
            "status_code": int(exc.code),
            "error": f"HTTP error {exc.code}",
            "details": details,
        }
    except URLError as exc:
        return {
            "ok": False,
            "base_url": BASE_URL,
            "error": "Connection error",
            "details": str(exc.reason),
        }
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "base_url": BASE_URL,
            "error": "Invalid JSON response",
            "details": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "base_url": BASE_URL,
            "error": "Unexpected error",
            "details": str(exc),
        }


@mcp.tool()
def dashboard_ready() -> dict[str, Any]:
    """Return dashboard readiness from /ready."""
    return _http_get("/ready")


@mcp.tool()
def dashboard_capabilities() -> dict[str, Any]:
    """Return runtime capabilities and tracked agent count from /capabilities."""
    return _http_get("/capabilities")


@mcp.tool()
def dashboard_insights(include_agents: bool = True, include_interactions: bool = False) -> dict[str, Any]:
    """Return aggregated telemetry from /insights with optional payload trimming."""
    payload = _http_get("/insights")
    if not payload.get("ok"):
        return payload

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not include_agents:
        data.pop("agents", None)
    if not include_interactions:
        data.pop("interactions", None)

    payload["data"] = data
    return payload


@mcp.tool()
def agent_drilldown(agent_name: str) -> dict[str, Any]:
    """Return full drilldown for one agent using /drilldown/<agent>."""
    safe_agent = quote(agent_name, safe="")
    return _http_get(f"/drilldown/{safe_agent}")


@mcp.tool()
def agent_node_details(agent_name: str, node_id: str) -> dict[str, Any]:
    """Return deep details for one node using /drilldown/<agent>/node/<nodeId>."""
    safe_agent = quote(agent_name, safe="")
    safe_node = quote(node_id, safe="")
    return _http_get(f"/drilldown/{safe_agent}/node/{safe_node}")


@mcp.tool()
def dashboard_docs_index() -> dict[str, Any]:
    """Return docs manifest from /docs/index."""
    return _http_get("/docs/index")


@mcp.tool()
def dashboard_doc_content(doc_name: str) -> dict[str, Any]:
    """Return one docs file body from /docs/content/<docName>."""
    safe_doc = quote(doc_name, safe="")
    return _http_get(f"/docs/content/{safe_doc}")


if __name__ == "__main__":
    mcp.run()
