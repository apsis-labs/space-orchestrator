"""space-orchestrator: a vendor-neutral contact scheduler for satellite fleets.

Build order (the spine):
    visibility  ->  scheduler (greedy + CP-SAT)  ->  reconciler/failover
    ->  provider adapters (mock + live AWS + stubs)  ->  observability

This package implements the full spine: visibility engine, schedulers,
failover control loop with provider adapters (mock + AWS Ground Station),
and observability (dashboard + Prometheus).
"""

from .domain import ContactWindow, GroundStation
from .exceptions import (
    BookingError,
    ConfigurationError,
    OrchestratorError,
    PollError,
    ProviderError,
    ProviderUnavailableError,
    TLEError,
    ValidationError,
    VisibilityError,
)
from .logging import configure_logging, get_logger
from .observability import (
    Metrics,
    ProviderStats,
    compute_metrics,
    cleanup_old_reports,
    format_report_for_narration,
    format_trend_for_narration,
    load_report,
    prometheus_metrics,
    render_fleet_snapshot,
    render_html,
    render_rich_dashboard,
    render_trend_html,
    save_report,
    write_dashboard,
)
from .providers import (
    AwsGroundStationAdapter,
    Booking,
    ContactOutcome,
    KsatAdapter,
    LeafSpaceAdapter,
    MockProviderAdapter,
    ProviderAdapter,
)
from .reconciler import Attempt, AttemptState, ReconcileReport, Reconciler
from .scheduler import (
    SchedulePlan,
    ScheduledContact,
    contact_value,
    pass_quality,
    schedule_cpsat,
    schedule_greedy,
)
from .tle import load_satellites_from_celestrak, load_satellites_from_file
from .visibility import (
    compute_all_opportunities,
    compute_passes,
    satellite_position,
    satellite_positions,
    visibility_footprint,
)

__all__ = [
    # Exceptions
    "OrchestratorError",
    "ProviderError",
    "BookingError",
    "PollError",
    "ProviderUnavailableError",
    "ConfigurationError",
    "ValidationError",
    "TLEError",
    "VisibilityError",
    # Logging
    "configure_logging",
    "get_logger",
    # Domain
    "ContactWindow",
    "GroundStation",
    "load_satellites_from_file",
    "load_satellites_from_celestrak",
    "compute_passes",
    "compute_all_opportunities",
    "satellite_position",
    "satellite_positions",
    "visibility_footprint",
    "visibility_footprint",
    "schedule_greedy",
    "schedule_cpsat",
    "SchedulePlan",
    "ScheduledContact",
    "pass_quality",
    "contact_value",
    "ProviderAdapter",
    "MockProviderAdapter",
    "AwsGroundStationAdapter",
    "KsatAdapter",
    "LeafSpaceAdapter",
    "Booking",
    "ContactOutcome",
    "Reconciler",
    "ReconcileReport",
    "Attempt",
    "AttemptState",
    "compute_metrics",
    "prometheus_metrics",
    "render_html",
    "render_trend_html",
    "save_report",
    "load_report",
    "cleanup_old_reports",
    "format_report_for_narration",
    "format_trend_for_narration",
    "render_fleet_snapshot",
    "render_rich_dashboard",
    "write_dashboard",
    "Metrics",
    "ProviderStats",
]
