# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install (editable, with optional live/optimization deps)
pip install -e ".[aws,optimization,test]"

# Or minimal
pip install -e .

# Run all tests
python -m pytest tests/ -q

# Run a single test file
python -m pytest tests/test_visibility.py -q

# Run a specific test
python -m pytest tests/test_visibility.py::test_passes_are_wellformed_and_clear_the_mask -v

# Core library usage is shown in tests/ and the README.
# (Demos have been archived to archive/demos/.)
```

The package is now installable via pyproject.toml (no more PYTHONPATH=src required after `pip install -e .`).
Optional extras: aws (boto3 for live adapters), optimization (ortools for CP-SAT scheduler).

## Architecture

This is a vendor-neutral contact scheduler for satellite fleets. The system books/queries ground station contacts but never touches command-and-control (off the flight-critical path).

**The Spine (build order):**
```
TLE sources -> Visibility Engine -> Scheduler -> Reconciler/Failover -> Provider Adapters -> Observability
    (done)          (done)          (done)          (done)              (mock + AWS live skeleton + stubs)   (prototype + real design doc)
```

**Currently implemented:** Full spine (prototype observability; live adapters partial).
Demos archived to archive/demos/.

### Key Design Decisions

1. **Provider-adapter interface as the seam**: The adapter layer is both the vendor abstraction and the test boundary. The entire system can run against a simulated ground segment with real orbital data, then swap to live providers (KSAT, Leaf Space, AWS Ground Station) without upstream changes.

2. **Frozen value objects in domain.py**: `GroundStation` and `ContactWindow` are immutable dataclasses that decouple downstream components from Skyfield and provider specifics. All components speak in these terms.

3. **Pure orbital mechanics**: The visibility engine uses SGP4 propagation via Skyfield. Tests assert physical invariants (pass ordering, elevation mask clearance, inclination limits) rather than exact times, keeping them valid as TLE elements change.

### Module Responsibilities

- `orchestrator/domain.py` - Core types: `GroundStation`, `ContactWindow` (frozen dataclasses)
- `orchestrator/tle.py` - TLE loading from file or CelesTrak API (cache results; don't hammer the API)
- `orchestrator/visibility.py` - `compute_passes()` for single sat/station, `compute_all_opportunities()` for Cartesian sweep
- `orchestrator/scheduler.py` - `schedule_greedy()` and `schedule_cpsat()` -> `SchedulePlan`
- `orchestrator/providers.py` - `ProviderAdapter` interface, `MockProviderAdapter` (fault injection), `AwsGroundStationAdapter` (live)
- `orchestrator/reconciler.py` - `Reconciler` control loop: books contacts, polls outcomes, re-books failures
- `orchestrator/observability.py` - Metrics, Prometheus text export, self-contained HTML dashboard

### Terminology

- **AOS** - Acquisition of signal (satellite rises above elevation mask)
- **TCA** - Time of closest approach (culmination, peak elevation)
- **LOS** - Loss of signal (satellite sets below mask)
- **Elevation mask** - Minimum angle above horizon for usable contact (typically 5-10 degrees)
