"""The reconciler -- the SRE heart of the orchestrator.

A scheduler produces a *desired* plan. The world then disagrees with it: passes
fail, weather aborts, stations drop. The reconciler is the control loop that
closes that gap. It books each scheduled contact through a provider adapter,
polls the outcome, and when a contact fails it re-schedules the lost downlink
onto the next-best future opportunity -- preferring a different provider for
resilience -- until the demand is met or the recovery budget is exhausted.

This is a reconciliation loop in the Kubernetes-controller sense: compare
desired state (the plan) against actual state (outcomes) and act to converge.
Everything is driven through the provider-adapter interface, so the same loop
runs against simulated and live ground segments unchanged.

Reliability is made explicit: a yield SLO sets how many contacts are allowed to
go unrecovered (the error budget), and the report says whether the budget held.
"""

from __future__ import annotations

import heapq
import logging
import math
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Iterable, Mapping, Optional

from .domain import ContactWindow, GroundStation

_log = logging.getLogger("orchestrator.reconciler")
from .exceptions import ConfigurationError, ValidationError
from .providers import Booking, ProviderAdapter
from .scheduler import DEFAULT_SETUP_TEARDOWN_S, SchedulePlan, StationLedger, contact_value


class AttemptState(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class Attempt:
    """One execution of a contact: an original booking or a recovery of one."""

    origin_id: int          # which planned contact this attempt serves
    attempt: int            # 0 = original, 1+ = recovery depth
    window: ContactWindow
    provider: str
    booking: Booking
    state: AttemptState
    detail: str = ""
    recovers: Optional[ContactWindow] = None  # the failed window this replaces


@dataclass
class ReconcileReport:
    """Outcome of a reconciliation run, framed in reliability terms."""

    attempts: list[Attempt]
    planned: int                 # number of originally scheduled contacts (demands)
    satisfied: int               # demands with at least one successful attempt
    slo_target: float

    @property
    def unrecovered(self) -> int:
        return self.planned - self.satisfied

    @property
    def recoveries_booked(self) -> int:
        return sum(1 for a in self.attempts if a.attempt > 0)

    @property
    def recovered_demands(self) -> int:
        """Demands whose original failed but a later attempt succeeded."""
        first_success = {}
        for a in sorted(self.attempts, key=lambda a: (a.origin_id, a.attempt)):
            if a.state is AttemptState.SUCCEEDED and a.origin_id not in first_success:
                first_success[a.origin_id] = a.attempt
        return sum(1 for depth in first_success.values() if depth > 0)

    @property
    def error_budget(self) -> int:
        """How many unrecovered failures the SLO tolerates over this plan."""
        return math.floor((1.0 - self.slo_target) * self.planned)

    @property
    def achieved_yield(self) -> float:
        return self.satisfied / self.planned if self.planned else 1.0

    @property
    def slo_met(self) -> bool:
        return self.unrecovered <= self.error_budget

    def timeline(self) -> list[Attempt]:
        return sorted(self.attempts, key=lambda a: a.window.aos)


class Reconciler:
    """Drives a plan to completion, recovering failures along the way."""

    def __init__(
        self,
        adapters: Mapping[str, ProviderAdapter],
        stations: Iterable[GroundStation],
        opportunities: Iterable[ContactWindow],
        priorities: Optional[Mapping[str, float]] = None,
        provider_costs: Optional[Mapping[str, float]] = None,
        slo_target: float = 0.95,
        max_recovery_attempts: int = 2,
        booking_lead_time_s: float = 60.0,
        setup_teardown_s: float = DEFAULT_SETUP_TEARDOWN_S,
        resilience_bonus: float = 0.1,
    ):
        # Validate configuration
        if not adapters:
            raise ConfigurationError("at least one adapter is required")
        if not 0.0 <= slo_target <= 1.0:
            raise ConfigurationError(f"slo_target must be in [0, 1], got {slo_target}")

        # Validate numeric parameters
        if max_recovery_attempts < 0:
            raise ValidationError(
                f"max_recovery_attempts must be >= 0, got {max_recovery_attempts}"
            )
        if booking_lead_time_s < 0:
            raise ValidationError(
                f"booking_lead_time_s must be >= 0, got {booking_lead_time_s}"
            )
        if setup_teardown_s < 0:
            raise ValidationError(
                f"setup_teardown_s must be >= 0, got {setup_teardown_s}"
            )

        self.adapters = dict(adapters)
        self.stations_by_name = {s.name: s for s in stations}
        self.opportunities = list(opportunities)
        self.priorities = priorities or {}
        self.provider_costs = provider_costs or {}
        self.slo_target = slo_target
        self.max_recovery_attempts = max_recovery_attempts
        self.lead = timedelta(seconds=booking_lead_time_s)
        self.buffer = timedelta(seconds=setup_teardown_s)
        self.resilience_bonus = resilience_bonus

    def _provider_of(self, station_name: str) -> str:
        station = self.stations_by_name.get(station_name)
        return station.provider if station else "unknown"

    def _adapter_for(self, provider: str) -> ProviderAdapter:
        try:
            return self.adapters[provider]
        except KeyError as exc:
            raise KeyError(f"no adapter registered for provider {provider!r}") from exc

    def _find_recovery(
        self, failed: ContactWindow, failed_provider: str, used: set[ContactWindow], ledger: StationLedger
    ) -> tuple[ContactWindow, str] | None:
        """Best future window for the same satellite on a free antenna.

        Uses the shared StationLedger so recovery choices respect the same
        non-overlap + buffer rule as the original schedule.
        """
        earliest = failed.los + self.lead
        candidates = []
        for w in self.opportunities:
            if w.satellite != failed.satellite or w in used or w.aos < earliest:
                continue
            if not ledger.is_free(w):
                continue
            provider = self._provider_of(w.station)
            value = contact_value(
                w, self.priorities.get(w.satellite, 1.0), self.provider_costs.get(provider, 0.0)
            )
            if provider != failed_provider:
                value += self.resilience_bonus  # prefer switching away from a bad provider
            candidates.append((value, w, provider))
        if not candidates:
            return None
        candidates.sort(key=lambda t: (-t[0], t[1].aos))  # best value, then recover soonest
        return candidates[0][1], candidates[0][2]

    def run(self, plan: SchedulePlan) -> ReconcileReport:
        _log.info(
            "starting reconciliation",
            extra={"planned": len(plan.scheduled), "slo_target": self.slo_target},
        )

        # Seed the shared station timeline from the (already conflict-free) plan.
        # Recoveries will consult and extend the same ledger.
        ledger = StationLedger(self.buffer)
        used: set[ContactWindow] = set()
        for c in plan.scheduled:
            ledger.claim(c.window)
            used.add(c.window)

        # A min-queue of executions ordered by AOS; recoveries get pushed in later.
        seq = 0
        queue: list[tuple] = []  # (aos, seq, origin_id, attempt, window, provider, recovers)
        for origin_id, c in enumerate(plan.scheduled):
            heapq.heappush(queue, (c.window.aos, seq, origin_id, 0, c.window, c.provider, None))
            seq += 1

        attempts: list[Attempt] = []
        while queue:
            aos, _, origin_id, depth, window, provider, recovers = heapq.heappop(queue)
            _log.debug(
                "booking contact",
                extra={
                    "origin_id": origin_id,
                    "attempt": depth,
                    "satellite": window.satellite,
                    "station": window.station,
                    "provider": provider,
                },
            )
            booking = self._adapter_for(provider).book(window)
            outcome = self._adapter_for(provider).poll(booking)

            if outcome.succeeded:
                attempts.append(
                    Attempt(
                        origin_id, depth, window, provider, booking,
                        AttemptState.SUCCEEDED, outcome.detail, recovers
                    )
                )
                continue

            _log.warning(
                "contact failed",
                extra={
                    "origin_id": origin_id,
                    "attempt": depth,
                    "satellite": window.satellite,
                    "station": window.station,
                    "provider": provider,
                    "detail": outcome.detail,
                },
            )
            attempts.append(
                Attempt(
                    origin_id, depth, window, provider, booking,
                    AttemptState.FAILED, outcome.detail, recovers
                )
            )

            if depth >= self.max_recovery_attempts:
                _log.debug(
                    "recovery budget exhausted",
                    extra={"origin_id": origin_id, "max_attempts": self.max_recovery_attempts},
                )
                continue  # recovery budget for this demand exhausted
            found = self._find_recovery(window, provider, used, ledger)
            if found is None:
                _log.debug(
                    "no recovery available",
                    extra={"origin_id": origin_id, "satellite": window.satellite},
                )
                continue  # nothing left to recover onto
            rec_window, rec_provider = found
            _log.info(
                "scheduling recovery",
                extra={
                    "origin_id": origin_id,
                    "recovery_station": rec_window.station,
                    "recovery_provider": rec_provider,
                },
            )
            used.add(rec_window)
            ledger.claim(rec_window)
            heapq.heappush(
                queue,
                (rec_window.aos, seq, origin_id, depth + 1, rec_window, rec_provider, window),
            )
            seq += 1

        satisfied = len({a.origin_id for a in attempts if a.state is AttemptState.SUCCEEDED})
        report = ReconcileReport(
            attempts=attempts,
            planned=len(plan.scheduled),
            satisfied=satisfied,
            slo_target=self.slo_target,
        )
        _log.info(
            "reconciliation complete",
            extra={
                "satisfied": report.satisfied,
                "planned": report.planned,
                "yield": report.achieved_yield,
                "slo_met": report.slo_met,
                "recoveries": report.recoveries_booked,
            },
        )
        return report
