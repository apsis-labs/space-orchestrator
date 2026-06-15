# Contributing

Thanks for your interest in contributing to space-orchestrator!

## Development Setup

```bash
# Clone and install in development mode
git clone https://github.com/apsis-labs/space-orchestrator.git
cd space-orchestrator
pip install -e ".[test,aws,optimization]"

# Run tests
python -m pytest tests/ -q

# Type check
pip install mypy
python -m mypy src/orchestrator --ignore-missing-imports
```

## Adding a New Provider

Want to add support for KSAT, Leaf Space, or another ground station network?

1. Look at `examples/custom_provider.py` for a complete template
2. Implement the `ProviderAdapter` protocol (see `src/orchestrator/providers.py`)
3. Add tests in `tests/test_providers.py`
4. Update the provider status table in `README.md`

The key methods to implement:
- `book(window) -> Booking` — Reserve antenna time
- `poll(booking) -> ContactOutcome` — Check if contact succeeded
- `cancel(booking) -> None` — Best-effort cancellation

## Guidelines

- **Domain purity**: Keep `domain.py` free of Skyfield and provider specifics. It's the shared vocabulary everything else speaks.
- **Provider abstraction**: New providers implement the adapter interface. Nothing upstream should know which provider it's talking to.
- **Physical invariants**: Tests should assert ordering, constraints, and logical properties — not brittle exact values that break when TLEs update.
- **No over-engineering**: Keep changes focused. A bug fix doesn't need surrounding code cleaned up.

## Code Style

- Type hints on all public functions
- Docstrings for modules and classes
- Run `mypy` before submitting

## Pull Requests

1. Fork the repo and create a branch
2. Make your changes with tests
3. Ensure `pytest` and `mypy` pass
4. Submit a PR with a clear description

Issues and PRs welcome!
