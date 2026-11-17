(() => {
  "use strict";

  const physics = window.gpsPhysics;
  const BODIES = {
    sun: { label: "Sol", color: "#ffd48b", radiusKm: physics.RADII_KM.sun, visualRadius: 0.15, pole: [286.13, 63.87] },
    earth: { label: "Terra", color: "#7ac8f6", radiusKm: physics.RADII_KM.earth, visualRadius: 0.11, pole: [0, 90] },
    mars: { label: "Marte", color: "#f59879", radiusKm: physics.RADII_KM.mars, visualRadius: 0.07, pole: [317.27, 54.43] },
  };
  const BODY_LOCATION = { sun: "no Sol", earth: "na Terra", mars: "em Marte" };
  const AXES = ["x", "y", "z"];
  const UNAVAILABLE = "Data fora da cobertura. Use um instante UTC entre 2000 e 2049.";
  const INVALID_INTERVAL = "O fim do recorte deve ser posterior ao início.";

  const formatNumber = new Intl.NumberFormat("pt-BR", {
    maximumFractionDigits: 4, minimumFractionDigits: 4,
  });
  const formatDiameter = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
  const formatWhole = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
  const formatRatio = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const formatSpeed = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3, minimumFractionDigits: 3 });
  const formatScale = new Intl.NumberFormat("pt-BR", { maximumSignificantDigits: 3 });
  const formatAcceleration = new Intl.NumberFormat("pt-BR", {
    notation: "scientific", maximumSignificantDigits: 4,
  });
  const formatEpoch = (instant) => `${instant.slice(0, 19).replace("T", " ")} UTC`;
  const inputInstant = (value) => `${value.length === 16 ? value + ":00" : value}Z`;

  function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  }

  function magnitude({ x, y, z }) {
    return Math.hypot(x, y, z);
  }

  function showInstant(element, instant) {
    element.dateTime = instant;
    element.textContent = formatEpoch(instant);
  }

  function utcMilliseconds(instant) {
    const seconds = Date.parse(`${instant.slice(0, 19)}Z`);
    const fraction = instant[19] === "." ? Number(`0${instant.slice(19, -1)}`) : 0;
    return seconds + 1000 * fraction;
  }

  window.createSolarSystemView = (root, requestApi) => {
    const find = (selector) => root.querySelector(selector);
    const stage = find("#gps-stage");
    const form = find("#gps-form");
    const start = find("#gps-instant");
    const end = find("#gps-end");
    const status = find("#gps-status");
    const readout = find("#gps-readout");
    const epoch = find("#gps-epoch");
    const liveState = find("#gps-live-state");
    const canvas = stage.querySelector("canvas");
    const slider = find("#gps-timeline");
    const play = find("#gps-play");
    const focus = find("#gps-focus");
    const free = find("#gps-free");
    const playbackRate = find("#gps-playback-rate");
    const referenceSelect = find("#gps-reference");
    const compare = find("#gps-compare-3d");
    const outsideEarth = find("#gps-outside-earth");
    const pairSelect = find("#gps-measure-pair");
    const measureValue = find("#gps-measure-value");
    const measureAu = find("#gps-measure-au");
    const measureKm = find("#gps-measure-km");
    const ruler = find("#gps-view-scale");
    const rulerPlane = find("#gps-view-scale-plane");
    const rulerValue = find("#gps-view-scale-value");
    const rulerBar = find("#gps-view-scale-bar");
    const cameraRange = find("#gps-view-range");
    const speedLabels = Object.fromEntries(Object.keys(BODIES).map((body) => [body, find(`#gps-speed-${body}`)]));
    const speedBars = Object.fromEntries(Object.keys(BODIES).map((body) => [body, find(`#gps-speed-bar-${body}`)]));
    const speedAxis = find("#gps-speed-axis");
    const speedMax = find("#gps-speed-max");
    const velocityLegend = find("#gps-velocity-legend");
    const velocityScale = find("#gps-velocity-scale");
    const gravityToggle = find("#gps-gravity");
    const gravityReadout = find("#gps-gravity-readout");
    const gravityFocus = find("#gps-gravity-focus");
    const gravitySelect = find("#gps-gravity-source");
    const accelerationList = find("#gps-accelerations");
    const apparentLabel = find("#gps-apparent");
    const bodyButtons = root.querySelectorAll("[data-gps-body]");
    const clockButtons = root.querySelectorAll("[data-gps-clock]");
    const scaleButtons = root.querySelectorAll("[data-gps-scale]");

    const solarRadius = BODIES.sun.radiusKm;
    find("#gps-diameter-ratio").textContent = `${formatRatio.format(solarRadius / BODIES.earth.radiusKm)} vezes`;
    for (const [key, { radiusKm }] of Object.entries(BODIES)) {
      find(`[data-diameter-disk="${key}"]`).style.setProperty("--diameter-ratio", radiusKm / solarRadius);
      find(`[data-diameter-value="${key}"]`).textContent = `${formatDiameter.format(2 * radiusKm)} km`;
    }

    let scene = null;
    let initialized = false;
    let active = false;
    let cutWindow = null;
    let resumeOnActivate = true;
    let range = null;
    let orbitExtents = {};
    let orbitSamples = null;
    let positions = null;
    let velocities = null;
    let framePositions = null;
    let accelerations = null;
    let gravityReadoutBody = null;
    let apparentSizes = {};
    let selected = "mars";
    let reference = "sun";
    let mode = "simulation";
    let cameraLabel = "Navegação livre";
    let activeRequest = null;
    let playTimer = null;

    function setStatus(message, state = "") {
      if (status.textContent !== message) status.textContent = message;
      status.dataset.state = state;
    }

    function updateReadout() {
      const body = BODIES[selected];
      find("#gps-body-name").textContent = body.label;
      focus.disabled = !scene || !positions;
      outsideEarth.disabled = focus.disabled;
      if (!positions) return;
      const position = framePositions[selected];
      for (const axis of AXES) find(`#gps-coordinate-${axis}`).textContent = formatNumber.format(position[axis]);
      find("#gps-body-diameter").textContent = `${formatDiameter.format(2 * body.radiusKm)} km`;
      find("#gps-distance-sun").textContent = `${formatNumber.format(distance(positions[selected], positions.sun))} ua`;
      find("#gps-distance-earth").textContent = `${formatNumber.format(distance(positions[selected], positions.earth))} ua`;
      const extent = orbitExtents[selected];
      find("#gps-orbit-extent").hidden = !extent;
      if (extent) {
        find("#gps-orbit-radii").textContent =
          `${formatNumber.format(extent.min)}–${formatNumber.format(extent.max)} ua`;
      }
      updateGravityReadout();
      readout.hidden = false;
    }

    function updateGravityReadout() {
      const acceleration = accelerations?.[selected];
      gravityReadout.hidden = !acceleration;
      if (!acceleration) return;
      const readings = { total: acceleration.total, ...acceleration.contributions };
      if (gravityReadoutBody !== selected) {
        gravityReadoutBody = selected;
        const rows = [];
        const options = [];
        for (const source of Object.keys(readings)) {
          const label = source === "total" ? "Resultante" : BODIES[source].label;
          const row = document.createElement("div");
          const name = document.createElement("dt");
          name.textContent = label;
          const value = document.createElement("dd");
          value.dataset.gravityReading = source;
          row.append(name, value);
          rows.push(row);
          options.push(new Option(label, source));
        }
        accelerationList.replaceChildren(...rows);
        gravitySelect.replaceChildren(...options);
      }
      for (const value of accelerationList.querySelectorAll("dd")) {
        value.textContent = `${formatAcceleration.format(magnitude(readings[value.dataset.gravityReading]))} m/s²`;
      }
    }

    function showSpeeds(frameVelocities) {
      const speeds = Object.fromEntries(Object.keys(BODIES).map((body) => [
        body, frameVelocities ? magnitude(frameVelocities[body]) : null,
      ]));
      const maximum = Math.max(10, Math.ceil(Math.max(...Object.values(speeds)) / 10) * 10);
      speedAxis.hidden = !frameVelocities;
      speedMax.textContent = `${maximum} km/s`;
      for (const [body, speed] of Object.entries(speeds)) {
        speedLabels[body].textContent = speed === null ? "—" : `${formatSpeed.format(speed)} km/s`;
        speedBars[body].style.width = `${100 * (speed ?? 0) / maximum}%`;
      }
    }

    function updateApparentSize() {
      const pixels = apparentSizes[selected];
      const text = pixels == null ? "—" :
        `${pixels < 1 ? formatScale.format(pixels) : formatDiameter.format(pixels)} px`;
      if (apparentLabel.textContent !== text) apparentLabel.textContent = text;
    }

    function updateMeasurement() {
      const [first, second] = pairSelect.value.split("-");
      measureValue.hidden = !positions || !second;
      if (measureValue.hidden) return;
      const distanceAu = distance(positions[first], positions[second]);
      measureAu.textContent = `${formatNumber.format(distanceAu)} ua`;
      measureKm.textContent = `${formatWhole.format(distanceAu * physics.AU_KM)} km`;
    }

    function showViewScale(scale) {
      ruler.hidden = !scale;
      if (!scale) return;
      const plane = scale.rangeKm === null ? "Régua comum" : `Régua ${BODY_LOCATION[scale.key]}`;
      const length = `${formatScale.format(scale.length)} ${scale.unit}`;
      if (rulerPlane.textContent !== plane) rulerPlane.textContent = plane;
      if (rulerValue.textContent !== length) rulerValue.textContent = length;
      rulerBar.style.width = `${scale.pixels.toFixed(2)}px`;
      cameraRange.hidden = scale.rangeKm === null;
      if (cameraRange.hidden) return;
      const value = scale.rangeKm >= physics.AU_KM / 10
        ? `${formatScale.format(scale.rangeKm / physics.AU_KM)} ua`
        : `${formatWhole.format(scale.rangeKm)} km`;
      const label = `Câmera–centro · ${value}`;
      if (cameraRange.textContent !== label) cameraRange.textContent = label;
    }

    function selectBody(key, center = true) {
      if (key !== selected) {
        gravitySelect.value = "total";
        scene?.setGravitySource("total");
      }
      selected = key;
      for (const button of bodyButtons) button.setAttribute("aria-pressed", String(button.dataset.gpsBody === key));
      scene?.select(key);
      if (center) scene?.focus(key);
      updateApparentSize();
      updateReadout();
    }

    function showFrame() {
      if (!positions) return;
      framePositions = physics.relativeVectors(positions, reference);
      const frameVelocities = velocities && physics.relativeVectors(velocities, reference);
      accelerations = gravityToggle.checked ? physics.gravitationalAccelerations(positions) : null;
      showSpeeds(frameVelocities);
      scene?.showPositions(framePositions, frameVelocities, accelerations, reference, trailSamples());
      updateMeasurement();
      updateReadout();
    }

    function showPositions(instant, vectors, velocityVectors) {
      positions = vectors;
      velocities = velocityVectors;
      showInstant(epoch, instant);
      showFrame();
    }

    function upperSample(time) {
      let first = 0;
      let last = range.times.length - 1;
      while (first < last) {
        const middle = Math.floor((first + last) / 2);
        if (range.times[middle] < time) first = middle + 1;
        else last = middle;
      }
      return first;
    }

    function stateAt(time, upper = upperSample(time)) {
      return physics.interpolateEphemeris(range.data.trajectory, range.times, time, upper);
    }

    function trailSamples() {
      if (!range) return [];
      const startTime = Math.max(range.times[0], range.time - physics.TRAIL_MS);
      if (range.time <= startTime) return [];
      return Array.from({ length: physics.TRAIL_POINTS }, (_, index) => {
        const time = startTime + (range.time - startTime) * index / (physics.TRAIL_POINTS - 1);
        return physics.relativeVectors(stateAt(time).positions, reference);
      });
    }

    function showTime(instant) {
      const time = Math.max(range.times[0], Math.min(instant, range.times.at(-1)));
      range.time = time;
      const upper = upperSample(time);
      const state = stateAt(time, upper);
      const timestamp = range.times[upper] === time ? range.data.trajectory[upper].instant_utc : new Date(time).toISOString();
      slider.value = range.times[upper] === time ? upper : Math.max(0, upper - 1);
      const label = formatEpoch(timestamp);
      if (slider.getAttribute("aria-valuetext") !== label) slider.setAttribute("aria-valuetext", label);
      showPositions(timestamp, state.positions, state.velocities);
    }

    function loadOrbits(samples) {
      orbitSamples = samples;
      orbitExtents = {};
      for (const body of ["earth", "mars"]) {
        let min = Infinity;
        let max = 0;
        for (const sample of samples) {
          const { x, y, z } = sample[body];
          const radius = Math.hypot(x, y, z);
          min = Math.min(min, radius);
          max = Math.max(max, radius);
        }
        orbitExtents[body] = { min, max };
      }
      scene?.loadTrajectory(samples, reference);
    }

    function setReference(next) {
      if (positions) scene?.shiftReference(physics.subtract(positions[reference], positions[next]));
      reference = next;
      find("#gps-frame-origin").textContent = BODY_LOCATION[reference];
      find("#gps-readout-origin").textContent = BODIES[reference].label;
      for (const [body, label] of Object.entries(BODIES)) {
        const track = find(`#gps-${body}-track`);
        track.hidden = body === reference;
        const name = body === "sun" ? "do Sol" : body === "earth" ? "da Terra" : `de ${label.label}`;
        track.textContent = reference === "sun" ? `Órbita ${name}` : `Trajetória ${name}`;
      }
      if (orbitSamples) scene?.loadTrajectory(orbitSamples, reference);
      showFrame();
    }

    function showRange(data, isDemo, instant = utcMilliseconds(data.geometry.instant_utc)) {
      const samples = data.trajectory;
      range = { data, isDemo, times: samples.map((sample) => utcMilliseconds(sample.instant_utc)), time: instant };
      const first = samples[0].instant_utc;
      const last = samples.at(-1).instant_utc;
      if (mode === "range") {
        start.value = first.slice(0, 19);
        end.value = last.slice(0, 19);
      }
      showInstant(find("#gps-range-start"), first);
      showInstant(find("#gps-range-end"), last);
      find("#gps-source").textContent = isDemo ? "Demonstração local" : data.geometry.model;
      find(".gps-time").hidden = false;
      slider.max = samples.length - 1;
      slider.disabled = false;
      play.disabled = false;
      loadOrbits(samples);
      showTime(instant);
    }

    function updateMotionClock() {
      const clock = find("#gps-movement-clock");
      const rate = mode === "live" ? "1 s/s" : playbackRate.selectedOptions[0].textContent;
      clock.textContent = playTimer === null ? "Simulação pausada" : `Em movimento · ${rate}`;
      playbackRate.disabled = mode === "live";
    }

    function stopPlayback() {
      cancelAnimationFrame(playTimer);
      playTimer = null;
      play.textContent = "Reproduzir";
      updateMotionClock();
    }

    function startPlayback() {
      if (!range || playTimer !== null) return;
      const endTime = range.times.at(-1);
      if (mode === "live") {
        const now = Date.now();
        if (now < range.times[0] || now >= endTime) {
          loadWindow(now, true);
          return;
        }
        showTime(now);
      } else if (range.time >= endTime) {
        showTime(range.times[0]);
      }
      const startTime = range.time;
      const startFrame = performance.now();
      const speed = mode === "live" ? 1 : Number(playbackRate.value);
      let lastPaint = -Infinity;
      play.textContent = "Pausar";
      function advance(now) {
        const instant = startTime + (now - startFrame) * speed;
        // Keep the simulated clock tied to elapsed time even on slower renderers.
        if (now - lastPaint >= 28 || instant >= endTime) {
          showTime(instant);
          lastPaint = now;
        }
        if (instant < endTime) {
          playTimer = requestAnimationFrame(advance);
          return;
        }
        stopPlayback();
        if (mode !== "range" && !range.isDemo && endTime < Date.UTC(2049, 11, 31, 23, 59, 59)) {
          loadWindow(endTime, true);
        }
      }
      playTimer = requestAnimationFrame(advance);
      updateMotionClock();
    }

    function togglePlayback() {
      if (playTimer === null) startPlayback();
      else stopPlayback();
    }

    function cancelRequests() {
      activeRequest?.abort();
      activeRequest = null;
    }

    function beginRequest() {
      cancelRequests();
      const controller = new AbortController();
      activeRequest = controller;
      return controller;
    }

    async function loadWindow(instant, autoplay) {
      const controller = beginRequest();
      play.disabled = true;
      slider.disabled = true;
      liveState.textContent = "Carregando efemérides…";
      try {
        const result = await requestApi("/ephemerides/solar-system", {
          instant: new Date(instant).toISOString(), velocities: true,
        }, { signal: controller.signal, timeoutMs: 6500 });
        if (controller.signal.aborted) return;
        showRange(result, false);
        liveState.textContent = mode === "live" ? "Acompanhando o relógio UTC" : "Efemérides da simulação";
        setStatus("");
        if (autoplay) startPlayback();
      } catch (error) {
        if (controller.signal.aborted) return;
        if (!range) {
          showRange(window.solarDemo, true);
          liveState.textContent = "Demonstração local";
          if (autoplay) startPlayback();
        } else {
          liveState.textContent = "Último intervalo recebido";
          play.disabled = false;
          slider.disabled = false;
        }
        setStatus(error.status === 422 ? UNAVAILABLE : "Efemérides indisponíveis. Verifique o servidor Python.", "error");
      } finally {
        if (activeRequest === controller) activeRequest = null;
      }
    }

    function selectMode(next) {
      if (next === mode) return;
      if (mode === "range") cutWindow = range;
      stopPlayback();
      cancelRequests();
      mode = next;
      updateMotionClock();
      for (const button of clockButtons) button.setAttribute("aria-pressed", String(button.dataset.gpsClock === mode));
      find("#gps-cut-fields").hidden = mode !== "range";
      liveState.hidden = mode === "range";
      setStatus("");
      if (mode === "range") {
        const selectedWindow = cutWindow ?? range;
        if (selectedWindow) showRange(selectedWindow.data, selectedWindow.isDemo, selectedWindow.time);
        else showRange(window.solarDemo, true);
        if (range.isDemo) setStatus("A demonstração usa o recorte incluído. Para consultar outras datas, execute python app.py.");
      } else {
        loadWindow(Date.now(), true);
      }
    }

    async function applyRange() {
      stopPlayback();
      const instant = inputInstant(start.value);
      const finish = inputInstant(end.value);
      if (finish <= instant) {
        cancelRequests();
        setStatus(INVALID_INTERVAL, "error");
        return;
      }
      const controller = beginRequest();
      setStatus("Calculando o recorte…", "loading");
      try {
        const result = await requestApi("/ephemerides/solar-system", { instant, end: finish, velocities: true }, {
          signal: controller.signal,
          timeoutMs: 6500,
        });
        if (controller.signal.aborted) return;
        showRange(result, false);
        setStatus("Recorte aplicado.");
      } catch (error) {
        if (controller.signal.aborted) return;
        setStatus(error.status === 422 ? UNAVAILABLE : "Recorte indisponível. Verifique o servidor Python.", "error");
      } finally {
        if (activeRequest === controller) activeRequest = null;
      }
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (mode === "range") applyRange();
    });
    for (const field of [start, end]) field.addEventListener("invalid", () => setStatus(UNAVAILABLE, "error"));
    for (const button of clockButtons) button.addEventListener("click", () => selectMode(button.dataset.gpsClock));
    slider.addEventListener("input", () => {
      stopPlayback();
      showTime(range.times[Number(slider.value)]);
    });
    play.addEventListener("click", togglePlayback);
    playbackRate.addEventListener("change", () => {
      if (playTimer === null) return;
      stopPlayback();
      startPlayback();
    });
    referenceSelect.addEventListener("change", () => setReference(referenceSelect.value));
    pairSelect.addEventListener("change", () => {
      scene?.setMeasuredPair(pairSelect.value ? pairSelect.value.split("-") : []);
      updateMeasurement();
    });
    find("#gps-show-velocities").addEventListener("change", (event) => scene?.setVelocityVisibility(event.target.checked));
    gravityToggle.addEventListener("change", () => {
      find("#gps-gravity-legend").hidden = !gravityToggle.checked;
      scene?.setGravityVisibility(gravityToggle.checked);
      showFrame();
    });
    gravitySelect.addEventListener("change", () => scene?.setGravitySource(gravitySelect.value));
    find("#gps-curvature").addEventListener("change", (event) => {
      find("#gps-curvature-info").hidden = !event.target.checked;
      scene?.setCurvature(event.target.checked);
    });
    for (const button of bodyButtons) button.addEventListener("click", () => selectBody(button.dataset.gpsBody));
    function chooseScale(scale) {
      for (const option of scaleButtons) option.setAttribute("aria-pressed", String(option.dataset.gpsScale === scale));
      find("#gps-scale-note").textContent = scale === "real"
        ? "Diâmetros e distâncias na mesma escala. ◇ indica menos de 2 px. Selecione um astro para se aproximar."
        : "Diâmetros ampliados para leitura. Posições e distâncias em escala linear.";
      scene?.setScale(scale);
    }

    for (const button of scaleButtons) {
      button.addEventListener("click", () => {
        scene?.setComparison(false);
        chooseScale(button.dataset.gpsScale);
      });
    }
    compare.addEventListener("click", () => scene?.setComparison(compare.getAttribute("aria-pressed") !== "true"));
    outsideEarth.addEventListener("click", () => {
      chooseScale("real");
      selectBody("earth", false);
      scene?.outsideEarth();
    });
    focus.addEventListener("click", () => {
      scene?.focus(selected);
      canvas.focus();
    });
    find("#gps-edit-date").addEventListener("click", () => {
      selectMode("range");
      start.focus();
    });
    find("#gps-reset").addEventListener("click", () => scene?.reset());
    free.addEventListener("click", () => scene?.free());
    find("#gps-zoom-in").addEventListener("click", () => scene?.zoom(-0.22));
    find("#gps-zoom-out").addEventListener("click", () => scene?.zoom(0.22));
    find("#gps-explore").addEventListener("click", () => {
      if (scene) canvas.focus();
      else clockButtons[0].focus();
    });

    return {
      selectBody,
      deactivate() {
        active = false;
        resumeOnActivate = playTimer !== null || !range;
        scene?.stopApproach();
        stopPlayback();
        cancelRequests();
        if (status.dataset.state === "loading") setStatus("");
      },
      activate() {
        if (active) return;
        active = true;
        if (!initialized) {
          initialized = true;
          try {
            scene = window.createSolarScene(stage, BODIES, {
              onSelect: selectBody,
              onTarget: (key, approaching = false, preset = false) => {
                const target = find("#gps-camera-target");
                cameraLabel = preset ? "Fora da Terra → Sol" : approaching ? `Aproximação · ${BODIES[key].label}` :
                  key ? `Foco ${BODY_LOCATION[key]}` : "Navegação livre";
                target.textContent = cameraLabel;
                free.setAttribute("aria-pressed", String(key === null));
                gravityFocus.hidden = key === null;
                find("#gps-earth-view-note").hidden = !preset;
              },
              onComparison: (enabled) => {
                compare.setAttribute("aria-pressed", String(enabled));
                find("#gps-camera-target").textContent = enabled ? "Comparação em escala real" : cameraLabel;
                find("#gps-comparison-note").hidden = !enabled;
                find("#gps-earth-view-note").hidden = enabled || cameraLabel !== "Fora da Terra → Sol";
                find(".gps-measure").hidden = enabled;
                find("#gps-zoom-in").disabled = enabled;
                find("#gps-zoom-out").disabled = enabled;
              },
              onMissingTextures: (names) => {
                const notice = find("#gps-texture-status");
                notice.textContent = `Texturas indisponíveis para ${names.join(", ")}. Modelos exibidos com cores de referência.`;
                notice.hidden = false;
              },
              onApparentSizes: (sizes) => {
                apparentSizes = sizes;
                updateApparentSize();
              },
              onViewScale: showViewScale,
              onVelocityScale: (scale) => {
                velocityLegend.hidden = scale === null;
                if (scale !== null) {
                  const text = `${formatScale.format(10 * scale)} ua por 10 km/s`;
                  if (velocityScale.textContent !== text) velocityScale.textContent = text;
                }
              },
            });
            if (pairSelect.value) scene.setMeasuredPair(pairSelect.value.split("-"));
            selectBody(selected, false);
          } catch (error) {
            console.warn("Falha ao iniciar a cena 3D.", error);
            find("#gps-render-error").hidden = false;
            for (const button of root.querySelectorAll("[data-gps-camera], [data-gps-scale]")) button.disabled = true;
          }
          if (location.protocol === "file:") {
            selectMode("range");
            startPlayback();
            return;
          }
        }
        scene?.resize();
        if (range) {
          if (resumeOnActivate) startPlayback();
        } else {
          liveState.hidden = false;
          loadWindow(Date.now(), true);
        }
      },
    };
  };
})();
