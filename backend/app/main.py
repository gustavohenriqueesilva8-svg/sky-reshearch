"""Sky Researcher v2 API. Run from the checkout with uvicorn backend.app.main:app."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
import logging
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from time import monotonic
from typing import Annotated, BinaryIO
from urllib.parse import urlsplit
from xml.etree import ElementTree

from astropy import units as u
from astropy.coordinates import (
    CartesianRepresentation,
    SkyCoord,
    SphericalRepresentation,
    get_body_barycentric_posvel,
)
from astropy.io import fits
from astropy.io.votable import parse_single_table
from astropy.time import Time
from astropy.wcs import WCS
from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import numpy as np
from pydantic import AwareDatetime

from .schemas import (
    EphemerisResponse,
    ResearchFeedResponse,
    ScientificArticleItem,
    SpectralPoint,
    SpherexIrsaResponse,
    StateVector3D,
)

logger = logging.getLogger(__name__)

_TARGET_NAMES = {
    "sun": "Sun",
    "venus": "Venus",
    "earth": "Earth",
    "mars": "Mars",
    "jupiter": "Jupiter",
    "planet_x_candidate": "Planet X Candidate",
}
_PLANET_X_QUERY = "Trans-Neptunian Planet Nine SPHEREx"
_PLANET_X_UNAVAILABLE = "O candidato é hipotético e não possui uma posição observacional confirmada."
_ARXIV_URL = "https://export.arxiv.org/api/query"
_ARXIV_REQUEST_GAP_SECONDS = 3.0
_ATOM = {"atom": "http://www.w3.org/2005/Atom"}
_IRSA_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
_IRSA_ARCHIVE_HOSTS = frozenset({
    "irsa.ipac.caltech.edu",
    "nasa-irsa-spherex.s3.us-east-1.amazonaws.com",
    "nasa-irsa-spherex.s3.amazonaws.com",
})
_IRSA_MAX_BYTES = 512 * 1024 * 1024
_XML_MAX_BYTES = 1024 * 1024
_IRSA_CUBE_DEADLINE_SECONDS = 45
_IRSA_SOURCE = "SPHEREx DR1 All-Sky Cube / NASA-IPAC IRSA"
_IRSA_BLANK_CHANNELS = frozenset({51, 52})
_IRSA_SLOTS = BoundedSemaphore(2)

app = FastAPI(title="Sky Researcher v2 MVP", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

ephemeris_cache: TTLCache[tuple[str, datetime | None], EphemerisResponse] = TTLCache(maxsize=128, ttl=900)
research_cache: TTLCache[tuple[str, str], ResearchFeedResponse] = TTLCache(maxsize=128, ttl=1800)
_arxiv_lock = asyncio.Lock()
_arxiv_last_request = -float("inf")


def _vector(values: CartesianRepresentation, unit: u.UnitBase) -> StateVector3D:
    x, y, z = values.xyz.to_value(unit)
    return StateVector3D(x=float(x), y=float(y), z=float(z))


def _is_archive_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.netloc in _IRSA_ARCHIVE_HOSTS


def _download_cube(client: httpx.Client, url: str, destination: BinaryIO, deadline: float) -> None:
    """Spool a bounded archive product to disk so FITS sections do not load a full cube in RAM."""
    written = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        declared_size = response.headers.get("content-length")
        if declared_size is not None and int(declared_size) > _IRSA_MAX_BYTES:
            raise ValueError("O cubo SPHEREx excede o limite da consulta.")
        for chunk in response.iter_bytes(chunk_size=256 * 1024):
            written += len(chunk)
            if written > _IRSA_MAX_BYTES or monotonic() > deadline:
                raise ValueError("O download do cubo SPHEREx excede o limite da consulta.")
            destination.write(chunk)


def _read_spectrum(cube: BinaryIO, sightline: SkyCoord) -> list[SpectralPoint]:
    with fits.open(cube, memmap=False, lazy_load_hdus=True) as hdul:
        image = hdul["IMAGE"]
        channel_table = hdul["SPECTRAL_CHANNELS"]
        wavelength_column = channel_table.columns["WAVELENGTH"]
        wavelength_unit = u.Unit(wavelength_column.unit or "um")
        wavelengths = (np.asarray(channel_table.data["WAVELENGTH"]).reshape(-1) * wavelength_unit).to_value(u.um)
        channels, height, width = image.shape
        if len(wavelengths) != channels:
            raise ValueError("A tabela de comprimentos de onda não corresponde ao cubo.")
        x, y = WCS(image.header, fobj=hdul).celestial.world_to_pixel(sightline)
        if not (-0.5 <= x < width - 0.5 and -0.5 <= y < height - 0.5):
            return []
        column, row = round(float(x)), round(float(y))
        aperture = np.s_[:, max(0, row - 1):row + 2, max(0, column - 1):column + 2]
        brightness = image.section[aperture]
        hits = hdul["NHITS"].section[aperture]
        flux_unit = u.Unit(image.header.get("BUNIT", "MJy/sr"))
        to_mjy_sr = flux_unit.to(u.MJy / u.sr)
        points: list[SpectralPoint] = []
        for channel, (wavelength, pixels, coverage) in enumerate(zip(wavelengths, brightness, hits, strict=True), 1):
            if channel in _IRSA_BLANK_CHANNELS:
                continue
            valid = pixels[(coverage > 0) & np.isfinite(pixels)]
            if valid.size and np.isfinite(wavelength) and wavelength > 0:
                points.append(SpectralPoint(
                    wavelength_um=float(wavelength),
                    flux_mjy_sr=float(np.median(valid) * to_mjy_sr),
                ))
        return sorted(points, key=lambda point: point.wavelength_um)


class AstroComputationalEngine:
    """Astropy states and synchronous archive access for executor threads."""

    @staticmethod
    def get_ephemeris(target_id: str, instant_utc: datetime) -> EphemerisResponse:
        if target_id == "planet_x_candidate":
            return EphemerisResponse(
                target_id=target_id, instant_utc=instant_utc, status="unavailable",
                source="cenário hipotético", message=_PLANET_X_UNAVAILABLE,
            )
        epoch = Time(instant_utc, scale="utc")
        position, velocity = get_body_barycentric_posvel(target_id, epoch, ephemeris="builtin")
        sun_position, sun_velocity = get_body_barycentric_posvel("sun", epoch, ephemeris="builtin")
        return EphemerisResponse(
            target_id=target_id,
            instant_utc=instant_utc,
            position_au=_vector(position - sun_position, u.au),
            velocity_km_s=_vector(velocity - sun_velocity, u.km / u.s),
        )

    @staticmethod
    def get_spherex_spectrum(target_id: str, instant_utc: datetime) -> SpherexIrsaResponse:
        if target_id == "planet_x_candidate":
            return SpherexIrsaResponse(target_id=target_id, status="unavailable", message=_PLANET_X_UNAVAILABLE)
        if target_id == "earth":
            return SpherexIrsaResponse(
                target_id=target_id, status="unavailable",
                message="O centro da Terra não define uma direção para uma consulta geocêntrica.",
            )

        epoch = Time(instant_utc, scale="utc")
        body, _ = get_body_barycentric_posvel(target_id, epoch, ephemeris="builtin")
        earth, _ = get_body_barycentric_posvel("earth", epoch, ephemeris="builtin")
        direction = (body - earth).represent_as(SphericalRepresentation)
        sightline = SkyCoord(ra=direction.lon, dec=direction.lat, frame="icrs")
        ra, dec = float(sightline.ra.deg), float(sightline.dec.deg)
        if not _IRSA_SLOTS.acquire(blocking=False):
            return SpherexIrsaResponse(
                target_id=target_id, status="unavailable", ra_deg=ra, dec_deg=dec,
                message="O limite de consultas SPHEREx simultâneas foi atingido.",
            )
        try:
            return AstroComputationalEngine._query_spherex_sightline(target_id, sightline)
        finally:
            _IRSA_SLOTS.release()

    @staticmethod
    def _query_spherex_sightline(target_id: str, sightline: SkyCoord) -> SpherexIrsaResponse:
        ra, dec = float(sightline.ra.deg), float(sightline.dec.deg)
        try:
            with httpx.Client(timeout=8.0) as client:
                with client.stream("GET", _IRSA_SIA_URL, params={
                    "POS": f"CIRCLE {ra:.9f} {dec:.9f} 0.0166667",
                    "COLLECTION": "spherex_dr1_cube", "MAXREC": 2,
                }) as response:
                    response.raise_for_status()
                    votable = BytesIO()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        if votable.tell() + len(chunk) > _XML_MAX_BYTES:
                            raise ValueError("A resposta SIA excede o limite da consulta.")
                        votable.write(chunk)
                votable.seek(0)
                results = parse_single_table(votable).to_table()
                urls = (str(url) for url in results["access_url"]) if len(results) else ()
                last_error: Exception | None = None
                deadline = monotonic() + _IRSA_CUBE_DEADLINE_SECONDS
                for url in urls:
                    if not _is_archive_url(url) or monotonic() >= deadline:
                        continue
                    try:
                        with TemporaryDirectory() as directory:
                            path = Path(directory) / "tile.fits"
                            with path.open("wb") as cube:
                                _download_cube(client, url, cube, deadline)
                            with path.open("rb") as cube:
                                points = _read_spectrum(cube, sightline)
                    except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
                        last_error = exc
                        continue
                    if points:
                        return SpherexIrsaResponse(
                            target_id=target_id, source=_IRSA_SOURCE, profile_kind="sky_background",
                            ra_deg=ra, dec_deg=dec, points=points,
                            message=(
                                "Mediana de pixels cobertos em uma abertura de até 3 × 3 no cubo. "
                                "O perfil descreve o fundo celeste nessa direção."
                            ),
                        )
                if last_error is not None:
                    raise last_error
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            logger.warning("Consulta SPHEREx indisponível para %s (%s).", target_id, type(exc).__name__)
            message = "O índice ou o cubo SPHEREx está indisponível para esta consulta."
        else:
            message = "O cubo SPHEREx não retornou cobertura espectral válida para esta direção."
        return SpherexIrsaResponse(
            target_id=target_id, status="unavailable", source=_IRSA_SOURCE,
            ra_deg=ra, dec_deg=dec, message=message,
        )


def _fallback_article() -> ScientificArticleItem:
    return ScientificArticleItem(
        title="Cosmology with the SPHEREX All-Sky Spectral Survey",
        authors=["Olivier Doré et al."],
        url="https://arxiv.org/abs/1412.4872",
        published=datetime(2014, 12, 16, tzinfo=timezone.utc),
        source="arXiv (referência de contingência)",
    )


def _parse_articles(payload: bytes, max_results: int) -> list[ScientificArticleItem]:
    root = ElementTree.fromstring(payload)
    if root.tag != f"{{{_ATOM['atom']}}}feed":
        raise ValueError("A resposta do arXiv não é um feed Atom.")
    articles: list[ScientificArticleItem] = []
    for entry in root.findall("atom:entry", _ATOM)[:max_results]:
        title = " ".join(entry.findtext("atom:title", default="", namespaces=_ATOM).split())
        identifier = entry.findtext("atom:id", default="", namespaces=_ATOM).strip()
        parsed = urlsplit(identifier)
        if not title or not parsed.path.startswith("/abs/") or parsed.hostname not in {"arxiv.org", "export.arxiv.org"}:
            raise ValueError("O arXiv retornou uma entrada inválida.")
        published = entry.findtext("atom:published", namespaces=_ATOM)
        authors = [" ".join(author.text.split()) for author in entry.findall("atom:author/atom:name", _ATOM) if author.text]
        articles.append(ScientificArticleItem(
            title=title,
            authors=authors,
            url="https://arxiv.org" + parsed.path,
            summary=" ".join(entry.findtext("atom:summary", default="", namespaces=_ATOM).split()) or None,
            published=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
        ))
    return articles


async def fetch_arxiv_papers(search_query: str, max_results: int = 5) -> list[ScientificArticleItem]:
    """Query arXiv's Atom API and return a real SPHEREx reference on upstream failure."""
    global _arxiv_last_request
    terms = re.findall(r"\w+(?:[-.]\w+)*", search_query)
    if not terms or max_results < 1:
        return []
    query = " AND ".join([*(f'all:"{term}"' for term in terms), "cat:astro-ph*"])
    try:
        async with _arxiv_lock:
            delay = _arxiv_last_request + _ARXIV_REQUEST_GAP_SECONDS - monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            _arxiv_last_request = monotonic()
            async with httpx.AsyncClient(timeout=8.0) as client:
                async with client.stream("GET", _ARXIV_URL, params={
                    "search_query": query, "start": 0, "max_results": max_results,
                }) as response:
                    response.raise_for_status()
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        if len(chunks) + len(chunk) > _XML_MAX_BYTES:
                            raise ValueError("A resposta do arXiv excede o limite da consulta.")
                        chunks.extend(chunk)
        return _parse_articles(bytes(chunks), max_results)
    except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
        logger.warning("Feed arXiv indisponível (%s).", type(exc).__name__)
        return [_fallback_article()]


