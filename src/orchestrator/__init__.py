"""space-orchestrator: a vendor-neutral contact scheduler for satellite fleets.

Build order (the spine):
    visibility  ->  scheduler  ->  reconciler/failover  ->  provider adapters

This package currently implements the spine through the reconciler: visibility
engine, greedy scheduler, and the failover control loop with provider adapters.
"""

from .domain import ContactWindow, GroundStation
from .providers import (
    Booking,
    ContactOutcome,
    MockProviderAdapter,
    ProviderAdapter,
)
from .reconciler import Attempt, AttemptState, ReconcileReport, Reconciler
from .scheduler import (
    SchedulePlan,
    ScheduledContact,
    contact_value,
    pass_quality,
    schedule_greedy,
)
from .tle import load_satellites_from_celestrak, load_satellites_from_file
from .visibility import compute_all_opportunities, compute_passes

__all__ = [
    "ContactWindow",
    "GroundStation",
    "load_satellites_from_file",
    "load_satellites_from_celestrak",
    "compute_passes",
    "compute_all_opportunities",
    "schedule_greedy",
    "SchedulePlan",
    "ScheduledContact",
    "pass_quality",
    "contact_value",
    "ProviderAdapter",
    "MockProviderAdapter",
    "Booking",
    "ContactOutcome",
    "Reconciler",
    "ReconcileReport",
    "Attempt",
    "AttemptState",
]
