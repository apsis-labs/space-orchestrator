"""Load satellites from TLE data.

Two sources:

  * `load_satellites_from_file`  -- offline, from a bundled or cached TLE file.
  * `load_satellites_from_celestrak` -- live, from CelesTrak's GP API.

CelesTrak rate-limits and discourages scraping of the static files, so the
live path uses the gp.php query API and you should cache the result rather
than hammering it. In a sandbox without network egress to celestrak.org the
live path will fail by design -- use the bundled file there, and switch to
live in your own environment for current passes.
"""

from __future__ import annotations

import urllib.request
from typing import Optional

from skyfield.api import EarthSatellite, load

_TS = load.timescale()  # builtin timescale data; no network needed

CELESTRAK_GP = "https://celestrak.org/NORAD/elements/gp.php"


def _parse_3le(lines: list[str]) -> list[EarthSatellite]:
    """Parse a list of non-empty lines as 3LE (name/L1/L2) or bare 2LE blocks."""
    sats: list[EarthSatellite] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("1 ") and i + 1 < n and lines[i + 1].startswith("2 "):
            sats.append(EarthSatellite(line, lines[i + 1], "UNNAMED", _TS))
            i += 2
        elif i + 2 < n and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            sats.append(EarthSatellite(lines[i + 1], lines[i + 2], line.strip(), _TS))
            i += 3
        else:
            i += 1  # skip anything we can't make sense of
    return sats


def load_satellites_from_file(path: str) -> list[EarthSatellite]:
    with open(path, "r", encoding="utf-8") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    return _parse_3le(lines)


def load_satellites_from_celestrak(
    catnr: Optional[int] = None,
    group: Optional[str] = None,
    timeout: float = 20.0,
) -> list[EarthSatellite]:
    """Fetch current elements live. Pass either a catalog number or a group.

    Examples:
        load_satellites_from_celestrak(catnr=25544)        # the ISS
        load_satellites_from_celestrak(group="starlink")   # whole group
    """
    if (catnr is None) == (group is None):
        raise ValueError("pass exactly one of catnr or group")
    query = f"CATNR={catnr}" if catnr is not None else f"GROUP={group}"
    url = f"{CELESTRAK_GP}?{query}&FORMAT=TLE"
    req = urllib.request.Request(url, headers={"User-Agent": "space-orchestrator/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    lines = [ln.rstrip("\r") for ln in text.splitlines() if ln.strip()]
    return _parse_3le(lines)