def _target_name(target_id: str) -> str:
    name = _TARGET_NAMES.get(target_id)
    if name is None:
        raise HTTPException(status_code=404, detail="Astro fora do catálogo inicial.")
    return name


def _now() -> datetime:
    # Omit subsecond noise from default snapshots.
    return datetime.now(timezone.utc).replace(microsecond=0)


@app.get("/api/v1/ephemeris/{target_id}")
async def ephemeris(
    target_id: str,
    instant: Annotated[AwareDatetime | None, Query()] = None,
) -> EphemerisResponse:
    _target_name(target_id)
    utc = instant.astimezone(timezone.utc) if instant is not None else None
    key = target_id, utc
    cached = ephemeris_cache.get(key)
    if cached is not None:
        return cached
    try:
        result = await asyncio.to_thread(AstroComputationalEngine.get_ephemeris, target_id, utc or _now())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Instante fora da cobertura do modelo de efemérides.") from exc
    ephemeris_cache[key] = result
    return result


@app.get("/api/v1/spherex/spectrum/{target_id}")
async def spherex_spectrum(target_id: str) -> SpherexIrsaResponse:
    _target_name(target_id)
    return await asyncio.to_thread(AstroComputationalEngine.get_spherex_spectrum, target_id, _now())


@app.get("/api/v1/research/feed/{target_id}")
async def research_feed(
    target_id: str,
    query_name: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> ResearchFeedResponse:
    name = _target_name(target_id)
    query = _PLANET_X_QUERY if target_id == "planet_x_candidate" else (" ".join((query_name or "").split()) or name)
    key = target_id, query
    cached = research_cache.get(key)
    if cached is not None:
        return cached
    profile, articles = await asyncio.gather(
        asyncio.to_thread(AstroComputationalEngine.get_spherex_spectrum, target_id, _now()),
        fetch_arxiv_papers(query),
    )
    result = ResearchFeedResponse(target_id=target_id, query_name=query, spherex=profile, articles=articles)
    research_cache[key] = result
    return result
