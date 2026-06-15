#!/usr/bin/env python3
"""Example: Implementing a custom provider adapter.

This example shows how to implement a ProviderAdapter for a new ground
station provider (e.g., KSAT, Leaf Space, or your own antennas).

The adapter must implement three methods:
- book(window) -> Booking: Reserve antenna time
- poll(booking) -> ContactOutcome: Check if contact succeeded
- cancel(booking) -> None: Best-effort cancellation

Run with: python examples/custom_provider.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from orchestrator import (
    GroundStation,
    Reconciler,
    schedule_greedy,
)
from orchestrator.domain import ContactWindow
from orchestrator.providers import Booking, ContactOutcome, ProviderAdapter
from orchestrator.visibility import compute_all_opportunities
from orchestrator.tle import load_satellites_from_file


# -----------------------------------------------------------------------------
# Step 1: Implement the ProviderAdapter protocol
# -----------------------------------------------------------------------------

@dataclass
class MyProviderAdapter:
    """Example adapter for a hypothetical ground station provider.

    Replace the API calls with your provider's actual API.
    """

    name: str = "my-provider"

    # Your provider's configuration
    api_key: str = ""
    api_base_url: str = "https://api.myprovider.example.com"

    # Internal state
    _client: Any = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        """Initialize the API client."""
        # In a real implementation, you'd set up your HTTP client here
        # Example with requests:
        # import requests
        # self._session = requests.Session()
        # self._session.headers["Authorization"] = f"Bearer {self.api_key}"
        pass

    def book(self, window: ContactWindow) -> Booking:
        """Reserve antenna time with the provider.

        Args:
            window: The contact window to book (has satellite, station,
                   aos, los, peak_elevation, etc.)

        Returns:
            A Booking object with a unique ID from the provider.

        Raises:
            BookingError: If booking fails permanently (invalid request, etc.)
            ProviderUnavailableError: If booking fails transiently (retry may help)
        """
        # In a real implementation:
        # response = self._session.post(
        #     f"{self.api_base_url}/contacts",
        #     json={
        #         "satellite": window.satellite,
        #         "ground_station": window.station,
        #         "start_time": window.aos.isoformat(),
        #         "end_time": window.los.isoformat(),
        #     }
        # )
        # response.raise_for_status()
        # contact_id = response.json()["contact_id"]

        # For this example, simulate a successful booking
        contact_id = f"{self.name}-{window.satellite}-{window.aos.timestamp():.0f}"
        print(f"  [BOOK] {window.satellite} @ {window.station}: {contact_id}")

        return Booking(id=contact_id, provider=self.name, window=window)

    def poll(self, booking: Booking) -> ContactOutcome:
        """Check the outcome of a booked contact.

        This is called after the contact's scheduled time to determine
        if it succeeded.

        Args:
            booking: The booking to check.

        Returns:
            ContactOutcome with succeeded=True/False and detail message.
        """
        # In a real implementation:
        # response = self._session.get(
        #     f"{self.api_base_url}/contacts/{booking.id}"
        # )
        # status = response.json()["status"]
        # if status == "COMPLETED":
        #     return ContactOutcome(True, "Data received")
        # elif status in ["FAILED", "CANCELLED"]:
        #     return ContactOutcome(False, response.json().get("error", status))
        # else:
        #     return ContactOutcome(False, f"In progress: {status}")

        # For this example, simulate success
        print(f"  [POLL] {booking.id}: succeeded")
        return ContactOutcome(succeeded=True, detail="Contact completed")

    def cancel(self, booking: Booking) -> None:
        """Cancel a booked contact (best-effort).

        This is called if we need to cancel a contact, e.g., when
        re-scheduling. Failures are logged but not raised.
        """
        # In a real implementation:
        # try:
        #     self._session.delete(f"{self.api_base_url}/contacts/{booking.id}")
        # except Exception as e:
        #     logger.warning(f"Cancel failed for {booking.id}: {e}")

        print(f"  [CANCEL] {booking.id}")


# Verify it satisfies the protocol
assert isinstance(MyProviderAdapter(), ProviderAdapter)


# -----------------------------------------------------------------------------
# Step 2: Use the adapter with the reconciler
# -----------------------------------------------------------------------------

def main() -> None:
    # Define stations using your provider
    stations = [
        GroundStation("MY-STATION-1", 52.0, 4.3, provider="my-provider"),
        GroundStation("MY-STATION-2", 35.6, 139.6, provider="my-provider"),
    ]

    # Load satellites
    satellites = load_satellites_from_file("data/sample_tle.txt")

    # Compute opportunities
    now = datetime.now(timezone.utc)
    opportunities = compute_all_opportunities(
        satellites, stations, now, now + timedelta(hours=12)
    )
    print(f"Found {len(opportunities)} opportunities")

    # Schedule
    plan = schedule_greedy(opportunities, stations)
    print(f"Scheduled {plan.scheduled_count} contacts\n")

    if plan.scheduled_count == 0:
        print("No contacts to book")
        return

    # Create your adapter
    adapter = MyProviderAdapter(
        name="my-provider",
        api_key="your-api-key-here",
    )

    # Run reconciliation
    reconciler = Reconciler(
        adapters={"my-provider": adapter},
        stations=stations,
        opportunities=opportunities,
        slo_target=0.95,
    )

    print("Booking contacts:")
    report = reconciler.run(plan)

    print(f"\nResults:")
    print(f"  Satisfied: {report.satisfied}/{report.planned}")
    print(f"  SLO met: {'Yes' if report.slo_met else 'No'}")


if __name__ == "__main__":
    main()
