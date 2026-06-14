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
   (real)         (real, done)      (done)        (done)                   (mock done│live next)   (next)
```

The provider-adapter interface is the key seam: it is both the vendor-neutral
abstraction and the real-vs-simulated test boundary, so the whole system can be
built and exercised against a simulated ground segment with *real* orbital data,
then swapped onto live providers without changing anything upstream.

### Status

- [x] **Visibility engine** — SGP4 propagation, pass detection, peak elevation,
      azimuths. Pure deterministic orbital mechanics.
- [x] **Scheduler** — greedy, value-ranked (priority × pass quality − provider
      cost), no antenna double-booked. CP-SAT optimization to follow.
- [x] **Reconciler / failover control loop** — books contacts, polls outcomes,
      re-books failures onto the next-best future opportunity (preferring a
      different provider), with an explicit yield SLO and error budget.
- [x] **Provider adapters** — interface + mock with fault injection (failure
      rates, station outages). Live adapters (AWS Ground Station first) to follow.
- [ ] Observability — dashboard for the yield SLO, error-budget burn, per-provider reliability.

## Quickstart

```bash
pip install skyfield
PYTHONPATH=src python3 examples/next_passes.py
```

The example runs offline against a bundled ISS element set, computing passes in
a 48h window at that TLE's epoch (keeping SGP4 accurate near epoch). The output
is physically self-checking: Svalbard (78°N) sees **zero** ISS passes because
the 51.6° orbit never reaches that latitude, while Punta Arenas (52.9°S), right
under the orbit's edge, gets near-overhead passes.

### Live data (verify against a tracker)

Set `USE_LIVE = True` in `examples/next_passes.py` and run in an environment
with network access to celestrak.org. It fetches current elements and computes
passes from *now*, which you can check against https://www.n2yo.com for your
location.

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
  scheduler.py    greedy allocator: schedule_greedy -> SchedulePlan
  providers.py    ProviderAdapter interface + MockProviderAdapter (fault injection)
  reconciler.py   the failover control loop: Reconciler -> ReconcileReport
data/
  sample_tle.txt  bundled ISS element set (offline demo)
  stations.json   ground-station registry (real sites, provider-tagged)
examples/
  next_passes.py    compute upcoming ISS passes over the registry
  schedule_demo.py  schedule real opportunities + a contention scenario
  failover_demo.py  schedule, inject a station outage, watch recovery + SLO
tests/
  test_visibility.py
  test_scheduler.py
  test_reconciler.py
```
