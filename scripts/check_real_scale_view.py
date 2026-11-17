"""Verify real-scale markers and the textured close-ups in the served page."""

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from check_gps_physics import cut

BODIES = {
    "Sol": ("sun", "1.391.400 km", lambda r, g, b: r > 120 and r > 1.1 * g and g > 1.15 * b),
    "Terra": ("earth", "12.756,2 km", lambda r, g, b: b > 1.05 * r or g > 1.04 * r),
    "Marte": ("mars", "6.792,4 km", lambda r, g, b: r > 80 and r > 1.25 * g and g > 1.1 * b),
}


def apparent(page):
    return float(page.locator("#gps-apparent").inner_text().removesuffix(" px").replace(",", "."))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002/")
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--captures", type=Path)
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel)
        for width, height in ((1440, 1050), (390, 844)):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                is_mobile=width < 500,
                has_touch=width < 500,
            )
            page = context.new_page()
            page.goto(args.url)
            expect(page.locator("#gps-readout")).to_be_visible()
            expect(page.locator("#gps-camera-target")).to_have_text("Navegação livre")
            cut(page)
            real = page.get_by_role("button", name="Proporção real", exact=True)
            real.click()
            reset = page.get_by_role("button", name="Visão geral", exact=True)
            expect(page.locator("#gps-camera-target")).to_have_text("Navegação livre")
            expect(page.locator("#gps-render-error")).to_be_hidden()
            canvas = page.locator("#gps-stage canvas[tabindex]")
            report = []
            for name, (key, diameter, is_body_pixel) in BODIES.items():
                reset.click()
                marker = page.get_by_role("button", name=f"Centralizar {name} na cena")
                expect(marker).to_be_visible()
                if key != "sun" or width < 500:
                    expect(marker).to_have_attribute("data-subpixel", "")
                else:
                    expect(marker).not_to_have_attribute("data-subpixel", "")
                    assert marker.bounding_box()["y"] + marker.bounding_box()["height"] < (
                        canvas.bounding_box()["y"] + canvas.bounding_box()["height"] / 2 - 4
                    )
                marker.click()
                expect(page.locator("#gps-camera-target")).to_have_text(f"Foco em {name}")
                expect(page.locator("#gps-body-diameter")).to_have_text(diameter)
                expect(real).to_have_attribute("aria-pressed", "true")
                pixels = apparent(page)
                assert pixels > 80, (name, pixels)
                capture_path = args.captures / f"modelo-{key}-{width}.png" if args.captures else None
                with Image.open(BytesIO(canvas.screenshot(path=capture_path))) as capture:
                    image = capture.convert("RGB")
                    x, y = image.width // 2, image.height // 2
                    center = image.crop((x - 25, y - 25, x + 25, y + 25))
                    samples = iter(center.tobytes())
                    colors = list(zip(samples, samples, samples, strict=True))
                    assert sum(is_body_pixel(*color) for color in colors) > 1600, (name, width)
                    assert len(set(colors)) > 12, (name, width)
                page.get_by_role("button", name="Navegação livre", exact=True).click()
                expect(page.locator("#gps-camera-target")).to_have_text("Navegação livre")
                report.append(f"{name} {pixels:.1f} px")
            print(f"{width}px | visão geral → inspeção → navegação livre | " + " · ".join(report))
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
