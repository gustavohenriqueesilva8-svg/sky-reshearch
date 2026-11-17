(() => {
  "use strict";

  const assetRoot = new URL("./solar/", document.currentScript.src);
  const AU_KM = 149_597_870.7;
  const RADIANS = Math.PI / 180;

  window.createSolarScene = (stage, bodies) => {
    const THREE = window.SkyThree;
    const canvas = stage.querySelector("canvas");
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.02, 30);
    const overview = new THREE.Vector3(2.65, 2.65, 4.7);
    camera.position.copy(overview);

    const controls = new THREE.OrbitControls(camera, canvas);
    controls.enablePan = false;
    controls.maxDistance = 14;
    controls.update();

    // Rotate the astronomical frame by -90° around X to use Y as scene up.
    // One astronomical unit is one scene unit for every center and trajectory.
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
    let trackedBody = null;
    let scaleMode = "visual";

    const cameraUp = new THREE.Vector3();
    function placeLabel(label, vector) {
      const point = vector.clone().project(camera);
      label.hidden = point.z < -1 || point.z > 1 || Math.abs(point.x) > 1 || Math.abs(point.y) > 1;
      if (!label.hidden) {
        label.style.left = `${(point.x + 1) * 50}%`;
        label.style.top = `${(1 - point.y) * 50}%`;
      }
    }

    function draw() {
      if (!stage.clientWidth || !stage.clientHeight) return;
      const near = Math.min(0.02, camera.position.distanceTo(controls.target) / 40);
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

    for (const [key, body] of Object.entries(bodies)) {
      const material = key === "sun"
        ? new THREE.MeshBasicMaterial({ color: body.color })
        : new THREE.MeshStandardMaterial({ color: body.color, roughness: 1 });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 40), material);
      const [ra, dec] = body.pole.map((angle) => angle * RADIANS);
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), toWorld({
        x: Math.cos(dec) * Math.cos(ra),
        y: Math.cos(dec) * Math.sin(ra),
        z: Math.sin(dec),
      }));
      mesh.name = `astro-${key}`;
      mesh.visible = false;
      meshes[key] = mesh;
      scene.add(mesh);
      if (location.protocol !== "file:") {
        textures.load(new URL(`${key}.jpg`, assetRoot).href, (texture) => {
          texture.colorSpace = THREE.SRGBColorSpace;
          material.map = texture;
          material.color.set(0xffffff);
          material.needsUpdate = true;
          draw();
        });
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
      controls.update();
      draw();
    }

    function zoom(factor) {
      changeOffset(camera.position.clone().sub(controls.target).multiplyScalar(factor));
    }

    function setMinimumDistance() {
      controls.minDistance = meshes[trackedBody ?? "sun"].scale.x * 1.5;
    }

    function focus(key) {
      if (!meshes[key].visible) return;
      trackedBody = key;
      const distance = scaleMode === "real" ? meshes[key].scale.x * 6 : 1.52;
      const offset = camera.position.clone().sub(controls.target).setLength(distance);
      controls.target.copy(meshes[key].position);
      setMinimumDistance();
      changeOffset(offset);
    }

    function setScale(mode) {
      scaleMode = mode;
      for (const [key, mesh] of Object.entries(meshes)) {
        const { equatorialKm, polarKm, visualRadius } = bodies[key];
        const radius = mode === "real" ? equatorialKm / AU_KM : visualRadius;
        mesh.scale.set(radius, radius * polarKm / equatorialKm, radius);
      }
      if (trackedBody) {
        focus(trackedBody);
      } else {
        setMinimumDistance();
        controls.update();
        draw();
      }
    }

    controls.addEventListener("change", draw);
    new ResizeObserver(resize).observe(stage);
    canvas.addEventListener("keydown", (event) => {
      if (event.key === "+" || event.key === "=" || event.key === "-") {
        event.preventDefault();
        zoom(event.key === "-" ? 1.25 : 0.8);
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
        for (const [key, mesh] of Object.entries(meshes)) {
          mesh.position.copy(toWorld(positions[key]));
          mesh.visible = true;
        }
        if (trackedBody) {
          const target = meshes[trackedBody].position;
          camera.position.sub(controls.target).add(target);
          controls.target.copy(target);
          controls.update();
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
        trackedBody = null;
        controls.target.set(0, 0, 0);
        setMinimumDistance();
        changeOffset(overview);
      },
    };
  };
})();
