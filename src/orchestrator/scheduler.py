"""Greedy contact scheduler.

Takes the opportunity set from the visibility engine and allocates contacts to
antennas, resolving contention so no antenna is ever double-booked. This is the
v1 scheduler: a value-ranked greedy pass. It is intentionally simple and fast,
and it establishes the interface (opportunities in, a plan of scheduled and
dropped contacts out) that a later CP-SAT optimizer can drop straight into.

Value model (deliberately small and explainable):

    value = priority(satellite) * quality(pass) - cost(provider)

where quality is peak elevation normalized to [0, 1] -- a near-overhead pass is
worth more than a horizon scrape -- priority is a per-satellite weight, and cost
is a per-provider penalty. Sorting opportunities by value and greedily placing
each on its antenna (if free, with a setup/teardown gap) gives a plan that
beats a spreadsheet decisively while staying easy to reason about.

A station is modeled as a single antenna: it can serve one contact at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional

from .domain import ContactWindow, GroundStation

try:
    from ortools.sat.python import cp_model
except ImportError:
    cp_model = None  # type: ignore[assignment]

#: Default slew/configure gap an antenna needs between consecutive contacts.
DEFAULT_SETUP_TEARDOWN_S = 30.0


@dataclass
class StationLedger:
    """Tracks claimed time intervals per station, enforcing a minimum buffer
    (setup/teardown gap) between consecutive contacts on the same antenna.

    This is the single source of truth for the "no double-booking" rule.
    Both the initial greedy scheduler and the reconciler's recovery logic
    use it so the rule cannot drift.
    """

    buffer: timedelta = field(default_factory=lambda: timedelta(seconds=DEFAULT_SETUP_TEARDOWN_S))
    _intervals: dict[str, list[tuple[datetime, datetime]]] = field(
        default_factory=dict, repr=False, init=False
    )

    def is_free(self, window: ContactWindow) -> bool:
        """True iff booking `window` would not violate the buffer gap on its station."""
        intervals = self._intervals.get(window.station, [])
        return all(
            (window.los + self.buffer <= start) or (window.aos - self.buffer >= end)
            for (start, end) in intervals
        )

    def claim(self, window: ContactWindow) -> None:
        """Record that this window's station time is now taken."""
        self._intervals.setdefault(window.station, []).append((window.aos, window.los))


@dataclass(frozen=True)
class ScheduledContact:
    """An opportunity that was booked, with the provider and value it scored."""

    window: ContactWindow
    provider: str
    value: float


