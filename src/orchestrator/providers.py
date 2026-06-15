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

Live adapters (AwsGroundStationAdapter first) are drop-in replacements for the
mock and require only the provider-specific configuration (ARNs, credentials,
station name mapping).
"""

from __future__ import annotations

import functools
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

from .domain import ContactWindow
from .exceptions import BookingError, PollError, ProviderUnavailableError

_log = logging.getLogger("orchestrator.providers")

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = Exception  # type: ignore[misc,assignment]
    ClientError = Exception  # type: ignore[misc,assignment]

T = TypeVar("T")


def with_retry(
    max_attempts: int = 3,
    base_delay_s: float = 1.0,
    max_delay_s: float = 30.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (ProviderUnavailableError,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for retrying transient provider failures with exponential backoff."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = base_delay_s
            last_exception: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts - 1:
                        _log.warning(
                            "retrying after transient error",
                            extra={
                                "attempt": attempt + 1,
                                "max_attempts": max_attempts,
                                "delay_s": min(delay, max_delay_s),
                                "error": str(exc),
                            },
                        )
                        time.sleep(min(delay, max_delay_s))
                        delay *= backoff_factor
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


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


@dataclass
class AwsGroundStationAdapter:
    """Production-ready live adapter for AWS Ground Station (requires `boto3`).

    Implements the exact ProviderAdapter seam so the rest of the system
    (reconciler, etc.) is completely unaware of AWS specifics.

    Configuration (provide via constructor or AwsGroundStationAdapter.from_config()):
    - satellite_arn: ARN of your onboarded satellite.
    - mission_profile_arn: ARN of a pre-configured mission profile
      (includes configs for antenna, dataflow, etc.).
    - ground_station_map: your station.name -> AWS ground station name
      (e.g. {"FAIRBANKS": "Alaska 1", "OHIO": "Ohio 1"}).
    - region_name, profile_name: standard boto3 options.

    Behavior:
    - book(): direct reserve_contact (supports Workflow 2 in AWS docs).
    - poll(): describe_contact + status mapping to succeeded/failed.
      Intermediate states (SCHEDULING etc.) return succeeded=False with detail.
    - cancel(): best-effort cancel_contact.

    Prerequisites in AWS:
    - Satellite onboarded with ephemeris.
    - Mission profile + data delivery (S3 or endpoint) configured.
    - Appropriate IAM permissions for groundstation:ReserveContact etc.

    See AWS docs for full onboarding. This adapter does *not* perform
    pre-scheduling availability checks (use ListContacts if you need that
    before calling the orchestrator).
    """

    name: str = "aws-ground-station"
    satellite_arn: str = ""
    mission_profile_arn: str = ""
    ground_station_map: dict[str, str] = field(default_factory=dict)
    region_name: str | None = None
    profile_name: str | None = None
    _client: Any = field(init=False, repr=False)

    @classmethod
    def from_config(
        cls,
        satellite_arn: str,
        mission_profile_arn: str,
        ground_station_map: dict[str, str],
        region_name: str | None = None,
        profile_name: str | None = None,
        name: str = "aws-ground-station",
    ) -> "AwsGroundStationAdapter":
        """Convenience constructor with validation."""
        if not satellite_arn or not mission_profile_arn:
            raise ValueError("satellite_arn and mission_profile_arn are required")
        if not ground_station_map:
            raise ValueError("ground_station_map is required (station name -> AWS GS name)")
        return cls(
            name=name,
            satellite_arn=satellite_arn,
            mission_profile_arn=mission_profile_arn,
            ground_station_map=ground_station_map,
            region_name=region_name,
            profile_name=profile_name,
        )

    def __post_init__(self) -> None:
        if boto3 is None:
            raise ImportError(
                "boto3 is required for AwsGroundStationAdapter. "
                "pip install boto3"
            )
        session_kwargs = {}
        if self.profile_name:
            session_kwargs["profile_name"] = self.profile_name
        session = boto3.Session(**session_kwargs)
        self._client = session.client("groundstation", region_name=self.region_name)

        # Lightweight validation
        if not self.satellite_arn or not self.mission_profile_arn:
            # Allow partial init for tests/mocks; real use should provide them
            pass
        if not self.ground_station_map:
            pass

    def _get_aws_ground_station(self, our_station: str) -> str:
        return self.ground_station_map.get(our_station, our_station)

    @with_retry(max_attempts=3, retryable_exceptions=(ProviderUnavailableError,))
    def book(self, window: ContactWindow) -> Booking:
        gs = self._get_aws_ground_station(window.station)
        _log.debug(
            "reserving AWS contact",
            extra={
                "satellite": window.satellite,
                "station": window.station,
                "aws_ground_station": gs,
            },
        )
        try:
            resp = self._client.reserve_contact(
                satelliteArn=self.satellite_arn,
                missionProfileArn=self.mission_profile_arn,
                groundStation=gs,
                startTime=window.aos,
                endTime=window.los,
            )
            contact_id: str = resp["contactId"]
            _log.info(
                "AWS contact reserved",
                extra={"contact_id": contact_id, "station": window.station},
            )
            return Booking(id=contact_id, provider=self.name, window=window)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            _log.warning(
                "AWS API error",
                extra={"error_code": error_code, "station": window.station},
            )
            if error_code in ("ServiceUnavailable", "Throttling", "RequestLimitExceeded"):
                raise ProviderUnavailableError(
                    f"AWS transient error: {error_code}"
                ) from exc
            raise BookingError(
                self.name,
                f"reserve_contact failed: {exc}",
                cause=exc,
            ) from exc
        except BotoCoreError as exc:
            _log.warning("AWS connection error", extra={"error": str(exc)})
            raise ProviderUnavailableError(f"AWS connection error: {exc}") from exc

    def poll(self, booking: Booking) -> ContactOutcome:
        _log.debug("polling AWS contact", extra={"contact_id": booking.id})
        try:
            resp = self._client.describe_contact(contactId=booking.id)
            status: str = resp.get("contactStatus", "UNKNOWN")
            error: str = resp.get("errorMessage", "")
            detail = error or status

            # Terminal success (antenna side)
            if status in {"COMPLETED", "PASSED"}:
                _log.debug("contact succeeded", extra={"contact_id": booking.id})
                return ContactOutcome(True, detail)
            # Terminal failure
            if status in {
                "FAILED",
                "AWS_FAILED",
                "CANCELLED",
                "AWS_CANCELLED",
                "FAILED_TO_SCHEDULE",
                "REJECTED",
            }:
                _log.warning(
                    "contact failed",
                    extra={"contact_id": booking.id, "status": status, "error": error},
                )
                return ContactOutcome(False, detail)
            # In progress / still actionable
            return ContactOutcome(False, f"status={status}")
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            _log.warning(
                "poll API error",
                extra={"contact_id": booking.id, "error_code": error_code},
            )
            return ContactOutcome(False, f"describe_contact error: {error_code}")
        except BotoCoreError as exc:
            _log.warning(
                "poll connection error",
                extra={"contact_id": booking.id, "error": str(exc)},
            )
            return ContactOutcome(False, f"describe_contact error: {exc}")

    def cancel(self, booking: Booking) -> None:
        _log.debug("cancelling AWS contact", extra={"contact_id": booking.id})
        try:
            self._client.cancel_contact(contactId=booking.id)
            _log.info("contact cancelled", extra={"contact_id": booking.id})
        except (ClientError, BotoCoreError) as exc:
            # Best effort; the reconciler treats this as non-fatal
            _log.warning(
                "cancel failed (non-fatal)",
                extra={"contact_id": booking.id, "error": str(exc)},
            )


@dataclass
class KsatAdapter:
    """Extension point for KSAT ground station integration.

    This is a stub adapter that raises NotImplementedError. To use KSAT
    ground stations in production, you need to implement this adapter
    with your KSAT API credentials.

    See examples/custom_provider.py for a complete implementation guide.

    For testing without KSAT API access, use MockProviderAdapter:
        adapters = {"ksat": MockProviderAdapter("ksat", failure_rate=0.1)}
    """

    name: str = "ksat"

    def book(self, window: ContactWindow) -> Booking:
        raise NotImplementedError(
            "KsatAdapter is an extension point for KSAT API integration. "
            "See examples/custom_provider.py for implementation guide. "
            "For testing, use MockProviderAdapter instead."
        )

    def poll(self, booking: Booking) -> ContactOutcome:
        raise NotImplementedError(
            "KsatAdapter.poll() not implemented. "
            "See examples/custom_provider.py for implementation guide."
        )

    def cancel(self, booking: Booking) -> None:
        raise NotImplementedError(
            "KsatAdapter.cancel() not implemented. "
            "See examples/custom_provider.py for implementation guide."
        )


@dataclass
class LeafSpaceAdapter:
    """Extension point for Leaf Space ground station integration.

    This is a stub adapter that raises NotImplementedError. To use Leaf Space
    ground stations in production, you need to implement this adapter
    with your Leaf Space API credentials.

    See examples/custom_provider.py for a complete implementation guide.

    For testing without Leaf Space API access, use MockProviderAdapter:
        adapters = {"leaf-space": MockProviderAdapter("leaf-space", failure_rate=0.1)}
    """

    name: str = "leaf-space"

    def book(self, window: ContactWindow) -> Booking:
        raise NotImplementedError(
            "LeafSpaceAdapter is an extension point for Leaf Space API integration. "
            "See examples/custom_provider.py for implementation guide. "
            "For testing, use MockProviderAdapter instead."
        )

    def poll(self, booking: Booking) -> ContactOutcome:
        raise NotImplementedError(
            "LeafSpaceAdapter.poll() not implemented. "
            "See examples/custom_provider.py for implementation guide."
        )

    def cancel(self, booking: Booking) -> None:
        raise NotImplementedError(
            "LeafSpaceAdapter.cancel() not implemented. "
            "See examples/custom_provider.py for implementation guide."
        )
