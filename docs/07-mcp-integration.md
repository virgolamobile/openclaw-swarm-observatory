# MCP Integration

## Overview

This repository includes a native MCP server that exposes OpenClaw Agent Dashboard APIs as MCP tools.

Server file: `mcp_server.py`

## Toolset

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

## VS Code setup

A ready-to-use config is included in `.vscode/mcp.json`:

- server name: `openclaw-observatory`
- transport: `stdio`
- command: `python mcp_server.py`

If needed, update `OPENCLAW_DASHBOARD_BASE_URL` to target a remote dashboard.

## Tool behavior

All tools return a common envelope:

- `ok`
- `base_url`
- `status_code` (when available)
- `data` on success
- `error` and `details` on failure

This design keeps clients resilient even when the dashboard is offline or partially available.

## REST to MCP mapping

- `dashboard_ready` -> `GET /ready`
- `dashboard_capabilities` -> `GET /capabilities`
- `dashboard_insights` -> `GET /insights`
- `agent_drilldown` -> `GET /drilldown/<agent>`
- `agent_node_details` -> `GET /drilldown/<agent>/node/<nodeId>`
- `dashboard_docs_index` -> `GET /docs/index`
- `dashboard_doc_content` -> `GET /docs/content/<docName>`

## Typical flows

### Health check

1. Call `dashboard_ready`
2. If ready, call `dashboard_capabilities`
3. Then call `dashboard_insights`

### Agent investigation

1. Call `dashboard_insights` to identify target agent
2. Call `agent_drilldown(agent_name)`
3. Call `agent_node_details(agent_name, node_id)` for deep node analysis

### Documentation retrieval

1. Call `dashboard_docs_index`
2. Call `dashboard_doc_content(doc_name)` for targeted guidance

## Operational notes

- `dashboard_insights` supports payload trimming:
  - `include_agents`
  - `include_interactions`
- URL path arguments are safely encoded by the server.
- For production environments, keep dashboard behind auth/reverse proxy and expose MCP only on trusted clients.
