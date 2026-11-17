(() => {
  "use strict";

  const AU_KM = 149_597_870.7;
  const RADIANS = Math.PI / 180;
  const WHEEL_SENSITIVITY = 0.0025;
  const MIN_CLEARANCE_RADII = 0.06;
  const PLANET_SURFACES = {
    earth: { roughness: 0.78, emissive: 0x193766, emissiveIntensity: 0.12 },
    mars: { roughness: 1, emissive: 0x6a2715, emissiveIntensity: 0.1 },
  };

  window.createSolarScene = (stage, bodies, { onSelect, onTarget, onMissingTextures }) => {
    const THREE = window.SkyThree;
    const canvas = stage.querySelector("canvas");
    const renderError = stage.querySelector("#gps-render-error");
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.02, 30);
    const overview = new THREE.Vector3(2.65, 2.65, 4.7);
    camera.position.copy(overview);

    const controls = new THREE.OrbitControls(camera, canvas);
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
    scene.add(new THREE.PointLight(0xffe7cc, 2.5, 0, 0));
    const labels = Object.fromEntries(Array.from(stage.querySelectorAll("[data-scene-label]"),
      (element) => [element.dataset.sceneLabel, element]));
    const meshes = {};
    const paths = {};
    const textures = new THREE.TextureLoader();
    const missingTextures = new Set();
    let trackedBody = null;
    let contextAvailable = true;

    const cameraUp = new THREE.Vector3();
    function placeLabel(label, vector) {
      const point = vector.clone().project(camera);
      label.hidden = point.z < -1 || point.z > 1 || Math.abs(point.x) > 1 || Math.abs(point.y) > 1;
      if (!label.hidden) {
        label.style.left = `${(point.x + 1) * 50}%`;
        label.style.top = `${(1 - point.y) * 50}%`;
      }
    }

    function targetRadius() {
      return meshes[trackedBody ?? "sun"].scale.x;
    }

    function draw() {
      if (!contextAvailable || !stage.clientWidth || !stage.clientHeight) return;
      const clearance = camera.position.distanceTo(controls.target) - targetRadius();
      const near = Math.min(0.02, Math.max(1e-9, clearance / 4));
      if (camera.near !== near) {
        camera.near = near;
        camera.updateProjectionMatrix();
      }
      renderer.render(scene, camera);
      cameraUp.setFromMatrixColumn(camera.matrixWorld, 1);
      for (const [key, tip] of axes) placeLabel(labels[key], tip);
      for (const [key, mesh] of Object.entries(meshes)) {
        if (mesh.visible) {
          placeLabel(labels[key], mesh.position.clone().addScaledVector(cameraUp, mesh.scale.x));
        }
      }
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

      if (key === "sun") continue;
      const path = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({
        color: body.color, transparent: true, opacity: 0.5,
      }));
      path.name = `orbit-${key}`;
      path.visible = false;
      paths[key] = path;
      scene.add(path);
    }

    function resize() {
      const { clientWidth: width, clientHeight: height } = stage;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      draw();
    }

    function changeOffset(offset) {
      camera.position.copy(controls.target).add(offset);
      if (!controls.update()) draw();
    }

    function zoom(logStep) {
      const offset = camera.position.clone().sub(controls.target);
      const radius = targetRadius();
      const factor = Math.exp(Math.max(-0.75, Math.min(0.75, logStep)));
      // Scale the altitude, retaining a small gap outside the bounding sphere.
      const next = radius + (offset.length() - radius) * factor;
      const distance = Math.max(controls.minDistance, Math.min(controls.maxDistance, next));
      changeOffset(offset.setLength(distance));
    }

    function setMinimumDistance() {
      controls.minDistance = targetRadius() * (1 + MIN_CLEARANCE_RADII);
    }

    function center(key) {
      trackedBody = key;
      for (const id of Object.keys(meshes)) labels[id].setAttribute("aria-pressed", String(id === key));
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

    function setScale(mode, selectedBody) {
      const previousRadius = targetRadius();
      const offset = camera.position.clone().sub(controls.target);
      const distance = offset.length();
      for (const [key, mesh] of Object.entries(meshes)) {
        const { equatorialKm, polarKm, visualRadius } = bodies[key];
        const radius = mode === "real" ? equatorialKm / AU_KM : visualRadius;
        mesh.scale.set(radius, radius * polarKm / equatorialKm, radius);
      }
      setMinimumDistance();
      // Preserve the close-up framing and angle across scale changes.
      if (trackedBody && meshes[trackedBody].visible && distance <= previousRadius * 20) {
        offset.setLength(distance * targetRadius() / previousRadius);
      } else if (mode === "real") {
        // At system scale the real planets are smaller than a screen pixel.
        focus(trackedBody ?? selectedBody);
        return;
      }
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
    function pinchSpan() {
      if (touches.size !== 2) return 0;
      const [first, second] = touches.values();
      return Math.hypot(first.x - second.x, first.y - second.y);
    }

    canvas.addEventListener("pointerdown", (event) => {
      const { pointerId: id, clientX: x, clientY: y } = event;
      if (event.pointerType === "touch") {
        touches.set(id, { x, y });
        canvas.setPointerCapture(id);
      }
      if (touches.size > 1) {
        clickStart = null;
        controls.enableRotate = false;
      } else if (event.button === 0) {
        clickStart = { id, x, y };
      }
    });
    canvas.addEventListener("pointermove", (event) => {
      const { pointerId: id, clientX: x, clientY: y } = event;
      if (clickStart?.id === id && Math.hypot(x - clickStart.x, y - clickStart.y) > 6) clickStart = null;
      if (!touches.has(id)) return;
      const previousSpan = pinchSpan();
      touches.set(id, { x, y });
      const span = pinchSpan();
      if (previousSpan && span) zoom(Math.log(previousSpan / span));
    });
    function dropPointer(event) {
      touches.delete(event.pointerId);
      if (touches.size < 2) controls.enableRotate = true;
      if (clickStart?.id === event.pointerId) clickStart = null;
    }
    function finishPointer(event) {
      const wasClick = clickStart?.id === event.pointerId;
      dropPointer(event);
      if (wasClick) pickBody(event.clientX, event.clientY);
    }
    canvas.addEventListener("pointerup", finishPointer);
    canvas.addEventListener("pointercancel", dropPointer);
    canvas.addEventListener("lostpointercapture", dropPointer);
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
      const turn = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
      if (!turn) return;
      event.preventDefault();
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
      loadTrajectory(samples) {
        for (const [key, path] of Object.entries(paths)) {
          path.geometry.dispose();
          path.geometry = new THREE.BufferGeometry().setFromPoints(samples.map((sample) => toWorld(sample[key])));
          path.visible = true;
        }
      },
      showPositions(positions) {
        const pendingFocus = trackedBody && !meshes[trackedBody].visible;
        for (const [key, mesh] of Object.entries(meshes)) {
          mesh.position.copy(toWorld(positions[key]));
          mesh.visible = true;
        }
        if (pendingFocus) {
          focus(trackedBody);
          return;
        }
        if (trackedBody) {
          const target = meshes[trackedBody].position;
          camera.position.sub(controls.target).add(target);
          controls.target.copy(target);
          if (controls.update()) return;
        }
        draw();
      },
      select(key) {
        for (const id of Object.keys(meshes)) labels[id].classList.toggle("selected", id === key);
        for (const [id, path] of Object.entries(paths)) path.material.opacity = id === key ? 0.88 : 0.48;
        draw();
      },
      focus,
      reset() {
        center(null);
        controls.target.set(0, 0, 0);
        setMinimumDistance();
        changeOffset(overview);
      },
    };
  };
})();
