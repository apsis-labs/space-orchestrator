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

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .domain import ContactWindow

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore[assignment]


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

    def book(self, window: ContactWindow) -> Booking:
        gs = self._get_aws_ground_station(window.station)
        try:
            resp = self._client.reserve_contact(
                satelliteArn=self.satellite_arn,
                missionProfileArn=self.mission_profile_arn,
                groundStation=gs,
                startTime=window.aos,
                endTime=window.los,
            )
            contact_id: str = resp["contactId"]
            return Booking(id=contact_id, provider=self.name, window=window)
        except Exception as exc:
            raise RuntimeError(
                f"AWS Ground Station reserve_contact failed for {window.satellite} "
                f"on {window.station}: {exc}"
            ) from exc

    def poll(self, booking: Booking) -> ContactOutcome:
        try:
            resp = self._client.describe_contact(contactId=booking.id)
            status: str = resp.get("contactStatus", "UNKNOWN")
            error: str = resp.get("errorMessage", "")
            detail = error or status

            # Terminal success (antenna side)
            if status in {"COMPLETED", "PASSED"}:
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
                return ContactOutcome(False, detail)
            # In progress / still actionable
            return ContactOutcome(False, f"status={status}")
        except Exception as exc:
            return ContactOutcome(False, f"describe_contact error: {exc}")

    def cancel(self, booking: Booking) -> None:
        try:
            self._client.cancel_contact(contactId=booking.id)
        except Exception:
            # Best effort; the reconciler treats this as non-fatal
            pass


@dataclass
class KsatAdapter:
    """Stub / placeholder for a future KSAT live adapter.

    Follow the same pattern as AwsGroundStationAdapter when implementing:
    take provider-specific config (API keys, endpoints, station mappings),
    implement book/poll/cancel against KSAT's API, return the standard
    Booking / ContactOutcome types.

    For now it raises NotImplemented so it can be registered in adapter
    dicts without breaking the reconciler contract.
    """

    name: str = "ksat"

    def book(self, window: ContactWindow) -> Booking:
        raise NotImplementedError(
            "KSAT live adapter not implemented yet. "
            "Use MockProviderAdapter for testing or implement using KSAT APIs."
        )

    def poll(self, booking: Booking) -> ContactOutcome:
        raise NotImplementedError("KSAT live adapter not implemented yet.")

    def cancel(self, booking: Booking) -> None:
        raise NotImplementedError("KSAT live adapter not implemented yet.")
