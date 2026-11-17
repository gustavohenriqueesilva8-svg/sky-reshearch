(() => {
  "use strict";

  const physics = window.gpsPhysics;
  const RADIANS = Math.PI / 180;
  const WHEEL_SENSITIVITY = 0.0025;
  const MIN_CLEARANCE_RADII = 0.06;
  const GRAVITY_INK = "#e1ceff";
  const GRAVITY_ARROW_OFFSETS = { sun: -10, earth: 0, mars: 10 };
  const GRAVITY_VECTOR_LENGTH_AU = 0.36;
  const STAR_SPHERE_AU = 600;
  const OVERVIEW_FOV = 42;
  const EARTH_ALTITUDE_AU = 5_000 / physics.AU_KM;

  window.createSolarScene = (stage, bodies, {
    onSelect, onTarget, onMissingTextures, onApparentSizes, onVelocityScale, onViewScale, onComparison,
  }) => {
    const THREE = window.SkyThree;
    const canvas = stage.querySelector("canvas");
    const renderError = stage.querySelector("#gps-render-error");
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, logarithmicDepthBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const overlay = stage.querySelector(".gps-vector-overlay");
    const ink = overlay.getContext("2d");
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#080f1c");
    const comparisonScene = new THREE.Scene();
    comparisonScene.background = scene.background;
    const camera = new THREE.PerspectiveCamera(OVERVIEW_FOV, 1, 1e-8, STAR_SPHERE_AU * 2);
    const comparisonCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1e-8, 1);
    const overview = new THREE.Vector3(2.65, 2.65, 4.7);
    camera.position.copy(overview);

    const controls = new THREE.OrbitControls(camera, canvas);
    controls.enabled = false;
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.maxDistance = 14;
    controls.update();

    // Rotate the astronomical frame by -90° around X to use Y as scene up.
    // Every center already comes in au. Physical radii are converted to au once.
    const toWorld = ({ x, y, z }) => new THREE.Vector3(x, z, -y);
    const eclipticAt = (radius, angle) => new THREE.Vector3(
      radius * Math.cos(angle),
      radius * Math.sin(angle) * Math.sin(physics.OBLIQUITY_J2000),
      -radius * Math.sin(angle) * Math.cos(physics.OBLIQUITY_J2000),
    );
    const eclipticNormal = new THREE.Vector3(0, Math.cos(physics.OBLIQUITY_J2000), Math.sin(physics.OBLIQUITY_J2000));
    const origin = new THREE.Vector3();
    const gridInk = new THREE.LineBasicMaterial({ color: 0x536d8f, transparent: true, depthWrite: false });
    const grid = new THREE.Group();
    const ticks = [];
    for (const radius of [0.5, 1, 1.5, 2]) {
      const points = Array.from({ length: 129 }, (_, i) => eclipticAt(radius, i * Math.PI / 64));
      grid.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), gridInk));
      if (radius < 2) ticks.push([`ring-${radius}`, eclipticAt(radius, Math.PI * 1.12)]);
    }
    const spokes = Array.from({ length: 8 }, (_, i) => [origin, eclipticAt(2, i * Math.PI / 4)]).flat();
    grid.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(spokes), gridInk));
    scene.add(grid);

    const starCoords = [];
    const starColors = [];
    const starColor = new THREE.Color();
    let seed = 21413;
    function randomStar() {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 2 ** 32;
    }
    for (let i = 0; i < 4000; i += 1) {
      const y = 2 * randomStar() - 1;
      const angle = 2 * Math.PI * randomStar();
      const r = Math.sqrt(1 - y * y);
      starCoords.push(STAR_SPHERE_AU * r * Math.cos(angle), STAR_SPHERE_AU * y, STAR_SPHERE_AU * r * Math.sin(angle));
      const strength = 0.13 + 0.72 * randomStar() ** 4;
      starColor.set(i % 5 ? 0xc1d2ef : 0xf4d6a9).multiplyScalar(strength ** 2);
      starColors.push(starColor.r, starColor.g, starColor.b);
    }
    const starGeometry = new THREE.BufferGeometry()
      .setAttribute("position", new THREE.Float32BufferAttribute(starCoords, 3))
      .setAttribute("color", new THREE.Float32BufferAttribute(starColors, 3));
    const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({
      vertexColors: true, size: 1.35, sizeAttenuation: false, depthWrite: false,
    }));
    scene.add(stars);

    const baseline = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([origin, origin]),
      new THREE.LineBasicMaterial({ color: 0xf0e5cc, transparent: true, opacity: 0.8, depthWrite: false }),
    );
    baseline.visible = false;
    baseline.frustumCulled = false;
    scene.add(baseline);
    const ruler = stage.querySelector("#gps-view-scale");
    const sunlight = new THREE.PointLight(0xfff1df, 4.6, 0, 2);
    scene.add(sunlight);
    const halo = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
      uniforms: { glow: { value: new THREE.Color("#ffb45c") } },
      transparent: true, depthWrite: false,
      vertexShader: `
        #include <common>
        #include <logdepthbuf_pars_vertex>
        varying vec2 haloUv;
        void main() {
          haloUv = uv * 2.0 - 1.0;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          #include <logdepthbuf_vertex>
        }`,
      fragmentShader: `
        #include <logdepthbuf_pars_fragment>
        uniform vec3 glow;
        varying vec2 haloUv;
        void main() {
          #include <logdepthbuf_fragment>
          float r = length(haloUv);
          float a = 0.38 * exp(-6.5 * max(0.0, r - 0.36)) * (1.0 - smoothstep(0.78, 1.0, r));
          gl_FragColor = vec4(glow, a);
          #include <colorspace_fragment>
        }`,
    }));
    halo.visible = false;
    scene.add(halo);
    const labels = Object.fromEntries(Array.from(stage.querySelectorAll("[data-scene-label]"),
      (element) => [element.dataset.sceneLabel, element]));
    const meshes = {};
    const comparisonMeshes = {};
    const paths = {};
    const trails = {};
    const textures = new THREE.TextureLoader();
    const missingTextures = new Set();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let approachFrame = null;
    let trackedBody = null;
    let comparing = false;
    let earthPreset = false;
    let earthAltitude = EARTH_ALTITUDE_AU;
    let frameReference = "sun";
    let measuredPair = [];
    let freeReference = overview.length();
    let contextAvailable = true;
    let velocities = null;
    let showVelocityArrows = true;
    let curvature = null;
    let gravity = null;
    let accelerations = null;
    let gravitySource = "total";

    function placeLabel(label, vector) {
      const point = vector.clone().project(camera);
      label.hidden = point.z < -1 || point.z > 1 || Math.abs(point.x) > 1 || Math.abs(point.y) > 1;
      if (!label.hidden) {
        label.style.left = `${(point.x + 1) * 50}%`;
        label.style.top = `${(1 - point.y) * 50}%`;
      }
    }

    function screenPoint(view, width, height, viewing = camera) {
      const point = view.clone().applyMatrix4(viewing.projectionMatrix);
      return { x: (point.x + 1) * width / 2, y: (1 - point.y) * height / 2 };
    }

    function overlaps(a, b) {
      return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    }

    function placeBodyLabel(label, center, width, height, occupied) {
      const { x, y, diameterPx, silhouette } = center;
      const subpixel = diameterPx < 2;
      label.toggleAttribute("data-subpixel", subpixel);
      label.toggleAttribute("data-comparison-marker", comparing && subpixel);
      label.removeAttribute("data-marker-only");
      if (subpixel) label.setAttribute("aria-description", "Diâmetro aparente inferior a dois pixels.");
      else label.removeAttribute("aria-description");
      label.hidden = x < 0 || x > width || y < 0 || y > height;
      if (label.hidden) return;
      if (comparing && subpixel) {
        label.removeAttribute("data-left");
        label.style.left = `${x}px`;
        label.style.top = `${y}px`;
        return;
      }
      const fits = (box) => box.left >= 0 && box.right <= width && box.top >= 0 && box.bottom <= height &&
        !occupied.some((other) => overlaps(box, other));
      if (subpixel) {
        const { offsetWidth: w, offsetHeight: h } = label.firstElementChild;
        label.style.left = `${x}px`;
        label.style.top = `${y}px`;
        for (const onLeft of [false, true]) {
          const left = onLeft ? x - 10 - w : x + 10;
          const box = { left, top: y - h / 2, right: left + w, bottom: y + h / 2 };
          if (!fits(box)) continue;
          label.toggleAttribute("data-left", onLeft);
          occupied.push(box);
          return;
        }
        label.setAttribute("data-marker-only", "");
        return;
      }

      const halfWidth = label.offsetWidth / 2;
      const h = label.offsetHeight;
      const centeredX = Math.max(halfWidth, Math.min(x, width - halfWidth));
      const candidates = [
        [centeredX, silhouette.top - 6],
        [silhouette.right + 6 + halfWidth, y + h / 2],
        [silhouette.left - 6 - halfWidth, y + h / 2],
        [centeredX, silhouette.bottom + 6 + h],
      ];
      for (const [anchorX, anchorY] of candidates) {
        const box = { left: anchorX - halfWidth, top: anchorY - h, right: anchorX + halfWidth, bottom: anchorY };
        if (!fits(box)) continue;
        label.style.left = `${anchorX}px`;
        label.style.top = `${anchorY}px`;
        occupied.push(box);
        return;
      }
      label.hidden = true;
    }

    function paintVector(vector, center, width, height, annotations) {
      const { x, y, diameterPx, view } = center;
      if (x < 0 || x > width || y < 0 || y > height) return;
      const tipView = view.clone().add(vector.delta.clone().applyMatrix3(viewRotation));
      // A projected line remains straight. Clip at the near plane before projecting.
      if (tipView.z > -camera.near) {
        tipView.lerp(view, (-camera.near - tipView.z) / (view.z - tipView.z));
      }
      const tip = screenPoint(tipView, width, height);
      const dx = tip.x - x;
      const dy = tip.y - y;
      const length = Math.hypot(dx, dy);
      const gap = Math.max(9, diameterPx / 2 + 4);
      if (!Number.isFinite(length) || length - gap < 9) return;
      const ux = dx / length;
      const uy = dy / length;
      // Separate parallel gravity arrows in projection while preserving their bearing.
      const offset = vector.offset ?? 0;
      const ox = Math.abs(uy) * offset;
      const oy = -ux * (Math.sign(uy) || 1) * offset;
      const horizontal = ux === 0 ? Infinity : ((ux > 0 ? width : 0) - x - ox) / ux;
      const vertical = uy === 0 ? Infinity : ((uy > 0 ? height : 0) - y - oy) / uy;
      const visibleLength = Math.min(length, horizontal, vertical);
      if (visibleLength - gap < 9) return;
      const clipped = visibleLength < length;
      tip.x = x + ox + ux * visibleLength;
      tip.y = y + oy + uy * visibleLength;
      const head = clipped ? 0 : Math.min(12, (visibleLength - gap) * 0.64);
      const arrowBase = { x: tip.x - ux * head, y: tip.y - uy * head };
      const dash = vector.gravity ? [5, 4] : [];

      ink.lineCap = "round";
      ink.lineJoin = "round";
      ink.beginPath();
      ink.moveTo(x + ox + ux * gap, y + oy + uy * gap);
      ink.lineTo(arrowBase.x, arrowBase.y);
      ink.setLineDash(dash);
      ink.strokeStyle = "#070e1a";
      ink.lineWidth = 6;
      ink.stroke();
      ink.strokeStyle = vector.color;
      ink.lineWidth = vector.gravity ? 2 : 3.25;
      ink.stroke();
      ink.setLineDash([]);
      if (clipped) return;
      ink.beginPath();
      ink.moveTo(tip.x, tip.y);
      ink.lineTo(arrowBase.x - uy * head * 0.45, arrowBase.y + ux * head * 0.45);
      ink.lineTo(arrowBase.x + uy * head * 0.45, arrowBase.y - ux * head * 0.45);
      ink.closePath();
      ink.strokeStyle = "#070e1a";
      ink.lineWidth = 4;
      ink.stroke();
      ink.fillStyle = vector.gravity ? "#0b1525" : vector.color;
      ink.fill();
      if (vector.gravity) {
        ink.strokeStyle = vector.color;
        ink.lineWidth = 1.5;
        ink.stroke();
      }
      if (tip.x >= 0 && tip.x <= width && tip.y >= 0 && tip.y <= height) {
        const headBounds = {
          left: Math.min(tip.x, arrowBase.x) - 6, right: Math.max(tip.x, arrowBase.x) + 6,
          top: Math.min(tip.y, arrowBase.y) - 6, bottom: Math.max(tip.y, arrowBase.y) + 6,
        };
        annotations.push({ ...vector, tip, ux, uy, headBounds });
      }
    }

    function paintVectorLabels(annotations, occupied, width, height) {
      ink.font = "600 11px system-ui, sans-serif";
      ink.textBaseline = "middle";
      for (const { tip, ux, uy, name, color } of annotations) {
        const w = ink.measureText(name).width + 12;
        const h = 19;
        // Try beyond the tip, then to either side of the arrow.
        const offsets = [[ux, uy], [-uy, ux], [uy, -ux], [1, 0], [-1, 0], [0, -1], [0, 1],
          [1, 1], [-1, 1], [1, -1], [-1, -1]];
        for (const [dx, dy] of offsets) {
          const x = Math.max(2, Math.min(width - w - 2, tip.x + dx * (w / 2 + 7) - w / 2));
          const y = Math.max(2, Math.min(height - h - 2, tip.y + dy * (h / 2 + 8) - h / 2));
          const box = { left: x, top: y, right: x + w, bottom: y + h };
          if (occupied.some((other) => overlaps(box, other))) continue;
          ink.fillStyle = "#0a1322";
          ink.beginPath();
          ink.roundRect(x, y, w, h, 4);
          ink.fill();
          ink.fillStyle = color;
          ink.fillText(name, x + 6, y + h / 2);
          occupied.push(box);
          break;
        }
      }
    }

    const viewRotation = new THREE.Matrix3();
    function drawVectors(centers, width, height, occupied) {
      ink.clearRect(0, 0, width, height);
      viewRotation.setFromMatrix4(camera.matrixWorldInverse);
      const velocityScale = velocities ? physics.VELOCITY_AU_PER_KM_S : null;
      onVelocityScale(showVelocityArrows && velocityScale ? velocityScale : null);
      const annotations = [];
      for (const [key, center] of Object.entries(centers)) {
        const name = bodies[key].label;
        if (accelerations && gravity?.visible) {
          const source = key === trackedBody ? gravitySource : "total";
          const { total, contributions } = accelerations[key];
          const delta = toWorld(contributions[source] ?? total).setLength(GRAVITY_VECTOR_LENGTH_AU);
          paintVector({
            delta, name: source === "total" ? `g · ${name}` : `g · ${name} ← ${bodies[source].label}`,
            color: GRAVITY_INK, gravity: true,
            offset: trackedBody ? 0 : GRAVITY_ARROW_OFFSETS[key],
          }, center, width, height, annotations);
        }
        if (showVelocityArrows && velocityScale) {
          const delta = toWorld(velocities[key]).multiplyScalar(velocityScale);
          paintVector({ delta, name: `v · ${name}`, color: bodies[key].color }, center, width, height, annotations);
        }
      }
      if (!annotations.length) return;
      for (const { headBounds } of annotations) occupied.push(headBounds);
      paintVectorLabels(annotations, occupied, width, height);
    }

    function targetRadius() {
      return meshes[trackedBody ?? "sun"].scale.x;
    }

    function nearestSurface() {
      let clearance = Infinity;
      for (const mesh of Object.values(meshes)) {
        if (mesh.visible) {
          clearance = Math.min(clearance, camera.position.distanceTo(mesh.position) - mesh.scale.x);
        }
      }
      return clearance;
    }

    function updateBaseline() {
      const [first, second] = measuredPair.map((key) => meshes[key]);
      baseline.visible = Boolean(first?.visible && second?.visible);
      if (!baseline.visible) return;
      const vertices = baseline.geometry.getAttribute("position");
      for (const [i, { position }] of [first, second].entries()) {
        vertices.setXYZ(i, position.x, position.y, position.z);
      }
      vertices.needsUpdate = true;
    }

    function updateViewScale(pixelsPerSlope, width, viewing) {
      const key = comparing ? "sun" : trackedBody ?? frameReference;
      const mesh = comparing ? comparisonMeshes.sun : meshes[key];
      if (!mesh.visible) {
        onViewScale(null);
        return;
      }
      const depth = -mesh.position.clone().applyMatrix4(viewing.matrixWorldInverse).z;
      if (depth <= viewing.near) {
        onViewScale(null);
        return;
      }
      const auPerPx = (comparing ? 1 : depth) / pixelsPerSlope;
      const maxAu = Math.min(135, width * 0.37) * auPerPx;
      const unit = maxAu >= 0.1 ? "ua" : "km";
      const unitsPerAu = unit === "ua" ? 1 : physics.AU_KM;
      const maxLength = maxAu * unitsPerAu;
      const decade = 10 ** Math.floor(Math.log10(maxLength));
      const length = ([5, 2, 1].find((step) => step * decade <= maxLength) ?? 1) * decade;
      onViewScale({
        key, unit, length, pixels: length / (unitsPerAu * auPerPx),
        rangeKm: comparing ? null : camera.position.distanceTo(mesh.position) * physics.AU_KM,
      });
    }

    function draw() {
      const { clientWidth: width, clientHeight: height } = stage;
      if (!contextAvailable || !width || !height) return;
      const viewing = comparing ? comparisonCamera : camera;
      if (comparing) {
        renderer.render(comparisonScene, comparisonCamera);
      } else {
        const clearance = nearestSurface();
        const t = Math.max(0, Math.min(1, (clearance - 0.0125) / (physics.ZOOM_GRID_LIMIT_AU - 0.0125)));
        const guideOpacity = t * t * (3 - 2 * t);
        grid.visible = guideOpacity > 0;
        gridInk.opacity = 0.7 * guideOpacity;
        baseline.material.opacity = 0.8 * guideOpacity;
        for (const path of Object.values(paths)) path.material.opacity = path.userData.opacity * guideOpacity;
        for (const trail of Object.values(trails)) trail.material.opacity = guideOpacity;
        halo.quaternion.copy(camera.quaternion);
        renderer.render(scene, camera);
      }
      const apparentSizes = {};
      const centers = {};
      const pixelsPerSlope = height * viewing.projectionMatrix.elements[5] / 2;
      for (const [key, mesh] of Object.entries(comparing ? comparisonMeshes : meshes)) {
        if (!mesh.visible) continue;
        const view = mesh.position.clone().applyMatrix4(viewing.matrixWorldInverse);
        const radius = mesh.scale.x;
        const depth = -view.z;
        const diameterPx = comparing ? 2 * radius * pixelsPerSlope :
          physics.apparentDiameterPx(radius, depth, view.y, pixelsPerSlope);
        apparentSizes[key] = diameterPx;
        if (diameterPx === null || depth > viewing.far) {
          labels[key].hidden = true;
          continue;
        }
        const { x, y } = screenPoint(view, width, height, viewing);
        const shift = comparing ? 0 : pixelsPerSlope * radius ** 2 / (depth * (depth ** 2 - radius ** 2));
        const cx = x + shift * view.x;
        const cy = y - shift * view.y;
        const halfWidth = Math.max(7, comparing ? diameterPx / 2 :
          physics.apparentDiameterPx(radius, depth, view.x, pixelsPerSlope) / 2);
        const halfHeight = Math.max(7, diameterPx / 2);
        centers[key] = { x, y, view, diameterPx, silhouette: {
          left: cx - halfWidth, top: cy - halfHeight, right: cx + halfWidth, bottom: cy + halfHeight,
        } };
      }
      const occupied = Object.values(centers).map(({ silhouette }) => silhouette);
      const bounds = overlay.getBoundingClientRect();
      updateViewScale(pixelsPerSlope, width, viewing);
      if (!ruler.hidden) {
        const rect = ruler.getBoundingClientRect();
        occupied.push({
          left: rect.left - bounds.left, top: rect.top - bounds.top,
          right: rect.right - bounds.left, bottom: rect.bottom - bounds.top,
        });
      }
      for (const [key, center] of Object.entries(centers)) {
        placeBodyLabel(labels[key], center, width, height, occupied);
      }
      for (const [key, tip] of ticks) {
        const label = labels[key];
        label.style.opacity = gridInk.opacity;
        if (comparing || !grid.visible) {
          label.hidden = true;
          continue;
        }
        placeLabel(label, tip);
        if (label.hidden) continue;
        const rect = label.getBoundingClientRect();
        const box = {
          left: rect.left - bounds.left, top: rect.top - bounds.top,
          right: rect.right - bounds.left, bottom: rect.bottom - bounds.top,
        };
        label.hidden = occupied.some((other) => overlaps(box, other));
        if (!label.hidden) occupied.push(box);
      }
      if (comparing || earthPreset) {
        ink.clearRect(0, 0, width, height);
        onVelocityScale(null);
      } else {
        drawVectors(centers, width, height, occupied);
      }
      onApparentSizes(apparentSizes);
    }

    function textureUnavailable(key) {
      missingTextures.add(bodies[key].label);
      onMissingTextures([...missingTextures]);
    }

    for (const [key, body] of Object.entries(bodies)) {
      const material = key === "sun"
        ? new THREE.MeshBasicMaterial({ color: 0xffb460 })
        : new THREE.MeshStandardMaterial({ color: body.color, roughness: key === "earth" ? 0.82 : 1 });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 40), material);
      const [ra, dec] = body.pole.map((angle) => angle * RADIANS);
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), toWorld({
        x: Math.cos(dec) * Math.cos(ra),
        y: Math.cos(dec) * Math.sin(ra),
        z: Math.sin(dec),
      }));
      mesh.name = `astro-${key}`;
      mesh.userData.body = key;
      mesh.visible = false;
      meshes[key] = mesh;
      scene.add(mesh);
      labels[key].addEventListener("click", () => onSelect(key));

      const comparison = new THREE.Mesh(mesh.geometry, new THREE.MeshBasicMaterial({ color: material.color }));
      comparison.scale.setScalar(body.radiusKm / physics.AU_KM);
      comparison.quaternion.copy(mesh.quaternion);
      comparisonMeshes[key] = comparison;
      comparisonScene.add(comparison);

      const source = window.gpsSolarTextures?.[key];
      if (source) {
        textures.load(source, (texture) => {
          texture.colorSpace = THREE.SRGBColorSpace;
          for (const surface of [material, comparison.material]) {
            surface.map = texture;
            surface.color.set(0xffffff);
            surface.needsUpdate = true;
          }
          draw();
        }, undefined, () => textureUnavailable(key));
      } else {
        textureUnavailable(key);
      }

      const path = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({
        color: body.color, transparent: true, opacity: 0.5,
      }));
      path.name = `orbit-${key}`;
      path.visible = false;
      path.userData.opacity = 0.38;
      paths[key] = path;
      scene.add(path);

      const color = new THREE.Color(body.color);
      const colors = [];
      for (let i = 0; i < physics.TRAIL_POINTS; i += 1) {
        colors.push(color.r, color.g, color.b, (i / (physics.TRAIL_POINTS - 1)) ** 1.4);
      }
      const trailGeometry = new THREE.BufferGeometry()
        .setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(physics.TRAIL_POINTS * 3), 3))
        .setAttribute("color", new THREE.Float32BufferAttribute(colors, 4));
      const trail = new THREE.Line(trailGeometry, new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, depthWrite: false,
      }));
      trail.frustumCulled = false;
      trail.visible = false;
      trails[key] = trail;
      scene.add(trail);
    }

    const solarRadius = comparisonMeshes.sun.scale.x;
    let rightEdge = -solarRadius;
    for (const mesh of Object.values(comparisonMeshes)) {
      mesh.position.x = rightEdge + mesh.scale.x;
      rightEdge += 2 * mesh.scale.x + solarRadius * 0.44;
    }
    rightEdge -= solarRadius * 0.44;
    const comparisonCenter = (rightEdge - solarRadius) / 2;
    const comparisonHalfWidth = (rightEdge + solarRadius) / 2;

    function frameComparison() {
      const halfHeight = 1.23 * Math.max(solarRadius, comparisonHalfWidth / camera.aspect);
      comparisonCamera.top = halfHeight;
      comparisonCamera.bottom = -halfHeight;
      comparisonCamera.right = halfHeight * camera.aspect;
      comparisonCamera.left = -comparisonCamera.right;
      comparisonCamera.position.set(comparisonCenter, 0, 0.1);
      comparisonCamera.updateProjectionMatrix();
    }

    function setComparison(enabled) {
      if (comparing === enabled) return;
      comparing = enabled;
      if (enabled) {
        stopApproach();
        frameComparison();
      }
      controls.enabled = !comparing && !earthPreset && trackedBody !== null;
      onComparison(enabled);
      draw();
    }

    function updateTrails(samples) {
      for (const [key, trail] of Object.entries(trails)) {
        trail.visible = key !== frameReference && samples.length > 1;
        if (!trail.visible) continue;
        const vertices = trail.geometry.getAttribute("position");
        samples.forEach((sample, i) => {
          const { x, y, z } = sample[key];
          vertices.setXYZ(i, x, z, -y);
        });
        vertices.needsUpdate = true;
      }
    }

    function setCurvature(visible) {
      if (visible && !curvature) {
        const { positions, triangles, lines } = physics.curvatureSurface();
        const vertices = new THREE.Float32BufferAttribute(positions, 3);
        const surface = new THREE.BufferGeometry().setAttribute("position", vertices).setIndex(triangles);
        const wire = new THREE.BufferGeometry().setAttribute("position", vertices).setIndex(lines);
        curvature = new THREE.Group();
        curvature.name = "schwarzschild-sun";
        curvature.add(new THREE.Mesh(surface, new THREE.MeshBasicMaterial({
          color: "#397ac2", transparent: true, opacity: 0.24, depthWrite: false, side: THREE.DoubleSide,
        })));
        curvature.add(new THREE.LineSegments(wire, new THREE.LineBasicMaterial({
          color: "#75b7e6", transparent: true, opacity: 0.42, depthWrite: false,
        })));
        scene.add(curvature);
      }
      if (curvature) {
        curvature.position.copy(meshes.sun.position);
        curvature.visible = visible;
      }
      draw();
    }

    function createGravitySurface() {
      const keys = Object.keys(bodies);
      const material = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        uniforms: {
          sourceOffsets: { value: keys.map(() => new THREE.Vector3()) },
          gmPerAu: { value: keys.map((key) => physics.GM_KM3_S2[key] / physics.AU_KM) },
          radiiAu: { value: keys.map((key) => bodies[key].radiusKm / physics.AU_KM) },
          logLimits: { value: new THREE.Vector2(Math.log(300), Math.log(200_000)) },
          farColor: { value: new THREE.Color("#3f8caa") },
          middleColor: { value: new THREE.Color("#9a78d2") },
          nearColor: { value: new THREE.Color("#eface2") },
          fillOpacity: { value: 0.28 },
        },
        vertexShader: `
          #include <common>
          #include <logdepthbuf_pars_vertex>
          varying vec3 offsetAu;
          void main() {
            offsetAu = mat3(modelMatrix) * position;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            #include <logdepthbuf_vertex>
          }`,
        fragmentShader: `
          #include <logdepthbuf_pars_fragment>
          varying vec3 offsetAu;
          uniform vec3 sourceOffsets[3];
          uniform float gmPerAu[3], radiiAu[3];
          uniform vec2 logLimits;
          uniform vec3 farColor, middleColor, nearColor;
          uniform float fillOpacity;
          void main() {
            float magnitude = 0.0;
            bool exterior = true;
            for (int i = 0; i < 3; i++) {
              float distanceAu = length(offsetAu - sourceOffsets[i]);
              exterior = exterior && distanceAu >= radiiAu[i];
              // Magnitude of Phi = -sum(GM / r) in km²/s².
              magnitude += gmPerAu[i] / max(distanceAu, radiiAu[i]);
            }
            float t = clamp((log(magnitude) - logLimits.x) / (logLimits.y - logLimits.x), 0.0, 1.0);
            vec3 color = t < 0.5 ? mix(farColor, middleColor, t * 2.0) : mix(middleColor, nearColor, t * 2.0 - 1.0);
            float bands = t * 16.0;
            float line = 1.0 - smoothstep(0.0, clamp(fwidth(bands), 0.025, 0.2), abs(fract(bands + 0.5) - 0.5));
            float opacity = (fillOpacity + 0.43 * line) * (1.0 - smoothstep(1.86, 2.2, length(offsetAu)));
            if (!exterior) discard;
            #include <logdepthbuf_fragment>
            gl_FragColor = vec4(color, opacity);
            #include <colorspace_fragment>
          }`,
      });
      const surface = new THREE.Mesh(new THREE.PlaneGeometry(4.4, 4.4), material);
      surface.name = "newtonian-potential";
      surface.rotation.x = physics.OBLIQUITY_J2000 - Math.PI / 2;
      surface.visible = false;
      scene.add(surface);
      return surface;
    }

    function updateGravitySurface() {
      const sun = meshes.sun.position;
      gravity.position.copy(sun);
      if (trackedBody) {
        const height = meshes[trackedBody].position.clone().sub(sun).dot(eclipticNormal);
        gravity.position.addScaledVector(eclipticNormal, height);
      }
      const offsets = gravity.material.uniforms.sourceOffsets.value;
      for (const [i, mesh] of Object.values(meshes).entries()) offsets[i].copy(mesh.position).sub(gravity.position);
      gravity.material.uniforms.fillOpacity.value = trackedBody ? 0.12 : 0.28;
    }

    function resize() {
      const { clientWidth: width, clientHeight: height } = stage;
      if (!width || !height) return;
      camera.aspect = width / height;
      updateFieldOfView();
      camera.updateProjectionMatrix();
      frameComparison();
      renderer.setSize(width, height, false);
      const ratio = renderer.getPixelRatio();
      overlay.width = Math.round(width * ratio);
      overlay.height = Math.round(height * ratio);
      ink.setTransform(overlay.width / width, 0, 0, overlay.height / height, 0, 0);
      draw();
    }

    function updateCamera() {
      if (earthPreset) {
        camera.lookAt(controls.target);
        draw();
        return;
      }
      if (!controls.update()) draw();
    }

    function changeOffset(offset) {
      camera.position.copy(controls.target).add(offset);
      updateCamera();
    }

    function limitMovement(delta) {
      const travel = delta.length();
      if (travel === 0) return delta;
      const direction = delta.clone().divideScalar(travel);
      let allowed = travel;
      // Find the first intersection of the camera's travel segment with a body.
      for (const mesh of Object.values(meshes)) {
        if (!mesh.visible) continue;
        const fromCenter = camera.position.clone().sub(mesh.position);
        const along = fromCenter.dot(direction);
        if (along >= 0) continue;
        const safeRadius = mesh.scale.x * (1 + MIN_CLEARANCE_RADII);
        const outside = fromCenter.lengthSq() - safeRadius ** 2;
        const discriminant = along ** 2 - outside;
        if (discriminant > 0) {
          allowed = Math.min(allowed, Math.max(0, -along - Math.sqrt(discriminant)));
        }
      }
      return delta.multiplyScalar(allowed / travel);
    }

    function moveFree(delta) {
      const movement = limitMovement(delta);
      camera.position.add(movement);
      controls.target.add(movement);
      return movement.length();
    }

    function freeMotionScale() {
      return Math.max(1e-9, Math.min(freeReference, nearestSurface()));
    }

    function turnFree(yaw, pitch) {
      const direction = controls.target.clone().sub(camera.position);
      const angle = new THREE.Spherical().setFromVector3(direction);
      angle.theta -= yaw;
      angle.phi += pitch;
      controls.target.copy(camera.position).add(direction.setFromSpherical(angle.makeSafe()));
      updateCamera();
    }

    function panFree(x, y) {
      const scale = 2 * freeMotionScale() / Math.max(1, canvas.clientHeight);
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
      moveFree(right.multiplyScalar(-x * scale).addScaledVector(up, y * scale));
      updateCamera();
    }

    function keepFreeCameraOutside() {
      for (const mesh of Object.values(meshes)) {
        if (!mesh.visible) continue;
        const offset = camera.position.clone().sub(mesh.position);
        const safeRadius = mesh.scale.x * (1 + MIN_CLEARANCE_RADII);
        if (offset.length() >= safeRadius) continue;
        const outward = offset.lengthSq() > 0 ? offset.clone() : camera.position.clone().sub(controls.target);
        const correction = outward.setLength(safeRadius).sub(offset);
        camera.position.add(correction);
        controls.target.add(correction);
      }
    }

    function zoom(logStep, point) {
      if (comparing) return;
      stopApproach();
      const factor = Math.exp(Math.max(-0.75, Math.min(0.75, logStep)));
      if (earthPreset) {
        const radius = meshes.earth.scale.x;
        earthAltitude = Math.max(radius * MIN_CLEARANCE_RADII, Math.min(controls.maxDistance - radius, earthAltitude * factor));
        frameEarthPreset();
        updateCamera();
        return;
      }
      if (!trackedBody) {
        const step = freeMotionScale() * (1 - factor);
        const forward = point ? castAt(point.x, point.y).direction.clone() : camera.getWorldDirection(new THREE.Vector3());
        const moved = moveFree(forward.multiplyScalar(step));
        freeReference = Math.max(1e-9, Math.min(14, freeReference - Math.sign(step) * moved));
        updateCamera();
        return;
      }
      const offset = camera.position.clone().sub(controls.target);
      const radius = targetRadius();
      // Scale the altitude, retaining a small gap outside the bounding sphere.
      const next = radius + (offset.length() - radius) * factor;
      const distance = Math.max(controls.minDistance, Math.min(controls.maxDistance, next));
      const delta = offset.clone().setLength(distance).sub(offset);
      changeOffset(offset.add(limitMovement(delta)));
    }

    function setMinimumDistance() {
      controls.minDistance = trackedBody ? targetRadius() * (1 + MIN_CLEARANCE_RADII) : 0;
    }

    function center(key) {
      earthPreset = false;
      camera.up.set(0, 1, 0);
      updateFieldOfView();
      trackedBody = key;
      controls.enabled = key !== null;
      for (const id of Object.keys(meshes)) labels[id].setAttribute("aria-pressed", String(id === key));
      if (gravity?.visible && meshes.sun.visible) updateGravitySurface();
      onTarget(key);
    }

    function updateFieldOfView() {
      const vertical = 2 * Math.atan(Math.tan(57.5 * RADIANS) / camera.aspect) / RADIANS;
      const next = earthPreset ? Math.max(78, vertical) : OVERVIEW_FOV;
      if (camera.fov === next) return;
      camera.fov = next;
      camera.updateProjectionMatrix();
    }

    function frameEarthPreset() {
      const earth = meshes.earth;
      const sunward = meshes.sun.position.clone().sub(earth.position).normalize();
      const sidelong = new THREE.Vector3().crossVectors(eclipticNormal, sunward).normalize();
      // The Sun and a sunlit crescent fit together when we look from the night side at an angle.
      const angle = 64 * RADIANS;
      const distance = earth.scale.x + earthAltitude;
      camera.position.copy(earth.position)
        .addScaledVector(sunward, -distance * Math.cos(angle))
        .addScaledVector(sidelong, distance * Math.sin(angle));
      const towardsEarth = earth.position.clone().sub(camera.position).normalize();
      const towardsSun = meshes.sun.position.clone().sub(camera.position).normalize();
      controls.target.copy(camera.position).addScaledVector(towardsEarth.lerp(towardsSun, 0.27).normalize(), distance);
    }

    function outsideEarth() {
      if (!meshes.earth.visible) return;
      stopApproach();
      setComparison(false);
      center("earth");
      earthPreset = true;
      earthAltitude = EARTH_ALTITUDE_AU;
      controls.enabled = false;
      camera.up.copy(eclipticNormal);
      updateFieldOfView();
      frameEarthPreset();
      onTarget("earth", false, true);
      updateCamera();
    }

    function stopApproach() {
      if (approachFrame === null) return;
      cancelAnimationFrame(approachFrame);
      approachFrame = null;
      onTarget(trackedBody);
    }

    function focus(key) {
      stopApproach();
      setComparison(false);
      center(key);
      if (!meshes[key].visible) return;
      const target = meshes[key].position;
      const offset = camera.position.clone().sub(target);
      const startDistance = offset.length();
      const endDistance = targetRadius() * 5 * Math.max(1, 1 / camera.aspect);
      const ratio = endDistance / startDistance;
      controls.target.copy(target);
      setMinimumDistance();
      if (reducedMotion.matches || !Number.isFinite(ratio) || Math.abs(Math.log(ratio)) < 0.02) {
        changeOffset(offset.setLength(endDistance));
        return;
      }

      const duration = Math.min(1300, 440 + 68 * Math.abs(Math.log(ratio)));
      const startTime = performance.now();
      function approach(now) {
        const progress = Math.min(1, (now - startTime) / duration);
        const ease = progress ** 2 * (3 - 2 * progress);
        const desired = offset.clone().multiplyScalar(ratio ** ease);
        const current = camera.position.clone().sub(controls.target);
        changeOffset(current.add(limitMovement(desired.sub(current))));
        if (progress < 1) {
          approachFrame = requestAnimationFrame(approach);
        } else {
          approachFrame = null;
          onTarget(key);
        }
      }
      onTarget(key, true);
      updateCamera();
      approachFrame = requestAnimationFrame(approach);
    }

    function setScale(mode) {
      const previousRadius = targetRadius();
      const offset = camera.position.clone().sub(controls.target);
      const distance = offset.length();
      for (const [key, mesh] of Object.entries(meshes)) {
        const { radiusKm, visualRadius } = bodies[key];
        mesh.scale.setScalar(mode === "real" ? radiusKm / physics.AU_KM : visualRadius);
      }
      setMinimumDistance();
      halo.scale.setScalar(meshes.sun.scale.x * 2.75);
      if (earthPreset) {
        frameEarthPreset();
        updateCamera();
        return;
      }
      if (approachFrame !== null) {
        focus(trackedBody);
        return;
      }
      // Preserve the close-up framing and angle across scale changes.
      if (trackedBody && meshes[trackedBody].visible && distance <= previousRadius * 20) {
        offset.setLength(distance * targetRadius() / previousRadius);
      }
      if (!trackedBody) keepFreeCameraOutside();
      changeOffset(offset);
    }

    const raycaster = new THREE.Raycaster();
    const cursor = new THREE.Vector2();
    function castAt(x, y) {
      const rect = canvas.getBoundingClientRect();
      cursor.set(2 * (x - rect.left) / rect.width - 1, 1 - 2 * (y - rect.top) / rect.height);
      raycaster.setFromCamera(cursor, comparing ? comparisonCamera : camera);
      return raycaster.ray;
    }

    function pickBody(x, y) {
      castAt(x, y);
      const visible = Object.values(comparing ? comparisonMeshes : meshes).filter((mesh) => mesh.visible);
      const [hit] = raycaster.intersectObjects(visible, false);
      if (hit) onSelect(hit.object.userData.body);
    }

    const touches = new Map();
    let clickStart = null;
    let freeDrag = null;
    let lastPair = null;
    let pinchFrame = null;
    function touchPair() {
      if (touches.size !== 2) return null;
      const [first, second] = touches.values();
      return {
        span: Math.hypot(first.x - second.x, first.y - second.y),
        x: (first.x + second.x) / 2,
        y: (first.y + second.y) / 2,
      };
    }

    function updatePinch() {
      pinchFrame = null;
      const pair = touchPair();
      if (lastPair?.span && pair?.span) {
        if (lastPair.span !== pair.span) zoom(Math.log(lastPair.span / pair.span), pair);
        if (!trackedBody && (lastPair.x !== pair.x || lastPair.y !== pair.y)) {
          panFree(pair.x - lastPair.x, pair.y - lastPair.y);
        }
      }
      lastPair = pair;
    }

    canvas.addEventListener("pointerdown", (event) => {
      stopApproach();
      const { pointerId: id, clientX: x, clientY: y } = event;
      if (event.pointerType === "touch") {
        touches.set(id, { x, y });
        canvas.setPointerCapture(id);
      }
      if (touches.size > 1) {
        lastPair = touchPair();
        clickStart = null;
        freeDrag = null;
        controls.enableRotate = false;
        return;
      }
      if (event.button === 0) clickStart = { id, x, y };
      if ((!trackedBody || earthPreset) && !comparing && (event.button === 0 || event.button === 2)) {
        freeDrag = { id, x, y, pan: event.shiftKey || event.button === 2 };
        canvas.setPointerCapture(id);
      }
    });
    canvas.addEventListener("pointermove", (event) => {
      const { pointerId: id, clientX: x, clientY: y } = event;
      if (clickStart?.id === id && Math.hypot(x - clickStart.x, y - clickStart.y) > 6) clickStart = null;
      if (touches.has(id)) {
        touches.set(id, { x, y });
        if (touches.size > 1) {
          if (pinchFrame === null) pinchFrame = requestAnimationFrame(updatePinch);
          return;
        }
      }
      if (freeDrag?.id === id && !comparing) {
        const dx = x - freeDrag.x;
        const dy = y - freeDrag.y;
        freeDrag.x = x;
        freeDrag.y = y;
        if (clickStart) return;
        if (earthPreset) leaveFocus();
        if (freeDrag.pan) panFree(dx, dy);
        else turnFree(dx * 0.005, dy * 0.005);
      }
    });
    function dropPointer(event) {
      if (touches.has(event.pointerId) && pinchFrame !== null) {
        cancelAnimationFrame(pinchFrame);
        updatePinch();
      }
      touches.delete(event.pointerId);
      lastPair = touchPair();
      if (touches.size < 2) controls.enableRotate = true;
      if (clickStart?.id === event.pointerId) clickStart = null;
      if (freeDrag?.id === event.pointerId) freeDrag = null;
    }
    function finishPointer(event) {
      const wasClick = clickStart?.id === event.pointerId;
      dropPointer(event);
      if (wasClick) pickBody(event.clientX, event.clientY);
    }
    canvas.addEventListener("pointerup", finishPointer);
    canvas.addEventListener("pointercancel", dropPointer);
    canvas.addEventListener("lostpointercapture", dropPointer);
    canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    stage.addEventListener("wheel", (event) => {
      event.preventDefault();
      const unitSize = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1;
      zoom(event.deltaY * unitSize * WHEEL_SENSITIVITY, { x: event.clientX, y: event.clientY });
    }, { passive: false });

    controls.addEventListener("change", draw);
    new ResizeObserver(resize).observe(stage);
    canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      contextAvailable = false;
      renderError.textContent = "A conexão com o renderizador 3D foi interrompida.";
      renderError.hidden = false;
    });
    canvas.addEventListener("webglcontextrestored", () => {
      contextAvailable = true;
      renderError.hidden = true;
      resize();
    });
    canvas.addEventListener("keydown", (event) => {
      if (comparing) return;
      if (event.key === "+" || event.key === "=" || event.key === "-") {
        event.preventDefault();
        zoom(event.key === "-" ? 0.22 : -0.22);
        return;
      }
      if (!trackedBody) {
        const key = event.key.toLowerCase();
        if (key === "w" || key === "s") {
          event.preventDefault();
          zoom(key === "w" ? -0.16 : 0.16);
          return;
        }
        const move = { a: [1, 0], d: [-1, 0], q: [0, -1], e: [0, 1] }[key];
        if (move) {
          event.preventDefault();
          const step = canvas.clientHeight * 0.07;
          panFree(move[0] * step, move[1] * step);
          return;
        }
      }
      const turn = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
      if (!turn) return;
      event.preventDefault();
      stopApproach();
      if (earthPreset) leaveFocus();
      if (!trackedBody) {
        turnFree(0.13 * turn[0], 0.13 * turn[1]);
        return;
      }
      const offset = camera.position.clone().sub(controls.target);
      const angle = new THREE.Spherical().setFromVector3(offset);
      angle.theta += 0.13 * turn[0];
      angle.phi += 0.13 * turn[1];
      changeOffset(offset.setFromSpherical(angle.makeSafe()));
    });
    setScale("real");
    resize();

    function leaveFocus() {
      if (!trackedBody) return;
      stopApproach();
      freeReference = Math.max(1e-9, camera.position.distanceTo(meshes[trackedBody].position) - targetRadius());
      center(null);
      setMinimumDistance();
      updateCamera();
    }

    return {
      resize,
      zoom,
      setScale,
      setComparison,
      outsideEarth,
      stopApproach,
      setMeasuredPair(pair) {
        measuredPair = pair;
        updateBaseline();
        draw();
      },
      setCurvature,
      setGravityVisibility(visible) {
        if (visible && !gravity) gravity = createGravitySurface();
        if (gravity) gravity.visible = visible;
      },
      setGravitySource(source) {
        gravitySource = source;
        draw();
      },
      setVelocityVisibility(visible) {
        showVelocityArrows = visible;
        draw();
      },
      shiftReference(offset) {
        if (trackedBody) return;
        const shift = toWorld(offset);
        camera.position.add(shift);
        controls.target.add(shift);
      },
      loadTrajectory(samples, reference) {
        for (const [key, path] of Object.entries(paths)) {
          path.geometry.dispose();
          path.visible = key !== reference;
          const points = path.visible ? samples.map((sample) => toWorld(physics.subtract(
            sample[key] ?? physics.ZERO, sample[reference] ?? physics.ZERO
          ))) : [];
          path.geometry = new THREE.BufferGeometry().setFromPoints(points);
        }
      },
      showPositions(positions, frameVelocities, frameAccelerations, reference, trailSamples) {
        const pendingFocus = trackedBody && !meshes[trackedBody].visible;
        for (const [key, mesh] of Object.entries(meshes)) {
          mesh.position.copy(toWorld(positions[key]));
          mesh.visible = true;
        }
        frameReference = reference;
        updateBaseline();
        updateTrails(trailSamples);
        velocities = frameVelocities;
        accelerations = frameAccelerations;
        if (gravity?.visible) updateGravitySurface();
        sunlight.position.copy(meshes.sun.position);
        halo.position.copy(meshes.sun.position);
        halo.visible = true;
        if (curvature) curvature.position.copy(meshes.sun.position);
        if (pendingFocus) {
          focus(trackedBody);
          return;
        }
        if (earthPreset) {
          frameEarthPreset();
        } else if (trackedBody) {
          const target = meshes[trackedBody].position;
          camera.position.sub(controls.target).add(target);
          controls.target.copy(target);
        } else {
          keepFreeCameraOutside();
        }
        updateCamera();
      },
      select(key) {
        for (const id of Object.keys(meshes)) labels[id].classList.toggle("selected", id === key);
        for (const [id, path] of Object.entries(paths)) path.userData.opacity = id === key ? 0.62 : 0.38;
        draw();
      },
      focus,
      free() {
        setComparison(false);
        leaveFocus();
      },
      reset() {
        stopApproach();
        setComparison(false);
        center(null);
        freeReference = overview.length();
        controls.target.set(0, 0, 0);
        setMinimumDistance();
        changeOffset(overview);
      },
    };
  };
})();
