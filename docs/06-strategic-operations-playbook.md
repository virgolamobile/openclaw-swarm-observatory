# Strategic Operations Playbook

## Dashboard objective

The dashboard is a strategic observability and explainability surface for multi-agent operations.

Primary objective:

- reduce reaction time,
- improve decision quality,
- preserve traceability from intent to outcome.

## Strategic goals

- Maintain reliable swarm execution under changing user pressure.
- Detect anomalies before they become systemic failures.
- Explain decisions with evidence, not assumptions.
- Align runtime behavior with workspace constraints and goals.

## Tools available

Core tools exposed by the product:

1. KPI pulse for immediate system health.
2. Swarm selection cards for scoped analysis.
3. Interaction streams for intent and coordination context.
4. Investigation tabs for multi-layer evidence.
5. Causal graph for root-to-outcome narratives.
6. Documentation tree for guided interpretation.

## Methodology

### Phase 1: detect

Use KPI strip and streams to detect pressure, interruption, or drift.

### Phase 2: isolate

Select one agent and freeze attention on one hypothesis.

### Phase 3: explain

Use Why decisions + SOUL/file derivation + Causal graph.

### Phase 4: decide

Define corrective action based on evidence confidence and impact.

### Phase 5: verify

Re-check timeline and cron outcomes after intervention.

## How to use it strategically

### Incident handling

- Prioritize agents with non-ok/interrupted signals.
- Confirm if incident is local (single agent) or systemic (interaction cascade).
- Apply smallest corrective action first, then verify.

### Reliability governance

- Monitor recurring cron degradations.
- Track whether root constraints are consistently respected.
- Convert repeated patterns into operational runbooks.

### Decision quality review

- Audit inferred decisions against source evidence.
- Flag low-confidence decisions for manual review.
- Use docs tree as institutional memory during handoffs.

## Common anti-patterns

- Looking only at one tab before deciding.
- Ignoring stream context while reading timeline.
- Treating graph outcome as certainty instead of evidence map.
- Skipping documentation in ambiguous scenarios.

## Execution checklist

1. KPI anomaly confirmed.
2. Target agent selected.
3. Decision rationale validated.
4. Root constraints checked.
5. Causal sequence consistent.
6. Action applied.
7. Post-action verification complete.
