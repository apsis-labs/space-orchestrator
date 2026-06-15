# space-orchestrator

A vendor-neutral contact scheduler for satellite fleets.

Small operators flying 5–30 satellites downlink their data across several
ground networks (KSAT, Leaf Space, AWS Ground Station, owned antennas), with
each satellite visible to a given antenna for only a few minutes per pass.
Today that scheduling is often a spreadsheet and a cron job that someone
babysits, and a missed pass is lost data that compounds. This project is the
reliability layer for that problem: compute the opportunities, schedule
contacts across every provider, and automatically recover failed ones against
an explicit downlink-yield SLO.

It deliberately sits **off the flight-critical command path** — it reads
elements and books/queries contacts; it never touches command-and-control.

## Architecture (the spine)

```
TLE sources ─► Visibility Engine ─► Scheduler ─► Reconciler / Failover ─► Provider Adapters ─► State + Observability
   (real)         (real, done)      (done)        (done)                   (mock done│live next)   (done)
```

The provider-adapter interface is the key seam: it is both the vendor-neutral
abstraction and the real-vs-simulated test boundary, so the whole system can be
built and exercised against a simulated ground segment with *real* orbital data,
then swapped onto live providers without changing anything upstream.

### Status

- [x] **Visibility engine** — SGP4 propagation, pass detection, peak elevation,
      azimuths. Pure deterministic orbital mechanics.
- [x] **Scheduler** — greedy (value-ranked) + CP-SAT (ortools) implementations.
      Same value model + StationLedger constraints. Produces SchedulePlan.
- [x] **Reconciler / failover control loop** — books contacts, polls outcomes,
      re-books failures onto the next-best future opportunity (preferring a
      different provider), with an explicit yield SLO and error budget.
- [x] **Provider adapters** — interface + mock with fault injection (failure
      rates, station outages). Live adapters: AwsGroundStationAdapter (full
      boto3-based with from_config(), ARNs, ground station mapping); KsatAdapter
      stub. See providers.py docstring for usage. Others (KSAT, Leaf Space) to follow.

**Live adapter (AWS) usage** (see providers.py for full docstring):
```python
adapter = AwsGroundStationAdapter.from_config(
    satellite_arn="arn:...:satellite/xxx",
    mission_profile_arn="arn:...:mission-profile/yyy",
    ground_station_map={"FAIRBANKS": "Alaska 1"},
)
adapters = {"aws-ground-station": adapter, "owned": MockProviderAdapter("owned")}
report = Reconciler(adapters, stations, opps, ...).run(plan)
```

- [x] **Observability** — self-contained HTML dashboard (bar height + colour encode pass quality) + Prometheus metrics; error budget + recovery timeline.

## Quickstart

```bash
pip install -e ".[test]"
python -m pytest tests/ -q

# Library usage (see tests/ and README examples for full pipeline)
from orchestrator import schedule_greedy, Reconciler, MockProviderAdapter
...
```

The example runs offline against a bundled ISS element set, computing passes in
a 48h window at that TLE's epoch (keeping SGP4 accurate near epoch). The output
is physically self-checking: Svalbard (78°N) sees **zero** ISS passes because
the 51.6° orbit never reaches that latitude, while Punta Arenas (52.9°S), right
under the orbit's edge, gets near-overhead passes.

### Live data (verify against a tracker)

The library supports live TLE fetching via `load_satellites_from_celestrak`.
See `tests/test_visibility.py` for usage patterns with real orbital data, or
use the functions directly in your own scripts to compute passes from current
elements and cross-check against public trackers like n2yo.com.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```

The tests assert physical invariants (ordering, mask clearance, inclination
limits) rather than exact times, so they stay valid as elements change.

## Layout

```
src/orchestrator/
  domain.py       GroundStation, ContactWindow value objects
  tle.py          load elements from file or live from CelesTrak
  visibility.py   the engine: compute_passes, compute_all_opportunities
  scheduler.py    greedy + CP-SAT: schedule_greedy / schedule_cpsat -> SchedulePlan
  providers.py    ProviderAdapter interface + Mock + AwsGroundStationAdapter (live) + stubs
  reconciler.py   the failover control loop: Reconciler -> ReconcileReport
  observability.py  Metrics, Prometheus text, self-contained HTML dashboard
data/
  sample_tle.txt  bundled ISS element set (for tests)
  stations.json   ground-station registry (real sites, provider-tagged)
tests/
  test_visibility.py
  test_scheduler.py
  test_reconciler.py
  test_observability.py
  test_providers.py
```

**Note on examples/demos**: All demo scripts have been archived to `archive/demos/` (see archive/demos/README.md). Demos were removed to keep focus on the core library and spine implementation. Use the library API directly (examples in tests/ and this README).
```
