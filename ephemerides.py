"""Geometric Solar System positions for the Mars service."""

from datetime import datetime, timedelta, timezone
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


class OrbitSample(TypedDict):
    instant_utc: str
    earth: Position
    mars: Position


class SolarSimulation(TypedDict):
    geometry: MarsGeometry
    trajectory: list[OrbitSample]


_EPHEMERIS = "builtin"
_IERS_LOCK = Lock()
_START_UTC = datetime(2000, 1, 1, tzinfo=timezone.utc)
_END_UTC = datetime(2050, 1, 1, tzinfo=timezone.utc)
_LAST_UTC = _END_UTC - timedelta(microseconds=1)
_TRAJECTORY_WINDOW = timedelta(days=720)
_TRAJECTORY_STEP = timedelta(days=5)
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


def _heliocentric_vectors(
    body: Literal["earth", "mars"], epoch: Time, sun_barycentric: CartesianRepresentation
) -> list[Vector3D]:
    barycentric = get_body_barycentric(body, epoch, ephemeris=_EPHEMERIS)
    x, y, z = (barycentric - sun_barycentric).xyz.to_value(u.au)
    return [
        (float(x_value), float(y_value), float(z_value))
        for x_value, y_value, z_value in zip(x, y, z, strict=True)
    ]


def _position(vector: Vector3D) -> Position:
    x, y, z = vector
    return {"x": x, "y": y, "z": z}


def _positions_at(instants: list[datetime]) -> tuple[list[Vector3D], list[Vector3D]]:
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
        epoch = Time(instants, scale="utc").tdb

    sun_barycentric = get_body_barycentric("sun", epoch, ephemeris=_EPHEMERIS)
    return (
        _heliocentric_vectors("earth", epoch, sun_barycentric),
        _heliocentric_vectors("mars", epoch, sun_barycentric),
    )


def _geometry(utc: datetime, earth: Vector3D, mars: Vector3D) -> MarsGeometry:
    sun: Vector3D = (0.0, 0.0, 0.0)

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


def mars_geometry(instant: str) -> MarsGeometry:
    """Return estimated heliocentric vectors and Mars distances in au.

    The metadata `axes: "ICRS"` names the nominal axes of `astropy:builtin`.
    Astropy directly combines BCRS-oriented Sun and Earth vectors derived from
    `erfa.epv00` with the heliocentric Mars vector from `erfa.plan94`, which
    uses the mean equator and equinox of J2000.0. This gives approximate ICRS
    alignment and preserves the native vector convention without a rotation.
    """
    utc = _parse_instant(instant)
    earth, mars = _positions_at([utc])
    return _geometry(utc, earth[0], mars[0])


def solar_simulation(instant: str, end: str | None = None) -> SolarSimulation:
    """Sample a trajectory in the same frame as mars_geometry.

    If end is supplied, instant and end delimit the requested interval.
    Otherwise return the 720-day overview around instant.
    """
    utc = _parse_instant(instant)
    if end is None:
        # Move the whole window near a coverage limit instead of extrapolating.
        start = max(_START_UTC, min(utc - _TRAJECTORY_WINDOW / 2, _LAST_UTC - _TRAJECTORY_WINDOW))
        finish = start + _TRAJECTORY_WINDOW
        step = _TRAJECTORY_STEP
    else:
        start = utc
        finish = _parse_instant(end)
        if finish <= start:
            raise ValueError("The interval end must be after its start.")
        # Keep short intervals navigable while retaining five-day spacing at most.
        step = min(_TRAJECTORY_STEP, max(timedelta(microseconds=1), (finish - start) / 144))

    dates = {
        start + index * step
        for index in range((finish - start) // step + 1)
    }
    dates.update((utc, finish))
    instants = sorted(dates)
    earth, mars = _positions_at(instants)
    selected = instants.index(utc)
    return {
        "geometry": _geometry(utc, earth[selected], mars[selected]),
        "trajectory": [
            {
                "instant_utc": date.isoformat().replace("+00:00", "Z"),
                "earth": _position(earth_vector),
                "mars": _position(mars_vector),
            }
            for date, earth_vector, mars_vector in zip(instants, earth, mars, strict=True)
        ],
    }
