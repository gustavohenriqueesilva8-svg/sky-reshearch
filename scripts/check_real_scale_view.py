"""Browser regression check for keeping the real-scale overview and inspecting Mars."""

import argparse
from io import BytesIO

from PIL import Image
from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002/")
    parser.add_argument("--channel", default="msedge")
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
            page.get_by_role("button", name="Proporção real", exact=True).click()
            expect(page.locator("#gps-camera-target")).to_have_text("Navegação livre")
            expect(page.locator("#gps-render-error")).to_be_hidden()
            mars = page.get_by_role("button", name="Centralizar Marte na cena")
            expect(mars).to_have_attribute("data-subpixel", "")
            expect(page.get_by_role("button", name="Centralizar Terra na cena")).to_have_attribute("data-subpixel", "")
            mars.click()
            expect(page.locator("#gps-camera-target")).to_have_text("Foco em Marte")
            expect(mars).not_to_have_attribute("data-subpixel", "")

            canvas = page.locator("#gps-stage canvas")
            with Image.open(BytesIO(canvas.screenshot())) as capture:
                image = capture.convert("RGB")
                x, y = image.width // 2, image.height // 2
                center = image.crop((x - 30, y - 30, x + 30, y + 30))
                channels = [channel.tobytes() for channel in center.split()]
                mars_pixels = sum(
                    red > 80 and red > 1.25 * green and green > 1.10 * blue
                    for red, green, blue in zip(*channels, strict=True)
                )
                assert mars_pixels >= 1800, f"Marte não apareceu no centro a {width}px"
            page.get_by_role("button", name="Navegação livre", exact=True).click()
            expect(page.locator("#gps-camera-target")).to_have_text("Navegação livre")
            print(f"{width}px: visão geral com marcadores, Marte renderizado ao aproximar e retorno à navegação livre.")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
