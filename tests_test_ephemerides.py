"""Offline tests for the built-in Mars geometry model."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Literal, NoReturn
import unittest
from unittest.mock import patch
import warnings

from astropy import units as u  # type: ignore[import-untyped]
from astropy.config import get_cache_dir, get_config_dir  # type: ignore[import-untyped]
from astropy.coordinates import (  # type: ignore[import-untyped]
    get_body_barycentric,
    get_body_barycentric_posvel,
    solar_system_ephemeris,
)
from astropy.time import Time, TimeDelta  # type: ignore[import-untyped]
from astropy.utils import data, iers  # type: ignore[import-untyped]
from erfa import ErfaWarning  # type: ignore[import-untyped]

import numpy as np

from ephemerides import mars_geometry, mars_state, solar_simulation


_AXES: tuple[Literal["x", "y", "z"], ...] = ("x", "y", "z")
_INSTANT = "2025-01-16T12:00:00Z"
_TIMESTAMP_MESSAGE = "Expected a timestamp YYYY-MM-DDTHH:MM:SS"


def _probe_leap_second_update(mode: Literal["control", "protected"]) -> None:
    """Run once in a fresh interpreter and report attempted downloads."""
    for directory, variable in (
        (get_cache_dir(), "XDG_CACHE_HOME"),
        (get_config_dir(), "XDG_CONFIG_HOME"),
    ):
        expected = Path(os.environ[variable]) / "astropy"
        if Path(directory).resolve() != expected.resolve():
            raise AssertionError(f"Astropy did not use the isolated {variable}")

    # Read local expirations without converting UTC, then move Astropy's
    # reference day past both. The real updater still decides what to fetch.
    expired_day = max(
        iers.LeapSeconds.from_erfa().expires,
        iers.LeapSeconds.from_iers_leap_seconds().expires,
    ) + TimeDelta(1, format="jd")
    attempts: list[str] = []

    def block_download(url: str, *args: object, **kwargs: object) -> NoReturn:
        attempts.append(url)
        raise OSError("Network disabled for the leap-second regression test")

    original_config = (iers.conf.auto_download, iers.conf.auto_max_age)
    with (
        patch.object(iers.LeapSeconds, "_today", return_value=expired_day),
        patch("astropy.utils.iers.iers.download_file", new=block_download),
        warnings.catch_warnings(),
    ):
        if mode == "control":
            warnings.simplefilter("ignore", iers.IERSStaleWarning)
            utc = datetime.fromisoformat(_INSTANT.replace("Z", "+00:00"))
            Time(utc, scale="utc").tdb
        else:
            warnings.simplefilter("error")
            result = mars_geometry(_INSTANT)
            if result["instant_utc"] != _INSTANT:
                raise AssertionError(f"Unexpected UTC instant: {result['instant_utc']}")
    if (iers.conf.auto_download, iers.conf.auto_max_age) != original_config:
        raise AssertionError("IERS settings were not restored")
    for url in attempts:
        print(url)


class MarsGeometryTests(unittest.TestCase):
    instant = _INSTANT

    def setUp(self) -> None:
        offline = ExitStack()
        self.addCleanup(offline.close)
        offline.enter_context(data.conf.set_temp("allow_internet", False))
        offline.enter_context(iers.conf.set_temp("auto_download", False))

    def test_sun_is_at_origin_and_metadata_describes_geometry(self) -> None:
        with solar_system_ephemeris.set(None):
            result = mars_geometry(self.instant)

        self.assertEqual(result["positions"]["sun"], {"x": 0.0, "y": 0.0, "z": 0.0})
        self.assertEqual(result["instant_utc"], self.instant)
        self.assertEqual(result["length_unit"], "au")
        self.assertEqual(result["frame"], {"origin": "sun", "axes": "ICRS"})
        self.assertEqual(result["model"], "astropy:builtin")

    def test_earth_and_mars_positions_are_translated_to_the_sun(self) -> None:
        result = mars_geometry(self.instant)
        epoch = Time(self.instant, scale="utc")
        sun = get_body_barycentric("sun", epoch, ephemeris="builtin").xyz.to_value(u.au)
        bodies: tuple[Literal["earth", "mars"], ...] = ("earth", "mars")
        for body in bodies:
            with self.subTest(body=body):
                barycentric = get_body_barycentric(body, epoch, ephemeris="builtin")
                x, y, z = barycentric.xyz.to_value(u.au) - sun
                expected = (float(x), float(y), float(z))
                for axis, component in zip(_AXES, expected, strict=True):
                    self.assertAlmostEqual(result["positions"][body][axis], component, places=12)

    def test_native_velocities_use_the_same_epoch_and_heliocentric_axes(self) -> None:
        result = mars_state(self.instant)
        geometry = mars_geometry(self.instant)
        self.assertEqual(result["positions"], geometry["positions"])
        self.assertNotIn("velocities_km_s", geometry)
        velocities = result["velocities_km_s"]
        self.assertEqual(velocities["sun"], {"x": 0.0, "y": 0.0, "z": 0.0})
        epoch = Time(self.instant, scale="utc").tdb
        _, sun = get_body_barycentric_posvel("sun", epoch, ephemeris="builtin")
        bodies: tuple[Literal["earth", "mars"], ...] = ("earth", "mars")
        for body in bodies:
            _, barycentric = get_body_barycentric_posvel(body, epoch, ephemeris="builtin")
            for axis, component in zip(_AXES, (barycentric - sun).xyz.to_value(u.km / u.s), strict=True):
                self.assertAlmostEqual(velocities[body][axis], float(component), places=12)
        relative_speed = sqrt(sum((velocities["mars"][axis] - velocities["earth"][axis]) ** 2 for axis in _AXES))
        self.assertAlmostEqual(relative_speed, 7.901003, places=5)

    def test_both_distances_use_all_three_components(self) -> None:
        result = mars_geometry(self.instant)
        positions = result["positions"]
        distances = result["distances"]
        mars = positions["mars"]
        for body, other, actual in (
            ("earth", positions["earth"], distances["mars_earth"]),
            ("sun", positions["sun"], distances["mars_sun"]),
        ):
            with self.subTest(body=body):
                expected = sqrt(sum((mars[axis] - other[axis]) ** 2 for axis in _AXES))
                self.assertAlmostEqual(actual, expected, places=12)

    def test_mars_changes_position_between_instants(self) -> None:
        before = mars_geometry(self.instant)["positions"]["mars"]
        after = mars_geometry("2025-04-16T12:00:00Z")["positions"]["mars"]
        self.assertNotEqual(before, after)

    def test_offset_and_utc_represent_the_same_instant(self) -> None:
        utc = mars_geometry("2025-01-16T00:30:00.100000Z")
        offset = mars_geometry("2025-01-15T21:30:00.1-03:00")
        self.assertEqual(offset, utc)
        self.assertEqual(offset["instant_utc"], "2025-01-16T00:30:00.100000Z")

    def test_rejects_invalid_timestamps(self) -> None:
        for invalid in (
            None,
            datetime(2025, 1, 16, 12),
            datetime(2025, 1, 16, 12, tzinfo=timezone.utc),
        ):
            with self.subTest(instant=invalid), self.assertRaisesRegex(ValueError, _TIMESTAMP_MESSAGE):
                mars_geometry(invalid)  # type: ignore[arg-type]

        for instant, message in (
            ("2025-01-16", _TIMESTAMP_MESSAGE),
            ("2025-01-16T12:00:00", _TIMESTAMP_MESSAGE),
            ("2025-02-30T12:00:00Z", "Invalid calendar date or clock time"),
            ("2025-01-16T24:00:00Z", "Invalid calendar date or clock time"),
            ("2025-01-16T12:00:00+01:60", _TIMESTAMP_MESSAGE),
            ("2016-12-31T23:59:60Z", "Invalid calendar date or clock time"),
            ("2025-01-16T12:00:00.1234567Z", _TIMESTAMP_MESSAGE),
        ):
            with self.subTest(instant=instant), self.assertRaisesRegex(ValueError, message):
                mars_geometry(instant)

    def test_date_range_is_checked_after_normalizing_to_utc(self) -> None:
        result = mars_geometry("1999-12-31T21:00:00-03:00")
        self.assertEqual(result["instant_utc"], "2000-01-01T00:00:00Z")
        for instant in ("2000-01-01T00:00:00+00:01", "2049-12-31T21:00:00-03:00"):
            with (
                self.subTest(instant=instant),
                self.assertRaisesRegex(ValueError, "UTC years 2000 through 2049"),
            ):
                mars_geometry(instant)

    def test_last_supported_instant_accepts_warnings_as_errors(self) -> None:
        instant = "2049-12-31T23:59:59.999999Z"
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = mars_geometry(instant)

        self.assertEqual(result["instant_utc"], instant)
        self.assertEqual(result["length_unit"], "au")
        self.assertEqual(result["frame"], {"origin": "sun", "axes": "ICRS"})
        self.assertEqual(result["model"], "astropy:builtin")
        positions = result["positions"]
        self.assertEqual(positions["sun"], {"x": 0.0, "y": 0.0, "z": 0.0})
        for position in (positions["sun"], positions["earth"], positions["mars"]):
            self.assertEqual(set(position), set(_AXES))
            for axis in _AXES:
                self.assertIsInstance(position[axis], float)
                self.assertTrue(isfinite(position[axis]))
        self.assertEqual(set(result["distances"]), {"mars_earth", "mars_sun"})
        for distance in (result["distances"]["mars_earth"], result["distances"]["mars_sun"]):
            self.assertIsInstance(distance, float)
            self.assertTrue(isfinite(distance))
            self.assertGreater(distance, 0.0)

    def test_other_erfa_warnings_propagate_and_iers_settings_are_restored(self) -> None:
        def warn_during_conversion(utc: list[datetime], *, scale: str) -> None:
            self.assertIs(iers.conf.auto_download, False)
            self.assertIsNone(iers.conf.auto_max_age)
            warnings.warn("unexpected ERFA warning", ErfaWarning)

        with (
            iers.conf.set_temp("auto_download", True),
            iers.conf.set_temp("auto_max_age", 42.0),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error")
            with (
                patch("ephemerides.Time", new=warn_during_conversion),
                self.assertRaisesRegex(ErfaWarning, "unexpected ERFA warning"),
            ):
                mars_geometry(self.instant)
            self.assertIs(iers.conf.auto_download, True)
            self.assertEqual(iers.conf.auto_max_age, 42.0)

    def test_trajectory_reuses_geometry_at_the_selected_and_sampled_instants(self) -> None:
        instant = "2025-01-16T13:37:25Z"
        simulation = solar_simulation(instant)
        self.assertEqual(simulation["geometry"], mars_geometry(instant))
        trajectory = simulation["trajectory"]
        for sample in (trajectory[0], trajectory[30], trajectory[72], trajectory[-1]):
            with self.subTest(instant=sample["instant_utc"]):
                direct = mars_geometry(sample["instant_utc"])["positions"]
                self.assertEqual(sample["earth"], direct["earth"])
                self.assertEqual(sample["mars"], direct["mars"])
        selected = next(sample for sample in trajectory if sample["instant_utc"] == instant)
        self.assertEqual(selected["earth"], simulation["geometry"]["positions"]["earth"])
        self.assertEqual(selected["mars"], simulation["geometry"]["positions"]["mars"])

    def test_sampled_mars_orbit_has_distinct_perihelion_and_aphelion(self) -> None:
        trajectory = solar_simulation(
            "2024-01-01T00:00:00Z", end="2025-12-31T00:00:00Z"
        )["trajectory"]
        radii = [sqrt(sum(sample["mars"][axis] ** 2 for axis in _AXES)) for sample in trajectory]
        perihelion = min(radii)
        aphelion = max(radii)
        self.assertAlmostEqual(perihelion, 1.3815, places=4)
        self.assertAlmostEqual(aphelion, 1.6660, places=4)
        self.assertAlmostEqual((aphelion - perihelion) / (aphelion + perihelion), 0.09336, places=4)
        for radius in (perihelion, aphelion):
            sample = trajectory[radii.index(radius)]
            geometry = mars_geometry(sample["instant_utc"])
            self.assertEqual(sample["mars"], geometry["positions"]["mars"])
            self.assertAlmostEqual(radius, geometry["distances"]["mars_sun"], places=12)

    def test_custom_trajectory_samples_a_short_cut_and_includes_both_ends(self) -> None:
        start = "2025-01-16T12:00:00Z"
        end = "2025-01-16T12:00:01Z"
        result = solar_simulation(start, end=end)
        samples = result["trajectory"]
        self.assertEqual(result["geometry"], mars_geometry(start))
        self.assertEqual(samples[0]["instant_utc"], start)
        self.assertEqual(samples[-1]["instant_utc"], end)
        self.assertGreater(len(samples), 100)
        middle = samples[len(samples) // 2]
        self.assertEqual(middle["earth"], mars_geometry(middle["instant_utc"])["positions"]["earth"])
        self.assertEqual(samples[-1]["mars"], mars_geometry(end)["positions"]["mars"])

    def test_cut_velocities_match_the_state_at_each_sampled_instant(self) -> None:
        end = "2025-01-17T12:00:00Z"
        result = solar_simulation(self.instant, end=end, include_velocities=True)
        self.assertEqual(result["geometry"], mars_state(self.instant))
        no_velocities = solar_simulation(self.instant, end=end)
        self.assertNotIn("velocities_km_s", no_velocities["geometry"])
        self.assertTrue(all("velocities_km_s" not in sample for sample in no_velocities["trajectory"]))
        samples = result["trajectory"]
        for sample in (samples[0], samples[len(samples) // 2], samples[-1]):
            with self.subTest(instant=sample["instant_utc"]):
                expected = mars_state(sample["instant_utc"])
                self.assertEqual(sample["velocities_km_s"], expected["velocities_km_s"])
                self.assertEqual(sample["mars"], expected["positions"]["mars"])

    def test_trajectory_window_stays_inside_coverage_and_keeps_distinct_planes(self) -> None:
        bounds = ("2000-01-01T00:00:00Z", "2049-12-31T23:59:59.999999Z")
        for instant in bounds:
            with self.subTest(instant=instant):
                with warnings.catch_warnings():
                    warnings.simplefilter("error")
                    trajectory = solar_simulation(instant)["trajectory"]
                times = [
                    datetime.fromisoformat(sample["instant_utc"].replace("Z", "+00:00"))
                    for sample in trajectory
                ]
                self.assertIn(instant, (trajectory[0]["instant_utc"], trajectory[-1]["instant_utc"]))
                self.assertLessEqual(bounds[0], trajectory[0]["instant_utc"])
                self.assertLessEqual(trajectory[-1]["instant_utc"], bounds[-1])
                self.assertEqual(times[-1] - times[0], timedelta(days=720))
                for earlier, later in zip(times, times[1:]):
                    self.assertLess(timedelta(), later - earlier)
                    self.assertLessEqual(later - earlier, timedelta(days=5))

                bodies: tuple[Literal["earth", "mars"], ...] = ("earth", "mars")
                normals = []
                for body in bodies:
                    first_vector = [trajectory[0][body][axis] for axis in _AXES]
                    later_vector = [trajectory[9][body][axis] for axis in _AXES]
                    normal = np.cross(first_vector, later_vector)
                    self.assertGreater(abs(float(normal[1])), 0.1)
                    normals.append(normal / np.linalg.norm(normal))
                self.assertGreater(float(np.linalg.norm(normals[0] - normals[1])), 0.01)


class MarsGeometryOfflineTests(unittest.TestCase):
    def _download_attempts(self, mode: Literal["control", "protected"]) -> list[str]:
        with TemporaryDirectory() as temp:
            cache = Path(temp) / "cache"
            config = Path(temp) / "config"
            # Astropy selects the XDG location only if its subdirectory exists.
            (cache / "astropy").mkdir(parents=True)
            (config / "astropy").mkdir(parents=True)
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from tests_test_ephemerides import _probe_leap_second_update\n"
                    f"_probe_leap_second_update({mode!r})",
                ],
                cwd=Path(__file__).resolve().parent,
                env={**os.environ, "XDG_CACHE_HOME": str(cache), "XDG_CONFIG_HOME": str(config)},
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        return probe.stdout.splitlines()

    def test_unprotected_first_conversion_tries_to_refresh_expired_table(self) -> None:
        attempts = self._download_attempts("control")
        self.assertTrue(attempts, "Expected a leap-second download attempt")
        leap_second_urls = {str(iers.IERS_LEAP_SECOND_URL), str(iers.IETF_LEAP_SECOND_URL)}
        self.assertLessEqual(set(attempts), leap_second_urls)

    def test_mars_geometry_first_conversion_uses_expired_table_offline(self) -> None:
        self.assertEqual(self._download_attempts("protected"), [])
