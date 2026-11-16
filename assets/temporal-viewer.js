function getObservationDate(metadata) {
  const raw = metadata.observation_time_utc || metadata.date_observed;
  if (!raw || raw === "N/A") return null;
  const match = String(raw).match(/^(\d{4})[-/](\d{2})[-/](\d{2})(?:$|[T ])/);
  return match ? { iso: `${match[1]}-${match[2]}-${match[3]}`, label: `${match[3]}/${match[2]}/${match[1]}` }
    : { iso: null, label: String(raw) };
}

function getSurveyLabel(metadata, fallback) {
  const collection = metadata.data_release_collection || metadata.survey_origin;
  const known = { spherex_dr1: "SPHEREx DR1", spherex_qr3: "SPHEREx QR3" };
  return known[String(collection).toLowerCase()] ?? (collection && collection !== "N/A" ? collection : fallback);
}

function showTemporalError(archive, errors) {
  updateInvestigationHeader("unavailable");
  document.getElementById("loading-indicator").style.display = "none";
  const panel = document.getElementById("viewer-caption");
  const caption = document.getElementById("viewer-caption-text");
  panel.hidden = false;
  if (archive === "example") {
    caption.textContent = "Os quadros do exemplo não carregaram. Reabra o aplicativo com a pasta assets junto de index.html.";
  } else if (errors.some((error) => error?.status === 422)) {
    caption.textContent = "As coordenadas ou os parâmetros da consulta são inválidos. Confira os valores no modo de pesquisa.";
  } else if (errors.length && errors.every((error) => error?.status === 404)) {
    caption.textContent = `${archive} não encontrou duas observações comparáveis para este campo. Isso não diz se o alvo mudou. Você pode continuar com o exemplo de Barnard.`;
  } else {
    caption.textContent = `A consulta a ${archive} não retornou dois quadros utilizáveis. Tente novamente ou continue com o exemplo de Barnard.`;
  }
  if (errors.length) {
    updateTemporalTechnicalError(errors);
  }
}

function updateTemporalTechnicalError(errors) {
  const panel = document.getElementById("metadata-panel");
  const detail = document.createElement("p");
  detail.textContent = errors.map(apiErrorMessage).join(" · ");
  panel.replaceChildren(detail);
  panel.style.display = uiComplexityMode === "tech" ? "block" : "none";
}

async function showBarnardExample() {
  const generation = prepareDisplay("Abrindo as duas placas de arquivo…");
  updateInvestigationHeader("loading");
  highlightSimpleActionButton("motion-video");
  try {
    const frames = await Promise.all(BARNARD_FRAMES.map(async (entry) => ({
      image: await loadImageDataUrl(`assets/${entry.file}`),
      marker: entry.point,
      sourceUrl: entry.url,
      metadata: {
        date_observed: entry.date,
        survey_origin: entry.survey,
        data_source: "Digitized Sky Survey · ESO/STScI",
        telescope: "Palomar, Schmidt de 48 polegadas",
        observation_id: entry.plate
      }
    })));
    if (generation !== displayGeneration) return;
    presentTemporalComparison(frames, { example: true });
    safeUpdateUrlParam("example", "barnard");
  } catch (error) {
    if (generation !== displayGeneration) return;
    showTemporalError("example", [error]);
  }
}

async function executeQuickMotionVideo(sourceOverride = null, { cadence = null } = {}) {
  const generation = prepareDisplay("Buscando duas observações para o mesmo campo…");
  updateInvestigationHeader("loading");
  highlightSimpleActionButton("motion-video");
  const coords = requireCoordinates();
  const fov = Number(document.getElementById("input-fov").value);
  if (!coords || !Number.isFinite(fov) || fov <= 0 || fov > 60) {
    showTemporalError("arquivo", [{ status: 422, message: "RA e Dec obrigatórias; o raio deve estar entre 0 e 60 arcmin." }]);
    return;
  }
  const source = sourceOverride || document.getElementById("motion-source").value;
  const archive = source === "spherex" ? "IRSA/SPHEREx" : source === "optical" ? "SkyView/DSS" : "IRSA e SkyView";
  const detector = document.getElementById("spherex-detector").value;
  const filtered = filterEnabled();
  const params = { ...coords, detector, filter: String(filtered) };
  const controller = new AbortController();
  temporalRequest = controller;

  async function loadPair(pairSource) {
    const optical = pairSource === "optical";
    const payload = await requestApi(optical ? "/motion_video" : "/spherex/blink", {
      ...params,
      ...(optical ? { fov, source: "optical", include_gif: "false" } : { fov: Math.min(fov, 30) })
    }, { signal: controller.signal, timeoutMs: optical ? 14000 : 25000 });
    if (payload.images?.length !== 2 || !payload.images.every(Boolean)) {
      throw new Error("A fonte não retornou os dois quadros necessários.");
    }
    const frames = await Promise.all(payload.images.map(async (image, index) => ({
      image: await loadImageDataUrl(image), metadata: payload.metadata?.[index] ?? {}
    })));
    return { frames, optical, fov: payload.coordinates?.fov_arcmin ?? (optical ? fov : Math.min(fov, 30)) };
  }

  try {
    // In auto mode, disclose which archive supplied the first usable pair.
    const pair = source === "auto"
      ? await Promise.any([loadPair("spherex"), loadPair("optical")]) : await loadPair(source);
    if (generation !== displayGeneration) return;
    presentTemporalComparison(pair.frames, {
      optical: pair.optical, automatic: source === "auto", fov: pair.fov,
      reducedFov: !pair.optical && fov > 30, filtered, cadence, targetId: selectedCatalogId
    });
  } catch (error) {
    if (generation !== displayGeneration) return;
    showTemporalError(archive, error.errors || [error]);
  } finally {
    controller.abort();
    if (temporalRequest === controller) temporalRequest = null;
  }
}

