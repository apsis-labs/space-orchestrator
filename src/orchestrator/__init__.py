"""space-orchestrator: a vendor-neutral contact scheduler for satellite fleets.

Build order (the spine):
    visibility  ->  scheduler  ->  reconciler/failover  ->  provider adapters

This package currently implements the first stage: the visibility engine.
"""

from .domain import ContactWindow, GroundStation
from .tle import load_satellites_from_celestrak, load_satellites_from_file
from .visibility import compute_all_opportunities, compute_passes

__all__ = [
    "ContactWindow",
    "GroundStation",
    "load_satellites_from_file",
    "load_satellites_from_celestrak",
    "compute_passes",
    "compute_all_opportunities",
]
