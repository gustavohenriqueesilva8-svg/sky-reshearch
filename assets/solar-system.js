(() => {
  "use strict";

  const BODIES = {
    sun: { label: "Sol", color: "#ffd48b", radius: 0.15 },
    earth: { label: "Terra", color: "#7ac8f6", radius: 0.09 },
    mars: { label: "Marte", color: "#f59879", radius: 0.048 },
  };
  const AXES = ["x", "y", "z"];
  const UNAVAILABLE = "Data fora da cobertura. Use um instante UTC entre 2000 e 2049.";
  const formatNumber = new Intl.NumberFormat("pt-BR", {
    maximumFractionDigits: 4, minimumFractionDigits: 4,
  });
  const formatDate = new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit", month: "short", year: "numeric", timeZone: "UTC",
  });

  function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  }

  window.createSolarSystemView = (root, requestApi) => {
    const find = (selector) => root.querySelector(selector);
    const stage = find("#gps-stage");
    const form = find("#gps-form");
    const input = find("#gps-instant");
    const status = find("#gps-status");
    const readout = find("#gps-readout");
    const epoch = find("#gps-epoch");
    const canvas = stage.querySelector("canvas");
    const slider = find("#gps-timeline");
    const play = find("#gps-play");
    const focus = find("#gps-focus");
    const bodyButtons = root.querySelectorAll("[data-gps-body]");

    let scene = null;
    let initialized = false;
    let simulation = null;
    let positions = null;
    let selected = "mars";
    let activeRequest = null;
    let timer = null;

    function setStatus(message, state = "") {
      status.textContent = message;
      status.dataset.state = state;
    }

    function updateReadout() {
      find("#gps-body-name").textContent = BODIES[selected].label;
      focus.disabled = !scene || !positions;
      if (!positions) return;
      const position = positions[selected];
      for (const axis of AXES) find(`#gps-coordinate-${axis}`).textContent = formatNumber.format(position[axis]);
      find("#gps-distance-sun").textContent = `${formatNumber.format(distance(position, positions.sun))} ua`;
      find("#gps-distance-earth").textContent = `${formatNumber.format(distance(position, positions.earth))} ua`;
      readout.hidden = false;
    }

    function selectBody(key) {
      selected = key;
      for (const button of bodyButtons) button.setAttribute("aria-pressed", String(button.dataset.gpsBody === key));
      scene?.select(key);
      updateReadout();
    }

    function showSample(index) {
      const sample = simulation.trajectory[index];
      const { instant_utc, earth, mars } = sample;
      positions = { sun: simulation.geometry.positions.sun, earth, mars };
      slider.value = index;
      input.value = instant_utc.slice(0, 19);
      epoch.dateTime = instant_utc;
      epoch.textContent = `${instant_utc.slice(0, 19).replace("T", " ")} UTC`;
      slider.setAttribute("aria-valuetext", epoch.textContent);
      scene?.showPositions(positions);
      updateReadout();
    }

    function stop() {
      if (timer === null) return;
      clearInterval(timer);
      timer = null;
      play.textContent = "Reproduzir";
    }

    function startPlayback() {
      if (timer !== null) {
        stop();
        return;
      }

      if (slider.value === slider.max) showSample(0);
      play.textContent = "Pausar";
      timer = setInterval(() => {
        const next = Number(slider.value) + 1;
        showSample(next);
        if (slider.value === slider.max) stop();
      }, 240);
    }

    function showSimulation(result, isDemo = false) {
      simulation = result;
      const samples = result.trajectory;
      const sampleIndex = samples.findIndex((sample) => sample.instant_utc === result.geometry.instant_utc);
      const first = new Date(`${samples[0].instant_utc.slice(0, 19)}Z`);
      const last = new Date(`${samples.at(-1).instant_utc.slice(0, 19)}Z`);
      find("#gps-range").textContent = `${formatDate.format(first)} — ${formatDate.format(last)}`;
      find("#gps-source").textContent = isDemo ? "Demonstração local" : result.geometry.model;
      slider.max = samples.length - 1;
      slider.disabled = false;
      play.disabled = false;
      scene?.loadTrajectory(samples);
      showSample(sampleIndex);
    }

    async function update() {
      stop();
      activeRequest?.abort();
      const controller = new AbortController();
      activeRequest = controller;
      setStatus("Calculando a trajetória…");
      const instant = `${input.value.length === 16 ? input.value + ":00" : input.value}Z`;
      try {
        const result = await requestApi("/ephemerides/solar-system", { instant }, {
          signal: controller.signal,
          timeoutMs: 6500,
        });
        if (!controller.signal.aborted) {
          showSimulation(result);
          setStatus("");
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error.status === 422) {
          setStatus(UNAVAILABLE, "error");
          return;
        }
        if (!simulation) showSimulation(window.solarDemo, true);
        setStatus("Servidor indisponível. Execute python app.py para consultar outras datas.", "error");
      } finally {
        if (activeRequest === controller) activeRequest = null;
      }
    }

    function setNow() {
      input.value = new Date().toISOString().slice(0, 19);
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      update();
    });
    input.addEventListener("invalid", () => setStatus(UNAVAILABLE, "error"));
    find("#gps-now").addEventListener("click", () => {
      setNow();
      form.requestSubmit();
    });
    slider.addEventListener("input", () => {
      stop();
      showSample(Number(slider.value));
    });
    play.addEventListener("click", startPlayback);
    for (const button of bodyButtons) button.addEventListener("click", () => selectBody(button.dataset.gpsBody));
    focus.addEventListener("click", () => {
      scene?.focus(selected);
      canvas.focus();
    });
    find("#gps-edit-date").addEventListener("click", () => input.focus());
    find("#gps-reset").addEventListener("click", () => scene?.reset());
    find("#gps-zoom-in").addEventListener("click", () => scene?.zoom(0.8));
    find("#gps-zoom-out").addEventListener("click", () => scene?.zoom(1.25));
    find("#gps-explore").addEventListener("click", () => {
      (scene ? canvas : input).focus();
    });

    return {
      selectBody,
      deactivate: stop,
      activate() {
        if (initialized) {
          scene?.resize();
          return;
        }
        initialized = true;
        try {
          scene = window.createSolarScene(stage, BODIES);
          selectBody(selected);
        } catch {
          find("#gps-render-error").hidden = false;
          for (const button of root.querySelectorAll("[data-gps-camera]")) button.disabled = true;
        }
        if (location.protocol === "file:") {
          showSimulation(window.solarDemo, true);
          setStatus("Para consultar outras datas, execute python app.py.");
          return;
        }
        setNow();
        if (!input.validity.valid) input.value = window.solarDemo.geometry.instant_utc.slice(0, 19);
        update();
      },
    };
  };
})();
