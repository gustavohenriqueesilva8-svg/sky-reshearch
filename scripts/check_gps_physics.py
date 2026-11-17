"""Check the GPS's rendered scales, motion and gravitational layers in Chromium."""

import argparse
from datetime import datetime, timedelta
from math import cos, dist, isclose, pi, sqrt
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

AU = 149_597_870.7
RADII = {"sun": (695_700, 695_700), "earth": (6378.1, 6356.8), "mars": (3396.2, 3376.2)}
GM = {"sun": 1.3271244e11, "earth": 398_600.435507, "mars": 42_828.37362}
START = "2025-01-16T12:00:00Z"
END = "2025-02-21T12:00:00Z"
ZERO = (0, 0, 0)
SCENE_JS = Path(__file__).resolve().parents[1] / "assets/solar-scene.js"
# Observe the renderer's live objects without adding production instrumentation.
TAP = """
      window.projectedVectors = [];
      window.vectorLabels = [];
      window.inspectGps = () => ({
        camera: camera.position.toArray(), target: controls.target.toArray(), trackedBody,
        light: sunlight.position.toArray(),
        velocityScale: window.velocityScale,
        vectors: window.projectedVectors, vectorLabels: window.vectorLabels,
        accelerations,
        meshes: Object.fromEntries(Object.entries(meshes).map(([id, mesh]) => [id, {
          center: mesh.getWorldPosition(new THREE.Vector3()).toArray(),
          scale: mesh.getWorldScale(new THREE.Vector3()).toArray(), visible: mesh.visible,
          geometry: mesh.geometry.type, textureWidth: mesh.material.map?.image.width,
          diameter: 2 * mesh.geometry.parameters.radius * mesh.getWorldScale(new THREE.Vector3()).x,
        }])),
        apparent: Object.fromEntries(Object.entries(meshes).map(([id, mesh]) => [
          id, physics.apparentDiameterPx(mesh.scale.x,
            -mesh.position.clone().applyMatrix4(camera.matrixWorldInverse).z,
            mesh.position.clone().applyMatrix4(camera.matrixWorldInverse).y,
            stage.clientHeight * camera.projectionMatrix.elements[5] / 2),
        ])),
        slice: curvature && {
          visible: curvature.visible, origin: curvature.position.toArray(),
          rings: Array.from({length: 37}, (_, ring) => {
            const vertices = curvature.children[0].geometry.getAttribute("position");
            const i = ring * 72;
            return [vertices.getX(i), vertices.getY(i)];
          }),
        },
        field: gravity && {
          visible: gravity.visible, origin: gravity.position.toArray(),
          offsets: gravity.material.uniforms.sourceOffsets.value.map(vector => vector.toArray()),
          radii: gravity.material.uniforms.radiiAu.value, gmPerAu: gravity.material.uniforms.gmPerAu.value,
          normal: new THREE.Vector3(0, 0, 1).applyQuaternion(gravity.quaternion).toArray(),
        },
      });
      window.gravityFieldPixels = () => {
        const gl = renderer.getContext();
        const width = gl.drawingBufferWidth;
        const height = gl.drawingBufferHeight;
        const copyPixels = () => {
          renderer.render(scene, camera);
          const pixels = new Uint8Array(width * height * 4);
          gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
          return pixels;
        };
        const on = copyPixels();
        gravity.visible = false;
        const off = copyPixels();
        gravity.visible = true;
        copyPixels();
        let changed = 0;
        for (let i = 0; i < on.length; i += 4) {
          if (Math.abs(on[i + 3] - off[i + 3]) > 12) changed++;
        }
        return changed / (width * height);
      };
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
VECTOR_TAP = """
      const ratio = overlay.width / width;
      const sampleX = Math.round((x + ox + ux * (gap + (length - gap - head) / 2)) * ratio);
      const sampleY = Math.round((y + oy + uy * (gap + (length - gap - head) / 2)) * ratio);
      const rgb = ink.getImageData(sampleX, sampleY, 1, 1).data;
      window.projectedVectors.push({
        name: vector.name, gravity: vector.gravity ?? false, delta: vector.delta.toArray(),
        dash: ink.getLineDash(), lineWidth: ink.lineWidth, rgba: [...rgb],
      });
