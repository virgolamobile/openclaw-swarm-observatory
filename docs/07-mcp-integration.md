# MCP Integration

## Overview

This repository includes a native MCP server that exposes OpenClaw Agent Dashboard APIs as MCP tools.

File: `mcp_server.py`

## Available MCP tools

- `dashboard_ready`
- `dashboard_capabilities`
- `dashboard_insights`
- `agent_drilldown`
- `agent_node_details`
- `dashboard_docs_index`
- `dashboard_doc_content`

## Prerequisites

- Dashboard backend running (default: `http://127.0.0.1:5050`)
- Python dependencies installed from `requirements.txt`

## Local run

```bash
python mcp_server.py
```

Environment variables:

- `OPENCLAW_DASHBOARD_BASE_URL` (default `http://127.0.0.1:5050`)
- `OPENCLAW_MCP_TIMEOUT_SEC` (default `10`)

## VS Code MCP config

A ready-to-use config is included in `.vscode/mcp.json`:

- server name: `openclaw-observatory`
- transport: `stdio`
- command: `python mcp_server.py`

You can adapt `OPENCLAW_DASHBOARD_BASE_URL` if the dashboard runs on another host/port.

## Operational notes

- Tools return a consistent envelope: `ok`, `base_url`, and either `data` or error fields.
- If dashboard is offline, tools return `ok: false` with connection details.
- `dashboard_insights` can trim payload with:
  - `include_agents`
  - `include_interactions`