function presentTemporalComparison(frames, { example = false, optical = false, automatic = false,
  fov = null, reducedFov = false, filtered = false, cadence = null, targetId = null } = {}) {
  const timeline = document.getElementById("comparison-epochs");
  const archive = example ? "DSS via ESO" : optical ? "DSS via NASA SkyView" : "SPHEREx via IRSA";
  timeline.replaceChildren();
  frames.forEach((frame, index) => {
    frame.date = getObservationDate(frame.metadata);
    frame.survey = getSurveyLabel(frame.metadata, archive);
    const item = document.createElement("li");
    const heading = document.createElement("strong");
    const date = document.createElement(frame.date?.iso ? "time" : "span");
    if (frame.date?.iso) date.dateTime = frame.date.iso;
    date.textContent = frame.date?.label || "Data não informada";
    heading.append(`Época ${index + 1} · `, date);
    const details = document.createElement("small");
    const wavelength = frame.metadata.wavelength_um;
    details.textContent = frame.survey + (frame.sourceUrl ? " · placa " : "")
      + (Number.isFinite(wavelength) ? ` · ${wavelength.toFixed(3).replace(".", ",")} µm` : "");
    if (frame.sourceUrl) {
      const link = document.createElement("a");
      link.href = frame.sourceUrl;
      link.textContent = frame.metadata.observation_id;
      link.setAttribute("aria-label", `Recorte FITS original da placa ${frame.metadata.observation_id}`);
      details.append(link);
    }
    item.append(heading, details);
    timeline.append(item);
    document.getElementById(`btn-epoch-${index + 1}`).textContent = frame.date?.label || `Época ${index + 1}`;
  });

  const sourceNote = document.getElementById("comparison-source-note");
  const instructions = document.getElementById("comparison-instructions");
  const interpretation = document.getElementById("comparison-interpretation");
  const limits = document.getElementById("comparison-limits");
  if (example) {
    instructions.textContent = "Alterne entre 1950 e 1991. O círculo marca a posição aproximada de Barnard; use as estrelas ao redor como referência.";
    interpretation.textContent = "Em 1950 a estrela marcada está na metade inferior. Em 1991 ela aparece mais acima, em direção ao norte do céu, enquanto as vizinhas continuam em posições semelhantes. Esse deslocamento é compatível com o movimento próprio conhecido de Barnard.";
    limits.textContent = "As placas ópticas têm resoluções e contrastes diferentes. O brilho na tela não mede a luminosidade da estrela, e o marcador não é uma medição da sua velocidade.";
    const credit = document.createElement("a");
    credit.href = "https://archive.stsci.edu/publishing/data-use";
    credit.textContent = "Créditos e termos do DSS";
    sourceNote.replaceChildren("Recortes do Digitized Sky Survey (STScI/Palomar), servidos pelo ESO. ", credit, ".");
  } else {
    instructions.textContent = "Alterne as épocas e compare a posição ou aparência de uma fonte com a das estrelas vizinhas. As imagens foram alinhadas pela posição no céu.";
    interpretation.textContent = targetId === "rdraconis" && !optical
      ? "Uma diferença de aparência pode motivar uma nova consulta. Duas imagens isoladas não mostram o período da estrela; para investigá-lo, seriam necessárias várias medições de brilho em datas diferentes."
      : "Se só uma fonte muda em relação às vizinhas, anote sua posição para investigar. A comparação não confirma movimento ou variação real. Se nada se destaca, isso não prova que nada mudou.";
    const spectralGap = frames.some(({ metadata }) => metadata.wavelength_delta_um > metadata.wavelength_match_tolerance_um);
    limits.textContent = (optical ? "Cada imagem óptica tem o contraste ajustado separadamente. " : "Os quadros compartilham uma escala visual; isso não calibra o brilho. ")
      + (spectralGap ? "As observações têm comprimentos de onda diferentes além da tolerância nominal, o que pode alterar a aparência. " : "")
      + "Resolução, fundo, faixa espectral e alinhamento também podem produzir diferenças.";
    sourceNote.textContent = (automatic && optical ? "O DSS óptico forneceu o primeiro par utilizável; estes dados não são SPHEREx. " : "")
      + `Arquivo: ${archive}. Raio: ${fov}′${reducedFov ? " (limite do SPHEREx)" : ""}.`
      + (filtered ? " Filtro de mediana 3×3 aplicado." : "");
  }

  Object.assign(videoState, {
    active: true, playing: false, frames, activeEpoch: 0, lastLabel: null,
    example, markTarget: true, crossfade: false, phase: 0, cadence
  });
  document.getElementById("btn-video-interp").setAttribute("aria-pressed", "false");
  document.getElementById("btn-barnard-marker").hidden = !example;
  document.getElementById("btn-barnard-marker").setAttribute("aria-pressed", "true");
  document.getElementById("loading-indicator").style.display = "none";
  document.getElementById("viewer-caption").hidden = true;
  document.getElementById("image-wrapper").style.display = "block";
  document.getElementById("display-canvas").style.display = "none";
  document.getElementById("video-render-canvas").style.display = "block";
  document.getElementById("viewer-crosshair").hidden = true;
  document.getElementById("video-controls-bar").style.display = "flex";
  document.getElementById("temporal-result").hidden = false;
  document.getElementById("comparison-layout").classList.add("has-temporal-result");
  setSourceBadge(archive);
  updateMetadataPanel(...frames.map((frame) => frame.metadata));
  updateInvestigationHeader(example ? "example" : "live");
  paintTemporalFrame(0);
}

