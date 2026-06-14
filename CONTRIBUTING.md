# Contributing

This is an early-stage project building out the spine described in the README:
visibility → scheduler → reconciler/failover → provider adapters → observability.

## Development

```bash
pip install -r requirements.txt pytest
PYTHONPATH=src python -m pytest -q
```

## Guidelines

- Keep the domain (`domain.py`) free of Skyfield and provider specifics; it's the
  shared vocabulary everything else speaks.
- The provider-adapter interface is the seam between real and simulated ground
  segments. New providers implement that interface; nothing upstream should know
  which provider it's talking to.
- Tests should assert physical or logical invariants, not brittle exact values,
  so they survive element-set updates and refactors.

Issues and PRs welcome.
