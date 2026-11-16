"""Geometric Solar System positions for the Mars service."""

from datetime import datetime, timezone
from math import dist
import re

from astropy import units as u
from astropy.coordinates import get_body_barycentric
from astropy.time import Time


_EPHEMERIS = "builtin"
_START_UTC = datetime(2000, 1, 1, tzinfo=timezone.utc)
_END_UTC = datetime(2050, 1, 1, tzinfo=timezone.utc)
_TIMESTAMP = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.([0-9]{1,6}))?(Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _parse_instant(instant: str) -> datetime:
    match = _TIMESTAMP.fullmatch(instant) if isinstance(instant, str) else None
    if match is None:
        raise ValueError("Expected a timestamp YYYY-MM-DDTHH:MM:SS with Z or ±HH:MM.")

    date_time, fraction, offset = match.groups()
    if fraction:
        date_time += "." + fraction.ljust(6, "0")
    timestamp = date_time + ("+00:00" if offset == "Z" else offset)
    try:
        utc = datetime.fromisoformat(timestamp).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("Invalid calendar date or clock time.") from exc
    except OverflowError as exc:
        raise ValueError("Timestamp is outside the supported UTC range.") from exc

    if not _START_UTC <= utc < _END_UTC:
        raise ValueError("Timestamp must be in UTC years 2000 through 2049.")
    return utc


def mars_geometry(instant: str) -> dict[str, object]:
    """Return estimated heliocentric vectors and Mars distances in au."""
    utc = _parse_instant(instant)
    epoch = Time(utc, scale="utc").tdb
    sun_barycentric = get_body_barycentric("sun", epoch, ephemeris=_EPHEMERIS)

    heliocentric = {"sun": (0.0, 0.0, 0.0)}
    for body in ("earth", "mars"):
        barycentric = get_body_barycentric(body, epoch, ephemeris=_EPHEMERIS)
        xyz = (barycentric - sun_barycentric).xyz.to_value(u.au)
        heliocentric[body] = tuple(float(component) for component in xyz)

    return {
        "instant_utc": utc.isoformat().replace("+00:00", "Z"),
        "length_unit": "au",
        "frame": {"origin": "sun", "axes": "ICRS"},
        "model": f"astropy:{_EPHEMERIS}",
        "positions": {
            body: dict(zip(("x", "y", "z"), xyz))
            for body, xyz in heliocentric.items()
        },
        "distances": {
            "mars_earth": dist(heliocentric["mars"], heliocentric["earth"]),
            "mars_sun": dist(heliocentric["mars"], heliocentric["sun"]),
        },
    }
