"""Offline tests for the built-in Mars geometry model."""

from contextlib import ExitStack
from math import sqrt
import unittest

from astropy import units as u
from astropy.coordinates import get_body_barycentric, solar_system_ephemeris
from astropy.time import Time
from astropy.utils import data, iers

from ephemerides import mars_geometry


class MarsGeometryTests(unittest.TestCase):
    instant = "2025-01-16T12:00:00Z"

    def setUp(self):
        offline = ExitStack()
        self.addCleanup(offline.close)
        offline.enter_context(data.conf.set_temp("allow_internet", False))
        offline.enter_context(iers.conf.set_temp("auto_download", False))

    def test_sun_is_at_origin_and_metadata_describes_geometry(self):
        with solar_system_ephemeris.set(None):
            result = mars_geometry(self.instant)

        self.assertEqual(result["positions"]["sun"], {"x": 0.0, "y": 0.0, "z": 0.0})
        self.assertEqual(result["instant_utc"], self.instant)
        self.assertEqual(result["length_unit"], "au")
        self.assertEqual(result["frame"], {"origin": "sun", "axes": "ICRS"})
        self.assertEqual(result["model"], "astropy:builtin")

    def test_earth_and_mars_positions_are_translated_to_the_sun(self):
        result = mars_geometry(self.instant)
        epoch = Time(self.instant, scale="utc")
        sun = get_body_barycentric("sun", epoch, ephemeris="builtin").xyz.to_value(u.au)
        for body in ("earth", "mars"):
            with self.subTest(body=body):
                barycentric = get_body_barycentric(body, epoch, ephemeris="builtin")
                heliocentric = barycentric.xyz.to_value(u.au) - sun
                for axis, expected in zip(("x", "y", "z"), heliocentric):
                    self.assertAlmostEqual(result["positions"][body][axis], expected, places=12)

    def test_both_distances_use_all_three_components(self):
        result = mars_geometry(self.instant)
        mars = result["positions"]["mars"]
        for body in ("earth", "sun"):
            with self.subTest(body=body):
                other = result["positions"][body]
                expected = sqrt(sum((mars[axis] - other[axis]) ** 2 for axis in ("x", "y", "z")))
                self.assertAlmostEqual(result["distances"][f"mars_{body}"], expected, places=12)

    def test_mars_changes_position_between_instants(self):
        before = mars_geometry(self.instant)["positions"]["mars"]
        after = mars_geometry("2025-04-16T12:00:00Z")["positions"]["mars"]
        self.assertNotEqual(before, after)

    def test_offset_and_utc_represent_the_same_instant(self):
        utc = mars_geometry("2025-01-16T00:30:00.100000Z")
        offset = mars_geometry("2025-01-15T21:30:00.1-03:00")
        self.assertEqual(offset, utc)
        self.assertEqual(offset["instant_utc"], "2025-01-16T00:30:00.100000Z")

    def test_rejects_invalid_timestamps(self):
        for instant in (
            None,
            "2025-01-16",
            "2025-01-16T12:00:00",
            "2025-02-30T12:00:00Z",
            "2025-01-16T24:00:00Z",
            "2025-01-16T12:00:00+01:60",
            "2016-12-31T23:59:60Z",
            "2025-01-16T12:00:00.1234567Z",
        ):
            with self.subTest(instant=instant), self.assertRaises(ValueError):
                mars_geometry(instant)

    def test_date_range_is_checked_after_normalizing_to_utc(self):
        result = mars_geometry("1999-12-31T21:00:00-03:00")
        self.assertEqual(result["instant_utc"], "2000-01-01T00:00:00Z")
        for instant in ("2000-01-01T00:00:00+00:01", "2049-12-31T21:00:00-03:00"):
            with self.subTest(instant=instant), self.assertRaises(ValueError):
                mars_geometry(instant)
