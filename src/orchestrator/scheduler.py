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

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Mapping, Optional

from .domain import ContactWindow, GroundStation

#: Default slew/configure gap an antenna needs between consecutive contacts.
DEFAULT_SETUP_TEARDOWN_S = 30.0


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
    buffer = timedelta(seconds=setup_teardown_s)

    # Score every opportunity, then rank by value (desc), AOS (asc) for stable order.
    scored: list[tuple[float, ContactWindow, str]] = []
    for w in opportunities:
        station = stations_by_name.get(w.station)
        provider = station.provider if station else "unknown"
        priority = priorities.get(w.satellite, 1.0)
        cost = provider_costs.get(provider, 0.0)
        scored.append((contact_value(w, priority, cost), w, provider))
    scored.sort(key=lambda t: (-t[0], t[1].aos))

    booked: dict[str, list[tuple]] = {}      # station -> [(aos, los), ...]
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

        intervals = booked.setdefault(w.station, [])
        # Compatible with an existing booking iff there's a buffer-sized gap on
        # one side; conflict if that holds for none of them.
        compatible = all(
            (w.los + buffer <= start) or (w.aos - buffer >= end)
            for (start, end) in intervals
        )
        if not compatible:
            dropped.append(w)
            continue

        intervals.append((w.aos, w.los))
        scheduled.append(ScheduledContact(window=w, provider=provider, value=value))
        per_sat[w.satellite] = per_sat.get(w.satellite, 0) + 1

    scheduled.sort(key=lambda c: c.window.aos)
    dropped.sort(key=lambda w: w.aos)
    return SchedulePlan(scheduled=scheduled, dropped=dropped)