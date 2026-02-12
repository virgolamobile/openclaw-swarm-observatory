# Contributing Guide

Thanks for your interest in improving the OpenClaw Agent Dashboard.

## Scope

This project is focused on passive observability for OpenClaw agents:

- Keep integrations core-first and non-invasive.
- Avoid introducing mandatory behavioral changes to agents.
- Prefer portability over host-specific assumptions.

## Development setup

1. Create/activate virtualenv.
2. Install runtime deps:

```bash
pip install -r requirements.txt
```

3. Install test deps:

```bash
pip install pytest pytest-cov
```

4. Run tests:

```bash
pytest -q
```

## Contribution workflow

1. Open an issue describing the problem/feature.
2. Keep changes focused and minimal.
3. Add or update tests for behavior changes.
4. Update docs in `docs/` when APIs/UI flows change.
5. Submit a PR with:
   - clear summary,
   - testing evidence,
   - compatibility notes.

## Coding guidelines

- Match existing style and naming conventions.
- Prefer root-cause fixes over superficial patches.
- Do not add unrelated refactors in the same PR.
- Avoid introducing hard-coded local paths.

## Testing expectations

- Unit tests should pass locally.
- New logic should include targeted test coverage.
- Keep tests deterministic (mock I/O, time, subprocess where possible).

## Security and responsible reporting

If you find a security issue, avoid public disclosure first. Open a private report to project maintainers with reproduction steps and impact.
