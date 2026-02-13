# OpenClaw Agent Dashboard

A real-time observability dashboard for OpenClaw multi-agent systems.

This project provides:
- Live swarm monitoring (agent state, interactions, cron activity)
- Progressive drilldown from overview to root-cause evidence
- Causal graph analysis (constraints → decisions → actions → outcomes)
- Deep node inspection with file-level provenance

## Why this project exists

Complex agent swarms are hard to debug. This dashboard turns distributed activity into a readable, inspectable, and explainable control surface.

You can move from:
1. **What is happening?**
2. **What happened before?**
3. **Why was a decision taken?**
4. **Which workspace documents influenced behavior?**

## Key features

- **Real-time updates** via Flask-SocketIO
- **OpenClaw-compliant passive mode** (no behavior changes required in agents)
- **Cron timeline** with next runs, outcomes, durations, and summaries
- **Causal graph** with map-like pan/zoom interaction
- **Node deep-dive** (`/drilldown/<agent>/node/<nodeId>`)
- **Dynamic markdown discovery** for context roots (not hardcoded to fixed file names)

## Architecture at a glance

- `app.py` — backend API + websocket + telemetry fusion + drilldown engine
- `templates/index.html` — dashboard UI, graph renderer, interaction logic
- `reader.py` — optional standalone bus reader utility
- `tests/test_app_logic.py` — backend unit tests

## Frontend dependencies (vendored)

The dashboard serves frontend libraries from local files under `static/vendor/`.

Vendored libraries:
- Socket.IO client
- marked
- DOMPurify
- highlight.js (JS + CSS theme)

This removes runtime dependency on public CDNs for normal operation.

## Quick start

### 1) Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Run locally

```bash
python app.py
```

Dashboard URL:

- `http://127.0.0.1:5050`

### 4) Production-style run (Gunicorn)

```bash
gunicorn --preload -k eventlet -w 1 -b 0.0.0.0:5050 app:app
```

## Environment variables

- `AGENT_DASHBOARD_MODE`
  - `auto` (default)
  - `core-only-passive`
  - `legacy`
- `AGENT_DASHBOARD_CORE_POLL_SEC` (default `5`)
- `AGENT_DASHBOARD_DISABLE_INTERNAL_READER=1` (optional)

## API reference (summary)

- `GET /ready`
  - Service readiness for frontend bootstrap
- `GET /capabilities`
  - Available telemetry channels and mode
- `GET /insights`
  - Aggregated global dashboard payload
- `GET /drilldown/<agent>`
  - Full layered drilldown for one agent
- `GET /drilldown/<agent>/node/<nodeId>`
  - Extra deep node-level analysis payload
- `GET /docs/index`
  - Documentation manifest used by in-app docs modal
- `GET /docs/content/<docName>`
  - Markdown content for one whitelisted docs file

## Testing

Run all unit tests:

```bash
./venv/bin/python -m pytest -q
```

## Mini changelog

### 2026-02-12

- Reached 100% unit-test coverage on `app.py` (`27 passed`).
- Added contribution governance files (`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`).
- Completed in-app documentation UX: header docs index, contextual help icons, docs modal.
- Extended drilldown explainability: causal graph, node-level deep dive, dynamic context-root discovery.

## Screens and usage flow

1. Select an agent in **Swarm Overview**
2. Navigate tabs:
   - **Why decisions**
   - **SOUL/file derivation**
   - **Causal Graph**
   - **Cron timeline**
   - **Full timeline**
3. In **Causal Graph**:
   - Drag = pan
   - Mouse wheel = zoom
   - Double-click = reset viewport
   - Click node = deeper node-level details

## Compliance and portability

This project is designed to be OpenClaw compliant:
- Passive read-only integration with core OpenClaw telemetry
- Graceful degradation on partially available channels
- Dynamic workspace markdown discovery for context provenance

## Documentation

See `docs/` for deep technical documentation:
- `docs/01-installation-and-operations.md`
- `docs/02-architecture-deep-dive.md`
- `docs/03-ui-ux-guide.md`
- `docs/04-api-and-data-model.md`
- `docs/05-licensing-and-release-guidelines.md`

The dashboard also exposes docs directly in-app:
- Header button: **Docs index**
- Contextual `?` help icons on key panels
- Modal navigation with deep links to each markdown file

## Community standards

- Contribution process: `CONTRIBUTING.md`
- Community behavior policy: `CODE_OF_CONDUCT.md`

## License

This repository is licensed under **PolyForm Noncommercial 1.0.0**.

- Commercial use is not permitted without separate permission.
- See `LICENSE` for full legal terms.

Third-party vendored assets are covered by their own upstream licenses.
See `THIRD_PARTY_NOTICES.md` and `static/vendor/licenses/` for details.

For commercial licensing, contact the project owner directly.