"""
TEST_TAPS = {
    "      renderer.render(scene, camera);": TAP,
    "      onVelocityScale(showVelocityArrows && velocityScale ? velocityScale : null);":
        "\n      window.velocityScale = velocityScale;",
    "      ink.lineWidth = vector.gravity ? 2 : 3.25;\n      ink.stroke();": VECTOR_TAP,
    "          ink.fillText(name, x + 6, y + h / 2);": "\n          window.vectorLabels.push(name);",
    "      drawVectors(centers, width, height, occupied);": """
      window.labelsCoverBodies = () => {
        const bounds = overlay.getBoundingClientRect();
        return Object.values(labels).filter(label => !label.hidden).some(label => {
          const rect = (label.firstElementChild ?? label).getBoundingClientRect();
          if (!rect.width || !rect.height) return false;
          const box = {
            left: rect.left - bounds.left, top: rect.top - bounds.top,
            right: rect.right - bounds.left, bottom: rect.bottom - bounds.top,
          };
          return Object.values(centers).some(({ silhouette }) => overlaps(box, silhouette));
        });
      };
""",
}
NAMES = {"Sol": "sun", "Terra": "earth", "Marte": "mars"}


def state(page):
    return page.evaluate("inspectGps()")


def world(vector, origin=ZERO):
    x, y, z = (vector[axis] - offset for axis, offset in zip("xyz", origin, strict=True))
    return x, z, -y


def assert_frame(page, data, reference):
    current = state(page)
    positions, velocities = data["positions"], data["velocities_km_s"]
    frame_velocities = {}
    for body, model in current["meshes"].items():
        center = world(positions[body], tuple(positions[reference][axis] for axis in "xyz"))
        velocity = world(velocities[body], tuple(velocities[reference][axis] for axis in "xyz"))
        assert dist(model["center"], center) < 1e-12
        frame_velocities[body] = velocity
        speed = f"{dist(velocity, ZERO):.3f}".replace(".", ",") + " km/s"
        expect(page.locator(f"#gps-speed-{body}")).to_have_text(speed)
        bar = page.locator(f"#gps-speed-bar-{body}")
        track = bar.locator("..")
        scale = float(page.locator("#gps-speed-max").inner_text().split()[0])
        width = bar.evaluate("(bar) => bar.getBoundingClientRect().width")
        assert abs(width - track.bounding_box()["width"] * dist(velocity, ZERO) / scale) < 0.08
    for arrow in current["vectors"]:
        if arrow["gravity"]:
            continue
        body = NAMES[arrow["name"].split(" · ")[1]]
        assert body != reference
        assert dist(arrow["delta"], tuple(component * current["velocityScale"] for component in frame_velocities[body])) < 1e-12
        assert arrow["lineWidth"] >= 3 and arrow["dash"] == []
    factor = float(page.locator("#gps-velocity-scale").inner_text().split()[0].replace(",", "."))
    assert isclose(factor / 10, current["velocityScale"], rel_tol=0.005)
    assert current["light"] == current["meshes"]["sun"]["center"]
    return current


def verify_gravity(page, data, current):
    field = current["field"]
    meshes = current["meshes"]
    assert field["visible"]
    anchor = current["trackedBody"] or "sun"
    x, _, z = meshes["sun"]["center"]
    origin = (x, meshes[anchor]["center"][1], z)
    assert dist(field["origin"], origin) < 1e-14
    assert dist(field["normal"], (0, 1, 0)) < 1e-14
    for i, (body, model) in enumerate(meshes.items()):
        assert dist(field["offsets"][i], tuple(a - b for a, b in zip(model["center"], origin, strict=True))) < 1e-14
        assert isclose(field["gmPerAu"][i], GM[body] / AU, rel_tol=1e-14)
        assert isclose(field["radii"][i], RADII[body][0] / AU, rel_tol=1e-14)
        here = data["positions"][body]
        actual = current["accelerations"][body]
        total = [0.0, 0.0, 0.0]
        for source, position in data["positions"].items():
            if source == body:
                continue
            km = [(position[axis] - here[axis]) * AU for axis in "xyz"]
            expected = [1000 * GM[source] * component / dist(km, ZERO) ** 3 for component in km]
            vector = actual["contributions"][source]
            assert dist(list(vector.values()), expected) < 1e-15 * dist(expected, ZERO)
            total = [a + b for a, b in zip(total, expected, strict=True)]
        assert dist(list(actual["total"].values()), total) < 1e-15 * dist(total, ZERO)
    for arrow in current["vectors"]:
        if not arrow["gravity"]:
            continue
        body, _, source = arrow["name"].split(" · ")[1].partition(" ← ")
        record = current["accelerations"][NAMES[body]]
        vector = world(record["contributions"][NAMES[source]] if source else record["total"])
        assert dist([v / dist(arrow["delta"], ZERO) for v in arrow["delta"]], [v / dist(vector, ZERO) for v in vector]) < 1e-14
        assert arrow["lineWidth"] == 2 and len(arrow["dash"]) == 2


def verify_isolated_source(page):
    close, far = page.evaluate("""() => [1, 2].map(x => gpsPhysics.accelerationFrom(
        {x, y: 0, z: 0}, gpsPhysics.ZERO, gpsPhysics.GM_KM3_S2.sun))""")
    assert close["x"] < 0 and close["y"] == close["z"] == 0
    assert isclose(-close["x"], 1000 * GM["sun"] / AU**2, rel_tol=1e-14)
    assert isclose(far["x"] / close["x"], 0.25, rel_tol=1e-14)
    return -close["x"], -far["x"]


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
    page.on("console", lambda message: errors.append(message.text) if "THREE.WebGLProgram: Shader Error" in message.text else None)
    canvas = page.locator("#gps-stage canvas[tabindex]")
    expect(canvas).to_be_visible()
    page.wait_for_function("Object.values(inspectGps().meshes).every(m => m.visible && m.textureWidth === 1024)")
    expect(page.locator("#gps-render-error")).to_be_hidden()
    expect(page.locator("#gps-live-state")).to_have_text("Acompanhando o relógio UTC")
    params = {"instant": START, "velocities": "true"}
    data = page.request.get("/api/ephemerides/mars", params=params).json()
    cut(page)
    assert not page.evaluate("labelsCoverBodies()")

    real = page.get_by_role("button", name="Proporção real", exact=True)
    real.press("Enter")
    assert not page.evaluate("labelsCoverBodies()")
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

    velocity_arrows = {arrow["name"]: arrow for arrow in overview["vectors"]}
    assert set(velocity_arrows) == {"v · Terra", "v · Marte"}
    assert set(overview["vectorLabels"]) == set(velocity_arrows)
    assert all(arrow["rgba"][3] >= 220 for arrow in velocity_arrows.values())
    if captures:
        page.locator("#gps-stage").screenshot(path=captures / f"visao-geral-{width}.png")
        page.locator(".gps-motion").screenshot(path=captures / f"velocidades-{width}.png")
    motion = page.get_by_role("region", name="Movimento relativo")
    curvature = motion.get_by_role("checkbox", name="Curvatura espacial")
    curvature.press("Space")
    expect(page.locator("#gps-curvature-info")).to_contain_text("1.000×")
    curved = assert_frame(page, data, "sun")
    assert curved["meshes"] == meshes and curved["vectors"] == overview["vectors"]
    assert curved["slice"]["origin"] == list(ZERO)
    rs, height_error = verify_surface(curved["slice"])
    if captures:
        page.locator("#gps-stage").screenshot(path=captures / f"curvatura-{width}.png")
    curvature.press("Space")

    gravity = motion.get_by_role("checkbox", name="Campo gravitacional")
    gravity.press("Space")
    expect(motion.locator("#gps-gravity-legend")).to_be_visible()
    field = assert_frame(page, data, "sun")
    assert field["meshes"] == meshes
    verify_gravity(page, data, field)
    assert {arrow["name"] for arrow in field["vectors"] if arrow["gravity"]} == {"g · Sol", "g · Terra", "g · Marte"}
    changed = page.evaluate("gravityFieldPixels()")
    assert changed > 0.12, changed
    near, far = verify_isolated_source(page)
    if captures:
        page.locator("#gps-stage").screenshot(path=captures / f"campo-{width}.png")

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
    assert closer["velocityScale"] != overview["velocityScale"]
    assert any(arrow["name"] == "v · Marte" for arrow in closer["vectors"])
    verify_gravity(page, data, closer)
    source = page.get_by_role("combobox", name="Vetor de aceleração no foco")
    expect(source).to_be_visible()
    source.select_option("earth")
    contribution = state(page)
    assert any(arrow["name"] == "g · Marte ← Terra" for arrow in contribution["vectors"])
    assert {"v · Marte", "g · Marte ← Terra"} <= set(contribution["vectorLabels"])
    verify_gravity(page, data, contribution)
    if captures:
        source.focus()
        page.locator("#gps-stage").screenshot(path=captures / f"foco-marte-{width}.png")
        page.locator("#gps-gravity-readout").screenshot(path=captures / f"contribuicoes-marte-{width}.png")

    select.focus()
    select.press("Tab")
    expect(page.get_by_role("checkbox", name="Vetores de velocidade")).to_be_focused()
    select.select_option("earth")
    earth = assert_frame(page, data, "earth")
    assert earth["trackedBody"] == "mars"
    assert earth["target"] == earth["meshes"]["mars"]["center"]
    assert earth["accelerations"] == field["accelerations"]
    verify_gravity(page, data, earth)
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
            equatorial, polar = RADII[key]
            if is_real:
                assert isclose(model["diameter"], meshes[key]["diameter"], rel_tol=1e-13)
                assert isclose(model["scale"][1], polar / AU, rel_tol=1e-13)
            else:
                assert model["diameter"] > 2 * equatorial / AU
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
    stationary = assert_frame(page, data, "mars")
    page.get_by_role("button", name="Visão geral", exact=True).click()
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
    advanced = assert_frame(page, sampled, "mars")
    verify_gravity(page, sampled, advanced)
    assert advanced["field"]["offsets"] != stationary["field"]["offsets"]
    assert advanced["accelerations"] != stationary["accelerations"]
    if captures:
        page.locator("#gps-stage").screenshot(path=captures / f"campo-data-avancada-{width}.png")
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    assert not errors, errors
    print(f"{width}px | Sol/Terra {ratio:.8f} | Terra–Marte {separation:.12f} ua | rₛ {rs:.8f} km")
    sizes = " / ".join(f"{overview['apparent'][body]:.6f}" for body in ("sun", "earth", "mars"))
    print(f"  Diâmetros iniciais Sol/Terra/Marte: {sizes} px. Erro de altura de Flamm ≤ {1000 * height_error:.3f} m.")
    print(f"  Fonte solar isolada: {near:.9g} m/s² a 1 ua e {far:.9g} m/s² a 2 ua. Campo alterou {changed:.1%} do canvas.")
    print(f"  Reprodução 2×: avanço de {step:.2f} dias simulados em 1,6 segundo.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002/")
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--captures", type=Path)
    args = parser.parse_args()
    original = SCENE_JS.read_text()
    source = original
    for statement, tap in TEST_TAPS.items():
        assert source.count(statement) == 1
        source = source.replace(statement, statement + tap)

    def observe_scene(route):
        response = route.fetch()
        assert response.ok and response.text() == original
        route.fulfill(response=response, body=source)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel)
        for width, height in ((1440, 1050), (390, 844)):
            context = browser.new_context(
                base_url=args.url, viewport={"width": width, "height": height},
                is_mobile=width < 500, has_touch=width < 500,
            )
            context.route("**/assets/solar-scene.js", observe_scene)
            page = context.new_page()
            page.goto(args.url)
            check_view(page, width, args.captures)
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
