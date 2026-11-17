"""Check the GPS's rendered scales, reference frames and curvature in Chromium."""

import argparse
from datetime import datetime, timedelta
from math import cos, dist, isclose, pi, sqrt
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

AU = 149_597_870.7
RADII = {"sun": (695_700, 695_700), "earth": (6378.1, 6356.8), "mars": (3396.2, 3376.2)}
START = "2025-01-16T12:00:00Z"
END = "2025-02-21T12:00:00Z"
ZERO = (0, 0, 0)
SCENE_JS = Path(__file__).resolve().parents[1] / "assets/solar-scene.js"
# Observe the renderer's live objects without adding production instrumentation.
TAP = """
      window.inspectGps = () => ({
        camera: camera.position.toArray(), target: controls.target.toArray(), trackedBody,
        light: sunlight.position.toArray(),
        meshes: Object.fromEntries(Object.entries(meshes).map(([id, mesh]) => [id, {
          center: mesh.position.toArray(), scale: mesh.scale.toArray(), visible: mesh.visible,
          geometry: mesh.geometry.type, textureWidth: mesh.material.map?.image.width,
          diameter: 2 * mesh.geometry.parameters.radius * mesh.scale.x,
        }])),
        arrows: Object.fromEntries(Object.entries(arrows).map(([id, arrow]) => [id, {
          origin: arrow.position.toArray(), visible: arrow.visible,
          vector: new THREE.Vector3(0, arrow.cone.position.y, 0).applyQuaternion(arrow.quaternion).toArray(),
        }])),
        slice: curvature && {
          visible: curvature.visible, origin: curvature.position.toArray(),
          rings: Array.from({length: 37}, (_, ring) => {
            const vertices = curvature.children[0].geometry.getAttribute("position");
            const i = ring * 72;
            return [vertices.getX(i), vertices.getY(i)];
          }),
        },
      });
      window.centerModelPixels = () => {
        renderer.render(scene, camera);
        const gl = renderer.getContext();
        const x = Math.floor(gl.drawingBufferWidth / 2);
        const y = Math.floor(gl.drawingBufferHeight / 2);
        const pixels = new Uint8Array(9 * 9 * 4);
        gl.readPixels(x - 4, y - 4, 9, 9, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        const colors = new Set();
        for (let i = 0; i < pixels.length; i += 4) {
          if (pixels[i + 3] === 255) colors.add(pixels.slice(i, i + 3).join(","));
        }
        return colors.size;
      };
"""


def state(page):
    return page.evaluate("inspectGps()")


def world(vector, origin=ZERO):
    x, y, z = (vector[axis] - offset for axis, offset in zip("xyz", origin, strict=True))
    return x, z, -y


def assert_frame(page, data, reference):
    current = state(page)
    positions, velocities = data["positions"], data["velocities_km_s"]
    for body, model in current["meshes"].items():
        center = world(positions[body], tuple(positions[reference][axis] for axis in "xyz"))
        velocity = world(velocities[body], tuple(velocities[reference][axis] for axis in "xyz"))
        assert dist(model["center"], center) < 1e-12
        arrow = current["arrows"][body]
        assert arrow["visible"] == (body != reference)
        if arrow["visible"]:
            assert dist(arrow["origin"], center) < 1e-12
            assert dist(arrow["vector"], tuple(component * 0.012 for component in velocity)) < 1e-12
        speed = f"{dist(velocity, ZERO):.3f}".replace(".", ",") + " km/s"
        expect(page.locator(f"#gps-speed-{body}")).to_have_text(speed)
    assert current["light"] == current["meshes"]["sun"]["center"]
    return current


def cut(page):
    page.get_by_role("button", name="Recorte UTC").click()
    page.get_by_label("Início (UTC)").fill(START.rstrip("Z"))
    page.get_by_label("Fim (UTC)").fill(END.rstrip("Z"))
    page.get_by_role("button", name="Aplicar recorte").click()
    expect(page.locator("#gps-status")).to_have_text("Recorte aplicado.")
    expect(page.locator("#gps-epoch")).to_have_attribute("datetime", START)


