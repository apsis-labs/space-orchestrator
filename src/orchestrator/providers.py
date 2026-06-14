"""Provider adapters: the seam between the orchestrator and ground networks.

Every ground network (KSAT, Leaf Space, AWS Ground Station, an owned antenna)
is reached through one small interface. The reconciler talks only to this
interface, so it never knows or cares which provider it's driving -- that's the
vendor-neutral abstraction. It's also the real-vs-simulated boundary: swap the
mock for a live adapter and nothing upstream changes.

A real adapter would `book` antenna time against the provider's API and `poll`
for the contact's outcome after the pass. The mock does the same shape, but
simulates outcomes with a seeded RNG so runs are deterministic and so we can
inject failures, weather aborts, and station outages on demand.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from .domain import ContactWindow


@dataclass(frozen=True)
class Booking:
    """A reservation of antenna time, returned by an adapter's `book`."""

    id: str
    provider: str
    window: ContactWindow


@dataclass(frozen=True)
class ContactOutcome:
    """The result of attempting a booked contact."""

    succeeded: bool
    detail: str = ""


@runtime_checkable
class ProviderAdapter(Protocol):
    """The interface every ground provider implements."""

    name: str

    def book(self, window: ContactWindow) -> Booking: ...

    def poll(self, booking: Booking) -> ContactOutcome: ...

    def cancel(self, booking: Booking) -> None: ...


@dataclass
class MockProviderAdapter:
    """A simulated provider for development, testing, and demos.

    Args:
        name: provider name (matches a station's `provider` field).
        failure_rate: probability in [0, 1] that any given contact fails.
        outages: list of (station_name, start, end) windows during which every
            contact on that station fails outright -- models a station drop.
        seed: RNG seed, so a given configuration always produces the same run.
    """

    name: str
    failure_rate: float = 0.0
    outages: list[tuple[str, datetime, datetime]] = field(default_factory=list)
    seed: int = 0
    _rng: random.Random = field(init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def book(self, window: ContactWindow) -> Booking:
        self._counter += 1
        return Booking(id=f"{self.name}-{self._counter:04d}", provider=self.name, window=window)

    def poll(self, booking: Booking) -> ContactOutcome:
        w = booking.window
        for station, start, end in self.outages:
            overlaps = w.station == station and not (w.los <= start or w.aos >= end)
            if overlaps:
                return ContactOutcome(False, f"station outage at {station}")
        if self._rng.random() < self.failure_rate:
            return ContactOutcome(False, "link failure")
        return ContactOutcome(True, "ok")

    def cancel(self, booking: Booking) -> None:
        return None
