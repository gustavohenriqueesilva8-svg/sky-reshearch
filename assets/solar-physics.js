(() => {
  "use strict";

  const AU_KM = 149_597_870.7;
  const C_KM_S = 299_792.458;
  const SOLAR_GM_KM3_S2 = 1.3271244e11;
  const RADII_KM = {
    sun: { equatorialKm: 695_700, polarKm: 695_700 },
    earth: { equatorialKm: 6378.1, polarKm: 6356.8 },
    mars: { equatorialKm: 3396.2, polarKm: 3376.2 },
  };
  // IAU nominal Sun, JPL DE440 Earth and JPL MAR097 Mars (planet alone).
  // https://ssd.jpl.nasa.gov/sats/phys_par/
  const GM_KM3_S2 = { sun: SOLAR_GM_KM3_S2, earth: 398_600.435507, mars: 42_828.37362 };
  const SCHWARZSCHILD_RADIUS_KM = 2 * SOLAR_GM_KM3_S2 / C_KM_S ** 2;
  const CURVATURE_OUTER_AU = 2;
  const CURVATURE_HEIGHT_SCALE = 1000;
  const ZERO = { x: 0, y: 0, z: 0 };

  function subtract(a, b) {
    return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
  }

  function relativeVectors(vectors, reference) {
    return Object.fromEntries(Object.entries(vectors).map(([body, vector]) => [
      body, subtract(vector, vectors[reference]),
    ]));
  }

  function accelerationFrom(position, sourcePosition, gm) {
    const { x, y, z } = subtract(sourcePosition, position);
    const distanceAu = Math.hypot(x, y, z);
    // Δr is in au. Convert the resulting acceleration to m/s².
    const factor = 1000 * gm / (AU_KM ** 2 * distanceAu ** 3);
    return { x: x * factor, y: y * factor, z: z * factor };
  }

  function gravitationalAccelerations(positions) {
    return Object.fromEntries(Object.keys(positions).map((body) => {
      const contributions = {};
      const total = { ...ZERO };
      for (const [source, position] of Object.entries(positions)) {
        if (source === body) continue;
        const vector = accelerationFrom(positions[body], position, GM_KM3_S2[source]);
        contributions[source] = vector;
        total.x += vector.x;
        total.y += vector.y;
        total.z += vector.z;
      }
      return [body, { total, contributions }];
    }));
  }

  function flammHeightKm(radiusKm) {
    if (radiusKm < RADII_KM.sun.equatorialKm) throw new RangeError("The slice starts at the solar surface.");
    const rs = SCHWARZSCHILD_RADIUS_KM;
    // The vertical origin is arbitrary. Place the outer boundary on the XY grid.
    return 2 * Math.sqrt(rs * (radiusKm - rs)) -
      2 * Math.sqrt(rs * (CURVATURE_OUTER_AU * AU_KM - rs));
  }

  function curvatureSurface() {
    const radialSteps = 36;
    const angularSteps = 72;
    // Offset the polygon's inner vertices so its chords also stay outside.
    const innerKm = RADII_KM.sun.equatorialKm / Math.cos(Math.PI / angularSteps);
    const outerKm = CURVATURE_OUTER_AU * AU_KM;
    const positions = [];
    const triangles = [];
    const lines = [];

    for (let ring = 0; ring <= radialSteps; ring += 1) {
      const radiusKm = innerKm * (outerKm / innerKm) ** (ring / radialSteps);
      const radius = radiusKm / AU_KM;
      const height = flammHeightKm(radiusKm) * CURVATURE_HEIGHT_SCALE / AU_KM;
      for (let sector = 0; sector < angularSteps; sector += 1) {
        const angle = sector * 2 * Math.PI / angularSteps;
        // Apply the scene's (X, Z, -Y) mapping to the embedding coordinates.
        positions.push(radius * Math.cos(angle), height, -radius * Math.sin(angle));
        const current = ring * angularSteps + sector;
        const next = ring * angularSteps + (sector + 1) % angularSteps;
        if (ring % 3 === 0) lines.push(current, next);
        if (ring === radialSteps) continue;
        if (sector % 6 === 0) lines.push(current, current + angularSteps);
        triangles.push(current, next, current + angularSteps, next, next + angularSteps, current + angularSteps);
      }
    }
    return { positions, triangles, lines };
  }

  // Perspective projection of the enclosing sphere. For an oblate body this
  // bounds the apparent vertical diameter, independent of the texture or zoom.
  function apparentDiameterPx(radius, depth, height, pixelsPerSlope) {
    if (depth <= radius) return null;
    const denominator = depth ** 2 - radius ** 2;
    return 2 * pixelsPerSlope * radius * Math.sqrt(denominator + height ** 2) / denominator;
  }

  window.gpsPhysics = {
    AU_KM, RADII_KM, SOLAR_GM_KM3_S2, SCHWARZSCHILD_RADIUS_KM, CURVATURE_HEIGHT_SCALE,
    CURVATURE_OUTER_AU, GM_KM3_S2, ZERO, subtract, relativeVectors, flammHeightKm,
    curvatureSurface, apparentDiameterPx, accelerationFrom, gravitationalAccelerations,
  };
})();
