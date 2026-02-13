# OpenClaw Portable Compliance Matrix

Author: Niccolò Zamborlini (encom.io)  
Project: https://github.com/virgolamobile/openclaw-swarm-observatory/tree/main

## Purpose

Define what is OpenClaw protocol-level behavior, what is optional at runtime, and how the dashboard must degrade gracefully without failing startup.

## Core distinction

- **Protocol requirement**: a channel expected by OpenClaw governance.
- **Runtime prerequisite**: a technical dependency required to run the dashboard.

The dashboard must remain protocol-aware while never hard-failing when one or more channels are missing in the target installation.

## Channel matrix

| Channel | OpenClaw protocol status | Runtime prerequisite | Portable fallback | Minimum guaranteed output |
|---|---|---|---|---|
| `shared/events/bus.jsonl` | Required (broadcast) | NO | CLI/Gateway provider, or disable-safe mode | base event timeline |
| `shared/requests/` | Required (async p2p) | NO | infer interactions from bus/direct messages | partial relations |
| `shared/results/` | Required (outcomes) | NO | infer completion from milestones/events | estimated completions |
| `shared/action-ledger/*` | Required (progress protocol) | NO | infer KPIs from events/cron runs | medium-confidence KPIs |
| `cron/jobs.json` | Architecturally required | NO | `openclaw cron list --json` | next runs + cron health |
| `cron/runs/*.jsonl` | Architecturally required | NO | cron last-run summary/state | limited duration/status trends |
| `agents/*/sessions/*.jsonl` | Common but implementation-dependent | NO | bus + cron + agent state | inferred doing-now |
| session lock files | Implementation detail | NO | watchdog/blocker events | partial lock insights |

## Recommended profile: core-only-passive

This profile is designed to run across heterogeneous OpenClaw installations without requiring local custom files.

### Baseline read-only commands

| Command | Usage |
|---|---|
| `openclaw agents list --json` | agent/workspace discovery |
| `openclaw cron list --json` | scheduling + job status |
| `openclaw status --json` | aggregated runtime snapshot |
| `openclaw system presence --json` | gateway/node presence |
| `openclaw health` | infrastructure health |

### Guarantee

If these commands are available, the dashboard must:

- always start
- display agents/cron/system status
- avoid requiring changes in agent prompts or identity files

## Bootstrap contract

At startup the system should emit:

1. `capabilities.json` with per-channel availability
2. global `coverage score` (0-100)
3. selected `mode` (`strict-openclaw`, `portable-openclaw`, `minimal`)
4. `remediation hints` for missing channels

## Degradation rules

1. No channels available → start in `minimal` mode with setup diagnostics.
2. Partial channels available → start in `portable` mode and expose per-panel confidence.
3. Full channels available → start in `strict` mode with complete features.

## Public release requirements

- No user-specific absolute hardcoded paths
- Custom root support via env/config
- All connectors implement `discover/snapshot/stream/health`
- No crash for missing files/directories
- Test matrix on at least three profiles:
  - full OpenClaw
  - partial (bus + cron, no requests/results)
  - minimal (CLI only)

## Acceptance criterion

The tool is considered out-of-the-box when, on an unknown installation, it shows within 30 seconds:

- bootstrap state
- detected capabilities
- at least one populated real-time panel
- actionable guidance to increase coverage
