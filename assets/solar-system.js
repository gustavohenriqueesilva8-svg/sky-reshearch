(() => {
  "use strict";

  const BODIES = {
    sun: { label: "Sol", color: "#ffd48b", equatorialKm: 695700, polarKm: 695700, visualRadius: 0.15, pole: [286.13, 63.87] },
    earth: { label: "Terra", color: "#7ac8f6", equatorialKm: 6378.1, polarKm: 6356.8, visualRadius: 0.11, pole: [0, 90] },
    mars: { label: "Marte", color: "#f59879", equatorialKm: 3396.2, polarKm: 3376.2, visualRadius: 0.07, pole: [317.27, 54.43] },
  };
  const AXES = ["x", "y", "z"];
  const UNAVAILABLE = "Data fora da cobertura. Use um instante UTC entre 2000 e 2049.";
  const INVALID_INTERVAL = "O fim do recorte deve ser posterior ao início.";
  const formatNumber = new Intl.NumberFormat("pt-BR", {
    maximumFractionDigits: 4, minimumFractionDigits: 4,
  });
  const formatDiameter = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
  const formatEpoch = (instant) => instant.replace("T", " ").replace("Z", " UTC");
  const inputInstant = (value) => `${value.length === 16 ? value + ":00" : value}Z`;

  function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  }

  function showInstant(element, instant) {
    element.dateTime = instant;
    element.textContent = formatEpoch(instant);
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
    const bodyButtons = root.querySelectorAll("[data-gps-body]");
    const clockButtons = root.querySelectorAll("[data-gps-clock]");
    const scaleButtons = root.querySelectorAll("[data-gps-scale]");

    let scene = null;
    let initialized = false;
    let active = false;
    let liveWindow = null;
    let range = null;
    let positions = null;
    let selected = "mars";
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
      const position = positions[selected];
      for (const axis of AXES) find(`#gps-coordinate-${axis}`).textContent = formatNumber.format(position[axis]);
      find("#gps-body-diameter").textContent = `${formatDiameter.format(2 * body.equatorialKm)} km`;
      find("#gps-distance-sun").textContent = `${formatNumber.format(distance(position, positions.sun))} ua`;
      find("#gps-distance-earth").textContent = `${formatNumber.format(distance(position, positions.earth))} ua`;
      readout.hidden = false;
    }

    function selectBody(key, center = true) {
      selected = key;
      for (const button of bodyButtons) button.setAttribute("aria-pressed", String(button.dataset.gpsBody === key));
      scene?.select(key);
      if (center) scene?.focus(key);
      updateReadout();
    }

    function showPositions(instant, vectors) {
      positions = vectors;
      showInstant(epoch, instant);
      scene?.showPositions(positions);
      updateReadout();
    }

    function showSample(index) {
      const { trajectory, geometry } = range.data;
      const { instant_utc, earth, mars } = trajectory[index];
      range.index = index;
      slider.value = index;
      slider.setAttribute("aria-valuetext", formatEpoch(instant_utc));
      showPositions(instant_utc, { sun: geometry.positions.sun, earth, mars });
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
      scene?.loadTrajectory(samples);
      showSample(index);
    }

    function stopPlayback() {
      clearInterval(playTimer);
      playTimer = null;
      play.textContent = "Reproduzir";
    }

    function togglePlayback() {
      if (playTimer !== null) {
        stopPlayback();
        return;
      }
      const last = Number(slider.max);
      const stride = Math.max(1, Math.ceil(last / 144));
      if (range.index === last) showSample(0);
      play.textContent = "Pausar";
      playTimer = setInterval(() => {
        showSample(Math.min(last, range.index + stride));
        if (range.index === last) stopPlayback();
      }, 240);
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
        const result = await requestApi(needsWindow ? "/ephemerides/solar-system" : "/ephemerides/mars", { instant }, {
          signal: controller.signal,
          timeoutMs: 6500,
        });
        if (controller.signal.aborted) return;
        if (needsWindow) {
          liveWindow = result;
          scene?.loadTrajectory(result.trajectory);
        }
        const geometry = needsWindow ? result.geometry : result;
        showPositions(geometry.instant_utc, geometry.positions);
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
      for (const button of clockButtons) button.setAttribute("aria-pressed", String(button.dataset.gpsClock === mode));
      const isLive = mode === "live";
      find("#gps-cut-fields").hidden = isLive;
      find(".gps-time").hidden = isLive;
      liveState.hidden = !isLive;
      setStatus("");
      if (isLive) {
        liveState.textContent = "Sincronizando o relógio UTC…";
        if (liveWindow) scene?.loadTrajectory(liveWindow.trajectory);
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
        const result = await requestApi("/ephemerides/solar-system", { instant, end: finish }, {
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
    for (const button of bodyButtons) button.addEventListener("click", () => selectBody(button.dataset.gpsBody));
    for (const button of scaleButtons) {
      button.addEventListener("click", () => {
        const scale = button.dataset.gpsScale;
        for (const option of scaleButtons) option.setAttribute("aria-pressed", String(option === button));
        find("#gps-scale-note").textContent = scale === "real"
          ? "Diâmetros na mesma escala das distâncias. O modo aproxima a câmera do astro ao abrir."
          : "Diâmetros ampliados para leitura. Posições e distâncias em escala linear.";
        scene?.setScale(scale, selected);
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
                find("#gps-camera-target").textContent = key ? BODIES[key].label : "Sol (visão geral)";
              },
              onMissingTextures: (names) => {
                const notice = find("#gps-texture-status");
                notice.textContent = `Texturas indisponíveis para ${names.join(", ")}. Modelos exibidos com cores de referência.`;
                notice.hidden = false;
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
