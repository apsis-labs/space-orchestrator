"""The visibility engine -- the foundation everything else consumes.

Given a satellite (as a Skyfield EarthSatellite) and a ground station, compute
the windows during which the satellite clears the station's elevation mask.
These ContactWindows are the raw "opportunities" the scheduler later allocates.

Also provides continuous position sampling (`satellite_position` / `satellite_positions`)
for live visualizations (2D maps with ground tracks + visibility circles, 3D
Cesium scenes, etc.). The same SGP4 propagation powers both discrete passes and
continuous positions.

This is pure, deterministic orbital mechanics.
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


def satellite_position(
    satellite: EarthSatellite,
    time: datetime,
) -> dict:
    """Return the geodetic (lat, lon, elevation) position of the satellite at a specific UTC time.

    This is the continuous-sampling counterpart to the discrete pass computation.
    Essential for live visualizations:
    - 2D world maps: sub-satellite point + ground track
    - 3D (CesiumJS etc.): real-time orbiting positions + contact links
    - Footprint circles: combine with station elevation masks to show current visibility

    Returns a dict with:
        latitude_deg, longitude_deg, elevation_m, time
    """
    t = _TS.from_datetime(time)
    subpoint = wgs84.subpoint(satellite.at(t))
    return {
        "latitude_deg": subpoint.latitude.degrees,
        "longitude_deg": subpoint.longitude.degrees,
        "elevation_m": subpoint.elevation.m,
        "time": time,
    }


def satellite_positions(
    satellite: EarthSatellite,
    times: Iterable[datetime],
) -> list[dict]:
    """Batch version of satellite_position for efficiency.

    Use this to generate ground tracks or sample positions for 2D/3D renderers
    without paying repeated timescale overhead.
    """
    return [satellite_position(satellite, t) for t in times]


def visibility_footprint(
    station: GroundStation,
    satellite: EarthSatellite,
    time: datetime,
    mask_deg: float | None = None,
) -> dict:
    """Compute the instantaneous visibility footprint for a station-satellite pair.

    Returns the sub-satellite point plus a rough great-circle radius (in degrees)
    for the visibility circle at the given mask. Useful for live 2D maps.

    This is approximate (assumes spherical Earth); good enough for visualization.
    """
    pos = satellite_position(satellite, time)
    mask = mask_deg if mask_deg is not None else station.min_elevation_deg

    # Rough Earth-central angle for visibility at given elevation mask
    # Using simple geometric approximation (good for viz, not precision navigation)
    import math
    earth_radius = 6371.0  # km
    sat_alt = pos["elevation_m"] / 1000.0  # km
    # Angle from station to horizon to sat
    gamma = math.acos( (earth_radius / (earth_radius + sat_alt)) * math.cos(math.radians(mask)) )
    earth_angle_deg = math.degrees(gamma) - mask  # very rough; sufficient for map circles

    return {
        "sub_latitude_deg": pos["latitude_deg"],
        "sub_longitude_deg": pos["longitude_deg"],
        "visibility_radius_deg": max(0.0, earth_angle_deg),
        "mask_deg": mask,
        "time": time,
    }
