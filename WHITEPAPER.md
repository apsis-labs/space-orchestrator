# A Vendor-Neutral Reliability Layer for Satellite Ground Operations

**Architecture and reference implementation of `space-orchestrator`**

*Jessie Hermosillo* · Version 0.2 · June 2026 · github.com/&lt;org&gt;/space-orchestrator*

---

## Abstract

Small and mid-sized low-Earth-orbit (LEO) operators downlink their data through
several heterogeneous ground networks, where each satellite is visible to a
given antenna for only a few minutes per pass. In practice this scheduling is
run on a spreadsheet and a cron job that an engineer babysits, and a missed pass
is lost, revenue-bearing data whose cost compounds. `space-orchestrator` is an
open-source reference implementation of a vendor-neutral contact-scheduling and
failover layer that sits *off* the flight-critical command path. It computes
pass opportunities from orbital elements, schedules contacts across providers,
recovers failed contacts through a reconciliation control loop, and reports
achieved downlink yield against an explicit service-level objective (SLO). On
real orbital elements with a simulated ground segment, an injected station
outage that destroyed the two highest-value contacts in a plan was automatically
recovered to 100% downlink yield, within the error budget.

## 1. The problem

A commercial operator flying roughly 5–30 satellites contracts capacity across
multiple ground networks — for example KSAT, Leaf Space, AWS Ground Station, and
its own antennas. Each satellite clears a given antenna's horizon for only a few
minutes, a handful of times per day, and several satellites may contend for the
same antenna at once. A missed contact is not a nuisance but lost data: the next
opportunity is hours away, the onboard buffer fills, and the data ages past its
freshness commitment.

As a constellation grows from a handful of satellites to dozens, the artisanal
"one operator watching one spreadsheet" model breaks — the same transition web
infrastructure faced when it moved from hand-managed servers to fleet
operations. The discipline that solved it there, site reliability engineering,
has barely reached spacecraft ground operations.

## 2. Design principles

**Off the command path.** The system reads orbital elements and books or queries
contacts; it never issues commands to a spacecraft. This both lowers the trust
barrier — operators will not let an unproven tool touch command-and-control, but
will let it optimize scheduling — and bounds the problem to a tractable scope.

**Vendor-neutral.** Every ground network is reached through one small adapter
interface; the scheduler and reconciler are provider-agnostic. Neutrality is a
structural property that a single-provider or platform vendor cannot credibly
offer.

**Reliability as a first-class output.** Contacts carry a yield SLO and an error
budget, and failures are recovered by a control loop rather than a human. The
vocabulary of error budgets, largely absent from spacecraft operations, is
applied directly.

**A real-versus-simulated seam.** The adapter interface is also the boundary
between simulated and live ground segments, so the whole system is developed and
tested against real orbital data and a simulated ground segment, then connected
to live providers without changing anything upstream.

## 3. System architecture

The system is a linear pipeline — the *spine* — with one clean seam between each
stage:

Install with:

```bash
pip install -e ".[test]"
python -m pytest tests/ -q
```

See `README.md` and the tests for current usage patterns and reproducibility.
