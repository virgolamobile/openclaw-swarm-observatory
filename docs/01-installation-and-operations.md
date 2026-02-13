# Installation and Operations Guide

## 1. Prerequisites

- Python 3.10+
- OpenClaw runtime installed and available in `PATH`
- Access to OpenClaw data directories under `~/.openclaw`

Note: frontend assets are served locally from `static/vendor/` (no external CDN required at runtime).

## 2. Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Start commands

### Development

```bash
python app.py
```

### Production-like

```bash
gunicorn --preload -k eventlet -w 1 -b 0.0.0.0:5050 app:app
```

## 4. Runtime modes

### `auto` (default)
- Uses OpenClaw core polling
- Uses bus/session channels when available
- Best balance between fidelity and resilience

### `core-only-passive`
- Uses OpenClaw core CLI channels only
- Strictly passive and portable
- Best for compliance-sensitive installs

### `legacy`
- Keeps bus/session-first behavior

## 5. Operational environment variables

- `AGENT_DASHBOARD_MODE`
- `AGENT_DASHBOARD_CORE_POLL_SEC`
- `AGENT_DASHBOARD_DISABLE_INTERNAL_READER`

## 6. Readiness and health checks

Use:

- `GET /ready`
- `GET /capabilities`

Example:

```bash
curl -s http://127.0.0.1:5050/ready
curl -s http://127.0.0.1:5050/capabilities
```

## 7. Common issues

- `ready=false` immediately after startup: expected during warm-up.
- Missing cron data: verify `openclaw cron list --json` works.
- Empty drilldown: ensure agent has recent activity or available context files.

## 8. Security notes

- Do not expose dashboard publicly without reverse proxy auth.
- Do not commit runtime secrets (`credentials/`, tokens, private logs).
- Review OpenClaw workspace access before multi-user deployment.

## 9. MCP operations

The project ships with a native MCP server (`mcp_server.py`) that maps dashboard APIs to MCP tools.

Run MCP server:

```bash
python mcp_server.py
```

Main variables:

- `OPENCLAW_DASHBOARD_BASE_URL` (target dashboard URL)
- `OPENCLAW_MCP_TIMEOUT_SEC` (HTTP timeout)

VS Code client configuration example is available in `.vscode/mcp.json`.
For full details, see `docs/07-mcp-integration.md`.