def verify_surface(layer):
    rs = 2 * 1.3271244e11 / 299_792.458 ** 2
    rings = layer["rings"]
    assert layer["visible"] and len(rings) == 37
    assert isclose(rings[0][0] * cos(pi / 72), 695_700 / AU, rel_tol=1e-7)
    assert rings[-1] == [2, 0]
    height_errors = []
    for radius_au, height_au in rings:
        radius = radius_au * AU
        height_km = 2 * sqrt(rs) * (sqrt(radius - rs) - sqrt(2 * AU - rs))
        height_errors.append(abs(height_au * AU / 1000 - height_km))
    max_error = max(height_errors)
    assert max_error < 0.006
    slopes = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(rings, rings[1:])]
    assert all(a > b > 0 for a, b in zip(slopes, slopes[1:]))
    return rs, max_error


def pinch_in(page, canvas):
    canvas.scroll_into_view_if_needed()
    rect = canvas.bounding_box()
    x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
    device = page.context.new_cdp_session(page)
    for event, spread in (("touchStart", 24), ("touchMove", 45), ("touchEnd", 0)):
        points = [
            {"x": x - spread, "y": y, "id": 1}, {"x": x + spread, "y": y, "id": 2}
        ] if spread else []
        device.send("Input.dispatchTouchEvent", {"type": event, "touchPoints": points})
    device.detach()


