# API and Data Model Reference

## 1. REST endpoints

### `GET /ready`

Returns:

```json
{"ready": true}
```

### `GET /capabilities`

Returns runtime mode, tracked agents, and channel capability matrix.

### `GET /insights`

Returns global dashboard data:
- `agents`
- `interactions.user_agent`
- `interactions.agent_agent`
- `cron.summary`
- `cron.by_agent`

### `GET /drilldown/<agent>`

Returns deep data package:
- `overview`
- `timeline`
- `decision_trace`
- `cron`
- `cron_timeline`
- `context_roots`
- `causal_graph`

### `GET /drilldown/<agent>/node/<nodeId>`

Returns:
- selected node metadata
- inbound/outbound edges
- related nodes
- optional linked file details

## 2. WebSocket events

### Incoming
- `init_request`

### Outgoing
- `init`
- `update`
- `init_pending`

## 3. Core internal schema (agent snapshot)

- `agent`
- `status`
- `task`
- `last_seen`
- `cron_jobs`
- `active_missions`
- `recent_messages`
- `recent_thoughts`
- `current_thought`
- `cron_details`
- `interrupted_tasks`
- `message_history`
- `thought_history`

## 4. Decision trace record

- `ts`
- `agent`
- `decision`
- `why[]`
- `evidence[]`
- `confidence`
- `source`
- `type`
- `root_causes[]`

## 5. Causal graph model

Node fields:
- `id`
- `label`
- `group`
- `meta`

Edge fields:
- `source`
- `target`
- `label`

## 6. Error behavior

- Missing agent: `404 agent_not_found`
- Missing graph node: `404 node_not_found`
- Partial channels: successful response with partial payload

## 7. MCP mapping

The MCP server (`mcp_server.py`) exposes the following tool-to-endpoint bindings:

- `dashboard_ready` -> `GET /ready`
- `dashboard_capabilities` -> `GET /capabilities`
- `dashboard_insights` -> `GET /insights`
- `agent_drilldown` -> `GET /drilldown/<agent>`
- `agent_node_details` -> `GET /drilldown/<agent>/node/<nodeId>`
- `dashboard_docs_index` -> `GET /docs/index`
- `dashboard_doc_content` -> `GET /docs/content/<docName>`

All MCP responses use a stable envelope with `ok`, `base_url`, and either `data` or error fields.
