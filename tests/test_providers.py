"""Tests for provider adapters.

Covers the core interface contract (used by Reconciler), MockProviderAdapter,
and the live adapter stubs/skeletons.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import (
    AwsGroundStationAdapter,
    Booking,
    ContactOutcome,
    GroundStation,
    KsatAdapter,
    MockProviderAdapter,
    ProviderAdapter,
)
from orchestrator.domain import ContactWindow

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def window(station: str, start_min: int = 0, dur_min: int = 8) -> ContactWindow:
    aos = T0 + timedelta(minutes=start_min)
    los = aos + timedelta(minutes=dur_min)
    return ContactWindow(
        satellite="TEST-SAT",
        station=station,
        aos=aos,
        tca=aos + timedelta(minutes=dur_min / 2),
        los=los,
        peak_elevation_deg=45.0,
        aos_azimuth_deg=0.0,
        los_azimuth_deg=180.0,
        duration_s=dur_min * 60.0,
    )


def test_mock_provider_adapter_basic_flow():
    adapter = MockProviderAdapter("mock-test", failure_rate=0.0, seed=42)
    w = window("STATION-1")

    booking = adapter.book(w)
    assert isinstance(booking, Booking)
    assert booking.provider == "mock-test"
    assert booking.window is w
    assert booking.id.startswith("mock-test-")

    outcome = adapter.poll(booking)
    assert isinstance(outcome, ContactOutcome)
    assert outcome.succeeded is True
    assert outcome.detail == "ok"

    # Cancel is no-op
    adapter.cancel(booking)


def test_mock_provider_adapter_outages_and_failures():
    outage_start = T0 + timedelta(minutes=5)
    outage_end = T0 + timedelta(minutes=15)
    adapter = MockProviderAdapter(
        "mock-fail",
        failure_rate=1.0,
        outages=[("STATION-OUT", outage_start, outage_end)],
        seed=1,
    )

    # Normal window -> link failure
    w1 = window("STATION-1", 0)
    booking1 = adapter.book(w1)
    out1 = adapter.poll(booking1)
    assert out1.succeeded is False
    assert out1.detail == "link failure"

    # Overlap outage
    w2 = window("STATION-OUT", 10)
    booking2 = adapter.book(w2)
    out2 = adapter.poll(booking2)
    assert out2.succeeded is False
    assert "station outage" in out2.detail


def test_provider_adapter_protocol_is_satisfied_by_mock():
    adapter = MockProviderAdapter("proto-test")
    assert isinstance(adapter, ProviderAdapter)  # runtime_checkable


def test_aws_ground_station_adapter_requires_boto3(monkeypatch):
    # Simulate missing boto3
    monkeypatch.setattr("orchestrator.providers.boto3", None)
    with pytest.raises(ImportError, match="boto3 is required"):
        AwsGroundStationAdapter()


@patch("orchestrator.providers.boto3")
def test_aws_ground_station_adapter_book_poll_cancel_mocked(mock_boto3):
    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_boto3.Session.return_value = mock_session

    # Simulate successful reserve
    mock_client.reserve_contact.return_value = {"contactId": "aws-12345"}

    adapter = AwsGroundStationAdapter(
        satellite_arn="arn:aws:groundstation:us-east-1:123:satellite/abc",
        mission_profile_arn="arn:aws:groundstation:us-east-1:123:mission-profile/def",
        ground_station_map={"STATION-1": "Ohio 1"},
    )

    w = window("STATION-1")
    booking = adapter.book(w)
    assert booking.id == "aws-12345"
    assert booking.provider == "aws-ground-station"

    mock_client.reserve_contact.assert_called_once()

    # Poll success
    mock_client.describe_contact.return_value = {"contactStatus": "COMPLETED"}
    outcome = adapter.poll(booking)
    assert outcome.succeeded is True
    assert outcome.detail == "COMPLETED"

    # Poll failure
    mock_client.describe_contact.return_value = {
        "contactStatus": "FAILED",
        "errorMessage": "link lost",
    }
    outcome = adapter.poll(booking)
    assert outcome.succeeded is False
    assert "link lost" in outcome.detail

    # Cancel
    adapter.cancel(booking)
    mock_client.cancel_contact.assert_called_once_with(contactId="aws-12345")


def test_ksat_adapter_stub_raises():
    adapter = KsatAdapter()
    w = window("STATION-1")

    with pytest.raises(NotImplementedError, match="KSAT live adapter not implemented"):
        adapter.book(w)

    with pytest.raises(NotImplementedError):
        adapter.poll(Booking("id", "ksat", w))

    with pytest.raises(NotImplementedError):
        adapter.cancel(Booking("id", "ksat", w))


@patch("orchestrator.providers.boto3")
def test_adapters_can_be_used_in_dict_like_reconciler_expects(mock_boto3):
    # The reconciler takes Mapping[str, ProviderAdapter]
    mock_boto3.client.return_value = MagicMock()
    adapters = {
        "mock": MockProviderAdapter("mock"),
        "aws": AwsGroundStationAdapter(
            satellite_arn="fake",
            mission_profile_arn="fake",
            ground_station_map={},
        ),
    }
    assert "mock" in adapters
    assert isinstance(adapters["mock"], ProviderAdapter)
    assert isinstance(adapters["aws"], ProviderAdapter)
