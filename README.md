# OpenClaw Agent Dashboard

[![Tests](https://github.com/virgolamobile/openclaw-swarm-observatory/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/virgolamobile/openclaw-swarm-observatory/actions/workflows/tests.yml)

When a multi-agent swarm starts making decisions at speed, logs alone become a detective novel written by four unreliable narrators. I built this dashboard to turn that chaos into something you can actually reason about: what happened, why it happened, what influenced it, and what to inspect next.

![OpenClaw Observatory Dashboard](screenshot.png)

## What this is (and why it exists)

OpenClaw Agent Dashboard is a real-time observability surface for OpenClaw systems. It is designed to stay passive and explain behavior, not alter it: it listens, correlates, and presents evidence from telemetry, timelines, and document provenance.

The goal is simple: move from “something feels off” to “here is the exact causal chain” without spending half your day grepping logs.

## Why it feels useful in practice

You start from a global view, zoom into one agent, then drill into a single node decision with provenance and constraints attached. Instead of bouncing between terminals and markdown files, you follow one coherent thread from signal to explanation. If your swarm behaves like an over-caffeinated jazz quartet, this gives you the score.

## Core capabilities

- Real-time updates via Flask-SocketIO
- Progressive drilldown from overview to root-cause evidence
- Causal graph exploration (constraints → decisions → actions → outcomes)
- Deep node inspection at `/drilldown/<agent>/node/<nodeId>`
- Cron timeline with schedule, outcomes, durations, and summaries
- Dynamic markdown context-root discovery (no brittle hardcoded file names)

## Architecture in one minute

- `app.py`: backend API, websocket events, telemetry fusion, drilldown logic
- `templates/index.html`: UI rendering, interactions, graph behaviors
- `reader.py`: optional standalone bus reader utility
- `tests/test_app_logic.py`: backend unit tests

Frontend dependencies are vendored under `static/vendor/` (Socket.IO client, marked, DOMPurify, highlight.js), so normal operation does not depend on public CDNs.

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Dashboard: `http://127.0.0.1:5050`

Production-style run:

```bash
gunicorn --preload -k eventlet -w 1 -b 0.0.0.0:5050 app:app
```

## API snapshot

- `GET /ready` – readiness for frontend bootstrap
- `GET /capabilities` – available telemetry channels and current mode
- `GET /insights` – aggregated dashboard payload
- `GET /drilldown/<agent>` – layered drilldown for one agent
- `GET /drilldown/<agent>/node/<nodeId>` – node-level deep analysis
- `GET /docs/index` – documentation manifest for in-app docs
- `GET /docs/content/<docName>` – markdown body for one whitelisted file

## Runtime configuration

- `AGENT_DASHBOARD_MODE`: `auto` (default), `core-only-passive`, `legacy`
- `AGENT_DASHBOARD_CORE_POLL_SEC`: polling interval (default `5`)
- `AGENT_DASHBOARD_DISABLE_INTERNAL_READER=1`: disable internal reader (optional)

## Testing

```bash
./venv/bin/python -m pytest -q
```

## Documentation

Project documentation is split in a practical way:

- `README.md` for orientation, setup, and quick usage
- `docs/` for versioned technical documentation
- GitHub Wiki for operational notes, walkthroughs, and playbooks that evolve over time

## Author

- Niccolò Zamborlini
- encom.io
- Project: https://github.com/virgolamobile/openclaw-swarm-observatory/tree/main

## Community and licensing

- Contribution process: `CONTRIBUTING.md`
- Community behavior policy: `CODE_OF_CONDUCT.md`
- License: **PolyForm Noncommercial 1.0.0** (`LICENSE`)

Third-party vendored assets are covered by upstream licenses in `THIRD_PARTY_NOTICES.md` and `static/vendor/licenses/`.
