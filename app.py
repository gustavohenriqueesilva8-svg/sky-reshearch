import asyncio
import base64
import concurrent.futures
from contextlib import contextmanager
import io
import logging
from pathlib import Path
import time
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
import requests
from astropy import units as u
from astropy.coordinates import ICRS, SkyCoord
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.time import Time
from astropy.utils.data import conf
from astropy.visualization import ImageNormalize, LogStretch, ZScaleInterval
from astropy.wcs import WCS
from astroquery.skyview import SkyView
import pyvo as vo
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from scipy.ndimage import median_filter

from ephemerides import MarsGeometry, SolarSimulation, mars_geometry, solar_simulation

logger = logging.getLogger(__name__)
conf.remote_timeout = 120


def _bound_http_session(session, connect_timeout: float = 3, read_timeout: float = 8):
    """Cap blocking PyVO/Astroquery HTTP calls so failover can start promptly."""
    original_request = session.request

    def bounded_request(method, url, **kwargs):
        kwargs.setdefault("timeout", (connect_timeout, read_timeout))
        return original_request(method, url, **kwargs)

    session.request = bounded_request
    return session


_bound_http_session(SkyView._session)
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

app = FastAPI(
    title="SPHEREx & All-Sky Data Processing API",
    description="API Quick-Look para canais SPHEREx DR1, imagens DSS/infravermelhas, subtração, metadados FITS e gráficos espectrais.",
    version="1.4.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

PROJECT_DIR = Path(__file__).resolve().parent
app.mount("/assets", StaticFiles(directory=PROJECT_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
async def get_application():
    return FileResponse(PROJECT_DIR / "index.html", media_type="text/html")


@app.middleware("http")
async def disable_api_response_caching(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        for name, value in NO_CACHE_HEADERS.items():
            response.headers[name] = value
    return response

INFRARED_SURVEYS = {
    "wise 3.4": "WISE 3.4",
    "wise 4.6": "WISE 4.6",
    "wise 12": "WISE 12",
    "wise 22": "WISE 22",
    "2mass-j": "2MASS-J",
    "2mass-h": "2MASS-H",
    "2mass-k": "2MASS-K",
    "iras 12 micron": "IRAS  12 micron",
    "iras 25 micron": "IRAS  25 micron",
    "iras 60 micron": "IRAS  60 micron",
    "iras 100 micron": "IRAS 100 micron",
    "iris 12": "IRIS  12",
    "iris 25": "IRIS  25",
    "iris 60": "IRIS  60",
    "iris 100": "IRIS 100",
    "akari n60": "AKARI N60",
    "akari wide-s": "AKARI WIDE-S",
    "akari wide-l": "AKARI WIDE-L",
    "akari n160": "AKARI N160",
}

CELESTIAL_CATALOG = [
    {"id": "barnard", "name": "Estrela de Barnard", "category": "challenge", "type_label": "Anã vermelha de alto movimento próprio", "ra": "17h57m48.5s", "dec": "+04d41m36s", "ra_deg": 269.452, "dec_deg": 4.693, "fov": 10, "distance": "≈ 5,96 anos-luz", "distance_ly": 5.96, "recommended": {"spherex_detector": 2, "spherex_mode": "detector", "spherex_band": 2, "filter": False, "infrared": "wise"}, "suggested_action": "spherex-subtract", "description": "Alvo para explorar movimento próprio, alinhamento WCS e diferenças entre épocas."},
    {"id": "wise0855", "name": "WISE 0855−0714", "category": "challenge", "type_label": "Anã marrom Y", "ra": "08h55m10.831s", "dec": "-07d14m42.53s", "ra_deg": 133.795, "dec_deg": -7.245, "fov": 30, "distance": "≈ 7,4 anos-luz", "distance_ly": 7.4, "recommended": {"spherex_detector": 6, "spherex_mode": "detector", "spherex_band": 6, "filter": False, "infrared": "wise"}, "suggested_action": "spherex-band", "description": "Alvo frio e próximo; compare o detector D6 com as bandas WISE W1/W2."},
    {"id": "epsilonindi", "name": "Epsilon Indi B", "category": "challenge", "type_label": "Par de anãs marrons", "ra": "22h04m10.595s", "dec": "-56d46m58.239s", "ra_deg": 331.044, "dec_deg": -56.783, "fov": 6, "distance": "≈ 12 anos-luz (sistema)", "distance_ly": 12, "recommended": {"spherex_detector": 2, "spherex_mode": "channel", "spherex_band": 15, "filter": False, "infrared": "wise"}, "suggested_action": "spherex-spectrum", "description": "Sistema próximo com anãs marrons; indicado para extração e inspeção espectral."},
    {"id": "rwaurigae", "name": "RW Aurigae", "category": "challenge", "type_label": "Sistema jovem variável T Tauri", "ra": "05h07m49.5s", "dec": "+30d24m05s", "ra_deg": 76.956, "dec_deg": 30.401, "fov": 5, "distance": "≈ 450 anos-luz", "distance_ly": 450, "recommended": {"spherex_detector": 5, "spherex_mode": "detector", "spherex_band": 5, "filter": True, "infrared": "wise"}, "suggested_action": "spherex-blink", "description": "Sistema jovem variável para examinar mudanças entre observações e o efeito do filtro de mediana."},
    {"id": "rdraconis", "name": "R Draconis", "category": "challenge", "type_label": "Variável Mira", "ra": "16h32m40.23s", "dec": "+66d45m17.9s", "ra_deg": 248.168, "dec_deg": 66.755, "fov": 10, "distance": "Distância sem valor confiável cadastrado", "distance_ly": None, "recommended": {"spherex_detector": 6, "spherex_mode": "detector", "spherex_band": 6, "filter": False, "infrared": "wise"}, "suggested_action": "spherex-add", "description": "Variável Mira para comparar a combinação exploratória de épocas."},
    {"id": "andromeda", "name": "Galáxia de Andrômeda (M31)", "category": "classic", "type_label": "Galáxia espiral", "ra": "00h42m44.3s", "dec": "+41d16m09s", "ra_deg": 10.685, "dec_deg": 41.269, "fov": 60, "distance": "≈ 2,5 milhões de anos-luz", "distance_ly": 2500000, "recommended": {"spherex_detector": 1, "spherex_mode": "detector", "spherex_band": 1, "filter": False, "infrared": "wise"}, "suggested_action": "infrared", "description": "Galáxia vizinha extensa; use o FOV amplo para observar seu núcleo e regiões internas."},
    {"id": "orion", "name": "Nebulosa de Órion (M42)", "category": "classic", "type_label": "Nebulosa de emissão e berçário estelar", "ra": "05h35m17.3s", "dec": "-05d23m28s", "ra_deg": 83.822, "dec_deg": -5.391, "fov": 30, "distance": "≈ 1.344 anos-luz", "distance_ly": 1344, "recommended": {"spherex_detector": 4, "spherex_mode": "detector", "spherex_band": 4, "filter": False, "infrared": "wise-mid"}, "suggested_action": "spherex-band", "description": "Região de formação estelar para explorar emissão e poeira em imagens infravermelhas."},
    {"id": "pleiades", "name": "Aglomerado das Plêiades (M45)", "category": "classic", "type_label": "Aglomerado estelar aberto", "ra": "03h47m24.0s", "dec": "+24d07m00s", "ra_deg": 56.850, "dec_deg": 24.117, "fov": 45, "distance": "≈ 450 anos-luz", "distance_ly": 450, "recommended": {"spherex_detector": 2, "spherex_mode": "detector", "spherex_band": 2, "filter": False, "infrared": "wise"}, "suggested_action": "infrared", "description": "Aglomerado próximo com nebulosidade de reflexão; alvo amplo para comparação entre surveys."},
    {"id": "sombrero", "name": "Galáxia do Sombrero (M104)", "category": "classic", "type_label": "Galáxia espiral quase de perfil", "ra": "12h39m59.4s", "dec": "-11d37m23s", "ra_deg": 189.998, "dec_deg": -11.623, "fov": 15, "distance": "≈ 30 milhões de anos-luz", "distance_ly": 30000000, "recommended": {"spherex_detector": 5, "spherex_mode": "detector", "spherex_band": 5, "filter": False, "infrared": "wise"}, "suggested_action": "spherex-band", "description": "Galáxia com faixa de poeira proeminente, adequada para inspeção infravermelha."},
    {"id": "whirlpool", "name": "Galáxia do Redemoinho (M51)", "category": "classic", "type_label": "Galáxia espiral em interação", "ra": "13h29m52.7s", "dec": "+47d11m43s", "ra_deg": 202.470, "dec_deg": 47.195, "fov": 15, "distance": "≈ 23 milhões de anos-luz", "distance_ly": 23000000, "recommended": {"spherex_detector": 3, "spherex_mode": "detector", "spherex_band": 3, "filter": False, "infrared": "wise"}, "suggested_action": "blink-optical", "description": "Par de galáxias em interação; carregue o alvo e compare a referência DSS."},
    {"id": "sirius", "name": "Sirius (α Canis Majoris)", "category": "classic", "type_label": "Sistema binário estelar", "ra": "06h45m08.9s", "dec": "-16d42m58s", "ra_deg": 101.287, "dec_deg": -16.716, "fov": 10, "distance": "≈ 8,6 anos-luz", "distance_ly": 8.6, "recommended": {"spherex_detector": 2, "spherex_mode": "channel", "spherex_band": 10, "filter": False, "infrared": "2mass"}, "suggested_action": "infrared", "description": "Sistema estelar brilhante no céu noturno, útil para experimentar diferentes levantamentos."},
    {"id": "proxima", "name": "Proxima Centauri", "category": "classic", "type_label": "Anã vermelha com alto movimento próprio", "ra": "14h29m42.9s", "dec": "-62d40m46s", "ra_deg": 217.429, "dec_deg": -62.679, "fov": 10, "distance": "≈ 4,24 anos-luz", "distance_ly": 4.24, "recommended": {"spherex_detector": 2, "spherex_mode": "detector", "spherex_band": 2, "filter": False, "infrared": "wise"}, "suggested_action": "spherex-subtract", "description": "A estrela mais próxima do Sol; carregue suas coordenadas para análise temporal."},
    {"id": "betelgeuse", "name": "Betelgeuse (α Orionis)", "category": "classic", "type_label": "Supergigante vermelha variável", "ra": "05h55m10.3s", "dec": "+07d24m25s", "ra_deg": 88.793, "dec_deg": 7.407, "fov": 15, "distance": "≈ 700 anos-luz (estimativa aproximada)", "distance_ly": 700, "recommended": {"spherex_detector": 2, "spherex_mode": "detector", "spherex_band": 2, "filter": False, "infrared": "2mass"}, "suggested_action": "spherex-band", "description": "Supergigante vermelha variável, apresentada como alvo de exploração infravermelha."},
]

SPHEREX_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
SPHEREX_IMAGE_COLLECTIONS = ("spherex_dr1", "spherex_qr3")
SPHEREX_S3_CUBE_ROOT = (
    "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
    "dr1/hips5_cube/hips_20261026"
)
SPHEREX_DETECTOR_CHANNELS = {
    detector: tuple(range((detector - 1) * 17 + 1, detector * 17 + 1))
    for detector in range(1, 7)
}
SPHEREX_BLANK_CHANNELS = {51, 52}
SPHEREX_BAD_FLAG_NAMES = (
    "TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "DICHROIC", "MISSING_DATA", "HOT", "COLD",
    "PHANMISS", "NONLINEAR", "PERSIST", "OUTLIER", "CROSSTALK", "GHOST", "GHOST_FPA",
    "GHOST_EXT", "STREAK", "BLOOM", "SNOWBALL", "HALO", "SATELLITE_HALO",
)


def _is_remote_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status = (
        getattr(exc, "status", None)
        or getattr(exc, "status_code", None)
        or getattr(exc, "code", None)
        or getattr(response, "status_code", None)
    )
    if status == 404:
        return True
    message = str(exc).casefold()
    return any(marker in message for marker in ("404 not found", "no such key", "not found"))


def _extract_spherex_flag_definitions(flag_header) -> dict[str, int]:
    definitions = {}
    for key in flag_header.keys():
        if key.startswith("MSKN"):
            suffix = key[4:].strip()
            name = str(flag_header[key]).strip().upper()
            if suffix.isdigit() and name in SPHEREX_BAD_FLAG_NAMES:
                definitions[name] = int(suffix)
    for name in SPHEREX_BAD_FLAG_NAMES:
        if name not in definitions and f"MP_{name}" in flag_header:
            definitions[name] = int(flag_header[f"MP_{name}"])
    return definitions


@contextmanager
def _open_cube_hdul(access_url: str):
    """Use range reads for remote cubes while keeping local FITS fixtures dependency-light."""
    is_remote = str(access_url).startswith(("http://", "https://"))
    if not is_remote:
        with fits.open(access_url, lazy_load_hdus=True, memmap=False) as hdul:
            yield hdul
        return
    try:
        hdul = fits.open(
            access_url,
            use_fsspec=True,
            fsspec_kwargs={"block_size": 1048576},
            lazy_load_hdus=True,
            memmap=False,
        )
    except Exception:
        if "nasa-irsa-spherex.s3.us-east-1.amazonaws.com" in str(access_url):
            # Do not silently turn an S3 Range failure into a 300+ MB whole-cube download.
            raise
        # The IRSA HTTP server may reject range requests; retry with normal HTTP I/O.
        hdul = fits.open(access_url, cache=False, memmap=False)
    with hdul:
        yield hdul


class OutOfCoverageError(BaseModel):
    detail: str = Field(
        ..., examples=["O SkyView não encontrou imagens para esta região do céu."]
    )
    survey: str = Field(..., examples=["WISE 3.4"])
    coordinates: str = Field(..., examples=["15.5, -30.2"])
    fov: float = Field(..., examples=[0.1])


def resolve_infrared_survey(name: str) -> str:
    """Mapeia nome informado pelo usuário para o identificador SkyView."""
    key = " ".join(name.strip().split()).casefold()
    try:
        return INFRARED_SURVEYS[key]
    except KeyError as exc:
        options = ", ".join(INFRARED_SURVEYS.values())
        raise ValueError(f"Survey infravermelho não suportado. Opções: {options}.") from exc


def parse_coordinates(ra: str, dec: str) -> SkyCoord:
    """Parse coordenadas em graus decimais ou sexagesimais."""
    ra_text, dec_text = str(ra).strip(), str(dec).strip()
    if not ra_text or not dec_text:
        raise ValueError("RA e Dec não podem estar vazios.")
    try:
        coordinate = SkyCoord(float(ra_text), float(dec_text), unit=(u.deg, u.deg), frame="icrs")
    except ValueError:
        coordinate = SkyCoord(ra_text, dec_text, frame="icrs")
    if not np.isfinite(coordinate.ra.deg) or not np.isfinite(coordinate.dec.deg):
        raise ValueError("As coordenadas devem ser finitas.")
    return coordinate


def sanitize_json(value: Any) -> Any:
    """Converte tipos NumPy e valores NaN/Inf em valores aceitos por JSON."""
    if isinstance(value, dict):
        return {str(k): sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [sanitize_json(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is None or isinstance(value, (str, bool)):
        return value
    return str(value)


def extract_safe_fits_metadata(header, survey_name: str) -> dict:
    def first(*keys, default=None):
        for key in keys:
            value = header.get(key)
            if value is not None and str(value).strip():
                return value
        return default

    observation_date = first("DATE-OBS", "DATE_OBS")
    if not observation_date:
        mjd = first("MJD-OBS", "MJD_OBS")
        if mjd is not None:
            try:
                observation_date = Time(float(mjd), format="mjd", scale="utc").isot
            except (TypeError, ValueError):
                pass

    is_spherex = any(key in header for key in ("DETECTOR", "OBSID", "EXPIDN"))
    fields = {
        "survey_origin": survey_name,
        "telescope": first("TELESCOP", "TELESCOPE", default="SPHEREx" if is_spherex else "Desconhecido"),
        "instrument": first("INSTRUME", "INSTRUMENT", "DETECTOR", default="Desconhecido"),
        "exposure_time_sec": first("EXPTIME", "EXPOSURE", "TELAPSE", default=0.0),
        # FITS DATE is file creation, not the date the sky was observed.
        "date_observed": observation_date or "N/A",
        "wcs_reference_pixel": [first("CRPIX1"), first("CRPIX2")],
        "wcs_reference_ra_dec": [first("CRVAL1", "RA_REF"), first("CRVAL2", "DEC_REF")],
        "pixel_scale": first("CDELT1", "CD1_1", "PIXSCAL1", default="N/A"),
        "wcs_projection": [first("CTYPE1", default="N/A"), first("CTYPE2", default="N/A")],
        "photometric_zero_point": first("MAGZPT", "MAGZERO", "ZP"),
        "bunit": header.get("BUNIT", "N/A"),
        "observation_id": first("OBSID", "EXPIDN", "PLATEID"),
        "data_source": first("SPHRSRC", default=survey_name),
    }
    return sanitize_json(fields)


def matrix_to_png_bytes(matrix: np.ndarray, cmap: str = "gray") -> bytes:
    """Renderiza uma matriz 2D em PNG, substituindo todos os valores não finitos."""
    data = np.asarray(matrix, dtype=np.float32)
    if data.ndim != 2 or not data.size:
        raise ValueError("A imagem FITS precisa ser uma matriz 2D não vazia.")
    finite = np.isfinite(data)
    fill = float(np.nanmin(data[finite])) if finite.any() else 0.0
    clean = np.nan_to_num(data, nan=fill, posinf=fill, neginf=fill)
    buf = io.BytesIO()
    plt.imsave(buf, clean, cmap=cmap, format="png", origin="lower")
    return buf.getvalue()


def matrix_to_png_bytes_scaled(matrix: np.ndarray, cmap: str, vmin: float, vmax: float) -> bytes:
    data = np.asarray(matrix, dtype=np.float32)
    if data.ndim != 2 or not data.size:
        raise ValueError("A imagem FITS precisa ser uma matriz 2D não vazia.")
    finite = np.isfinite(data)
    fill = vmin
    clean = np.nan_to_num(data, nan=fill, posinf=vmax, neginf=vmin)
    buf = io.BytesIO()
    plt.imsave(buf, clean, cmap=cmap, format="png", origin="lower", vmin=vmin, vmax=vmax)
    return buf.getvalue()


def apply_median_filter(matrix: np.ndarray) -> np.ndarray:
    """Reduz artefatos pontuais, preenchendo não finitos temporariamente."""
    data = np.asarray(matrix, dtype=np.float32)
    if data.ndim != 2:
        raise ValueError("O filtro de mediana aceita apenas matrizes 2D.")
    finite = np.isfinite(data)
    fill = float(np.median(data[finite])) if finite.any() else 0.0
    clean = np.nan_to_num(data, nan=fill, posinf=fill, neginf=fill)
    return median_filter(clean, size=3, mode="nearest")


class SpectrumRequest(BaseModel):
    text: Optional[str] = Field(None, max_length=1_000_000, description="Linhas CSV: wavelength,flux[,uncertainty].")
    wavelength: Optional[list[float]] = Field(None, min_length=2, max_length=10000)
    flux: Optional[list[float]] = Field(None, min_length=2, max_length=10000)
    uncertainty: Optional[list[float]] = Field(None, min_length=2, max_length=10000)
    title: str = Field("Espectro Quick-Look", max_length=160)
    wavelength_unit: str = Field("µm", max_length=24)
    flux_unit: str = Field("flux", max_length=40)

    @model_validator(mode="after")
    def validate_lengths(self):
        if self.text is not None:
            wavelengths, fluxes, uncertainties = [], [], []
            uncertainty_columns = set()
            for line_number, raw_line in enumerate(self.text.splitlines(), start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                columns = [column.strip() for column in line.split(",")]
                if len(columns) not in (2, 3):
                    raise ValueError(f"Linha {line_number}: informe wavelength,flux e incerteza opcional separados por vírgulas.")
                try:
                    values = [float(column) for column in columns]
                except ValueError as exc:
                    raise ValueError(f"Linha {line_number}: todos os campos precisam ser números.") from exc
                wavelengths.append(values[0])
                fluxes.append(values[1])
                uncertainty_columns.add(len(values) == 3)
                if len(values) == 3:
                    uncertainties.append(values[2])
                if len(wavelengths) > 10000:
                    raise ValueError("O espectro aceita no máximo 10.000 linhas de dados.")
            if len(uncertainty_columns) > 1:
                raise ValueError("Informe incerteza em todas as linhas ou em nenhuma.")
            if len(wavelengths) < 2:
                raise ValueError("Informe ao menos dois pontos espectrais.")
            self.wavelength = wavelengths
            self.flux = fluxes
            self.uncertainty = uncertainties if uncertainty_columns == {True} else None

        if self.wavelength is None or self.flux is None:
            raise ValueError("Envie o texto CSV ou os arrays wavelength e flux.")
        if len(self.wavelength) != len(self.flux):
            raise ValueError("wavelength e flux precisam ter o mesmo número de pontos.")
        if self.uncertainty is not None and len(self.uncertainty) != len(self.wavelength):
            raise ValueError("uncertainty precisa ter o mesmo número de pontos que wavelength.")
        if not all(np.isfinite(self.wavelength)) or not all(np.isfinite(self.flux)):
            raise ValueError("Os dados do espectro precisam ser finitos.")
        if any(value <= 0 for value in self.wavelength):
            raise ValueError("Os comprimentos de onda precisam ser positivos.")
        if self.uncertainty is not None and (not all(np.isfinite(self.uncertainty)) or any(v < 0 for v in self.uncertainty)):
            raise ValueError("As incertezas precisam ser finitas e não negativas.")
        return self


def _image_from_result(result, survey: str):
    if not result or len(result) == 0 or len(result[0]) == 0:
        raise LookupError(f"Sem cobertura do levantamento {survey} para essas coordenadas.")
    hdu = result[0][0]
    if hdu.data is None or np.asarray(hdu.data).ndim != 2:
        raise ValueError(f"O levantamento {survey} não retornou uma imagem 2D válida.")
    return hdu


async def fetch_survey(position: SkyCoord, radius: u.Quantity, survey: str, pixels: int = 500):
    result = await asyncio.to_thread(
        SkyView.get_images,
        position=position,
        survey=[survey],
        radius=radius,
        pixels=pixels,
        cache=False,
    )
    return _image_from_result(result, survey)


def _record_value(record, name, default=None):
    try:
        value = record.get(name, default)
    except AttributeError:
        try:
            value = record[name]
        except (KeyError, TypeError, IndexError):
            value = default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    return value


def _spherex_results(position: SkyCoord, collection: str, radius_deg: float, maxrec: int = 1000):
    retryable_messages = ("502 Server Error", "503 Server Error", "504 Server Error", "Proxy Error", "Bad Gateway")
    for attempt in range(2):
        try:
            session = _bound_http_session(requests.Session())
            try:
                service = vo.dal.SIA2Service(SPHEREX_SIA_URL, check_baseurl=False, session=session)
                return service.search(
                    pos=(position.ra.deg, position.dec.deg, radius_deg),
                    collection=collection,
                    maxrec=maxrec,
                )
            finally:
                session.close()
        except Exception as exc:
            if attempt == 1 or not any(token in str(exc) for token in retryable_messages):
                raise
            delay_seconds = 0.5
            logger.warning(
                "IRSA SIA retornou falha transitória (%s); uma nova tentativa ocorrerá em %ss.",
                exc, delay_seconds,
            )
            time.sleep(delay_seconds)


def _channel_wavelengths(hdul) -> np.ndarray:
    table = hdul["SPECTRAL_CHANNELS"].data
    names = {name.upper(): name for name in table.names}
    wavelength_column = names.get("WAVELENGTH")
    if wavelength_column is None:
        raise ValueError("O cubo não contém a coluna WAVELENGTH em SPECTRAL_CHANNELS.")
    wavelengths = np.asarray(table[wavelength_column], dtype=float).reshape(-1)
    if len(wavelengths) != 102:
        raise ValueError("A tabela SPECTRAL_CHANNELS não descreve os 102 canais do cubo.")
    return wavelengths


def _read_remote_cube_cutout(access_url: str, position: SkyCoord, fov: u.Quantity, *, mode: str, value: int):
    """Lê apenas os planos selecionados do cubo remoto usando HTTP range requests."""
    with _open_cube_hdul(access_url) as hdul:
        image_hdu = hdul["IMAGE"]
        if len(image_hdu.shape) != 3 or image_hdu.shape[0] != 102:
            raise ValueError("O produto IRSA não contém o cubo SPHEREx 102×512×512 esperado.")
        # The IMAGE header can include -TAB spectral coordinates whose lookup
        # table lives in another HDU. Pass the HDUList even though this reader
        # only needs the spatial axes, otherwise Astropy raises
        # "HDUList is required to retrieve -TAB coordinates" before it can
        # build the celestial WCS.
        cube_wcs = WCS(image_hdu.header, fobj=hdul).celestial
        x, y = cube_wcs.world_to_pixel(position)
        _, height, width = image_hdu.shape
        if not (-0.5 <= x < width - 0.5 and -0.5 <= y < height - 0.5):
            raise LookupError("O tile SPHEREx retornado não cobre as coordenadas consultadas.")

        wavelengths = _channel_wavelengths(hdul)
        if mode == "channel":
            if value < 1 or value > 102:
                raise ValueError("O canal SPHEREx precisa estar entre 1 e 102.")
            channels = [value]
        elif mode == "detector":
            if value not in SPHEREX_DETECTOR_CHANNELS:
                raise ValueError("O detector SPHEREx precisa estar entre 1 e 6.")
            channels = list(SPHEREX_DETECTOR_CHANNELS[value])
        else:
            raise ValueError("O modo SPHEREx precisa ser 'channel' ou 'detector'.")
        channels = [channel for channel in channels if channel not in SPHEREX_BLANK_CHANNELS]
        if not channels:
            raise ValueError("A seleção não contém canais SPHEREx com dados no DR1.")

        image_planes = np.stack([image_hdu.section[channel - 1, :, :] for channel in channels])
        nhits_hdu = hdul["NHITS"]
        flags_hdu = hdul["FLAGS"]
        hit_planes = np.stack([nhits_hdu.section[channel - 1, :, :] for channel in channels])
        flag_planes = np.stack([flags_hdu.section[channel - 1, :, :] for channel in channels]).astype(np.uint32)
        image_planes = np.where((hit_planes > 0) & np.isfinite(image_planes), image_planes, np.nan)
        with np.errstate(invalid="ignore"):
            image = np.nanmean(image_planes, axis=0)
        hits = np.sum(np.where(hit_planes > 0, hit_planes, 0), axis=0)
        flags = np.bitwise_or.reduce(flag_planes, axis=0)
        image[hits == 0] = np.nan

        cutout = Cutout2D(
            image,
            position=position,
            size=(2 * fov, 2 * fov),
            wcs=cube_wcs,
            mode="partial",
            fill_value=np.nan,
        )
        hits_cutout = Cutout2D(
            hits,
            position=position,
            size=(2 * fov, 2 * fov),
            wcs=cube_wcs,
            mode="partial",
            fill_value=0,
        ).data
        flags_cutout = Cutout2D(
            flags,
            position=position,
            size=(2 * fov, 2 * fov),
            wcs=cube_wcs,
            mode="partial",
            fill_value=0,
        ).data

        header = cutout.wcs.to_header()
        for key in ("HEALPIX", "HpxOrder", "HpxNside", "BUNIT", "DATAMIN", "DATAMAX"):
            if key in image_hdu.header:
                header[key] = image_hdu.header[key]
        header["TELESCOP"] = "SPHEREx"
        header["DATAPROD"] = "DR1 All-Sky Cube"
        header["SPHMODE"] = mode
        header["SPHVAL"] = value
        if mode == "channel":
            header["SPHBAND"] = value
            header["SPHWAVE"] = (float(wavelengths[value - 1]), "Nominal central wavelength [um]")
        else:
            header["DETECTOR"] = value
            header["SPHWAVE"] = (float(np.nanmean(wavelengths[np.asarray(channels) - 1])), "Mean nominal wavelength [um]")
            header["CHMIN"] = channels[0]
            header["CHMAX"] = channels[-1]

        finite_hits = hits_cutout[np.isfinite(hits_cutout) & (hits_cutout > 0)]
        flag_definitions = _extract_spherex_flag_definitions(flags_hdu.header)
        flag_counts = {
            name: int(np.count_nonzero((flags_cutout & (1 << bit)) != 0))
            for name, bit in flag_definitions.items()
        }
        quality = {
            "covered_pixels": int(np.count_nonzero(np.isfinite(cutout.data))),
            "total_pixels": int(cutout.data.size),
            "flagged_pixels": int(np.count_nonzero(flags_cutout)),
            "flag_counts": flag_counts,
            "nhits_min": int(np.min(finite_hits)) if finite_hits.size else 0,
            "nhits_max": int(np.max(finite_hits)) if finite_hits.size else 0,
            "nhits_mean": float(np.mean(finite_hits)) if finite_hits.size else 0.0,
            "flag_definitions": flag_definitions,
        }
        selected_wavelengths = [float(wavelengths[channel - 1]) for channel in channels]
        return fits.PrimaryHDU(data=cutout.data, header=header), quality, selected_wavelengths


async def fetch_spherex_cutout(position: SkyCoord, fov: u.Quantity, band: int, mode: str = "channel"):
    """Race IRSA SIA2 against the public AWS mirror and return the first image."""
    radius_deg = fov.to_value(u.deg)

    def fetch_sia():
        results = _spherex_results(position, "spherex_dr1_cube", radius_deg, maxrec=20)
        last_error = None
        for record in results:
            access_url = _record_value(record, "access_url")
            if not access_url:
                continue
            try:
                hdu, quality, wavelengths = _read_remote_cube_cutout(
                    str(access_url), position, fov, mode=mode, value=band
                )
                hdu.header["SPHRSRC"] = "IRSA SIA2"
                return hdu, quality, wavelengths
            except LookupError:
                continue
            except Exception as exc:
                last_error = exc
                logger.warning("Não foi possível ler o tile SPHEREx do IRSA %s: %s", access_url, exc)
        if last_error:
            raise RuntimeError(f"Os tiles SPHEREx do IRSA não puderam ser lidos: {last_error}") from last_error
        raise LookupError("O índice SIA2 não encontrou um tile SPHEREx com cobertura para esta coordenada.")

    def fetch_aws():
        hdu, quality, wavelengths = _read_remote_cube_cutout(
            _spherex_s3_cube_url(position), position, fov, mode=mode, value=band
        )
        hdu.header["SPHRSRC"] = "AWS Open Data S3"
        return hdu, quality, wavelengths

    tasks = {
        asyncio.create_task(asyncio.to_thread(fetch_sia)),
        asyncio.create_task(asyncio.to_thread(fetch_aws)),
    }
    failures = []
    try:
        while tasks:
            done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    result = task.result()
                except Exception as exc:
                    failures.append(exc)
                    continue
                for pending in tasks:
                    pending.cancel()
                return result
    finally:
        for pending in tasks:
            pending.cancel()

    if failures and all(isinstance(exc, LookupError) for exc in failures):
        raise LookupError("Nem o índice SIA2 nem o cubo SPHEREx DR1 no espelho AWS cobrem esta coordenada.")
    details = "; ".join(f"{type(exc).__name__}: {exc}" for exc in failures)
    raise RuntimeError(f"Falharam as consultas paralelas ao IRSA SIA2 e ao espelho AWS ({details}).")


def _read_remote_cube_spectrum(access_url: str, position: SkyCoord):
    """Extract an uncalibrated 3×3-pixel quick-look spectrum from the DR1 cube."""
    with _open_cube_hdul(access_url) as hdul:
        image_hdu = hdul["IMAGE"]
        cube_wcs = WCS(image_hdu.header, fobj=hdul).celestial
        x, y = cube_wcs.world_to_pixel(position)
        _, height, width = image_hdu.shape
        if not (-0.5 <= x < width - 0.5 and -0.5 <= y < height - 0.5):
            raise LookupError("O tile SPHEREx não cobre a coordenada para extração do espectro.")
        x_center, y_center = int(round(x)), int(round(y))
        x0, x1 = max(0, x_center - 1), min(width, x_center + 2)
        y0, y1 = max(0, y_center - 1), min(height, y_center + 2)
        image = np.asarray(image_hdu.section[:, y0:y1, x0:x1], dtype=np.float32)
        hits = np.asarray(hdul["NHITS"].section[:, y0:y1, x0:x1])
        flags = np.asarray(hdul["FLAGS"].section[:, y0:y1, x0:x1], dtype=np.uint32)
        wavelengths = _channel_wavelengths(hdul)

        valid = (hits > 0) & np.isfinite(image)
        image = np.where(valid, image, np.nan)
        with np.errstate(invalid="ignore"):
            flux = np.nanmedian(image, axis=(1, 2))
        channels = np.arange(1, 103)
        keep = np.isfinite(flux) & np.isfinite(wavelengths) & ~np.isin(channels, tuple(SPHEREX_BLANK_CHANNELS))
        quality = {
            "aperture_pixels": int((x1 - x0) * (y1 - y0)),
            "channels_with_coverage": int(np.count_nonzero(keep)),
            "flagged_samples": int(np.count_nonzero(flags)),
            "nhits_median": float(np.nanmedian(hits[hits > 0])) if np.any(hits > 0) else 0.0,
            "extraction": "median of covered pixels in a 3x3 aperture; MJy/sr; not PSF photometry",
        }
        if np.count_nonzero(keep) < 2:
            raise LookupError("O cubo não tem cobertura suficiente para gerar um espectro nesta coordenada.")
        return wavelengths[keep], flux[keep], quality


async def fetch_spherex_cube_spectrum(position: SkyCoord):
    """Race the IRSA index and AWS mirror for a real DR1 quick-look spectrum."""
    def fetch_sia():
        results = _spherex_results(position, "spherex_dr1_cube", 1 / 60, maxrec=20)
        last_error = None
        for record in results:
            access_url = _record_value(record, "access_url")
            if not access_url:
                continue
            try:
                wavelengths, flux, quality = _read_remote_cube_spectrum(str(access_url), position)
                quality["data_source"] = "IRSA SIA2"
                return wavelengths, flux, quality
            except LookupError:
                continue
            except Exception as exc:
                last_error = exc
                logger.warning("Não foi possível extrair o espectro do tile SPHEREx %s: %s", access_url, exc)
        if last_error:
            raise RuntimeError(f"O tile SPHEREx do IRSA não pôde ser lido: {last_error}") from last_error
        raise LookupError("O índice SIA2 não encontrou um tile para extração espectral nesta coordenada.")

    def fetch_aws():
        wavelengths, flux, quality = _read_remote_cube_spectrum(_spherex_s3_cube_url(position), position)
        quality["data_source"] = "AWS Open Data S3"
        return wavelengths, flux, quality

    tasks = {
        asyncio.create_task(asyncio.to_thread(fetch_sia)),
        asyncio.create_task(asyncio.to_thread(fetch_aws)),
    }
    failures = []
    try:
        while tasks:
            done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    result = task.result()
                except Exception as exc:
                    failures.append(exc)
                    continue
                for pending in tasks:
                    pending.cancel()
                return result
    finally:
        for pending in tasks:
            pending.cancel()

    if failures and all(isinstance(exc, LookupError) for exc in failures):
        raise LookupError("Nem o índice SIA2 nem o cubo SPHEREx DR1 no espelho AWS cobrem esta coordenada.")
    details = "; ".join(f"{type(exc).__name__}: {exc}" for exc in failures)
    raise RuntimeError(f"Falharam as consultas espectrais paralelas ao IRSA e ao espelho AWS ({details}).")


def _spherex_s3_cube_url(position: SkyCoord) -> str:
    """Build the public DR1 All-Sky Cube URL for the position's order-5 HEALPix tile."""
    from astropy_healpix import HEALPix

    healpix = HEALPix(nside=32, order="nested", frame=ICRS())
    pixel = int(healpix.skycoord_to_healpix(position.icrs))
    directory = (pixel // 10000) * 10000
    return f"{SPHEREX_S3_CUBE_ROOT}/Norder5/Dir{directory}/Npix{pixel}_cube.fits"


def _spherex_observation_time(record) -> float:
    value = _record_value(record, "t_min")
    if value is None:
        raise ValueError("A consulta SIA não retornou t_min para a imagem SPHEREx.")
    return float(value)


def _cutout_url(access_url: str, position: SkyCoord, fov: u.Quantity) -> str:
    size_deg = (2 * fov).to_value(u.deg)
    parsed = urlsplit(access_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in {"center", "size"}
    ]
    query.extend([
        ("center", f"{position.ra.deg:.8f},{position.dec.deg:.8f}d"),
        ("size", f"{size_deg:.8f}"),
    ])
    return urlunsplit(parsed._replace(query=urlencode(query, safe=",d")))


def _read_spherex_exposure(record, position: SkyCoord, fov: u.Quantity):
    access_url = str(_record_value(record, "access_url"))
    collection = str(_record_value(record, "obs_collection", "SPHEREx"))
    exposure_time = _spherex_observation_time(record)
    cutout_url = _cutout_url(access_url, position, fov)
    with fits.open(cutout_url, cache=False, memmap=False) as hdul:
        image_hdu = hdul["IMAGE"]
        source_image = np.asarray(image_hdu.data, dtype=np.float32)
        header = image_hdu.header
        spatial_wcs = WCS(header, fobj=hdul).celestial
        x, y = spatial_wcs.world_to_pixel(position)
        height, width = source_image.shape
        if not np.isfinite(x) or not np.isfinite(y) or not (-0.5 <= x < width - 0.5 and -0.5 <= y < height - 0.5):
            raise LookupError("O recorte SPHEREx não contém o pixel correspondente às coordenadas consultadas.")

        cutout_size = (2 * fov, 2 * fov)
        cutout = Cutout2D(
            source_image,
            position=position,
            size=cutout_size,
            wcs=spatial_wcs,
            mode="partial",
            fill_value=np.nan,
        )
        image = np.asarray(cutout.data, dtype=np.float32).copy()
        if "ZODI" in hdul and hdul["ZODI"].data is not None:
            zodi = Cutout2D(
                np.asarray(hdul["ZODI"].data, dtype=np.float32),
                position=position,
                size=cutout_size,
                wcs=spatial_wcs,
                mode="partial",
                fill_value=np.nan,
            ).data
            image -= np.asarray(zodi, dtype=np.float32)

        quality = {"flagged_pixels": 0, "masked_pixels": 0, "variance_available": "VARIANCE" in hdul}
        if "FLAGS" in hdul and hdul["FLAGS"].data is not None:
            flags = Cutout2D(
                np.asarray(hdul["FLAGS"].data, dtype=np.uint32),
                position=position,
                size=cutout_size,
                wcs=spatial_wcs,
                mode="partial",
                fill_value=0,
            ).data
            bad_mask = np.zeros(flags.shape, dtype=bool)
            flag_header = hdul["FLAGS"].header
            quality["flagged_pixels"] = int(np.count_nonzero(flags))
            definitions, flag_counts = _extract_spherex_flag_definitions(flag_header), {}
            for name, bit in definitions.items():
                bad_mask |= (flags & (1 << bit)) != 0
                flag_counts[name] = int(np.count_nonzero((flags & (1 << bit)) != 0))
            image[bad_mask] = np.nan
            quality["masked_pixels"] = int(np.count_nonzero(bad_mask))
            quality["bad_flag_bit_positions"] = definitions
            quality["flag_counts"] = flag_counts

        spectral_wcs = WCS(header, fobj=hdul, key="W")
        spectral_wcs.sip = None
        wavelength, bandwidth = spectral_wcs.pixel_to_world(x, y)
        wavelength_um = float(wavelength.to_value(u.um)) if hasattr(wavelength, "to_value") else float(wavelength)
        bandwidth_um = float(bandwidth.to_value(u.um)) if hasattr(bandwidth, "to_value") else float(bandwidth)
        primary_header = header.copy()
        for key in ("XTENSION", "PCOUNT", "GCOUNT", "EXTNAME", "CHECKSUM", "DATASUM"):
            primary_header.remove(key, ignore_missing=True, remove_all=True)
        primary_header.update(cutout.wcs.to_header(relax=True))
        hdu = fits.PrimaryHDU(data=image, header=primary_header)

    when = Time(exposure_time, format="mjd", scale="utc").isot
    metadata = extract_safe_fits_metadata(hdu.header, collection)
    metadata["observation_id"] = (
        metadata.get("observation_id")
        or _record_value(record, "obs_id")
        or _record_value(record, "obs_publisher_did", "N/A")
    )
    metadata.update({
        "date_observed": when,
        "wavelength_um": wavelength_um,
        "bandwidth_um": bandwidth_um,
        "detector_bandpass": _record_value(record, "energy_bandpassname", "N/A"),
        "data_release_collection": collection,
        "observation_mjd": exposure_time,
        "observation_time_utc": when,
        "data_quality": quality,
    })
    return hdu, metadata


def _temporal_candidate_pairs(rows, max_samples: int = 32, max_pairs: int = 96):
    """Sample observations across the full timeline and pair dates at least 30 days apart."""
    if len(rows) < 2:
        return []
    sample_count = min(len(rows), max_samples)
    sample_indices = np.linspace(0, len(rows) - 1, sample_count, dtype=int)
    sampled_rows = [rows[index] for index in np.unique(sample_indices)]
    candidate_pairs = []
    for index, candidate_first in enumerate(sampled_rows[:-1]):
        later_rows = [row for row in sampled_rows[index + 1:] if row[0] - candidate_first[0] >= 30]
        if not later_rows:
            continue
        later_indices = sorted({0, len(later_rows) // 2, len(later_rows) - 1})
        candidate_pairs.extend((candidate_first, later_rows[later_index]) for later_index in later_indices)
    candidate_pairs.sort(key=lambda pair: pair[1][0] - pair[0][0], reverse=True)
    return candidate_pairs[:max_pairs]


async def fetch_spherex_temporal_pair(position: SkyCoord, fov: u.Quantity, detector: int):
    """Find the earliest/latest matching DR1 and QR3 cutouts for one detector band."""
    if detector not in range(1, 7):
        raise ValueError("O detector SPHEREx deve estar entre 1 e 6.")

    def _sync_fetch():
        rows = []
        for collection in SPHEREX_IMAGE_COLLECTIONS:
            results = _spherex_results(position, collection, fov.to_value(u.deg), maxrec=1000)
            for record in results:
                bandpass = str(_record_value(record, "energy_bandpassname", ""))
                if bandpass.casefold() != f"spherex-d{detector}".casefold():
                    continue
                access_url = _record_value(record, "access_url")
                if not access_url:
                    continue
                try:
                    mjd = _spherex_observation_time(record)
                except (TypeError, ValueError):
                    continue
                rows.append((mjd, collection, record))
        if len(rows) < 2:
            raise LookupError(f"O IRSA retornou menos de duas imagens SPHEREx para o detector D{detector}.")
        rows.sort(key=lambda item: item[0])
        first = rows[0]
        later = next((row for row in reversed(rows) if row[0] - first[0] >= 30), None)
        if later is None:
            raise LookupError("As imagens SPHEREx disponíveis não têm intervalo temporal de pelo menos 30 dias.")

        candidate_pairs = _temporal_candidate_pairs(rows)
        unique_rows = {}
        for candidate_first, candidate_last in candidate_pairs:
            unique_rows[str(_record_value(candidate_first[2], "access_url"))] = candidate_first
            unique_rows[str(_record_value(candidate_last[2], "access_url"))] = candidate_last
        wavelength_failures = []
        coverage_failures = []
        download_failures = []
        loaded_observations = {}

        def fetch_one(item):
            access_url, row = item
            try:
                return access_url, "ok", _read_spherex_exposure(row[2], position, fov)
            except LookupError as exc:
                return access_url, "coverage", str(exc)
            except Exception as exc:
                return access_url, "download", str(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            for access_url, status, value in executor.map(fetch_one, unique_rows.items()):
                if status == "ok":
                    loaded_observations[access_url] = value
                elif status == "coverage":
                    coverage_failures.append(value)
                else:
                    download_failures.append(value)

        best_pair, best_delta = None, float("inf")
        for candidate_first, candidate_last in candidate_pairs:
            url1 = str(_record_value(candidate_first[2], "access_url"))
            url2 = str(_record_value(candidate_last[2], "access_url"))
            if url1 not in loaded_observations or url2 not in loaded_observations:
                continue
            hdu1, metadata1 = loaded_observations[url1]
            hdu2, metadata2 = loaded_observations[url2]
            delta_wavelength = abs(metadata1["wavelength_um"] - metadata2["wavelength_um"])
            tolerance = max(metadata1["bandwidth_um"], metadata2["bandwidth_um"]) * 0.5
            comparison = {"wavelength_match_tolerance_um": tolerance, "wavelength_delta_um": delta_wavelength}
            # Uma exposição aparece em vários pares; registre o resultado do par sem alterar a exposição em cache.
            pair = (hdu1, {**metadata1, **comparison}), (hdu2, {**metadata2, **comparison})
            if delta_wavelength > tolerance:
                wavelength_failures.append("As exposições disponíveis não têm comprimentos de onda compatíveis no alvo.")
                # Só aceita fallback espectral próximo quando os metadados são de observações reais.
                if (delta_wavelength <= tolerance * 6.0
                        and "observation_mjd" in metadata1
                        and "observation_mjd" in metadata2
                        and delta_wavelength < best_delta):
                    best_pair, best_delta = pair, delta_wavelength
                continue
            return pair
        if best_pair is not None:
            return best_pair
        # An observed spectral mismatch or a cutout outside the image footprint
        # is a coverage result, even if another candidate had a transient fetch
        # error. Only report 502 when no candidate could be evaluated at all.
        if wavelength_failures:
            raise LookupError(wavelength_failures[-1])
        if coverage_failures:
            raise LookupError(coverage_failures[-1])
        if download_failures:
            raise RuntimeError(
                f"Falha ao baixar/processar recortes SPHEREx: {download_failures[-1]}"
            )
        raise LookupError("Não há um par de épocas SPHEREx com cobertura temporal suficiente.")

    return await asyncio.to_thread(_sync_fetch)


def _bilinear_sample(data: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Amostra uma imagem em coordenadas fracionárias sem dependência extra."""
    height, width = data.shape
    valid = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (y >= 0) & (x < width - 1) & (y < height - 1)
    out = np.full(x.shape, np.nan, dtype=np.float32)
    if not valid.any():
        return out
    xv, yv = x[valid], y[valid]
    x0, y0 = np.floor(xv).astype(int), np.floor(yv).astype(int)
    dx, dy = xv - x0, yv - y0
    corners = np.stack((data[y0, x0], data[y0, x0 + 1], data[y0 + 1, x0], data[y0 + 1, x0 + 1]))
    weights = np.stack(((1-dx)*(1-dy), dx*(1-dy), (1-dx)*dy, dx*dy))
    good = np.isfinite(corners).all(axis=0)
    sampled = np.full(xv.shape, np.nan, dtype=np.float32)
    sampled[good] = np.sum(corners[:, good] * weights[:, good], axis=0)
    out[valid] = sampled
    return out


def reproject_to_reference(source_hdu, reference_hdu) -> tuple[np.ndarray, np.ndarray]:
    """Reprojeta a fonte para a grade WCS da referência por interpolação bilinear."""
    source = np.asarray(source_hdu.data, dtype=np.float32)
    reference = np.asarray(reference_hdu.data, dtype=np.float32)
    source_wcs, reference_wcs = WCS(source_hdu.header).celestial, WCS(reference_hdu.header).celestial
    if not source_wcs.has_celestial or not reference_wcs.has_celestial:
        raise ValueError("As duas imagens precisam conter WCS celestial para subtração alinhada.")
    yy, xx = np.indices(reference.shape, dtype=np.float64)
    try:
        world_ra, world_dec = reference_wcs.all_pix2world(xx, yy, 0)
        source_x, source_y = source_wcs.all_world2pix(world_ra, world_dec, 0, quiet=True)
    except Exception:
        world = reference_wcs.pixel_to_world_values(xx, yy)
        source_x, source_y = source_wcs.world_to_pixel_values(*world)
    return _bilinear_sample(source, source_x, source_y), reference


def _normalize(data: np.ndarray, median: float, std: float) -> np.ndarray:
    return (data - median) / (std if std > 1e-12 else 1.0)


@app.get("/api/catalog", responses={200: {"description": "Alvos SPHEREx e objetos celestes conhecidos."}})
async def get_celestial_catalog():
    """Retorna os presets astrométricos e parâmetros recomendados da interface."""
    return JSONResponse({"items": CELESTIAL_CATALOG})


@app.get("/api/ephemerides/mars", response_model=None)
def get_mars_geometry(
    instant: str = Query(..., description="Data e hora ISO 8601 com fuso explícito."),
) -> MarsGeometry:
    """Retorna as posições heliocêntricas e as distâncias de Marte em au."""
    try:
        return mars_geometry(instant)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/ephemerides/solar-system", response_model=None)
def get_solar_simulation(
    instant: str = Query(..., description="Instante consultado ou início do recorte, em ISO 8601."),
    end: str | None = Query(None, description="Fim opcional do recorte, em ISO 8601."),
) -> SolarSimulation:
    """Retorna a geometria heliocêntrica e as amostras do recorte ou da janela padrão de 720 dias."""
    try:
        return solar_simulation(instant, end=end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/blink_with_metadata")
async def get_blink_image_metadata(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    epoch: str = Query("1", pattern="^[12]$"),
    fov: float = Query(5.0, gt=0, le=60, description="Raio da região consultada, em minutos de arco."),
    apply_filter: bool = Query(False, alias="filter", description="Aplica filtro de mediana 3×3 à imagem retornada."),
):
    try:
        coord = parse_coordinates(ra, dec)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Coordenadas RA/Dec inválidas.") from exc
    survey = "DSS1 Blue" if epoch == "1" else "DSS2 Blue"
    try:
        hdu = await fetch_survey(coord, fov * u.arcmin, survey)
        matrix = apply_median_filter(hdu.data) if apply_filter else hdu.data
        image = base64.b64encode(matrix_to_png_bytes(matrix, "gray")).decode("ascii")
        return JSONResponse({
            "metadata": extract_safe_fits_metadata(hdu.header, survey),
            "image_data": f"data:image/png;base64,{image}",
        })
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Não há imagens disponíveis no levantamento {survey} para esta região. "
                "Sugerimos realizar a análise com o Espectro Quick-Look, enviando dados espectrais em /api/spectrum."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha ao consultar ou processar o SkyView.") from exc


@app.get("/api/subtract")
async def get_subtracted_image(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    fov: float = Query(5.0, gt=0, le=60, description="Raio da região consultada, em minutos de arco."),
    apply_filter: bool = Query(False, alias="filter", description="Aplica filtro de mediana 3×3 para reduzir artefatos pontuais."),
):
    try:
        coord = parse_coordinates(ra, dec)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Coordenadas RA/Dec inválidas.") from exc
    try:
        hdu1, hdu2 = await asyncio.gather(
            fetch_survey(coord, fov * u.arcmin, "DSS1 Blue"),
            fetch_survey(coord, fov * u.arcmin, "DSS2 Blue"),
        )
        first, second = reproject_to_reference(hdu1, hdu2)
        valid = np.isfinite(first) & np.isfinite(second)
        if apply_filter:
            first, second = apply_median_filter(first), apply_median_filter(second)
            first[~valid], second[~valid] = np.nan, np.nan
        if valid.sum() < 4:
            raise LookupError("As imagens DSS1 e DSS2 não têm área comum suficiente para a subtração.")
        first_values, second_values = first[valid], second[valid]
        first_norm = _normalize(first, float(np.median(first_values)), float(np.std(first_values)))
        second_norm = _normalize(second, float(np.median(second_values)), float(np.std(second_values)))
        difference = np.where(valid, second_norm - first_norm, np.nan)
        return StreamingResponse(io.BytesIO(matrix_to_png_bytes(difference)), media_type="image/png")
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Não há imagens alinháveis disponíveis para esta região ({exc}). "
                "Sugerimos realizar a análise com o Espectro Quick-Look, enviando dados espectrais em /api/spectrum."
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha ao consultar ou alinhar as imagens no SkyView.") from exc


@app.get("/api/add")
async def get_added_images(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    fov: float = Query(5.0, gt=0, le=60, description="Raio da região consultada, em minutos de arco."),
    apply_filter: bool = Query(False, alias="filter", description="Aplica filtro de mediana 3×3 antes da soma."),
):
    """Combina imagens ópticas DSS1/DSS2 como alternativa ao stack temporal SPHEREx."""
    try:
        coord = parse_coordinates(ra, dec)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Coordenadas RA/Dec inválidas.") from exc
    try:
        hdu1, hdu2 = await asyncio.gather(
            fetch_survey(coord, fov * u.arcmin, "DSS1 Blue"),
            fetch_survey(coord, fov * u.arcmin, "DSS2 Blue"),
        )
        second, first = reproject_to_reference(hdu2, hdu1)
        first = np.asarray(first, dtype=np.float32)
        valid = np.isfinite(first) & np.isfinite(second)
        if apply_filter:
            first, second = apply_median_filter(first), apply_median_filter(second)
            first[~valid], second[~valid] = np.nan, np.nan
        if valid.sum() < 4:
            raise LookupError("As imagens DSS1 e DSS2 não têm área comum suficiente para a soma.")
        first_values, second_values = first[valid], second[valid]
        first_norm = _normalize(first, float(np.median(first_values)), float(np.std(first_values)))
        second_norm = _normalize(second, float(np.median(second_values)), float(np.std(second_values)))
        combined = np.where(valid, first_norm + second_norm, np.nan)
        return StreamingResponse(io.BytesIO(matrix_to_png_bytes(combined)), media_type="image/png")
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Não há imagens DSS1/DSS2 alinháveis disponíveis para esta região ({exc}).",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha ao consultar ou combinar as imagens no SkyView.") from exc


@app.get(
    "/api/infrared",
    responses={
        200: {"description": "Imagem infravermelha PNG retornada com sucesso."},
        404: {
            "model": OutOfCoverageError,
            "description": "O survey solicitado não retornou imagem para a região consultada.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Não há imagens disponíveis para esta região neste survey. "
                            "Sugerimos a análise pelo Espectro Quick-Look com dados enviados em /api/spectrum."
                        ),
                        "survey": "WISE 3.4",
                        "coordinates": "15.5, -30.2",
                        "fov": 0.1,
                    }
                }
            },
        },
        502: {"description": "Falha ao consultar ou processar o survey no SkyView."},
    },
)
async def get_infrared_image(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    fov: float = Query(0.1, gt=0, le=2, description="Raio da região consultada, em graus."),
    band: str = Query("WISE 3.4", max_length=40),
    survey: Optional[str] = Query(None, max_length=40),
    apply_filter: bool = Query(False, alias="filter", description="Aplica filtro de mediana 3×3 para reduzir artefatos pontuais."),
):
    try:
        coord = parse_coordinates(ra, dec)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Coordenadas RA/Dec inválidas.") from exc
    try:
        selected_survey = resolve_infrared_survey(survey or band)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        # IR surveys are often much coarser than the DSS grid. A 384px cutout
        # avoids paying for oversampling while remaining crisp in the viewer.
        hdu = await fetch_survey(coord, fov * u.deg, selected_survey, pixels=384)
        matrix = np.asarray(hdu.data, dtype=np.float32)
        finite = matrix[np.isfinite(matrix)]
        if finite.size == 0:
            raise ValueError("A imagem infravermelha não contém pixels finitos.")
        fill = float(np.nanpercentile(finite, 5))
        matrix = np.nan_to_num(matrix, nan=fill, posinf=fill, neginf=fill)
        if apply_filter:
            matrix = apply_median_filter(matrix)
        normalized = ImageNormalize(matrix, interval=ZScaleInterval(), stretch=LogStretch())(matrix)
        return StreamingResponse(io.BytesIO(matrix_to_png_bytes(normalized, "magma")), media_type="image/png")
    except LookupError as exc:
        return JSONResponse(
            status_code=404,
            content=OutOfCoverageError(
                detail=(
                    f"O SkyView não retornou imagens para o survey '{selected_survey}' em "
                    f"RA={ra}, Dec={dec}, FOV={fov}°. Isso significa que não há "
                    "imagem disponível para essa região nesse survey. Tente ampliar o FOV "
                    "ou selecione outro survey infravermelho suportado. Se nenhum tiver cobertura, "
                    "sugerimos a análise através do Espectro Quick-Look com dados espectrais em /api/spectrum."
                ),
                survey=selected_survey,
                coordinates=f"{ra}, {dec}",
                fov=fov,
            ).model_dump(),
        )
    except Exception as exc:
        logger.exception("Falha no survey infravermelho %s", selected_survey)
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar ou processar o survey infravermelho '{selected_survey}' no SkyView.",
        ) from exc


@app.get(
    "/api/spherex/band",
    responses={
        200: {"description": "Imagem PNG de um canal do cubo SPHEREx DR1."},
        404: {"description": "O IRSA não retornou um tile que cubra esta coordenada."},
        422: {"description": "Coordenadas, FOV ou banda inválidos."},
        502: {"description": "Falha ao consultar ou baixar o cubo SPHEREx no IRSA."},
    },
)
async def get_spherex_band_image(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    band: int = Query(15, ge=1, le=102, description="Canal (1–102) ou detector (1–6), conforme mode."),
    mode: str = Query("channel", pattern="^(channel|detector)$", description="Imagem de um canal ou média dos 17 canais do detector."),
    fov: float = Query(5.0, gt=0, le=60, description="Raio do recorte, em minutos de arco."),
    apply_filter: bool = Query(False, alias="filter"),
):
    try:
        coord = parse_coordinates(ra, dec)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Coordenadas RA/Dec inválidas.") from exc
    if mode == "channel" and band in SPHEREX_BLANK_CHANNELS:
        raise HTTPException(
            status_code=422,
            detail="Os canais 51 e 52 correspondem a frames em branco no cubo all-sky SPHEREx DR1.",
        )
    try:
        hdu, quality, wavelengths = await fetch_spherex_cutout(coord, fov * u.arcmin, band, mode=mode)
        matrix = np.asarray(hdu.data, dtype=np.float32)
        finite = matrix[np.isfinite(matrix)]
        if finite.size == 0:
            raise LookupError("O canal SPHEREx não contém pixels válidos neste recorte.")
        fill = float(np.percentile(finite, 5))
        matrix = np.nan_to_num(matrix, nan=fill, posinf=fill, neginf=fill)
        if apply_filter:
            matrix = apply_median_filter(matrix)
        normalized = ImageNormalize(matrix, interval=ZScaleInterval(), stretch=LogStretch())(matrix)
        image = base64.b64encode(matrix_to_png_bytes(normalized, "magma")).decode("ascii")
        metadata = extract_safe_fits_metadata(hdu.header, f"SPHEREx DR1 {mode} {band}")
        metadata.update({
            "wavelengths_um": wavelengths,
            "data_quality": quality,
            "data_source": quality.get("data_source", metadata.get("data_source")),
            "projection_warning": "O cubo é um mosaico HEALPix (HPX); a exibição preserva sua projeção local.",
        })
        return JSONResponse({
            "metadata": metadata,
            "band": band,
            "mode": mode,
            "epoch": "DR1 All-Sky Cube (Surveys 1 + 2 combinados)",
            "source": metadata.get("data_source"),
            "image_data": f"data:image/png;base64,{image}",
        })
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao consultar SPHEREx DR1 band %s", band)
        cause = exc
        while cause.__cause__ is not None:
            cause = cause.__cause__
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar ou processar o cubo SPHEREx DR1 no IRSA ({type(cause).__name__}: {cause}).",
        ) from exc


@app.get("/api/spherex/spectrum", responses={
    200: {"description": "Espectro rápido extraído do cubo All-Sky SPHEREx DR1, em PNG."},
    404: {"description": "O cubo não tem cobertura suficiente nesta coordenada."},
    502: {"description": "Falha na consulta ao IRSA ou na leitura do cubo."},
})
async def get_spherex_spectrum(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
):
    try:
        coord = parse_coordinates(ra, dec)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Coordenadas RA/Dec inválidas.") from exc
    try:
        wavelengths, flux, quality = await fetch_spherex_cube_spectrum(coord)
        png = _spectrum_png_bytes(
            wavelengths,
            flux,
            title="SPHEREx DR1 — espectro Quick-Look da abertura 3×3",
            flux_unit="MJy/sr (mediana da abertura)",
        )
        encoded = base64.b64encode(png).decode("ascii")
        return JSONResponse({
            "image_data": f"data:image/png;base64,{encoded}",
            "wavelengths_um": wavelengths.tolist(),
            "flux_mjy_sr": flux.tolist(),
            "data_quality": quality,
            "source": quality.get("data_source", "SPHEREx DR1 All-Sky Cube"),
            "blank_channels_skipped": sorted(SPHEREX_BLANK_CHANNELS),
        })
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao extrair espectro SPHEREx para %s, %s", ra, dec)
        raise HTTPException(status_code=502, detail="Falha ao extrair o espectro do cubo SPHEREx DR1 no IRSA.") from exc


def _align_temporal_pair(pair):
    (hdu1, metadata1), (hdu2, metadata2) = pair
    first, second = reproject_to_reference(hdu1, hdu2)
    valid = np.isfinite(first) & np.isfinite(second)
    if valid.sum() < 4:
        raise LookupError("As imagens SPHEREx não têm área comum suficiente depois do alinhamento WCS.")
    return first, second, valid, hdu2.header, metadata1, metadata2


def _compose_temporal_pair(first, second, valid, operation: str, apply_filter: bool):
    first = np.asarray(first, dtype=np.float32).copy()
    second = np.asarray(second, dtype=np.float32).copy()
    if apply_filter:
        first, second = apply_median_filter(first), apply_median_filter(second)
        first[~valid], second[~valid] = np.nan, np.nan
    if operation == "subtract":
        first_norm = _normalize(first, float(np.median(first[valid])), float(np.std(first[valid])))
        second_norm = _normalize(second, float(np.median(second[valid])), float(np.std(second[valid])))
        return np.where(valid, second_norm - first_norm, np.nan)
    if operation == "add":
        return np.where(valid, first + second, np.nan)
    raise ValueError("Operação temporal desconhecida.")


def _crossfade_gif(first_png: bytes, second_png: bytes, frames: int = 12) -> bytes:
    """Cria uma animação de comparação entre épocas; não estima movimento próprio."""
    with Image.open(io.BytesIO(first_png)) as first_image, Image.open(io.BytesIO(second_png)) as second_image:
        first = first_image.convert("RGB")
        second = second_image.convert("RGB")
        if first.size != second.size:
            second = second.resize(first.size, Image.Resampling.BILINEAR)
        half = max(2, frames // 2)
        alphas = list(np.linspace(0.0, 1.0, half, endpoint=False)) + list(np.linspace(1.0, 0.0, half, endpoint=False))
        animation_frames = [Image.blend(first, second, float(alpha)) for alpha in alphas]
        output = io.BytesIO()
        animation_frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=animation_frames[1:],
            duration=90,
            loop=0,
            optimize=True,
        )
        return output.getvalue()


@app.get("/api/motion_video", responses={
    200: {"description": "Animação de comparação/crossfade entre duas épocas alinhadas, com metadados."},
    404: {"description": "Não há cobertura adequada nas épocas consultadas."},
})
async def get_motion_video(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    fov: float = Query(10.0, gt=0, le=60),
    source: str = Query("auto", pattern="^(auto|spherex|optical)$"),
    detector: int = Query(2, ge=1, le=6),
    apply_filter: bool = Query(True, alias="filter"),
    include_gif: bool = Query(True, description="Inclui o GIF além dos dois quadros PNG."),
):
    """Renderiza um blink animado; diferenças de imagem não são interpretadas como movimento próprio."""
    try:
        coord = parse_coordinates(ra, dec)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Coordenadas RA/Dec inválidas.") from exc

    selected_source = source
    fallback_reason = None
    used_fov = fov
    try:
        if source in ("auto", "spherex"):
            try:
                temporal_fov = min(fov, 30.0)
                pair = await fetch_spherex_temporal_pair(coord, temporal_fov * u.arcmin, detector)
                first, second, valid, header, metadata1, metadata2 = _align_temporal_pair(pair)
                selected_source = "spherex"
                used_fov = temporal_fov
                cmap = "magma"
                for metadata in (metadata1, metadata2):
                    metadata["projection"] = [header.get("CTYPE1", "N/A"), header.get("CTYPE2", "N/A")]
            except LookupError as exc:
                if source == "spherex":
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                selected_source = "optical"
                fallback_reason = str(exc)
            except Exception as exc:
                logger.exception("Falha no serviço SPHEREx ao preparar blink animado")
                if source == "spherex":
                    raise HTTPException(
                        status_code=502,
                        detail="Falha ao consultar ou processar as épocas SPHEREx no IRSA.",
                    ) from exc
                selected_source = "optical"
                fallback_reason = (
                    "SPHEREx indisponível; usando imagens observadas DSS1/DSS2 do SkyView. "
                    f"Detalhe técnico: {type(exc).__name__}: {exc}"
                )

        if selected_source == "optical":
            hdu1, hdu2 = await asyncio.gather(
                fetch_survey(coord, fov * u.arcmin, "DSS1 Blue"),
                fetch_survey(coord, fov * u.arcmin, "DSS2 Blue"),
            )
            first, second = reproject_to_reference(hdu1, hdu2)
            valid = np.isfinite(first) & np.isfinite(second)
            if valid.sum() < 4:
                raise LookupError("As imagens DSS1 e DSS2 não têm área comum suficiente para a animação.")
            metadata1 = extract_safe_fits_metadata(hdu1.header, "DSS1 Blue")
            metadata2 = extract_safe_fits_metadata(hdu2.header, "DSS2 Blue")
            cmap = "gray"
            used_fov = fov

        if apply_filter:
            first = apply_median_filter(first)
            second = apply_median_filter(second)
            first[~valid], second[~valid] = np.nan, np.nan

        # Mostre apenas a cobertura comum, para uma borda de recorte não parecer uma alteração no céu.
        first, second = np.where(valid, first, np.nan), np.where(valid, second, np.nan)

        # Normalização robusta e independente por época, apenas para visualização.
        first_norm = _normalize(first, float(np.median(first[valid])), float(np.std(first[valid])))
        second_norm = _normalize(second, float(np.median(second[valid])), float(np.std(second[valid])))
        first_png = matrix_to_png_bytes_scaled(first_norm, cmap, -2.5, 6.0)
        second_png = matrix_to_png_bytes_scaled(second_norm, cmap, -2.5, 6.0)
        first_b64 = base64.b64encode(first_png).decode("ascii")
        second_b64 = base64.b64encode(second_png).decode("ascii")
        result = {
            "source": selected_source,
            "comparison_type": "epoch_crossfade",
            "normalization": "normalização mediana/desvio padrão independente por época; visualização qualitativa",
            "fallback_reason": fallback_reason,
            "coordinates": {"ra_deg": float(coord.ra.deg), "dec_deg": float(coord.dec.deg), "fov_arcmin": used_fov},
            "images": [f"data:image/png;base64,{first_b64}", f"data:image/png;base64,{second_b64}"],
            "metadata": [metadata1, metadata2],
        }
        if include_gif:
            gif_b64 = base64.b64encode(_crossfade_gif(first_png, second_png)).decode("ascii")
            result["gif_data"] = f"data:image/gif;base64,{gif_b64}"
        return JSONResponse(result, headers=NO_CACHE_HEADERS)
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao gerar comparação animada de épocas")
        raise HTTPException(status_code=502, detail="Falha ao alinhar ou renderizar a comparação entre épocas.") from exc


@app.get("/api/spherex/blink", responses={
    200: {"description": "Duas imagens SPHEREx reais, em épocas distintas, alinhadas e com metadados."},
    404: {"description": "Não há duas observações comparáveis com cobertura."},
})
async def get_spherex_blink(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    detector: int = Query(5, ge=1, le=6),
    fov: float = Query(5.0, gt=0, le=30, description="Raio do recorte em minutos de arco."),
    apply_filter: bool = Query(False, alias="filter"),
):
    try:
        coord = parse_coordinates(ra, dec)
        pair = await fetch_spherex_temporal_pair(coord, fov * u.arcmin, detector)
        first, second, valid, header, metadata1, metadata2 = _align_temporal_pair(pair)
        if apply_filter:
            first, second = apply_median_filter(first), apply_median_filter(second)
            first[~valid], second[~valid] = np.nan, np.nan
        for metadata in (metadata1, metadata2):
            metadata["projection"] = [header.get("CTYPE1", "N/A"), header.get("CTYPE2", "N/A")]
        finite_values = np.concatenate((first[valid], second[valid]))
        first, second = np.where(valid, first, np.nan), np.where(valid, second, np.nan)
        vmin, vmax = np.percentile(finite_values, [1, 99])
        if vmax <= vmin:
            vmax = vmin + 1.0
        first_image = base64.b64encode(matrix_to_png_bytes_scaled(first, "magma", float(vmin), float(vmax))).decode("ascii")
        second_image = base64.b64encode(matrix_to_png_bytes_scaled(second, "magma", float(vmin), float(vmax))).decode("ascii")
        return JSONResponse({
            "metadata": [metadata1, metadata2],
            "images": [f"data:image/png;base64,{first_image}", f"data:image/png;base64,{second_image}"],
            "detector": detector,
            "coordinates": {"ra_deg": float(coord.ra.deg), "dec_deg": float(coord.dec.deg), "fov_arcmin": fov},
        })
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha no blink temporal SPHEREx")
        raise HTTPException(status_code=502, detail="Falha ao consultar, recortar ou alinhar observações SPHEREx no IRSA.") from exc


async def _spherex_combine_route(ra: str, dec: str, detector: int, fov: float, apply_filter: bool, operation: str):
    try:
        coord = parse_coordinates(ra, dec)
        pair = await fetch_spherex_temporal_pair(coord, fov * u.arcmin, detector)
        first, second, valid, reference_header, metadata1, metadata2 = _align_temporal_pair(pair)
        combined = _compose_temporal_pair(first, second, valid, operation, apply_filter)
        projection = [reference_header.get("CTYPE1", "N/A"), reference_header.get("CTYPE2", "N/A")]
        metadata1["projection"] = projection
        metadata2["projection"] = projection
        encoded = base64.b64encode(matrix_to_png_bytes(combined, "gray")).decode("ascii")
        return JSONResponse({
            "image_data": f"data:image/png;base64,{encoded}",
            "metadata": [metadata1, metadata2],
            "detector": detector,
            "operation": operation,
        })
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha na combinação temporal SPHEREx (%s)", operation)
        raise HTTPException(status_code=502, detail="Falha ao consultar ou alinhar as observações SPHEREx no IRSA.") from exc


@app.get("/api/spherex/subtract", responses={
    200: {"description": "JSON com diferença PNG e metadados das duas épocas."},
    404: {"description": "Não há par de observações SPHEREx comparáveis."},
})
async def get_spherex_subtraction(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    detector: int = Query(5, ge=1, le=6),
    fov: float = Query(5.0, gt=0, le=30),
    apply_filter: bool = Query(False, alias="filter"),
):
    return await _spherex_combine_route(ra, dec, detector, fov, apply_filter, "subtract")


@app.get("/api/spherex/add", responses={
    200: {"description": "JSON com soma PNG e metadados das duas épocas."},
    404: {"description": "Não há par de observações SPHEREx comparáveis."},
})
async def get_spherex_addition(
    ra: str = Query(..., min_length=1, max_length=64),
    dec: str = Query(..., min_length=1, max_length=64),
    detector: int = Query(5, ge=1, le=6),
    fov: float = Query(5.0, gt=0, le=30),
    apply_filter: bool = Query(False, alias="filter"),
):
    return await _spherex_combine_route(ra, dec, detector, fov, apply_filter, "add")


@app.post("/api/spectrum", responses={200: {"description": "Gráfico espectral Quick-Look em PNG."}})
async def create_spectrum_plot(payload: SpectrumRequest):
    wavelength = np.asarray(payload.wavelength, dtype=float)
    flux = np.asarray(payload.flux, dtype=float)
    order = np.argsort(wavelength)
    wavelength, flux = wavelength[order], flux[order]
    uncertainty = np.asarray(payload.uncertainty, dtype=float)[order] if payload.uncertainty is not None else None
    return StreamingResponse(
        io.BytesIO(_spectrum_png_bytes(
            wavelength,
            flux,
            title=payload.title,
            flux_unit=payload.flux_unit,
            uncertainty=uncertainty,
            wavelength_unit=payload.wavelength_unit,
        )),
        media_type="image/png",
    )


def _spectrum_png_bytes(wavelength, flux, *, title, flux_unit, uncertainty=None, wavelength_unit="µm"):
    fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    if uncertainty is None:
        ax.plot(wavelength, flux, color="#58a6ff", marker="o", markersize=3, linewidth=1)
    else:
        ax.errorbar(wavelength, flux, yerr=uncertainty, color="#58a6ff", marker="o", markersize=3, linewidth=1, capsize=2)
    ax.set(title=title, xlabel=f"Comprimento de onda ({wavelength_unit})", ylabel=flux_unit)
    ax.grid(True, alpha=0.25)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=130)
    plt.close(fig)
    return buffer.getvalue()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)
