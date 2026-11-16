"""Gera dois recortes didáticos reais. Veja créditos e termos em assets/README.md."""
import argparse
from datetime import datetime
import io
import json
from pathlib import Path
import sys

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
import numpy as np
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import matrix_to_png_bytes_scaled, reproject_to_reference

ESO = "https://archive.eso.org/dss/dss/image"
PLATES = (("DSS1", "099V", "%d/%m/%y", "DSS1 · POSS-I vermelho"),
          ("DSS2-red", "A0BG", "%Y/%m/%d", "DSS2 · POSS-II vermelho"))


def read_plate(survey, expected_id, local_path):
    params = {"ra": "17 57 50.5", "dec": "+04 36 20", "equinox": "J2000", "x": 16, "y": 16,
              "Sky-Survey": survey, "mime-type": "download-fits"}
    url = requests.Request("GET", ESO, params=params).prepare().url
    if local_path is None:
        response = requests.get(url, timeout=(10, 45))
        response.raise_for_status()
        local_path = io.BytesIO(response.content)
    with fits.open(local_path, memmap=False) as hdus:
        plate = hdus[0].copy()
    if plate.header.get("PLATEID") != expected_id:
        raise ValueError(f"Placa inesperada para {survey}; confira a identificação do campo didático.")
    return plate, url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fits", nargs=2, metavar="FITS", help="Recortes originais do ESO, DSS1 e DSS2-red.")
    args = parser.parse_args()
    plates, urls = zip(*(read_plate(survey, plate_id, path)
                         for (survey, plate_id, _, _), path in zip(PLATES, args.fits or (None, None))))
    first, second = reproject_to_reference(*plates)
    wcs = WCS(plates[1].header).celestial
    size = 840
    y0, x0 = ((length - size) // 2 for length in second.shape)
    region = np.s_[y0:y0 + size, x0:x0 + size]
    valid = np.isfinite(first[region]) & np.isfinite(second[region])

    # Posição J2000 e movimento próprio catalogados no SIMBAD (Gaia EDR3).
    # Aproximação linear para localizar a estrela, não uma medição nos recortes.
    barnard = SkyCoord("17h57m48.4983s +04d41m36.245s")
    frames = []
    for image, plate, url, (_, plate_id, date_format, label) in zip((first, second), plates, urls, PLATES):
        observed = datetime.strptime(plate.header["DATE-OBS"], date_format).date()
        # O DSS1 usa um ano de dois dígitos; o ano completo está em EPOCH.
        if date_format.endswith("%y"):
            observed = observed.replace(year=int(plate.header["EPOCH"]))
        date = observed.isoformat()
        years = Time(date, format="iso", scale="utc").jyear - 2000.0
        estimated = barnard.spherical_offsets_by(-0.801551 * years * u.arcsec, 10.362394 * years * u.arcsec)
        x, y = wcs.world_to_pixel(estimated)
        point = [round((float(x) - x0 + 0.5) / size, 5), round(1 - (float(y) - y0 + 0.5) / size, 5)]
        if not all(0 < axis < 1 for axis in point):
            raise ValueError(f"A posição esperada para {date} ficou fora do recorte.")
        data = image[region]
        low, high = np.percentile(data[valid], [36, 99.6])
        scaled = np.arcsinh(np.maximum(np.where(valid, data, low) - low, 0) * 7 / (high - low))
        png = matrix_to_png_bytes_scaled(scaled, "gray", 0, np.arcsinh(7))
        file = f"barnard-{date[:4]}.png"
        with Image.open(io.BytesIO(png)) as frame:
            frame.convert("L").resize((600, 600), Image.Resampling.LANCZOS).save(ROOT / "assets" / file, optimize=True)
        frames.append({"file": file, "date": date, "plate": plate_id, "survey": label, "point": point, "url": url})
    (ROOT / "assets" / "barnard-demo.js").write_text(
        "// Gerado por scripts/build_barnard_demo.py a partir de placas observadas.\n"
        f"const BARNARD_FRAMES = {json.dumps(frames, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
