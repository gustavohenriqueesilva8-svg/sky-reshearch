(() => {
  "use strict";

  const physics = window.gpsPhysics;
  const RADIANS = Math.PI / 180;
  const WHEEL_SENSITIVITY = 0.0025;
  const MIN_CLEARANCE_RADII = 0.06;
  const GRAVITY_INK = "#e1ceff";
  const GRAVITY_ARROW_OFFSETS = { sun: -10, earth: 0, mars: 10 };
  const PLANET_SURFACES = {
    earth: { roughness: 0.78, emissive: 0x193766, emissiveIntensity: 0.12 },
    mars: { roughness: 1, emissive: 0x6a2715, emissiveIntensity: 0.1 },
  };

  window.createSolarScene = (stage, bodies, { onSelect, onTarget, onMissingTextures, onApparentSizes, onVelocityScale }) => {
    const THREE = window.SkyThree;
    const canvas = stage.querySelector("canvas");
    const renderError = stage.querySelector("#gps-render-error");
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const overlay = stage.querySelector(".gps-vector-overlay");
    const ink = overlay.getContext("2d");
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.02, 30);
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
    const grid = new THREE.GridHelper(4, 8, 0x516b87, 0x334663);
    grid.material.transparent = true;
    grid.material.opacity = 0.62;
    scene.add(grid);

    const axes = [
      ["x", toWorld({ x: 2.15, y: 0, z: 0 }), 0xcd9a73],
      ["y", toWorld({ x: 0, y: 2.15, z: 0 }), 0x65b4c6],
      ["z", toWorld({ x: 0, y: 0, z: 1.35 }), 0xa1a5d8],
    ];
    const origin = new THREE.Vector3();
    for (const [, tip, color] of axes) {
      const geometry = new THREE.BufferGeometry().setFromPoints([origin, tip]);
      scene.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color })));
    }

    scene.add(new THREE.AmbientLight(0xffffff, 1.4));
    const sunlight = new THREE.PointLight(0xffe7cc, 2.5, 0, 0);
    scene.add(sunlight);
    const labels = Object.fromEntries(Array.from(stage.querySelectorAll("[data-scene-label]"),
      (element) => [element.dataset.sceneLabel, element]));
    const meshes = {};
    const paths = {};
    const textures = new THREE.TextureLoader();
    const missingTextures = new Set();
    let trackedBody = null;
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

    function screenPoint(view, width, height) {
      const point = view.clone().applyMatrix4(camera.projectionMatrix);
      return { x: (point.x + 1) * width / 2, y: (1 - point.y) * height / 2 };
    }

    function overlaps(a, b) {
      return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    }

    function placeBodyLabel(label, center, width, height, occupied) {
      const { x, y, diameterPx, silhouette } = center;
      const subpixel = diameterPx < 1;
      label.toggleAttribute("data-subpixel", subpixel);
      label.removeAttribute("data-marker-only");
      if (subpixel) label.setAttribute("aria-description", "Diâmetro aparente inferior a um pixel.");
      else label.removeAttribute("aria-description");
      label.hidden = x < 0 || x > width || y < 0 || y > height;
      if (label.hidden) return;
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
      if (length - gap < 9) return;
      const ux = dx / length;
      const uy = dy / length;
      // Separate parallel gravity arrows in projection while preserving their bearing.
      const offset = vector.offset ?? 0;
      const ox = Math.abs(uy) * offset;
      const oy = -ux * (Math.sign(uy) || 1) * offset;
      tip.x += ox;
      tip.y += oy;
      const head = Math.min(12, (length - gap) * 0.64);
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
    function fitFocusVector(delta, depth, width, height) {
      // Keep the focused arrowhead on screen by limiting its 3D length at the frustum.
      const tipOffset = delta.clone().applyMatrix3(viewRotation);
      const pixelsPerSlope = height * camera.projectionMatrix.elements[5] / 2;
      const horizontal = (width / 2 - 18) / pixelsPerSlope;
      const vertical = (height / 2 - 18) / pixelsPerSlope;
      if (horizontal <= 0 || vertical <= 0) return 1;
      return depth / Math.max(depth,
        tipOffset.z + Math.abs(tipOffset.x) / horizontal,
        tipOffset.z + Math.abs(tipOffset.y) / vertical);
    }

    function drawVectors(centers, width, height, occupied) {
      ink.clearRect(0, 0, width, height);
      viewRotation.setFromMatrix4(camera.matrixWorldInverse);
      const frameDistance = trackedBody ? camera.position.distanceTo(controls.target) : freeReference;
      const focusFactor = Math.min(1, camera.aspect);
      const speed = (key) => toWorld(velocities[key]).length();
      const referenceSpeed = velocities && (
        (trackedBody && speed(trackedBody)) || Math.max(...Object.keys(velocities).map(speed))
      );
      let velocityScale = referenceSpeed && frameDistance * (trackedBody ? 0.43 * focusFactor : 0.15) / referenceSpeed;
      if (trackedBody && velocityScale) {
        const focusedDelta = toWorld(velocities[trackedBody]).multiplyScalar(velocityScale);
        velocityScale *= fitFocusVector(focusedDelta, frameDistance, width, height);
      }
      onVelocityScale(showVelocityArrows && velocityScale ? velocityScale : null);
      const annotations = [];
      for (const [key, center] of Object.entries(centers)) {
        const name = bodies[key].label;
        if (accelerations && gravity?.visible) {
          const source = key === trackedBody ? gravitySource : "total";
          const { total, contributions } = accelerations[key];
          const delta = toWorld(contributions[source] ?? total)
            .setLength(frameDistance * (trackedBody ? 0.47 * focusFactor : 0.12));
          if (key === trackedBody) delta.multiplyScalar(fitFocusVector(delta, frameDistance, width, height));
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

    function draw() {
      const { clientWidth: width, clientHeight: height } = stage;
      if (!contextAvailable || !width || !height) return;
      const near = Math.min(0.02, Math.max(1e-9, nearestSurface() / 4));
      const far = Math.max(30, camera.position.length() + 5);
      if (camera.near !== near || camera.far !== far) {
        camera.near = near;
        camera.far = far;
        camera.updateProjectionMatrix();
      }
      renderer.render(scene, camera);
      const apparentSizes = {};
      const centers = {};
      const pixelsPerSlope = height * camera.projectionMatrix.elements[5] / 2;
      for (const [key, mesh] of Object.entries(meshes)) {
        if (!mesh.visible) continue;
        const view = mesh.position.clone().applyMatrix4(camera.matrixWorldInverse);
        const radius = mesh.scale.x;
        const depth = -view.z;
        const diameterPx = physics.apparentDiameterPx(radius, depth, view.y, pixelsPerSlope);
        apparentSizes[key] = diameterPx;
        if (diameterPx === null || depth > far) {
          labels[key].hidden = true;
          continue;
        }
        const { x, y } = screenPoint(view, width, height);
        const shift = pixelsPerSlope * radius ** 2 / (depth * (depth ** 2 - radius ** 2));
        const cx = x + shift * view.x;
        const cy = y - shift * view.y;
        const halfWidth = Math.max(7, physics.apparentDiameterPx(radius, depth, view.x, pixelsPerSlope) / 2);
        const halfHeight = Math.max(7, diameterPx / 2);
        centers[key] = { x, y, view, diameterPx, silhouette: {
          left: cx - halfWidth, top: cy - halfHeight, right: cx + halfWidth, bottom: cy + halfHeight,
        } };
      }
      const occupied = Object.values(centers).map(({ silhouette }) => silhouette);
      for (const [key, center] of Object.entries(centers)) {
        placeBodyLabel(labels[key], center, width, height, occupied);
      }
      const bounds = overlay.getBoundingClientRect();
      for (const [key, tip] of axes) {
        const label = labels[key];
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
      drawVectors(centers, width, height, occupied);
      onApparentSizes(apparentSizes);
    }

    function textureUnavailable(key) {
      missingTextures.add(bodies[key].label);
      onMissingTextures([...missingTextures]);
    }

    for (const [key, body] of Object.entries(bodies)) {
      const material = key === "sun"
        ? new THREE.MeshBasicMaterial({ color: 0xffb460 })
        : new THREE.MeshStandardMaterial({ color: body.color, ...PLANET_SURFACES[key] });
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

      const source = window.gpsSolarTextures?.[key];
      if (source) {
        textures.load(source, (texture) => {
          texture.colorSpace = THREE.SRGBColorSpace;
          material.map = texture;
          material.color.set(0xffffff);
          material.needsUpdate = true;
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
      paths[key] = path;
      scene.add(path);
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
          radiiAu: { value: keys.map((key) => bodies[key].equatorialKm / physics.AU_KM) },
          logLimits: { value: new THREE.Vector2(Math.log(300), Math.log(200_000)) },
          farColor: { value: new THREE.Color("#3f8caa") },
          middleColor: { value: new THREE.Color("#9a78d2") },
          nearColor: { value: new THREE.Color("#eface2") },
          fillOpacity: { value: 0.28 },
        },
        vertexShader: `
          varying vec3 offsetAu;
          void main() {
            offsetAu = mat3(modelMatrix) * position;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: `
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
            gl_FragColor = vec4(color, opacity);
            #include <colorspace_fragment>
          }`,
      });
      const surface = new THREE.Mesh(new THREE.PlaneGeometry(4.4, 4.4), material);
      surface.name = "newtonian-potential";
      surface.rotation.x = -Math.PI / 2;
      surface.visible = false;
      scene.add(surface);
      return surface;
    }

    function updateGravitySurface() {
      const sun = meshes.sun.position;
      gravity.position.copy(sun);
      if (trackedBody) gravity.position.y = meshes[trackedBody].position.y;
      const offsets = gravity.material.uniforms.sourceOffsets.value;
      for (const [i, mesh] of Object.values(meshes).entries()) offsets[i].copy(mesh.position).sub(gravity.position);
      gravity.material.uniforms.fillOpacity.value = trackedBody ? 0.12 : 0.28;
    }

    function resize() {
      const { clientWidth: width, clientHeight: height } = stage;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      const ratio = renderer.getPixelRatio();
      overlay.width = Math.round(width * ratio);
      overlay.height = Math.round(height * ratio);
      ink.setTransform(overlay.width / width, 0, 0, overlay.height / height, 0, 0);
      draw();
    }

    function updateCamera() {
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
      updateCamera();
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

    function zoom(logStep) {
      const factor = Math.exp(Math.max(-0.75, Math.min(0.75, logStep)));
      if (!trackedBody) {
        const step = freeMotionScale() * (1 - factor);
        const forward = controls.target.clone().sub(camera.position).normalize();
        const moved = moveFree(forward.multiplyScalar(step));
        freeReference = Math.max(1e-9, Math.min(14, freeReference - Math.sign(step) * moved));
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
      trackedBody = key;
      controls.enabled = key !== null;
      for (const id of Object.keys(meshes)) labels[id].setAttribute("aria-pressed", String(id === key));
      if (gravity?.visible && meshes.sun.visible) updateGravitySurface();
      onTarget(key);
    }

    function focus(key) {
      center(key);
      if (!meshes[key].visible) return;
      const distance = targetRadius() * 5 * Math.max(1, 1 / camera.aspect);
      const offset = camera.position.clone().sub(controls.target).setLength(distance);
      controls.target.copy(meshes[key].position);
      setMinimumDistance();
      changeOffset(offset);
    }

    function setScale(mode) {
      const previousRadius = targetRadius();
      const offset = camera.position.clone().sub(controls.target);
      const distance = offset.length();
      for (const [key, mesh] of Object.entries(meshes)) {
        const { equatorialKm, polarKm, visualRadius } = bodies[key];
        const radius = mode === "real" ? equatorialKm / physics.AU_KM : visualRadius;
        mesh.scale.set(radius, radius * polarKm / equatorialKm, radius);
      }
      setMinimumDistance();
      // Preserve the close-up framing and angle across scale changes.
      if (trackedBody && meshes[trackedBody].visible && distance <= previousRadius * 20) {
        offset.setLength(distance * targetRadius() / previousRadius);
      }
      if (!trackedBody) keepFreeCameraOutside();
      changeOffset(offset);
    }

    const raycaster = new THREE.Raycaster();
    const cursor = new THREE.Vector2();
    function pickBody(x, y) {
      const rect = canvas.getBoundingClientRect();
      cursor.set(2 * (x - rect.left) / rect.width - 1, 1 - 2 * (y - rect.top) / rect.height);
      raycaster.setFromCamera(cursor, camera);
      const visible = Object.values(meshes).filter((mesh) => mesh.visible);
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
        if (lastPair.span !== pair.span) zoom(Math.log(lastPair.span / pair.span));
        if (!trackedBody && (lastPair.x !== pair.x || lastPair.y !== pair.y)) {
          panFree(pair.x - lastPair.x, pair.y - lastPair.y);
        }
      }
      lastPair = pair;
    }

    canvas.addEventListener("pointerdown", (event) => {
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
      if (!trackedBody && (event.button === 0 || event.button === 2)) {
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
      if (!trackedBody && freeDrag?.id === id) {
        const dx = x - freeDrag.x;
        const dy = y - freeDrag.y;
        freeDrag.x = x;
        freeDrag.y = y;
        if (clickStart) return;
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
      zoom(event.deltaY * unitSize * WHEEL_SENSITIVITY);
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
    setScale("visual");
    resize();

    return {
      resize,
      zoom,
      setScale,
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
      showPositions(positions, frameVelocities, frameAccelerations) {
        const pendingFocus = trackedBody && !meshes[trackedBody].visible;
        for (const [key, mesh] of Object.entries(meshes)) {
          mesh.position.copy(toWorld(positions[key]));
          mesh.visible = true;
        }
        velocities = frameVelocities;
        accelerations = frameAccelerations;
        if (gravity?.visible) updateGravitySurface();
        sunlight.position.copy(meshes.sun.position);
        if (curvature) curvature.position.copy(meshes.sun.position);
        if (pendingFocus) {
          focus(trackedBody);
          return;
        }
        if (trackedBody) {
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
        for (const [id, path] of Object.entries(paths)) path.material.opacity = id === key ? 0.62 : 0.38;
        draw();
      },
      focus,
      free() {
        if (!trackedBody) return;
        freeReference = Math.max(1e-9, camera.position.distanceTo(controls.target) - targetRadius());
        center(null);
        setMinimumDistance();
        updateCamera();
      },
      reset() {
        center(null);
        freeReference = overview.length();
        controls.target.set(0, 0, 0);
        setMinimumDistance();
        changeOffset(overview);
      },
    };
  };
})();
