"""Core domain types for the orchestrator.

These are intentionally small, frozen value objects. Everything downstream
(scheduler, reconciler, provider adapters) speaks in these terms, so the
domain stays decoupled from Skyfield and from any particular ground provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class GroundStation:
    """A single antenna location we can attempt contacts from.

    `min_elevation_deg` is the elevation mask: below this angle the horizon,
    buildings, or link budget make a contact unusable, so passes that never
    clear it are not opportunities at all.
    """

    name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float = 0.0
    min_elevation_deg: float = 10.0
    provider: str = "unknown"


@dataclass(frozen=True)
class ContactWindow:
    """A computed opportunity: when a satellite is visible from a station.

    AOS = acquisition of signal (rise above the mask)
    TCA = time of closest approach (culmination, peak elevation)
    LOS = loss of signal (set below the mask)

    Peak elevation is a cheap proxy for link quality: a 78-degree overhead
    pass is worth far more than a 12-degree scrape along the horizon.
    """

    satellite: str
    station: str
    aos: datetime
    tca: datetime
    los: datetime
    peak_elevation_deg: float
    aos_azimuth_deg: float
    los_azimuth_deg: float
    duration_s: float

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.duration_s)

    def __str__(self) -> str:
        return (
            f"{self.satellite:<14} @ {self.station:<10} "
            f"AOS {self.aos:%Y-%m-%d %H:%M:%S}Z  "
            f"peak {self.peak_elevation_deg:5.1f}deg  "
            f"dur {self.duration_s/60:4.1f}min  "
            f"az {self.aos_azimuth_deg:5.1f}->{self.los_azimuth_deg:5.1f}"
        )
