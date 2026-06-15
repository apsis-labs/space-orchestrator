# space-orchestrator

Vendor-neutral satellite ground station contact scheduler with automatic failover.

Schedule contacts across AWS Ground Station, KSAT, Leaf Space, and owned antennas — with automatic recovery when passes fail.

## Features

- **Visibility engine** — SGP4 propagation, pass detection, peak elevation
- **Schedulers** — Greedy and CP-SAT (constraint optimization) algorithms
- **Automatic failover** — Re-books failed contacts on alternate providers
- **SLO tracking** — Explicit yield targets with error budgets
- **Self-contained dashboard** — HTML status page with Prometheus metrics

## Provider Status

| Provider | Status | Notes |
|----------|--------|-------|
| AWS Ground Station | **Production** | Full boto3 integration with retry logic |
| Mock | **Testing** | Configurable failure injection |
| KSAT | Stub | Extension point — PRs welcome |
| Leaf Space | Stub | Extension point — PRs welcome |

## Quickstart

```bash
pip install space-orchestrator

# List upcoming ISS passes over bundled ground stations
orchestrator passes --hours 12

# Schedule contacts (greedy algorithm)
orchestrator schedule --hours 24 --output plan.json

# Run reconciliation with simulated 20% failure rate
orchestrator reconcile --hours 24 --failure-rate 0.2 --output report.json

# Generate HTML dashboard
orchestrator dashboard --report report.json --output status.html
```

## Library Usage

```python
from datetime import datetime, timedelta, timezone
from orchestrator import (
    GroundStation,
    MockProviderAdapter,
    Reconciler,
    load_satellites_from_file,
    schedule_greedy,
)
from orchestrator.visibility import compute_all_opportunities

# Define stations
stations = [
    GroundStation("SVALBARD", 78.2, 15.4, provider="ksat"),
    GroundStation("FAIRBANKS", 64.8, -147.7, provider="aws"),
]

# Load TLEs and compute passes
satellites = load_satellites_from_file("data/sample_tle.txt")
now = datetime.now(timezone.utc)
opportunities = compute_all_opportunities(
    satellites, stations, now, now + timedelta(hours=24)
)

# Schedule and reconcile
plan = schedule_greedy(opportunities, stations)
adapters = {
    "ksat": MockProviderAdapter("ksat", failure_rate=0.1),
    "aws": MockProviderAdapter("aws", failure_rate=0.1),
}
report = Reconciler(adapters, stations, opportunities).run(plan)

print(f"Yield: {report.achieved_yield:.1%}, SLO met: {report.slo_met}")
```

See `examples/` for more:
- `quickstart.py` — Minimal working example
- `aws_integration.py` — AWS Ground Station setup
- `custom_provider.py` — Implementing a new provider adapter

## Architecture

```
TLE sources → Visibility Engine → Scheduler → Reconciler → Provider Adapters → Dashboard
                                                              ↓
                                              AWS │ Mock │ KSAT* │ Leaf*
                                                        (* = stub)
```

The **provider adapter interface** is the key abstraction: swap `MockProviderAdapter` for `AwsGroundStationAdapter` and nothing upstream changes. This lets you develop and test against simulated ground stations, then deploy to production without code changes.

## Installation

```bash
# Basic install
pip install space-orchestrator

# With AWS Ground Station support
pip install space-orchestrator[aws]

# With CP-SAT scheduler (requires OR-Tools)
pip install space-orchestrator[optimization]

# Development
pip install -e ".[test,aws,optimization]"
```

## Tests

```bash
pip install -e ".[test]"
python -m pytest tests/ -q
```

Tests assert physical invariants (pass ordering, elevation constraints) rather than exact times, so they stay valid as TLE elements change.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Want to add a provider?** See `examples/custom_provider.py` for a complete implementation template. PRs for KSAT and Leaf Space adapters are welcome!

## License

MIT
