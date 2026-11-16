"""Geometric Solar System positions for the Mars service."""

from datetime import datetime, timezone
from math import dist
import re
from threading import Lock
from typing import Literal, TypeAlias, TypedDict
import warnings

from astropy import units as u  # type: ignore[import-untyped]
from astropy.coordinates import CartesianRepresentation, get_body_barycentric  # type: ignore[import-untyped]
from astropy.time import Time  # type: ignore[import-untyped]
from astropy.utils import iers  # type: ignore[import-untyped]
from erfa import ErfaWarning  # type: ignore[import-untyped]


Vector3D: TypeAlias = tuple[float, float, float]


class Position(TypedDict):
    x: float
    y: float
    z: float


class Positions(TypedDict):
    sun: Position
    earth: Position
    mars: Position


class Distances(TypedDict):
    mars_earth: float
    mars_sun: float


class Frame(TypedDict):
    origin: Literal["sun"]
    axes: Literal["ICRS"]


class MarsGeometry(TypedDict):
    instant_utc: str
    length_unit: Literal["au"]
    frame: Frame
    model: Literal["astropy:builtin"]
    positions: Positions
    distances: Distances


_EPHEMERIS = "builtin"
_IERS_LOCK = Lock()
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


def _heliocentric_vector(
    body: Literal["earth", "mars"], epoch: Time, sun_barycentric: CartesianRepresentation
) -> Vector3D:
    barycentric = get_body_barycentric(body, epoch, ephemeris=_EPHEMERIS)
    x, y, z = (barycentric - sun_barycentric).xyz.to_value(u.au)
    return (float(x), float(y), float(z))


def _position(vector: Vector3D) -> Position:
    x, y, z = vector
    return {"x": x, "y": y, "z": z}


def mars_geometry(instant: str) -> MarsGeometry:
    """Return estimated heliocentric vectors and Mars distances in au.

    The metadata `axes: "ICRS"` names the nominal axes of `astropy:builtin`.
    Astropy directly combines BCRS-oriented Sun and Earth vectors derived from
    `erfa.epv00` with the heliocentric Mars vector from `erfa.plan94`, which
    uses the mean equator and equinox of J2000.0. This gives approximate ICRS
    alignment and preserves the native vector convention without a rotation.
    """
    utc = _parse_instant(instant)
    # Astropy's IERS settings are process-global. Serialize this temporary
    # configuration across calls, including the first leap-second table check.
    with (
        _IERS_LOCK,
        iers.conf.set_temp("auto_download", False),
        iers.conf.set_temp("auto_max_age", None),
        warnings.catch_warnings(),
    ):
        # Future UTC years can exceed ERFA's leap-second knowledge.
        warnings.filterwarnings("ignore", message=r".*dubious year.*", category=ErfaWarning)
        epoch = Time(utc, scale="utc").tdb

    sun_barycentric = get_body_barycentric("sun", epoch, ephemeris=_EPHEMERIS)
    sun: Vector3D = (0.0, 0.0, 0.0)
    earth = _heliocentric_vector("earth", epoch, sun_barycentric)
    mars = _heliocentric_vector("mars", epoch, sun_barycentric)

    return {
        "instant_utc": utc.isoformat().replace("+00:00", "Z"),
        "length_unit": "au",
        "frame": {"origin": "sun", "axes": "ICRS"},
        "model": "astropy:builtin",
        "positions": {
            "sun": _position(sun),
            "earth": _position(earth),
            "mars": _position(mars),
        },
        "distances": {
            "mars_earth": dist(mars, earth),
            "mars_sun": dist(mars, sun),
        },
    }
