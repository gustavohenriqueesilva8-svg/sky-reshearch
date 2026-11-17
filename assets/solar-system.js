(() => {
  "use strict";

  const BODIES = [
    { key: "sun", label: "Sol", color: "#ffd078", radius: 7 },
    { key: "earth", label: "Terra", color: "#68c9ff", radius: 5 },
    { key: "mars", label: "Marte", color: "#ff9379", radius: 5 },
  ];
  const AXES = ["x", "y", "z"];
  const VIEW_ANGLES = {
    tilted: [-0.25, -1],
    xy: [0, 0],
    xz: [0, -Math.PI / 2],
  };
  const formatNumber = new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });

  function strokeSegment(ctx, from, to) {
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }

  function drawSystem(canvas, view, positions) {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const ctx = canvas.getContext("2d");
    if (!width || !height || !ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const pixelWidth = Math.round(width * dpr);
    const pixelHeight = Math.round(height * dpr);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    // One linear scale for all three axes. The camera only rotates the vectors.
    const scale = Math.min(width, height) * 0.19;
    const [yaw, pitch] = VIEW_ANGLES[view];
    const cosYaw = Math.cos(yaw), sinYaw = Math.sin(yaw);
    const cosPitch = Math.cos(pitch), sinPitch = Math.sin(pitch);
    const project = (x, y, z) => ({
      x: width / 2 + scale * (x * cosYaw - y * sinYaw),
      y: height / 2 - scale * ((x * sinYaw + y * cosYaw) * cosPitch - z * sinPitch),
    });

    ctx.font = "12px 'JetBrains Mono', monospace";
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(132, 185, 239, 0.22)";
    ctx.fillStyle = "#a7bfde";
    for (const radius of [0.5, 1, 1.5, 2]) {
      ctx.beginPath();
      for (let index = 0; index <= 72; index += 1) {
        const angle = index / 72 * 2 * Math.PI;
        const x = radius * Math.cos(angle);
        const v = radius * Math.sin(angle);
        const point = view === "xz" ? project(x, 0, v) : project(x, v, 0);
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      }
      ctx.closePath();
      ctx.stroke();
    }

    ctx.strokeStyle = "rgba(161, 199, 240, 0.4)";
    for (const [axis, x, y, z] of [["X", 2.15, 0, 0], ["Y", 0, 2.15, 0], ["Z", 0, 0, 2.15]]) {
      const end = project(x, y, z);
      const start = project(-x, -y, -z);
      if (Math.hypot(end.x - start.x, end.y - start.y) < 1) continue;
      strokeSegment(ctx, start, end);
      ctx.fillText(`+${axis}`, end.x + 4, end.y - 5);
    }
    ctx.fillText("2 ua", 14, height - 16);
    strokeSegment(ctx, { x: 14, y: height - 33 }, { x: 14 + 2 * scale, y: height - 33 });

    if (!positions) return;
    const points = Object.fromEntries(BODIES.map(({ key }) => {
      const { x, y, z } = positions[key];
      return [key, project(x, y, z)];
    }));

    ctx.lineWidth = 1.35;
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = "rgba(255, 208, 120, 0.58)";
    strokeSegment(ctx, points.sun, points.mars);
    ctx.strokeStyle = "rgba(255, 147, 121, 0.95)";
    strokeSegment(ctx, points.earth, points.mars);
    ctx.setLineDash([]);

    for (const { key, color, radius } of BODIES) {
      const point = points[key];
      ctx.beginPath();
      ctx.arc(point.x, point.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = key === "sun" ? 18 : 10;
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    ctx.font = "700 14px 'Overpass', sans-serif";
    for (const { key, label, color } of BODIES) {
      const point = points[key];
      const x = key === "earth" ? point.x - ctx.measureText(label).width - 10 : point.x + 10;
      const y = point.y + (key === "sun" ? 19 : -10);
      ctx.lineWidth = 4;
      ctx.strokeStyle = "#060d20";
      ctx.strokeText(label, x, y);
      ctx.fillStyle = color;
      ctx.fillText(label, x, y);
    }
  }

  window.createSolarSystemView = (root, requestApi) => {
    const form = root.querySelector("#solar-form");
    const input = root.querySelector("#solar-instant");
    const status = root.querySelector("#solar-status");
    const canvas = root.querySelector("#solar-canvas");
    const readout = root.querySelector("#solar-readout");
    const epoch = root.querySelector("#solar-epoch");
    const coordinates = root.querySelector("#solar-coordinates");
    const viewButtons = root.querySelectorAll("[data-solar-view]");
    let view = "tilted";
    let positions = null;
    let activeRequest = null;
    let activated = false;
    const draw = () => drawSystem(canvas, view, positions);
    const setNow = () => { input.value = new Date().toISOString().slice(0, 19); };

    function showResult(result) {
      epoch.dateTime = result.instant_utc;
      epoch.textContent = result.instant_utc.replace("T", " ").replace(/Z$/, " UTC");
      root.querySelector("#solar-earth-distance").textContent = `${formatNumber.format(result.distances.mars_earth)} ua`;
      root.querySelector("#solar-sun-distance").textContent = `${formatNumber.format(result.distances.mars_sun)} ua`;
      root.querySelector("#solar-model").textContent =
        `${result.model} · Origem no Sol · Alinhamento aproximado ao ${result.frame.axes}`;
      coordinates.replaceChildren(...BODIES.map(({ key, label }) => {
        const row = document.createElement("tr");
        const name = document.createElement("th");
        name.scope = "row";
        name.textContent = label;
        row.append(name);
        for (const axis of AXES) {
          const cell = row.insertCell();
          cell.textContent = formatNumber.format(result.positions[key][axis]);
        }
        return row;
      }));
      positions = result.positions;
      readout.hidden = false;
      status.textContent = "Posições atualizadas.";
      draw();
    }

    async function update() {
      activeRequest?.abort();
      const controller = new AbortController();
      activeRequest = controller;
      delete status.dataset.state;
      status.textContent = "Calculando posições…";
      readout.hidden = true;
      positions = null;
      draw();

      const instant = `${input.value}${input.value.length === 16 ? ":00" : ""}Z`;
      try {
        const result = await requestApi("/ephemerides/mars", { instant }, {
          signal: controller.signal,
          timeoutMs: 8000,
        });
        if (!controller.signal.aborted) showResult(result);
      } catch (error) {
        if (controller.signal.aborted) return;
        status.dataset.state = "error";
        status.textContent = error.status === 422
          ? "Data ou hora inválida. Use um instante UTC entre 2000 e 2049."
          : "Não foi possível consultar as posições. Abra o aplicativo pelo servidor Python e tente novamente.";
      } finally {
        if (activeRequest === controller) activeRequest = null;
      }
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      update();
    });
    root.querySelector("#solar-now").addEventListener("click", () => {
      setNow();
      form.requestSubmit();
    });
    for (const button of viewButtons) {
      button.addEventListener("click", () => {
        view = button.dataset.solarView;
        for (const option of viewButtons) {
          option.classList.toggle("active", option === button);
          option.setAttribute("aria-pressed", String(option === button));
        }
        draw();
      });
    }
    new ResizeObserver(draw).observe(canvas);

    return {
      activate() {
        if (activated) return;
        activated = true;
        setNow();
        if (!input.validity.valid) input.value = "2025-01-16T12:00";
        update();
      },
    };
  };
})();
