"""Testes offline das rotas; SkyView é substituído por imagens FITS sintéticas."""
import base64
import asyncio
import io
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from fastapi.testclient import TestClient
from PIL import Image

import app
from ephemerides import mars_geometry


def synthetic_hdu(survey: str):
    yy, xx = np.indices((64, 64), dtype=np.float32)
    data = np.exp(-((xx - 31.5) ** 2 + (yy - 31.5) ** 2) / 20) * 100
    if survey == "DSS2 Blue":
        data = np.roll(data, 2, axis=1)
    header = fits.Header()
    header["TELESCOP"] = "Synthetic telescope"
    header["INSTRUME"] = "Synthetic camera"
    header["DATE-OBS"] = "2000-01-01"
    header["EXPTIME"] = 12.5
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CRPIX1"] = 32.5
    header["CRPIX2"] = 32.5
    header["CRVAL1"] = 10.0
    header["CRVAL2"] = 20.0
    header["CDELT1"] = -0.001
    header["CDELT2"] = 0.001
    return fits.HDUList([fits.PrimaryHDU(data, header=header)])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)

    def fake_skyview(self, position=None, survey=None, radius=None, pixels=None, cache=True):
        self.assertFalse(cache)
        return [synthetic_hdu(survey[0])]

    def assert_png(self, content):
        image = Image.open(io.BytesIO(content))
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.size, (64, 64))

    def assert_png_image(self, content):
        image = Image.open(io.BytesIO(content))
        self.assertEqual(image.format, "PNG")
        self.assertGreater(image.width, 0)
        self.assertGreater(image.height, 0)

    def test_application_serves_the_two_archive_frames(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Comparar a Estrela de Barnard", page.text)
        for name in ("barnard-1950.png", "barnard-1991.png"):
            frame = self.client.get(f"/assets/{name}")
            self.assertEqual(frame.status_code, 200)
            self.assert_png_image(frame.content)

    def test_catalog_endpoint_returns_challenge_and_famous_targets(self):
        response = self.client.get("/api/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["cache-control"])
        items = response.json()["items"]
        catalog = {item["id"]: item for item in items}
        challenge_targets = {"barnard", "wise0855", "epsilonindi", "rwaurigae", "rdraconis"}
        self.assertTrue(challenge_targets.issubset(catalog))
        self.assertIn("andromeda", catalog)
        self.assertEqual(catalog["andromeda"]["category"], "classic")
        self.assertEqual(catalog["barnard"]["suggested_action"], "spherex-subtract")
        self.assertIn("recommended", catalog["wise0855"])

    def test_mars_endpoint_serves_real_geometry_for_each_instant(self):
        endpoint = "/api/ephemerides/mars"
        first = self.client.get(endpoint, params={"instant": "2025-01-16T09:00:00-03:00"})
        second = self.client.get(endpoint, params={"instant": "2025-04-16T12:00:00Z"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn("no-store", first.headers["cache-control"])
        self.assertEqual(first.json(), mars_geometry("2025-01-16T12:00:00Z"))
        self.assertEqual(second.json(), mars_geometry("2025-04-16T12:00:00Z"))
        self.assertNotEqual(first.json()["positions"]["mars"], second.json()["positions"]["mars"])

    def test_mars_endpoint_rejects_invalid_instants(self):
        for instant, expected in (
            ("2025-01-16T12:00:00", "Expected a timestamp"),
            ("2050-01-01T00:00:00Z", "UTC years 2000 through 2049"),
        ):
            with self.subTest(instant=instant):
                response = self.client.get("/api/ephemerides/mars", params={"instant": instant})
                self.assertEqual(response.status_code, 422)
                self.assertIn(expected, response.json()["detail"])

    @patch.object(app.SkyView, "get_images")
    def test_dss_epochs_and_metadata(self, mocked):
        mocked.side_effect = self.fake_skyview
        for epoch, survey in ((1, "DSS1 Blue"), (2, "DSS2 Blue")):
            response = self.client.get("/api/blink_with_metadata", params={"ra": "10", "dec": "20", "epoch": epoch})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["metadata"]["survey_origin"], survey)
            self.assertEqual(body["metadata"]["telescope"], "Synthetic telescope")
            self.assert_png(base64.b64decode(body["image_data"].split(",", 1)[1]))
        self.assertEqual(mocked.call_args.kwargs["pixels"], 500)
        self.assertEqual(mocked.call_args.kwargs["radius"], 5 * app.u.arcmin)
        self.assertIn("no-store", response.headers["cache-control"])

    @patch.object(app.SkyView, "get_images")
    def test_motion_video_returns_labeled_epoch_crossfade(self, mocked):
        mocked.side_effect = self.fake_skyview
        response = self.client.get("/api/motion_video", params={
            "ra": "10", "dec": "20", "fov": 5, "source": "optical", "filter": "true"
        })
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["comparison_type"], "epoch_crossfade")
        self.assertEqual(payload["source"], "optical")
        self.assertNotIn("motion_peak", payload)
        self.assertEqual(len(payload["images"]), 2)
        for image_data in payload["images"]:
            self.assert_png_image(base64.b64decode(image_data.split(",", 1)[1]))
        gif = Image.open(io.BytesIO(base64.b64decode(payload["gif_data"].split(",", 1)[1])))
        self.assertEqual(gif.format, "GIF")
        self.assertGreaterEqual(getattr(gif, "n_frames", 1), 4)

    @patch.object(app.SkyView, "get_images")
    def test_temporal_frames_can_be_requested_without_gif(self, mocked):
        mocked.side_effect = self.fake_skyview
        response = self.client.get("/api/motion_video", params={
            "ra": "10", "dec": "20", "source": "optical", "include_gif": "false"
        })
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["images"]), 2)
        self.assertNotIn("gif_data", payload)

    @patch.object(app.SkyView, "get_images")
    @patch.object(app, "fetch_spherex_temporal_pair", new_callable=AsyncMock)
    def test_motion_video_auto_falls_back_to_dss_when_spherex_has_no_pair(self, mocked_pair, mocked_skyview):
        mocked_pair.side_effect = LookupError("Sem par temporal SPHEREx nesta região.")
        mocked_skyview.side_effect = self.fake_skyview
        response = self.client.get("/api/motion_video", params={"ra": "10", "dec": "20", "source": "auto"})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["source"], "optical")
        self.assertIn("Sem par temporal", payload["fallback_reason"])
        self.assertEqual(payload["comparison_type"], "epoch_crossfade")

    def test_spherex_cutout_url_merges_query_parameters(self):
        position = app.SkyCoord(15.5, -30.2, unit="deg")
        url = app._cutout_url(
            "https://example.test/image.fits?collection=dr1&center=old&size=1&token=abc",
            position,
            0.1 * app.u.deg,
        )
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/image.fits")
        self.assertEqual(query["collection"], ["dr1"])
        self.assertEqual(query["token"], ["abc"])
        self.assertEqual(query["center"], ["15.50000000,-30.20000000d"])
        self.assertEqual(query["size"], ["0.20000000"])
        self.assertEqual(len(query["center"]), 1)

    def test_spherex_exposure_is_cut_out_locally_and_keeps_spatial_wcs(self):
        wcs = WCS(naxis=2)
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        wcs.wcs.cunit = ["deg", "deg"]
        wcs.wcs.crpix = [50.5, 50.5]
        wcs.wcs.crval = [10.0, 20.0]
        wcs.wcs.cdelt = [-0.01, 0.01]
        header = wcs.to_header()
        header["BUNIT"] = "MJy/sr"
        image = np.full((100, 100), 10, dtype=np.float32)
        zodi = np.ones((100, 100), dtype=np.float32)
        flags = np.zeros((100, 100), dtype=np.uint32)
        flags[50, 50] = 1

        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/exposure.fits"
            fits.HDUList([
                fits.PrimaryHDU(),
                fits.ImageHDU(data=image, header=header, name="IMAGE"),
                fits.ImageHDU(data=zodi, header=header, name="ZODI"),
                fits.ImageHDU(data=flags, header=header, name="FLAGS"),
            ]).writeto(path)
            spectral_wcs = unittest.mock.Mock()
            spectral_wcs.pixel_to_world.return_value = (1.25 * app.u.um, 0.05 * app.u.um)
            with patch.object(app, "_cutout_url", return_value=path), patch.object(
                app, "WCS", side_effect=[wcs.celestial, spectral_wcs]
            ):
                hdu, metadata = app._read_spherex_exposure(
                    {"access_url": path, "obs_collection": "spherex_dr1", "t_min": 60000},
                    app.SkyCoord(10, 20, unit="deg"),
                    5 * app.u.arcmin,
                )

        self.assertLess(hdu.data.shape[0], image.shape[0])
        self.assertEqual(hdu.data.shape, (17, 17))
        self.assertAlmostEqual(float(np.nanmedian(hdu.data)), 9.0)
        center_x, center_y = WCS(hdu.header).celestial.world_to_pixel(app.SkyCoord(10, 20, unit="deg"))
        self.assertLessEqual(abs(center_x - (hdu.data.shape[1] - 1) / 2), 0.5)
        self.assertLessEqual(abs(center_y - (hdu.data.shape[0] - 1) / 2), 0.5)
        self.assertEqual(metadata["data_quality"]["flagged_pixels"], 1)
        self.assertAlmostEqual(metadata["wavelength_um"], 1.25)
        self.assertIsNone(spectral_wcs.sip)

    @patch.object(app.SkyView, "get_images")
    def test_subtraction_reprojects_and_returns_png(self, mocked):
        mocked.side_effect = self.fake_skyview
        response = self.client.get("/api/subtract", params={"ra": "10", "dec": "20"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assert_png(response.content)

    @patch.object(app.SkyView, "get_images")
    def test_dss_addition_reprojects_and_returns_png(self, mocked):
        mocked.side_effect = self.fake_skyview
        response = self.client.get("/api/add", params={"ra": "10", "dec": "20"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assert_png(response.content)

    @patch.object(app.SkyView, "get_images")
    def test_wise_bands_return_png(self, mocked):
        mocked.side_effect = self.fake_skyview
        for band in ("WISE 3.4", "WISE 4.6", "WISE 12", "WISE 22"):
            response = self.client.get("/api/infrared", params={"ra": "10", "dec": "20", "band": band})
            self.assertEqual(response.status_code, 200, response.text)
            self.assert_png(response.content)

    @patch.object(app.SkyView, "get_images")
    def test_alternate_infrared_surveys_return_png(self, mocked):
        mocked.side_effect = self.fake_skyview
        for requested, expected in (
            ("2MASS-J", "2MASS-J"),
            ("IRAS 12 micron", "IRAS  12 micron"),
            ("AKARI N60", "AKARI N60"),
        ):
            response = self.client.get(
                "/api/infrared", params={"ra": "10", "dec": "20", "survey": requested}
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assert_png(response.content)
            self.assertEqual(mocked.call_args.kwargs["survey"], [expected])

    def test_rejects_invalid_epoch_fov_band_and_coordinates(self):
        cases = [
            ("/api/blink_with_metadata", {"ra": "10", "dec": "20", "epoch": "9"}),
            ("/api/blink_with_metadata", {"ra": "10", "dec": "20", "fov": "0"}),
            ("/api/infrared", {"ra": "10", "dec": "20", "band": "WISE 999"}),
            ("/api/infrared", {"ra": "10", "dec": "20", "survey": "unknown"}),
            ("/api/blink_with_metadata", {"ra": "bad", "dec": "coordinate"}),
        ]
        for route, params in cases:
            self.assertEqual(self.client.get(route, params=params).status_code, 422)

    def test_non_finite_metadata_becomes_json_null(self):
        metadata = app.extract_safe_fits_metadata(
            {"TELESCOP": "test", "CRPIX1": np.float64(np.nan), "EXPTIME": np.float64(np.inf)},
            "synthetic",
        )
        self.assertIsNone(metadata["wcs_reference_pixel"][0])
        self.assertIsNone(metadata["exposure_time_sec"])

    def test_spherex_metadata_aliases_are_translated(self):
        metadata = app.extract_safe_fits_metadata(
            {"DETECTOR": "4", "OBSID": "obs-123", "EXPIDN": 987, "DATE_OBS": "2025-06-12T03:31:58"},
            "SPHEREx simulated",
        )
        self.assertEqual(metadata["telescope"], "SPHEREx")
        self.assertEqual(metadata["instrument"], "4")
        self.assertEqual(metadata["date_observed"], "2025-06-12T03:31:58")
        self.assertEqual(metadata["observation_id"], "obs-123")

    def test_observation_date_does_not_use_fits_file_creation_date(self):
        header = {"DATE": "2026-11-15"}
        self.assertEqual(app.extract_safe_fits_metadata(header, "DSS1")["date_observed"], "N/A")
        header["MJD-OBS"] = 51544.0
        self.assertEqual(app.extract_safe_fits_metadata(header, "DSS1")["date_observed"], "2000-01-01T00:00:00.000")

    def test_spherex_flag_definitions_support_mskn_and_legacy_mp_keywords(self):
        header = fits.Header()
        header["MSKN0000"] = "TRANSIENT"
        header["MSKN0010"] = "HOT"
        header["MP_COLD"] = 2
        self.assertEqual(
            app._extract_spherex_flag_definitions(header),
            {"TRANSIENT": 0, "HOT": 10, "COLD": 2},
        )

    @patch.object(app.time, "sleep")
    @patch.object(app.vo.dal, "SIA2Service")
    def test_spherex_sia_retries_transient_proxy_errors(self, mocked_service, mocked_sleep):
        mocked_service.return_value.search.side_effect = [
            RuntimeError("502 Server Error: Proxy Error"),
            [{"access_url": "https://example.test/cube.fits"}],
        ]
        result = app._spherex_results(app.SkyCoord(10, 20, unit="deg"), "spherex_dr1_cube", 0.1)
        self.assertEqual(len(result), 1)
        self.assertEqual(mocked_service.return_value.search.call_count, 2)
        mocked_sleep.assert_called_once()
        self.assertGreater(mocked_sleep.call_args.args[0], 0)

    def make_spherex_cube(self, path):
        wcs = WCS(naxis=2)
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        wcs.wcs.cunit = ["deg", "deg"]
        wcs.wcs.crpix = [8.5, 8.5]
        wcs.wcs.crval = [10.0, 20.0]
        wcs.wcs.cdelt = [-0.01, 0.01]
        header = wcs.to_header()
        header["BUNIT"] = "MJy/sr"
        yy, xx = np.indices((16, 16), dtype=np.float32)
        cube = np.stack([channel + xx + yy for channel in range(102)]).astype(np.float32)
        nhits = np.ones((102, 16, 16), dtype=np.int16)
        flags = np.zeros((102, 16, 16), dtype=np.uint32)
        flags[14, 7, 7] = 2
        wavelengths = np.linspace(0.75, 5.0, 102)
        table = fits.BinTableHDU.from_columns([
            fits.Column(name="WAVELENGTH", format="E", array=wavelengths),
            fits.Column(name="WL_MIN", format="E", array=wavelengths - 0.01),
            fits.Column(name="WL_MAX", format="E", array=wavelengths + 0.01),
        ], name="SPECTRAL_CHANNELS")
        fits.HDUList([
            fits.PrimaryHDU(),
            fits.ImageHDU(data=cube, header=header, name="IMAGE"),
            fits.ImageHDU(data=nhits, name="NHITS"),
            fits.ImageHDU(data=flags, name="FLAGS"),
            table,
        ]).writeto(path)

    @patch.object(app.vo.dal, "SIA2Service")
    def test_spherex_band_queries_sia_and_reads_selected_fits_plane(self, mocked_sia):
        with tempfile.TemporaryDirectory() as temp_dir:
            cube_path = f"{temp_dir}/spherex-cube.fits"
            self.make_spherex_cube(cube_path)
            mocked_sia.return_value.search.return_value = [{"access_url": cube_path}]
            response = self.client.get(
                "/api/spherex/band",
                params={"ra": "10", "dec": "20", "band": "15", "fov": "2"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["metadata"]["data_quality"]["flagged_pixels"], 1)
        self.assertEqual(body["metadata"]["bunit"], "MJy/sr")
        self.assertAlmostEqual(body["metadata"]["wavelengths_um"][0], np.linspace(0.75, 5.0, 102)[14], places=5)
        self.assert_png_image(base64.b64decode(body["image_data"].split(",", 1)[1]))
        mocked_sia.return_value.search.assert_called_once()
        self.assertEqual(mocked_sia.return_value.search.call_args.kwargs["collection"], "spherex_dr1_cube")

    @patch.object(app, "fetch_spherex_cutout", new_callable=AsyncMock)
    def test_spherex_band_502_exposes_root_cause_for_debugging(self, mocked_fetch):
        mocked_fetch.side_effect = RuntimeError("HTTP range request was rejected")
        response = self.client.get("/api/spherex/band", params={"ra": "10", "dec": "20"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("HTTP range request was rejected", response.json()["detail"])

    @patch.object(app, "fetch_spherex_cube_spectrum", new_callable=AsyncMock)
    def test_spherex_spectrum_endpoint_returns_cube_values_and_png(self, mocked_fetch):
        mocked_fetch.return_value = (
            np.array([0.8, 1.0, 1.2]),
            np.array([1.1, 1.4, 1.2]),
            {"channels_with_coverage": 3},
        )
        response = self.client.get("/api/spherex/spectrum", params={"ra": "10", "dec": "20"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source"], "SPHEREx DR1 All-Sky Cube")
        self.assertEqual(body["wavelengths_um"], [0.8, 1.0, 1.2])
        self.assertEqual(body["data_quality"]["channels_with_coverage"], 3)
        self.assert_png_image(base64.b64decode(body["image_data"].split(",", 1)[1]))

    @patch.object(app, "fetch_spherex_cutout", new_callable=AsyncMock)
    def test_spherex_detector_mode_is_supported(self, mocked_fetch):
        header = fits.Header({"BUNIT": "MJy/sr", "CTYPE1": "RA---HPX", "CTYPE2": "DEC--HPX"})
        hdu = fits.PrimaryHDU(np.arange(64, dtype=np.float32).reshape(8, 8), header=header)
        mocked_fetch.return_value = (hdu, {"covered_pixels": 64, "flagged_pixels": 0}, [4.2])
        response = self.client.get(
            "/api/spherex/band",
            params={"ra": "10", "dec": "20", "band": "5", "mode": "detector"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["mode"], "detector")
        self.assertEqual(mocked_fetch.await_args.kwargs["mode"], "detector")

    def test_spherex_blank_channels_are_rejected(self):
        for band in (51, 52):
            response = self.client.get(
                "/api/spherex/band", params={"ra": "10", "dec": "20", "band": band}
            )
            self.assertEqual(response.status_code, 422)

    def synthetic_spherex_pair(self):
        first = synthetic_hdu("DSS1 Blue")[0]
        second = synthetic_hdu("DSS2 Blue")[0]
        metadata1 = {
            "survey_origin": "spherex_dr1", "data_release_collection": "spherex_dr1",
            "date_observed": "2025-03-01", "observation_time_utc": "2025-03-01T00:00:00",
            "observation_id": "dr1-obs-1", "wavelength_um": 1.25, "bandwidth_um": 0.02,
            "data_quality": {"flagged_pixels": 2, "flag_counts": {"HOT": 1}},
        }
        metadata2 = {
            "survey_origin": "spherex_qr3", "data_release_collection": "spherex_qr3",
            "date_observed": "2026-03-01", "observation_time_utc": "2026-03-01T00:00:00",
            "observation_id": "qr3-obs-2", "wavelength_um": 1.251, "bandwidth_um": 0.02,
            "data_quality": {"flagged_pixels": 3, "flag_counts": {"COLD": 2}},
        }
        return (first, metadata1), (second, metadata2)

    @patch.object(app, "fetch_spherex_temporal_pair", new_callable=AsyncMock)
    def test_spherex_blink_returns_two_images_and_metadata(self, mocked_fetch):
        mocked_fetch.return_value = self.synthetic_spherex_pair()
        response = self.client.get("/api/spherex/blink", params={"ra": "10", "dec": "20", "detector": "2"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["images"]), 2)
        self.assertEqual(body["metadata"][0]["data_release_collection"], "spherex_dr1")
        self.assertEqual(body["metadata"][1]["data_release_collection"], "spherex_qr3")
        for image_data in body["images"]:
            self.assert_png(base64.b64decode(image_data.split(",", 1)[1]))

    @patch.object(app, "fetch_spherex_temporal_pair", new_callable=AsyncMock)
    def test_spherex_subtract_and_add_return_png(self, mocked_fetch):
        mocked_fetch.return_value = self.synthetic_spherex_pair()
        for route in ("/api/spherex/subtract", "/api/spherex/add"):
            response = self.client.get(route, params={"ra": "10", "dec": "20", "detector": "2"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["content-type"], "application/json")
            body = response.json()
            self.assertEqual(body["detector"], 2)
            self.assertEqual(len(body["metadata"]), 2)
            self.assertEqual(body["metadata"][0]["data_release_collection"], "spherex_dr1")
            self.assertEqual(body["metadata"][1]["data_release_collection"], "spherex_qr3")
            self.assertEqual(body["metadata"][0]["observation_id"], "dr1-obs-1")
            self.assertEqual(body["metadata"][1]["data_quality"]["flag_counts"], {"COLD": 2})
            self.assert_png(base64.b64decode(body["image_data"].split(",", 1)[1]))

    def test_spherex_add_sums_valid_pixels_and_preserves_missing_pixels(self):
        first = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32)
        second = np.array([[2.0, 5.0], [np.nan, 6.0]], dtype=np.float32)
        valid = np.isfinite(first) & np.isfinite(second)
        combined = app._compose_temporal_pair(first, second, valid, "add", False)
        np.testing.assert_allclose(combined, [[3.0, np.nan], [np.nan, 10.0]], equal_nan=True)

    def test_spherex_temporal_candidates_sample_observations_across_full_timeline(self):
        rows = [
            (index * 10.0, "spherex_dr1", {"access_url": f"https://example.test/{index}"})
            for index in range(40)
        ]
        pairs = app._temporal_candidate_pairs(rows)
        candidate_urls = {
            row[2]["access_url"]
            for pair in pairs
            for row in pair
        }
        self.assertLessEqual(len(pairs), 96)
        self.assertGreater(len(candidate_urls), 8)
        for first, second in pairs:
            self.assertGreaterEqual(second[0] - first[0], 30)

    def test_spherex_temporal_pair_prefers_known_wavelength_gap_over_isolated_download_failure(self):
        rows = [
            {
                "access_url": f"https://example.test/{index}",
                "obs_collection": "spherex_dr1" if index < 2 else "spherex_qr3",
                "energy_bandpassname": "SPHEREx-D5",
                "t_min": index * 40,
            }
            for index in range(4)
        ]

        def read_exposure(record, position, fov):
            if record["access_url"].endswith("/0"):
                raise RuntimeError("temporary remote download error")
            wavelength = float(record["t_min"]) / 100
            return fits.PrimaryHDU(np.ones((2, 2))), {
                "wavelength_um": wavelength,
                "bandwidth_um": 0.02,
            }

        with patch.object(app, "_spherex_results", side_effect=[rows[:2], rows[2:]]), \
                patch.object(app, "_read_spherex_exposure", side_effect=read_exposure):
            with self.assertRaisesRegex(LookupError, "comprimentos de onda compatíveis"):
                asyncio.run(app.fetch_spherex_temporal_pair(
                    app.SkyCoord(10, 20, unit="deg"), 1 * app.u.arcmin, detector=5
                ))

    def test_median_filter_removes_isolated_hot_pixel(self):
        matrix = np.zeros((7, 7), dtype=np.float32)
        matrix[3, 3] = 1000
        filtered = app.apply_median_filter(matrix)
        self.assertEqual(filtered[3, 3], 0)

    @patch.object(app.SkyView, "get_images")
    def test_filter_query_is_accepted_for_infrared_and_subtraction(self, mocked):
        mocked.side_effect = self.fake_skyview
        infrared = self.client.get("/api/infrared", params={"ra": "10", "dec": "20", "filter": "true"})
        subtraction = self.client.get("/api/subtract", params={"ra": "10", "dec": "20", "filter": "true"})
        self.assertEqual(infrared.status_code, 200, infrared.text)
        self.assert_png(infrared.content)
        self.assertEqual(subtraction.status_code, 200, subtraction.text)
        self.assert_png(subtraction.content)

    def test_spectrum_endpoint_returns_png_and_validates_matching_arrays(self):
        response = self.client.post("/api/spectrum", json={
            "wavelength": [2.0, 1.0, 1.5], "flux": [4.0, 2.0, 3.0],
            "uncertainty": [0.2, 0.1, 0.15], "title": "Synthetic spectrum",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "image/png")
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.format, "PNG")
        invalid = self.client.post("/api/spectrum", json={"wavelength": [1, 2], "flux": [1]})
        self.assertEqual(invalid.status_code, 422)

    @patch.object(app.SkyView, "get_images", return_value=[])
    def test_no_survey_coverage_is_404(self, mocked):
        response = self.client.get("/api/blink_with_metadata", params={"ra": "10", "dec": "20"})
        self.assertEqual(response.status_code, 404)

    @patch.object(app.SkyView, "get_images", return_value=[])
    def test_infrared_no_coverage_explains_region_and_alternatives(self, mocked):
        response = self.client.get(
            "/api/infrared",
            params={"ra": "10", "dec": "20", "fov": "0.5", "band": "WISE 3.4"},
        )
        self.assertEqual(response.status_code, 404)
        detail = response.json()["detail"]
        self.assertIn("WISE 3.4", detail)
        self.assertEqual(response.json()["survey"], "WISE 3.4")
        self.assertEqual(response.json()["coordinates"], "10, 20")
        self.assertEqual(response.json()["fov"], 0.5)

    def test_openapi_documents_structured_infrared_404(self):
        schema = self.client.get("/openapi.json").json()
        response_404 = schema["paths"]["/api/infrared"]["get"]["responses"]["404"]
        self.assertEqual(response_404["description"], "O survey solicitado não retornou imagem para a região consultada.")
        ref = response_404["content"]["application/json"]["schema"]["$ref"]
        model_name = ref.rsplit("/", 1)[-1]
        properties = schema["components"]["schemas"][model_name]["properties"]
        self.assertEqual(set(properties), {"detail", "survey", "coordinates", "fov"})
        example = response_404["content"]["application/json"]["example"]
        self.assertEqual(example["survey"], "WISE 3.4")
        self.assertEqual(example["coordinates"], "15.5, -30.2")

    @patch.object(app.SkyView, "get_images")
    def test_upstream_failure_names_requested_infrared_survey(self, mocked):
        mocked.side_effect = RuntimeError("synthetic upstream secret")
        response = self.client.get(
            "/api/infrared",
            params={"ra": "10", "dec": "20", "survey": "IRAS 100 micron"},
        )
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret", response.text)
        self.assertIn("IRAS 100 micron", response.json()["detail"])
        self.assertNotIn("WISE", response.json()["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
