# UI/UX Guide

## Interface objectives

This interface is designed to answer four operational questions quickly:

1. What is happening now?
2. Why is it happening?
3. What should I do next?
4. Where is the strongest evidence?

## Operating methodology

Recommended operator flow:

1. Start from KPIs to detect anomalies.
2. Select one agent from Swarm Overview.
3. Move through tabs from high-level to deep causality.
4. Use documentation help (`?`) when interpretation is ambiguous.
5. Convert findings into operational actions.

## Header and KPI strip

The top area provides immediate swarm health context:

- **Observed agents**: number of agents currently visible to telemetry.
- **Active cron jobs**: scheduled workload currently active.
- **User→agent interactions**: direct user pressure on the swarm.
- **Agent→agent interactions**: collaboration or delegation traffic.
- **Non-ok/interrupted tasks**: risk indicator requiring attention.

Use this strip as a triage gate before drilling into details.

## Swarm Overview section

Purpose:

- Select the target agent for investigation.
- See current status, current task, mission hints, and last event.

Interpretation hints:

- `Active` with frequent updates: normal runtime progression.
- `Observed` with stale last event: likely waiting state.
- `Attention` and non-ok tasks: prioritize this card first.

## Global streams section

Global Streams aggregate conversation-like signals across the swarm.

- Use them to detect coordination drift.
- Use them to correlate user requests with agent behavior changes.

## User to agent stream

Represents direct incoming demand and requests.

Use this stream to answer:

- What user intent is currently shaping behavior?
- Which agent is under request pressure?
- Are requests coherent with current operational goals?

## Agent to agent stream

Represents internal swarm communication and delegation.

Use this stream to answer:

- Which agent is orchestrating others?
- Are handoffs explicit and traceable?
- Is cross-agent chatter aligned with mission constraints?

## Investigation console section

The right-side console is the main reasoning workspace.

- It focuses one selected agent.
- It exposes multiple evidence layers.
- It supports deep causal and timeline analysis.

The strategic rule is: do not jump to conclusions from one tab only.

## Why decisions tab

Shows inferred decision statements with:

- confidence
- runtime evidence
- root-cause document linkage

Use this tab to validate **decision rationale quality**.

## SOUL file derivation tab

Shows contextual roots discovered in workspace documents.

Use it to understand:

- which files are influencing behavior,
- which anchors are matched,
- whether observed actions align with declared objectives.

## Causal graph tab

Graph layer maps constraints → decisions → actions → outcomes.

Interaction model:

- drag to pan
- wheel to zoom
- double-click to reset
- click node for deeper details

Use this tab for **cause-to-effect narratives**.

## Cron timeline tab

Shows ordered schedule/run events including status and duration.

Use it to detect:

- unstable jobs,
- repeated non-ok outcomes,
- schedule pressure windows.

## Full timeline tab

Combines session, realtime, interaction, and cron evidence.

Use it for reconstruction:

- what happened,
- in which order,
- under which context.

## Overview tab

Compact summary for the selected agent.

Use it for quick handover notes or status snapshots when switching focus.

## Documentation modal and help triggers

Documentation is integrated in two ways:

- header `Docs index`
- contextual `?` triggers near sections/subsections

The docs modal supports:

- left tree navigation from H1/H2 headings,
- markdown rendering,
- syntax-highlighted code blocks,
- anchor navigation to specific sections.

## Strategic usage patterns

### Pattern 1: anomaly triage

1. detect KPI spike,
2. open impacted agent,
3. inspect Cron timeline,
4. validate with Why decisions,
5. confirm in Causal graph.

### Pattern 2: decision audit

1. start with Why decisions,
2. validate roots in SOUL/file derivation,
3. test causal consistency in graph,
4. decide corrective action.

### Pattern 3: communication drift

1. inspect User→Agent stream,
2. inspect Agent→Agent stream,
3. compare with current task and timeline,
4. identify missing handoffs or contradictions.

## Tools map

Operational tools exposed by the UI:

- KPI strip for instant health pulse,
- Swarm cards for target selection,
- streams for communication evidence,
- tabs for layered investigation,
- docs modal for procedural clarity.

Use them together as one decision support surface, not isolated widgets.
