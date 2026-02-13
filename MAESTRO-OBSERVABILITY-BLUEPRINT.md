# MAESTRO Observability Blueprint

Author: Niccolò Zamborlini (encom.io)  
Project: https://github.com/virgolamobile/openclaw-swarm-observatory/tree/main

## Objective

Evolve `agent-dashboard` from status cards into a real-time OpenClaw control room that clearly answers:

- What agents are doing now
- What they just completed
- What is likely next
- Who is interacting with whom
- Which cron jobs are delayed/failing
- Which locks/watchdogs/blockers are active

## Compliance baseline

OpenClaw governance strongly recommends these channels:

- `shared/events/bus.jsonl` for broadcast events
- `shared/requests/` and `shared/results/` for async point-to-point workflows
- periodic heartbeats with channel checks
- action ledger under `shared/action-ledger/{agentId}/current.jsonl`
- root config in `~/.openclaw/openclaw.json`
- cron state in `~/.openclaw/cron/jobs.json` and `~/.openclaw/cron/runs/*`

Publishing rule: these conventions must improve observability but must not become hard runtime prerequisites.

## Product constraint

The public-ready version must work even if:

- some shared directories do not exist yet
- files are relocated or renamed
- only a subset of protocols is adopted
- telemetry is available only through CLI/gateway providers

Guiding principle: **progressive capability detection + graceful degradation**.

## Current state summary

- Main ingestion from `shared/events/bus.jsonl`
- Session bridge from `agents/*/sessions/*.jsonl`
- Socket.IO card-based UI (`init`, `update`)
- Mini message/thought history persisted in `shared/events/history/*.jsonl`

## Main gaps

1. **Data coverage gaps**
   - Native cron jobs/runs ingestion is incomplete.
   - No process/subprocess telemetry model.
   - Weak correlation with requests/results/locks.

2. **Event semantics fragility**
   - Session previews truncate content and lose context.
   - Event roles are not fully normalized under one typed schema.
   - In-memory dedup only; not durable across restarts.

3. **Non-deterministic realtime behavior**
   - Polling loops on large multi-source files.
   - In-process reader risks duplicate readers in multi-worker deployment.
   - Backfill and live streaming are not strictly offset-safe.

4. **Limited relational model**
   - No strong entities for `Turn`, `ToolCall`, `CronRun`, `Process`, `InteractionEdge`.
   - No full dependency graph for agent collaboration.

## Target architecture

### 0) Discovery and capability layer (mandatory)

Before ingestion starts:

1. Resolve OpenClaw root (`OPENCLAW_HOME`, cwd, fallback `~/.openclaw`).
2. Load available providers (filesystem, CLI, gateway).
3. Run non-destructive probes.
4. Build runtime `capabilities.json`.
5. Enable only supported connectors.

If a capability is missing, bootstrap still succeeds and UI reports partial observability with remediation hints.

### 1) Ingestion layer

- **Bus connector**: consumes event bus with persistent offsets.
- **Session connector**: consumes session streams with per-file offsets and rotation safety.
- **Cron connector**: jobs snapshot + runs stream, with CLI fallback.
- **Process connector**: process tree snapshots mapped to agents.
- **Lock/watchdog connector**: lock signals + watchdog/blocker events.
- **Request/result connector**: cross-agent dependency extraction.

All connectors must implement:

- `discover() -> capability`
- `snapshot() -> normalized events[]`
- `stream(since_offset) -> iterator`
- `health() -> connector status`

Provider options:

- `FsProvider`
- `CliProvider`
- `GatewayProvider`
- `NullProvider` (disable-safe)

### 2) Correlation layer

Correlate entities by IDs and time windows:

- `Turn` ↔ `ToolCall` ↔ `ToolResult`
- `CronJob` ↔ `CronRun`
- `Agent` ↔ `Process`
- `Request` ↔ `Result`

Derive high-level states:

- `doing_now`
- `just_done`
- `next_expected_action`
- `blocked_by`

### 3) Storage layer

- **Hot store**: Redis Streams or NATS JetStream for fan-out and short replay.
- **Warm store**: SQLite WAL or Postgres for timeline and diagnostics queries.
- **Cold archive**: append-only JSONL, backward compatible.

### 4) Delivery layer

- Stream channels: `/stream/agents`, `/stream/cron`, `/stream/processes`, `/stream/graph`, `/stream/alerts`
- Coherent initial snapshot + versioned deltas (`seq`, `offset`, `source`)

## Canonical unified event model

```json
{
  "id": "evt_...",
  "ts": "2026-02-12T18:12:27.316Z",
  "source": "session|bus|cron|proc|lock|request|result",
  "entity": "agent|turn|cron_job|cron_run|process|interaction|alert",
  "agent": "europa",
  "kind": "turn.started|turn.completed|cron.run.finished|process.spawned|alert.lock_stale",
  "severity": "info|warn|error",
  "labels": {},
  "payload": {},
  "causality": {"parentId": null, "traceId": "..."},
  "dedupKey": "...",
  "seq": 123456
}
```

## Operating modes

### `strict-openclaw`

Use when all canonical channels are available; full protocol validation and max KPI fidelity.

### `portable-openclaw` (default)

Auto-detect available channels, enable provider fallbacks, and expose source coverage in UI.

### `minimal`

Requires only root/CLI access plus one runtime signal (bus, cron, or sessions).
Dashboard still starts and provides constrained but truthful insight.

### `core-only-passive` (recommended for public release)

Uses only core OpenClaw read-only commands and does not require agent behavior changes.

## Product release checklist

- No user-specific absolute hardcoded paths
- Root and channels resolved through discovery
- Every connector has fallback or disable-safe behavior
- Successful startup with missing channels
- UI clearly exposes source coverage and confidence
- No plaintext secrets in exported payloads
- Documentation includes quickstart for full/partial/minimal setups

## Implementation phases

1. **Telemetry foundation (1-2 days)**
   - canonical schema, capability layer, provider abstraction, offset store
2. **Process and diagnostics (2-3 days)**
   - process connector, lock detector, Cron Radar + Process Observatory
3. **Graph and prediction (2-4 days)**
   - request/result correlation, interaction graph, next-action heuristics
4. **Production hardening (1-2 days)**
   - benchmarks, SLO alerts, chaos tests, installation matrix tests

## Success KPIs

- Incident diagnosis time reduced by >60%
- Delayed cron detection within one cycle
- Stale lock/orphan process detection in <30s
- `doing_now` accuracy >95% on verified samples

## Recommended technical decisions

- Separate event processing worker from the web server
- Monotonic WS delta protocol with replay on reconnect
- Normalized client-side store to prevent large rerender bursts
- End-to-end stream consistency tests