@dataclass(frozen=True)
class SchedulePlan:
    """The output of a scheduling run: what got booked and what got dropped."""

    scheduled: list[ScheduledContact]
    dropped: list[ContactWindow]

    @property
    def scheduled_count(self) -> int:
        return len(self.scheduled)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    @property
    def total_value(self) -> float:
        return sum(c.value for c in self.scheduled)

    def contacts_by_satellite(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.scheduled:
            counts[c.window.satellite] = counts.get(c.window.satellite, 0) + 1
        return counts

    def contacts_by_provider(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.scheduled:
            counts[c.provider] = counts.get(c.provider, 0) + 1
        return counts


def pass_quality(window: ContactWindow) -> float:
    """Peak elevation normalized to [0, 1]; 90 degrees overhead is the ideal."""
    return max(0.0, min(window.peak_elevation_deg, 90.0)) / 90.0


def contact_value(window: ContactWindow, priority: float, provider_cost: float) -> float:
    return priority * pass_quality(window) - provider_cost


def schedule_greedy(
    opportunities: Iterable[ContactWindow],
    stations: Iterable[GroundStation],
    priorities: Optional[Mapping[str, float]] = None,
    provider_costs: Optional[Mapping[str, float]] = None,
    setup_teardown_s: float = DEFAULT_SETUP_TEARDOWN_S,
    max_contacts_per_satellite: Optional[int] = None,
) -> SchedulePlan:
    """Allocate `opportunities` to antennas, greedily, highest value first.

    Args:
        opportunities: candidate contact windows (from the visibility engine).
        stations: the station registry, used to resolve each station's provider.
        priorities: per-satellite weight (default 1.0). Higher wins contention.
        provider_costs: per-provider penalty subtracted from value (default 0.0).
        setup_teardown_s: required gap between two contacts on the same antenna.
        max_contacts_per_satellite: optional cap so one satellite can't hog the
            plan; further opportunities for it are dropped once the cap is hit.

    Returns:
        A SchedulePlan. Every input opportunity ends up in exactly one of
        `scheduled` or `dropped` (nothing is silently lost).
    """
    priorities = priorities or {}
    provider_costs = provider_costs or {}
    stations_by_name = {s.name: s for s in stations}

    # Score every opportunity, then rank by value (desc), AOS (asc) for stable order.
    scored: list[tuple[float, ContactWindow, str]] = []
    for w in opportunities:
        station = stations_by_name.get(w.station)
        provider = station.provider if station else "unknown"
        priority = priorities.get(w.satellite, 1.0)
        cost = provider_costs.get(provider, 0.0)
        scored.append((contact_value(w, priority, cost), w, provider))
    scored.sort(key=lambda t: (-t[0], t[1].aos))

    ledger = StationLedger(timedelta(seconds=setup_teardown_s))
    per_sat: dict[str, int] = {}
    scheduled: list[ScheduledContact] = []
    dropped: list[ContactWindow] = []

    for value, w, provider in scored:
        if (
            max_contacts_per_satellite is not None
            and per_sat.get(w.satellite, 0) >= max_contacts_per_satellite
        ):
            dropped.append(w)
            continue

        if not ledger.is_free(w):
            dropped.append(w)
            continue

        ledger.claim(w)
        scheduled.append(ScheduledContact(window=w, provider=provider, value=value))
        per_sat[w.satellite] = per_sat.get(w.satellite, 0) + 1

    scheduled.sort(key=lambda c: c.window.aos)
    dropped.sort(key=lambda w: w.aos)
    return SchedulePlan(scheduled=scheduled, dropped=dropped)


def schedule_cpsat(
    opportunities: Iterable[ContactWindow],
    stations: Iterable[GroundStation],
    priorities: Optional[Mapping[str, float]] = None,
    provider_costs: Optional[Mapping[str, float]] = None,
    setup_teardown_s: float = DEFAULT_SETUP_TEARDOWN_S,
    max_contacts_per_satellite: Optional[int] = None,
    solver_time_limit_s: float = 30.0,
) -> SchedulePlan:
    """CP-SAT based optimal scheduler (alternative to greedy).

    Uses the same value model and StationLedger conflict rules as the greedy
    version so plans are directly comparable. Finds a globally optimal
    assignment (subject to the model) using Google OR-Tools CP-SAT.

    Falls back to a clear ImportError if ortools is not installed.
    """
    if cp_model is None:
        raise ImportError(
            "ortools is required for schedule_cpsat. "
            "pip install ortools"
        )

    priorities = priorities or {}
    provider_costs = provider_costs or {}
    stations_by_name = {s.name: s for s in stations}
    buffer = timedelta(seconds=setup_teardown_s)

    opps = list(opportunities)
    if not opps:
        return SchedulePlan(scheduled=[], dropped=[])

    # Precompute values and providers
    values: list[float] = []
    providers: list[str] = []
    for w in opps:
        station = stations_by_name.get(w.station)
        prov = station.provider if station else "unknown"
        prio = priorities.get(w.satellite, 1.0)
        cost = provider_costs.get(prov, 0.0)
        values.append(contact_value(w, prio, cost))
        providers.append(prov)

    # Group opps by station for conflict detection
    by_station: dict[str, list[int]] = {}
    for i, w in enumerate(opps):
        by_station.setdefault(w.station, []).append(i)

    # Identify conflicting pairs (same station, insufficient buffer gap)
    conflicts: list[tuple[int, int]] = []
    for station_opp_indices in by_station.values():
        for ii in range(len(station_opp_indices)):
            for jj in range(ii + 1, len(station_opp_indices)):
                i = station_opp_indices[ii]
                j = station_opp_indices[jj]
                wi, wj = opps[i], opps[j]
                if not (
                    (wi.los + buffer <= wj.aos) or (wj.los + buffer <= wi.aos)
                ):
                    conflicts.append((i, j))

    # Group by satellite for cardinality constraints
    by_sat: dict[str, list[int]] = {}
    for i, w in enumerate(opps):
        by_sat.setdefault(w.satellite, []).append(i)

    # Build CP-SAT model
    model = cp_model.CpModel()

    x = [model.NewBoolVar(f"x_{i}") for i in range(len(opps))]

    # Objective: maximize total value
    model.Maximize(sum(values[i] * x[i] for i in range(len(opps))))

    # Conflict constraints (no two conflicting on same station)
    for i, j in conflicts:
        model.Add(x[i] + x[j] <= 1)

    # Per-satellite max cardinality
    if max_contacts_per_satellite is not None:
        for sat_indices in by_sat.values():
            if len(sat_indices) > max_contacts_per_satellite:
                model.Add(sum(x[k] for k in sat_indices) <= max_contacts_per_satellite)

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_time_limit_s
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Degenerate case: fall back to nothing (or could raise)
        return SchedulePlan(scheduled=[], dropped=opps)

    scheduled: list[ScheduledContact] = []
    dropped: list[ContactWindow] = []

    for i, w in enumerate(opps):
        if solver.Value(x[i]) == 1:
            scheduled.append(
                ScheduledContact(window=w, provider=providers[i], value=values[i])
            )
        else:
            dropped.append(w)

    scheduled.sort(key=lambda c: c.window.aos)
    dropped.sort(key=lambda w: w.aos)
    return SchedulePlan(scheduled=scheduled, dropped=dropped)
