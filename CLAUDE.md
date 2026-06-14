# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
PYTHONPATH=src python3 -m pytest tests/ -q

# Run a single test file
PYTHONPATH=src python3 -m pytest tests/test_visibility.py -q

# Run a specific test
PYTHONPATH=src python3 -m pytest tests/test_visibility.py::test_passes_are_wellformed_and_clear_the_mask -v

# Run the example (offline, uses bundled TLE)
PYTHONPATH=src python3 examples/next_passes.py
```

Note: `PYTHONPATH=src` is required because there's no setup.py/pyproject.toml install.

## Architecture

This is a vendor-neutral contact scheduler for satellite fleets. The system books/queries ground station contacts but never touches command-and-control (off the flight-critical path).

**The Spine (build order):**
```
TLE sources -> Visibility Engine -> Scheduler -> Reconciler/Failover -> Provider Adapters
                    (done)          (planned)      (planned)              (planned)
```

**Currently implemented:** Visibility Engine only.

### Key Design Decisions

1. **Provider-adapter interface as the seam**: The adapter layer is both the vendor abstraction and the test boundary. The entire system can run against a simulated ground segment with real orbital data, then swap to live providers (KSAT, Leaf Space, AWS Ground Station) without upstream changes.

2. **Frozen value objects in domain.py**: `GroundStation` and `ContactWindow` are immutable dataclasses that decouple downstream components from Skyfield and provider specifics. All components speak in these terms.

3. **Pure orbital mechanics**: The visibility engine uses SGP4 propagation via Skyfield. Tests assert physical invariants (pass ordering, elevation mask clearance, inclination limits) rather than exact times, keeping them valid as TLE elements change.

### Module Responsibilities

- `orchestrator/domain.py` - Core types: `GroundStation` (antenna location + elevation mask), `ContactWindow` (AOS/TCA/LOS times, peak elevation, azimuths)
- `orchestrator/tle.py` - TLE loading from file or CelesTrak API (cache results; don't hammer the API)
- `orchestrator/visibility.py` - `compute_passes()` for single sat/station, `compute_all_opportunities()` for Cartesian sweep
- `data/stations.json` - Ground station registry with provider tags
- `data/sample_tle.txt` - Bundled ISS elements for offline testing

### Terminology

- **AOS** - Acquisition of signal (satellite rises above elevation mask)
- **TCA** - Time of closest approach (culmination, peak elevation)
- **LOS** - Loss of signal (satellite sets below mask)
- **Elevation mask** - Minimum angle above horizon for usable contact (typically 5-10 degrees)
