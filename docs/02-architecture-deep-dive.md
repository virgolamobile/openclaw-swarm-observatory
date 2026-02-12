# Architecture Deep Dive

## 1. High-level data flow

1. **Ingestion**
   - OpenClaw core CLI (`agents`, `cron`, `status`, `presence`)
   - Optional bus tailing (`shared/events/bus.jsonl`)
   - Optional session bridge (agent session JSONL)
2. **Normalization**
   - Events normalized into stable dashboard schema
3. **Fusion**
   - Core snapshots + realtime event deltas merged per agent
4. **Derivation**
   - Interactions, cron details, timelines, decision traces, causal graph
5. **Delivery**
   - REST APIs and Socket.IO updates

## 2. Core components

- `compute_core_capabilities`: channel availability model
- `build_core_agent_states`: passive core snapshot builder
- `build_cron_details`: cron telemetry enrichment
- `build_agent_timeline`: evidence timeline composition
- `infer_decision_trace`: reason/evidence inference
- `build_causal_graph`: graph model generation

## 3. Drilldown model

`/drilldown/<agent>` returns:

- `overview`
- `timeline`
- `decision_trace`
- `cron`
- `cron_timeline`
- `context_roots`
- `causal_graph`

`/drilldown/<agent>/node/<nodeId>` adds node-level relation and source detail.

## 4. Dynamic context root discovery

The dashboard does **not** assume fixed markdown filenames.
It scans agent workspace markdown files dynamically, applies ranking heuristics,
and uses anchor matching against current decision context.

## 5. Causal graph semantics

Node groups:

- `root`: workspace constraints/objectives
- `agent`: actor node
- `decision`: inferred decision points
- `action`: execution steps
- `outcome_ok` / `outcome_bad`: result states

Edge semantics:

- `constrain`
- `decides`
- `influences`
- `triggers`
- `results`

## 6. Concurrency and consistency

- Shared mutable structures protected by `state_lock`
- Background workers started once per process
- Frontend refresh strategy avoids graph reset during active interaction

## 7. Graceful degradation strategy

If one channel fails (e.g. cron runs unavailable), APIs still return partial data
with remaining channels preserved.

## 8. Design goals

- Explainability over raw logs
- Passive compliance with OpenClaw runtime
- High observability with low agent coupling
