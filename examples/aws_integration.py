#!/usr/bin/env python3
"""AWS Ground Station integration example.

This example shows how to configure the AwsGroundStationAdapter for
production use with AWS Ground Station.

Prerequisites:
1. AWS account with Ground Station access
2. Satellite onboarded with ephemeris
3. Mission profile configured
4. IAM permissions: groundstation:ReserveContact, DescribeContact, CancelContact

Run with: python examples/aws_integration.py
(Requires valid AWS credentials and ARNs)
"""

from datetime import datetime, timedelta, timezone
from orchestrator import (
    GroundStation,
    AwsGroundStationAdapter,
    MockProviderAdapter,
    Reconciler,
    load_satellites_from_file,
    schedule_greedy,
)
from orchestrator.visibility import compute_all_opportunities

# -----------------------------------------------------------------------------
# Configuration - Replace these with your actual values
# -----------------------------------------------------------------------------

# Your satellite ARN from AWS Ground Station console
SATELLITE_ARN = "arn:aws:groundstation:us-east-2:123456789012:satellite/my-satellite-id"

# Your mission profile ARN
MISSION_PROFILE_ARN = "arn:aws:groundstation:us-east-2:123456789012:mission-profile/my-profile-id"

# Map your station names to AWS ground station names
# Find these in the AWS Ground Station console under "Ground stations"
GROUND_STATION_MAP = {
    "FAIRBANKS": "Alaska 1",
    "OHIO": "Ohio 1",
    "OREGON": "Oregon 1",
}

# AWS region where your Ground Station resources are
AWS_REGION = "us-east-2"

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

# Define your ground stations (must match keys in GROUND_STATION_MAP)
stations = [
    GroundStation("FAIRBANKS", 64.8, -147.7, provider="aws-ground-station"),
    GroundStation("OHIO", 40.0, -82.9, provider="aws-ground-station"),
]

# Create the AWS adapter
# This will use your default AWS credentials (~/.aws/credentials or env vars)
try:
    aws_adapter = AwsGroundStationAdapter.from_config(
        satellite_arn=SATELLITE_ARN,
        mission_profile_arn=MISSION_PROFILE_ARN,
        ground_station_map=GROUND_STATION_MAP,
        region_name=AWS_REGION,
    )
    print("AWS adapter configured successfully")
except ImportError:
    print("boto3 not installed. Install with: pip install space-orchestrator[aws]")
    exit(1)
except Exception as e:
    print(f"AWS adapter configuration failed: {e}")
    print("Using mock adapter for demonstration")
    aws_adapter = MockProviderAdapter("aws-ground-station", failure_rate=0.1)

# -----------------------------------------------------------------------------
# Schedule and Reconcile
# -----------------------------------------------------------------------------

# Load your satellite TLE (replace with your actual TLE file)
satellites = load_satellites_from_file("data/sample_tle.txt")

# Compute opportunities
now = datetime.now(timezone.utc)
opportunities = compute_all_opportunities(
    satellites, stations, now, now + timedelta(hours=24)
)
print(f"Found {len(opportunities)} opportunities")

# Schedule
plan = schedule_greedy(opportunities, stations)
print(f"Scheduled {plan.scheduled_count} contacts")

if plan.scheduled_count == 0:
    print("No contacts to book")
    exit(0)

# Run reconciliation
# In production, this will call AWS Ground Station APIs to book contacts
reconciler = Reconciler(
    adapters={"aws-ground-station": aws_adapter},
    stations=stations,
    opportunities=opportunities,
    slo_target=0.95,
)

print("\nBooking contacts via AWS Ground Station...")
report = reconciler.run(plan)

print(f"\nResults:")
print(f"  Booked: {report.satisfied}/{report.planned}")
print(f"  Yield: {report.achieved_yield:.1%}")
print(f"  SLO met: {'Yes' if report.slo_met else 'No'}")

# Print details of each booking
print("\nBooking details:")
for attempt in report.timeline():
    status = "OK" if attempt.state.value == "succeeded" else "FAILED"
    print(f"  [{status}] {attempt.window.satellite} @ {attempt.window.station}")
    print(f"         AOS: {attempt.window.aos}")
    print(f"         Booking ID: {attempt.booking.id}")
