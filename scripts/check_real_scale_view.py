"""Verify real-scale markers and the textured close-ups in the served page."""

import argparse
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from check_gps_physics import AU, START, cut

BODIES = {
    "Sol": ("sun", "no Sol", "1.392.700 km", lambda r, g, b: r > 120 and r > 1.1 * g and g > 1.15 * b),
    "Terra": ("earth", "na Terra", "12.742 km", lambda r, g, b: b > 1.05 * r or g > 1.04 * r),
    "Marte": ("mars", "em Marte", "6.779 km", lambda r, g, b: r > 40 and r > 1.25 * g and g > 1.1 * b),
}


def apparent(page):
    return float(page.locator("#gps-apparent").inner_text().removesuffix(" px").replace(",", "."))

def as_km(text):
    quantity, unit = text.split()
    return float(quantity.replace(".", "").replace(",", ".")) * (AU if unit == "ua" else 1)

def km_per_pixel(page):
    ruler = as_km(page.locator("#gps-view-scale-value").inner_text())
    return ruler / page.locator("#gps-view-scale-bar").bounding_box()["width"]

def camera_range(page):
    return as_km(page.locator("#gps-view-range").inner_text().split(" · ")[1])


def wheel_toward_earth(page, canvas):
    earth = page.locator("[data-scene-label='earth']")
    mars = page.locator("[data-scene-label='mars']")
    canvas.scroll_into_view_if_needed()
    bounds = canvas.bounding_box()
    position = "(label) => [parseFloat(label.style.left), parseFloat(label.style.top)]"
    x, y = earth.evaluate(position)
    initial_mars = mars.evaluate("(label) => label.style.top")
    old_res = km_per_pixel(page)
    page.mouse.move(bounds["x"] + x, bounds["y"] + y)
    page.mouse.wheel(0, -180)
    page.wait_for_function(
        "(before) => document.querySelector('[data-scene-label=mars]').style.top !== before", arg=initial_mars,
    )
    new_x, new_y = earth.evaluate(position)
    assert abs(new_x - x) < 1 and abs(new_y - y) < 1, ((x, y), (new_x, new_y))
    assert km_per_pixel(page) < old_res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002/")
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--captures", type=Path)
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel)
        for width, height in ((1440, 1050), (662, 733), (390, 844)):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                is_mobile=width < 500,
                has_touch=width < 500,
            )
            page = context.new_page()
            page.goto(args.url)
            expect(page.locator("#gps-readout")).to_be_visible()
            expect(page.locator("#gps-camera-target")).to_have_text("Navegação livre")
            real = page.get_by_role("button", name="Proporção real", exact=True)
            expect(real).to_have_attribute("aria-pressed", "true")
            cut(page)
            expect(page.locator("#gps-diameter-ratio")).to_have_text("109,30 vezes")
            disk_sizes = [page.locator(f"[data-diameter-disk='{key}']").bounding_box()["width"]
                          for key, *_ in BODIES.values()]
            assert abs(disk_sizes[0] / disk_sizes[1] - 109.30) < 2
            assert abs(disk_sizes[0] / disk_sizes[2] - 205.44) < 5
            initial_scale = km_per_pixel(page)
            initial_range = camera_range(page)
            measure = page.locator("#gps-measure-value").inner_text()
            page.get_by_role("button", name="Aproximar", exact=True).click()
            assert km_per_pixel(page) < initial_scale * 0.85
            assert camera_range(page) < initial_range * 0.85
            assert page.locator("#gps-measure-value").inner_text() == measure
            reset = page.get_by_role("button", name="Visão geral", exact=True)
            reset.click()
            expect(page.locator("#gps-camera-target")).to_have_text("Navegação livre")
            expect(page.locator("#gps-render-error")).to_be_hidden()
            canvas = page.locator("#gps-stage canvas[tabindex]")
            if width == 662:
                wheel_toward_earth(page, canvas)
                reset.click()
            start = datetime.fromisoformat(START)
            page.clock.install(time=start)
            page.clock.pause_at(start + timedelta(seconds=1))
            report = []
            for name, (key, location, diameter, is_body_pixel) in BODIES.items():
                reset.click()
                marker = page.get_by_role("button", name=f"Centralizar {name} na cena")
                expect(marker).to_be_visible()
                expect(marker).to_have_attribute("data-subpixel", "")
                marker.click()
                expect(page.locator("#gps-camera-target")).to_have_text(f"Aproximação · {name}")
                initial_range = camera_range(page)
                page.clock.run_for(350)
                assert 0 < camera_range(page) < initial_range
                page.clock.run_for(1050)
                expect(page.locator("#gps-camera-target")).to_have_text(f"Foco {location}")
                expect(page.locator("#gps-body-diameter")).to_have_text(diameter)
                expect(real).to_have_attribute("aria-pressed", "true")
                pixels = apparent(page)
                assert pixels > 80, (name, pixels)
                before_zoom = camera_range(page)
                page.get_by_role("button", name="Aproximar", exact=True).click()
                assert camera_range(page) < before_zoom and apparent(page) > pixels
                assert page.locator("#gps-measure-value").inner_text() == measure
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