def check_view(page, width, captures):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    expect(page.locator("#gps-stage canvas")).to_be_visible()
    page.wait_for_function("Object.values(inspectGps().meshes).every(m => m.visible && m.textureWidth === 1024)")
    expect(page.locator("#gps-render-error")).to_be_hidden()
    expect(page.locator("#gps-live-state")).to_have_text("Acompanhando o relógio UTC")
    params = {"instant": START, "velocities": "true"}
    data = page.request.get("/api/ephemerides/mars", params=params).json()
    cut(page)

    real = page.get_by_role("button", name="Proporção real", exact=True)
    real.press("Enter")
    overview = assert_frame(page, data, "sun")
    for key, model in overview["meshes"].items():
        equatorial, polar = RADII[key]
        assert model["visible"] and model["geometry"] == "SphereGeometry"
        assert dist(model["scale"], (equatorial / AU, polar / AU, equatorial / AU)) < 1e-15
        assert isclose(model["diameter"], 2 * equatorial / AU, rel_tol=1e-13)
    meshes = overview["meshes"]
    ratio = meshes["sun"]["diameter"] / meshes["earth"]["diameter"]
    separation = dist(meshes["mars"]["center"], meshes["earth"]["center"])
    assert isclose(ratio, 695_700 / 6378.1, rel_tol=1e-13)
    assert isclose(separation, data["distances"]["mars_earth"], rel_tol=1e-13)
    expect(page.get_by_role("button", name="Centralizar Marte na cena")).to_have_attribute("data-subpixel", "")

    if width == 1440 and captures:
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=captures / "gps-velocidades-relativas.png")
    curvature = page.get_by_role("checkbox", name="Curvatura espacial")
    curvature.press("Space")
    expect(page.locator("#gps-curvature-info")).to_contain_text("1.000×")
    curved = assert_frame(page, data, "sun")
    assert curved["meshes"] == meshes and curved["arrows"] == overview["arrows"]
    assert curved["slice"]["origin"] == list(ZERO)
    rs, height_error = verify_surface(curved["slice"])
    if width == 1440 and captures:
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=captures / "gps-curvatura-espacial.png")

    canvas = page.locator("#gps-stage canvas")
    select = page.get_by_role("combobox", name="Referência do movimento")
    mars = page.get_by_role("button", name="Marte", exact=True)
    mars.click()
    expect(page.locator("#gps-camera-target")).to_have_text("Foco em Marte")
    before = state(page)
    expect(page.get_by_role("button", name="Centralizar Marte na cena")).not_to_have_attribute("data-subpixel", "")
    canvas.press("ArrowRight")
    canvas.press("+")
    closer = assert_frame(page, data, "sun")
    assert closer["meshes"] == meshes
    assert dist(closer["camera"], closer["target"]) < dist(before["camera"], before["target"])

    select.focus()
    select.press("Tab")
    expect(page.get_by_role("checkbox", name="Vetores de velocidade")).to_be_focused()
    select.select_option("earth")
    earth = assert_frame(page, data, "earth")
    assert earth["trackedBody"] == "mars"
    assert earth["target"] == earth["meshes"]["mars"]["center"]
    assert earth["slice"]["origin"] == earth["meshes"]["sun"]["center"]
    expect(page.locator("#gps-distance-earth")).to_have_text("0,6440 ua")
    select.select_option("mars")
    assert_frame(page, data, "mars")

    visual = page.get_by_role("button", name="Visualização aprimorada", exact=True)
    for scale, is_real in ((visual, False), (real, True)):
        scale.click()
        for key, name in (("sun", "Sol"), ("earth", "Terra"), ("mars", "Marte")):
            page.get_by_role("button", name=name, exact=True).click()
            current = state(page)
            model = current["meshes"][key]
            assert (model["diameter"] == meshes[key]["diameter"]) == is_real
            assert model["visible"] and model["textureWidth"] == 1024
            assert current["target"] == model["center"]
            px = float(page.locator("#gps-apparent").inner_text().removesuffix(" px").replace(",", "."))
            assert px > 80
            assert page.evaluate("centerModelPixels()") > 4
    if width < 500:
        before_pinch = state(page)
        pinch_in(page, canvas)
        after_pinch = state(page)
        assert after_pinch["target"] == before_pinch["target"]
        assert dist(after_pinch["camera"], after_pinch["target"]) < dist(before_pinch["camera"], before_pinch["target"])
    page.get_by_role("button", name="Navegação livre", exact=True).click()
    free = state(page)
    canvas.press("ArrowLeft")
    turned = state(page)
    assert dist(turned["camera"], free["camera"]) < 1e-12
    assert dist(turned["target"], free["target"]) > 1e-8

    playback = page.get_by_role("combobox", name="Ritmo de reprodução")
    playback.select_option("2")
    expect(page.locator("#gps-epoch")).to_have_attribute("datetime", START)
    assert_frame(page, data, "mars")
    play = page.get_by_role("button", name="Reproduzir")
    start = datetime.fromisoformat(START)
    page.clock.install(time=start)
    page.clock.pause_at(start + timedelta(seconds=1))
    play.evaluate("(button) => button.click()")
    expect(page.locator("#gps-movement-clock")).to_have_text("Reprodução · 2,000 dias/s")
    page.clock.run_for(1600)
    step_time = page.locator("#gps-epoch").get_attribute("datetime")
    step = (datetime.fromisoformat(step_time) - start).total_seconds() / 86400
    assert 2.8 <= step <= 3.5, step
    page.get_by_role("button", name="Pausar").evaluate("(button) => button.click()")
    paused = page.locator("#gps-epoch").get_attribute("datetime")
    sampled = page.request.get("/api/ephemerides/mars", params={**params, "instant": paused}).json()
    assert_frame(page, sampled, "mars")
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    assert not errors, errors
    print(f"{width}px | Sol/Terra {ratio:.8f} | Terra–Marte {separation:.12f} ua | rₛ {rs:.8f} km")
    print(f"  3 referenciais, 3 modelos nos 2 modos, erro máximo de altura {1000 * height_error:.3f} m nos 37 anéis.")
    print(f"  Reprodução 2×: avanço de {step:.2f} dias simulados em 1,6 segundo.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002/")
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--captures", type=Path)
    args = parser.parse_args()
    source = SCENE_JS.read_text().replace("      renderer.render(scene, camera);", "      renderer.render(scene, camera);" + TAP)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel)
        for width, height in ((1440, 1050), (390, 844)):
            context = browser.new_context(
                base_url=args.url, viewport={"width": width, "height": height},
                is_mobile=width < 500, has_touch=width < 500,
            )
            context.route("**/assets/solar-scene.js", lambda route: route.fulfill(
                status=200, content_type="text/javascript", body=source,
            ))
            page = context.new_page()
            page.goto(args.url)
            check_view(page, width, args.captures)
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
