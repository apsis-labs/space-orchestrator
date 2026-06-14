"""The visibility engine -- the foundation everything else consumes.

Given a satellite (as a Skyfield EarthSatellite) and a ground station, compute
the windows during which the satellite clears the station's elevation mask.
These ContactWindows are the raw "opportunities" the scheduler later allocates.

This is pure, deterministic orbital mechanics: SGP4 propagation via Skyfield's
`find_events`, which returns rise (0), culminate (1), and set (2) events. We
group those into passes and enrich each with peak elevation and azimuths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from skyfield.api import EarthSatellite, load, wgs84

from .domain import ContactWindow, GroundStation

_TS = load.timescale()


def compute_passes(
    satellite: EarthSatellite,
    station: GroundStation,
    start: datetime,
    end: datetime,
    min_elevation_deg: Optional[float] = None,
) -> list[ContactWindow]:
    """All passes of `satellite` over `station` in [start, end] (UTC, tz-aware)."""
    min_el = station.min_elevation_deg if min_elevation_deg is None else min_elevation_deg
    topos = wgs84.latlon(station.latitude_deg, station.longitude_deg, station.elevation_m)
    difference = satellite - topos

    t0 = _TS.from_datetime(start)
    t1 = _TS.from_datetime(end)
    times, events = satellite.find_events(topos, t0, t1, altitude_degrees=min_el)

    passes: list[ContactWindow] = []
    pending: dict = {}

    def elevation_az_at(t):
        alt, az, _ = difference.at(t).altaz()
        return alt.degrees, az.degrees

    for t, event in zip(times, events):
        if event == 0:  # rise / AOS
            pending = {"aos": t}
        elif event == 1:  # culminate / TCA
            if "aos" in pending:
                pending["tca"] = t
                pending["peak_elevation_deg"], _ = elevation_az_at(t)
        elif event == 2:  # set / LOS
            if "aos" in pending and "tca" in pending:
                aos_dt = pending["aos"].utc_datetime()
                los_dt = t.utc_datetime()
                _, aos_az = elevation_az_at(pending["aos"])
                _, los_az = elevation_az_at(t)
                passes.append(
                    ContactWindow(
                        satellite=satellite.name,
                        station=station.name,
                        aos=aos_dt,
                        tca=pending["tca"].utc_datetime(),
                        los=los_dt,
                        peak_elevation_deg=pending["peak_elevation_deg"],
                        aos_azimuth_deg=aos_az,
                        los_azimuth_deg=los_az,
                        duration_s=(los_dt - aos_dt).total_seconds(),
                    )
                )
            pending = {}

    return passes


def compute_all_opportunities(
    satellites: Iterable[EarthSatellite],
    stations: Iterable[GroundStation],
    start: datetime,
    end: datetime,
) -> list[ContactWindow]:
    """Cartesian sweep: every satellite against every station, sorted by AOS.

    This is the full opportunity set the scheduler optimizes over.
    """
    opportunities: list[ContactWindow] = []
    stations = list(stations)
    for sat in satellites:
        for station in stations:
            opportunities.extend(compute_passes(sat, station, start, end))
    opportunities.sort(key=lambda w: w.aos)
    return opportunities