function paintTemporalFrame(blend) {
  if (!videoState.active) return;
  const canvas = document.getElementById("video-render-canvas");
  const ctx = canvas.getContext("2d");
  const mixed = blend > 0 && blend < 1;
  const epoch = blend >= 0.5 ? 1 : 0;
  const frame = videoState.frames[epoch];
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const drawFrame = (entry, alpha) => {
    const image = entry.image;
    const scale = Math.min(canvas.width / image.naturalWidth, canvas.height / image.naturalHeight);
    const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
    const x = (canvas.width - width) / 2, y = (canvas.height - height) / 2;
    ctx.globalAlpha = alpha;
    ctx.drawImage(image, x, y, width, height);
    ctx.globalAlpha = 1;
    if (videoState.markTarget && !mixed && entry.marker) {
      ctx.beginPath();
      ctx.arc(x + entry.marker[0] * width, y + entry.marker[1] * height, 18, 0, 2 * Math.PI);
      ctx.strokeStyle = "#e6ff00";
      ctx.lineWidth = 2.5;
      ctx.stroke();
    }
  };
  if (mixed) {
    drawFrame(videoState.frames[0], 1);
    drawFrame(videoState.frames[1], blend);
  } else {
    drawFrame(frame, 1);
  }
  const key = mixed ? "mixed" : epoch;
  if (videoState.lastLabel === key) return;
  videoState.lastLabel = key;
  videoState.activeEpoch = epoch;
  const date = frame.date?.label ? ` · ${frame.date.label}` : "";
  document.getElementById("epoch-label").textContent = mixed ? "Mistura visual das duas épocas" : `Época ${epoch + 1}${date}`;
  canvas.setAttribute("aria-label", mixed ? "Mistura visual de duas observações, sem quadros intermediários reais"
    : `Imagem da época ${epoch + 1}${date} · ${frame.survey}`);
  document.getElementById("comparison-epochs").querySelectorAll("li").forEach((item, index) => {
    const active = !mixed && index === epoch;
    item.classList.toggle("is-current", active);
    document.getElementById(`btn-epoch-${index + 1}`).setAttribute("aria-pressed", String(active));
  });
}

function chooseTemporalEpoch(index) {
  stopTemporalPlayback();
  videoState.phase = index / 2;
  paintTemporalFrame(index);
}

function stopTemporalPlayback() {
  if (videoState.frameRequest !== null) cancelAnimationFrame(videoState.frameRequest);
  videoState.frameRequest = null;
  videoState.lastFrameAt = null;
  videoState.playing = false;
  document.getElementById("btn-video-play").textContent = "Reproduzir alternância";
}

function renderBlinkVideoFrame(now) {
  if (!videoState.active || !videoState.playing) return;
  const elapsed = now - (videoState.lastFrameAt ?? now);
  const cycleMs = videoState.cadence ? 2 * videoState.cadence * 1.5 : 2400;
  videoState.lastFrameAt = now;
  videoState.phase = (videoState.phase + elapsed * videoState.speed / cycleMs) % 1;
  const wave = 1 - Math.abs(2 * videoState.phase - 1);
  const blend = videoState.crossfade ? Math.max(0, Math.min(1, (wave - 0.2) / 0.6)) : Number(videoState.phase >= 0.5);
  if (videoState.crossfade || videoState.lastLabel !== blend) paintTemporalFrame(blend);
  videoState.frameRequest = requestAnimationFrame(renderBlinkVideoFrame);
}

function toggleVideoPlay() {
  if (!videoState.active) return;
  if (videoState.playing) {
    chooseTemporalEpoch(videoState.activeEpoch);
  } else {
    videoState.playing = true;
    document.getElementById("btn-video-play").textContent = "Pausar alternância";
    videoState.frameRequest = requestAnimationFrame(renderBlinkVideoFrame);
  }
}

function toggleVideoInterp() {
  videoState.crossfade = !videoState.crossfade;
  document.getElementById("btn-video-interp").setAttribute("aria-pressed", String(videoState.crossfade));
}
