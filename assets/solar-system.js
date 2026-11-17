(() => {
  "use strict";

  const physics = window.gpsPhysics;
  const BODIES = {
    sun: { label: "Sol", color: "#ffd48b", ...physics.RADII_KM.sun, visualRadius: 0.15, pole: [286.13, 63.87] },
    earth: { label: "Terra", color: "#7ac8f6", ...physics.RADII_KM.earth, visualRadius: 0.11, pole: [0, 90] },
    mars: { label: "Marte", color: "#f59879", ...physics.RADII_KM.mars, visualRadius: 0.07, pole: [317.27, 54.43] },
  };
  const AXES = ["x", "y", "z"];
  const UNAVAILABLE = "Data fora da cobertura. Use um instante UTC entre 2000 e 2049.";
  const INVALID_INTERVAL = "O fim do recorte deve ser posterior ao início.";
  const PLAYBACK_DURATION_MS = 36_000;
  const formatNumber = new Intl.NumberFormat("pt-BR", {
    maximumFractionDigits: 4, minimumFractionDigits: 4,
  });
  const formatDiameter = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
  const formatSpeed = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3, minimumFractionDigits: 3 });
  const formatScale = new Intl.NumberFormat("pt-BR", { maximumSignificantDigits: 3 });
  const formatAcceleration = new Intl.NumberFormat("pt-BR", {
    notation: "scientific", maximumSignificantDigits: 4,
  });
  const formatEpoch = (instant) => instant.replace("T", " ").replace("Z", " UTC");
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

    let scene = null;
    let initialized = false;
    let active = false;
    let liveWindow = null;
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
    let mode = "live";
    let activeRequest = null;
    let refreshTimer = null;
    let playTimer = null;

    function setStatus(message, state = "") {
      if (status.textContent !== message) status.textContent = message;
      status.dataset.state = state;
    }

    function updateReadout() {
      const body = BODIES[selected];
      find("#gps-body-name").textContent = body.label;
      focus.disabled = !scene || !positions;
      if (!positions) return;
      const position = framePositions[selected];
      for (const axis of AXES) find(`#gps-coordinate-${axis}`).textContent = formatNumber.format(position[axis]);
      find("#gps-body-diameter").textContent = `${formatDiameter.format(2 * body.equatorialKm)} km`;
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
      scene?.showPositions(framePositions, frameVelocities, accelerations);
      updateReadout();
    }

    function showPositions(instant, vectors, velocityVectors) {
      positions = vectors;
      velocities = velocityVectors;
      showInstant(epoch, instant);
      showFrame();
    }

    function showSample(index) {
      const { trajectory, geometry } = range.data;
      const { instant_utc, earth, mars, velocities_km_s } = trajectory[index];
      range.index = index;
      slider.value = index;
      slider.setAttribute("aria-valuetext", formatEpoch(instant_utc));
      showPositions(instant_utc, { sun: geometry.positions.sun, earth, mars }, velocities_km_s);
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
      find("#gps-frame-origin").textContent = { sun: "no Sol", earth: "na Terra", mars: "em Marte" }[reference];
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

    function showRange(data, isDemo, index) {
      range = { data, isDemo, index };
      const samples = data.trajectory;
      const first = samples[0].instant_utc;
      const last = samples.at(-1).instant_utc;
      start.value = first.slice(0, 19);
      end.value = last.slice(0, 19);
      showInstant(find("#gps-range-start"), first);
      showInstant(find("#gps-range-end"), last);
      find("#gps-source").textContent = isDemo ? "Demonstração local" : data.geometry.model;
      slider.max = samples.length - 1;
      slider.disabled = false;
      play.disabled = false;
      loadOrbits(samples);
      showSample(index);
    }

    function stopPlayback() {
      cancelAnimationFrame(playTimer);
      playTimer = null;
      play.textContent = "Reproduzir";
      updateMotionClock();
    }

    function playbackSpeed() {
      const samples = range.data.trajectory;
      const duration = utcMilliseconds(samples.at(-1).instant_utc) - utcMilliseconds(samples[0].instant_utc);
      return Number(playbackRate.value) * duration / PLAYBACK_DURATION_MS;
    }

    function updateMotionClock() {
      const clock = find("#gps-movement-clock");
      if (mode === "live") {
        clock.textContent = "Tempo real · 1 s/s";
      } else if (playTimer === null) {
        clock.textContent = "Recorte pausado";
      } else {
        const rate = playbackSpeed();
        const display = rate >= 86400 ? `${formatSpeed.format(rate / 86400)} dias/s` : `${formatSpeed.format(rate)} s/s`;
        clock.textContent = `Reprodução · ${display}`;
      }
    }

    function togglePlayback() {
      if (playTimer !== null) {
        stopPlayback();
        return;
      }
      const last = Number(slider.max);
      if (range.index === last) showSample(0);
      const sampleTimes = range.data.trajectory.map((sample) => utcMilliseconds(sample.instant_utc));
      const startTime = sampleTimes[range.index];
      const speed = playbackSpeed();
      const startFrame = performance.now();
      play.textContent = "Pausar";
      function advance(now) {
        const simulatedTime = startTime + (now - startFrame) * speed;
        let next = range.index;
        while (next < last && sampleTimes[next + 1] <= simulatedTime) next += 1;
        if (next !== range.index) showSample(next);
        if (next === last) stopPlayback();
        else playTimer = requestAnimationFrame(advance);
      }
      playTimer = requestAnimationFrame(advance);
      updateMotionClock();
    }

    function cancelRequests() {
      clearTimeout(refreshTimer);
      refreshTimer = null;
      activeRequest?.abort();
      activeRequest = null;
    }

    function beginRequest() {
      activeRequest?.abort();
      const controller = new AbortController();
      activeRequest = controller;
      return controller;
    }

    async function refreshLive() {
      if (!active || mode !== "live") return;
      const now = new Date().toISOString().slice(0, 19);
      const instant = `${now}Z`;
      const needsWindow = !liveWindow || now > liveWindow.trajectory.at(-1).instant_utc.slice(0, 19) ||
        now < liveWindow.trajectory[0].instant_utc.slice(0, 19);
      const controller = beginRequest();
      let delay = 1000;
      try {
        const result = await requestApi(needsWindow ? "/ephemerides/solar-system" : "/ephemerides/mars", { instant, velocities: true }, {
          signal: controller.signal,
          timeoutMs: 6500,
        });
        if (controller.signal.aborted) return;
        if (needsWindow) {
          liveWindow = result;
          loadOrbits(result.trajectory);
        }
        const geometry = needsWindow ? result.geometry : result;
        showPositions(geometry.instant_utc, geometry.positions, geometry.velocities_km_s);
        liveState.textContent = "Acompanhando o relógio UTC";
        setStatus("");
        delay = 1000 - Date.now() % 1000;
      } catch (error) {
        if (controller.signal.aborted) return;
        if (!liveWindow || error.status === 422) {
          selectMode("range");
          setStatus(error.status === 422 ? UNAVAILABLE : "Tempo real indisponível. Verifique o servidor Python.", "error");
          return;
        }
        delay = 3000;
        liveState.textContent = "Último instante recebido";
        setStatus("Conexão interrompida. Tentando atualizar novamente…", "error");
      } finally {
        if (activeRequest === controller) activeRequest = null;
      }
      if (!controller.signal.aborted) refreshTimer = setTimeout(refreshLive, delay);
    }

    function selectMode(next) {
      if (next === mode) return;
      stopPlayback();
      cancelRequests();
      mode = next;
      updateMotionClock();
      for (const button of clockButtons) button.setAttribute("aria-pressed", String(button.dataset.gpsClock === mode));
      const isLive = mode === "live";
      find("#gps-cut-fields").hidden = isLive;
      find(".gps-time").hidden = isLive;
      liveState.hidden = !isLive;
      setStatus("");
      if (isLive) {
        liveState.textContent = "Sincronizando o relógio UTC…";
        if (liveWindow) loadOrbits(liveWindow.trajectory);
        refreshLive();
      } else {
        if (range) {
          showRange(range.data, range.isDemo, range.index);
        } else {
          const data = liveWindow ?? window.solarDemo;
          const index = data.trajectory.findIndex((sample) => sample.instant_utc === data.geometry.instant_utc);
          showRange(data, !liveWindow, index);
        }
        if (range.isDemo) setStatus("A demonstração usa o recorte incluído. Para consultar outras datas, execute python app.py.");
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
        showRange(result, false, 0);
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
      showSample(Number(slider.value));
    });
    play.addEventListener("click", togglePlayback);
    playbackRate.addEventListener("change", () => {
      if (playTimer === null) return;
      stopPlayback();
      togglePlayback();
    });
    referenceSelect.addEventListener("change", () => setReference(referenceSelect.value));
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
    for (const button of scaleButtons) {
      button.addEventListener("click", () => {
        const scale = button.dataset.gpsScale;
        for (const option of scaleButtons) option.setAttribute("aria-pressed", String(option === button));
        find("#gps-scale-note").textContent = scale === "real"
          ? "Diâmetros e distâncias na mesma escala. ◇ indica menos de 1 px. Selecione um astro para inspecionar em 3D."
          : "Diâmetros ampliados para leitura. Posições e distâncias em escala linear.";
        scene?.setScale(scale);
      });
    }
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
              onTarget: (key) => {
                find("#gps-camera-target").textContent = key ? `Foco em ${BODIES[key].label}` : "Navegação livre";
                free.setAttribute("aria-pressed", String(key === null));
                gravityFocus.hidden = key === null;
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
              onVelocityScale: (scale) => {
                velocityLegend.hidden = scale === null;
                if (scale !== null) {
                  const text = `${formatScale.format(10 * scale)} ua por 10 km/s`;
                  if (velocityScale.textContent !== text) velocityScale.textContent = text;
                }
              },
            });
            selectBody(selected, false);
          } catch (error) {
            console.warn("Falha ao iniciar a cena 3D.", error);
            find("#gps-render-error").hidden = false;
            for (const button of root.querySelectorAll("[data-gps-camera], [data-gps-scale]")) button.disabled = true;
          }
          if (location.protocol === "file:") {
            selectMode("range");
            return;
          }
        }
        scene?.resize();
        if (mode === "live") {
          liveState.hidden = false;
          liveState.textContent = "Sincronizando o relógio UTC…";
          refreshLive();
        }
      },
    };
  };
})();
