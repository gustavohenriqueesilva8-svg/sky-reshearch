import { Vector3 } from "three";

import type { CelestialBodyData } from "../types/celestial.js";

const PLANET_X_ORBIT_AU = 380;

// Solar System Scope maps (CC BY 4.0) via Wikimedia Commons.
// https://ssi.solarsystemscope.com/textures/
// https://commons.wikimedia.org/wiki/Category:Solar_System_Scope
// https://creativecommons.org/licenses/by/4.0/
function scopeThumbnail(map: string, directory: string): string {
  const file = `Solarsystemscope_texture_2k_${map}.jpg`;
  return `https://upload.wikimedia.org/wikipedia/commons/thumb/${directory}/${file}/960px-${file}`;
}

// Observed-body parameters use NASA NSSDCA fact sheets. Planetary radii are
// volumetric means and the axes are J2000 values. Scene sizes and positions are
// schematic. Texture URLs are resolved when a renderer loads them.
// https://nssdc.gsfc.nasa.gov/planetary/planetfact.html
export const INITIAL_CELESTIAL_CATALOG: CelestialBodyData[] = [
  {
    id: "sun",
    namePt: "Sol",
    nameEn: "Sun",
    category: "star",
    massKg: 1.9884e30,
    radiusKm: 695_700,
    semiMajorAxisAu: 0,
    orbitalPeriodDays: 0,
    rotationPeriodHours: 609.12,
    axialTiltDeg: 7.25,
    effectiveTempK: 5772, // IAU nominal photospheric temperature.
    positionScene: new Vector3(0, 0, 0),
    visualRadius: 6.5,
    textures: { dayMap: "/assets/solar/sun.jpg" },
  },
  {
    id: "venus",
    namePt: "Vênus",
    nameEn: "Venus",
    category: "planet",
    massKg: 4.8673e24,
    radiusKm: 6_051.8,
    semiMajorAxisAu: 0.72333199,
    orbitalPeriodDays: 224.701,
    rotationPeriodHours: -5832.5,
    axialTiltDeg: 177.36,
    effectiveTempK: 226.6, // Black-body estimate from absorbed sunlight.
    albedo: 0.77,
    positionScene: new Vector3(16, 0, 0),
    visualRadius: 1.9,
    textures: { dayMap: scopeThumbnail("venus_atmosphere", "6/63") },
  },
  {
    id: "earth",
    namePt: "Terra",
    nameEn: "Earth",
    category: "planet",
    massKg: 5.9722e24,
    radiusKm: 6_371,
    semiMajorAxisAu: 1.00000011,
    orbitalPeriodDays: 365.256,
    rotationPeriodHours: 23.9345,
    axialTiltDeg: 23.439,
    effectiveTempK: 254,
    albedo: 0.294,
    positionScene: new Vector3(24, 0, 0),
    visualRadius: 2,
    textures: {
      dayMap: "/assets/solar/earth.jpg",
      nightMap: scopeThumbnail("earth_nightmap", "2/2f"),
    },
  },
  {
    id: "mars",
    namePt: "Marte",
    nameEn: "Mars",
    category: "planet",
    massKg: 6.4169e23,
    radiusKm: 3_389.5,
    semiMajorAxisAu: 1.52366231,
    orbitalPeriodDays: 686.98,
    rotationPeriodHours: 24.6229,
    axialTiltDeg: 25.19,
    effectiveTempK: 209.8,
    albedo: 0.25,
    positionScene: new Vector3(36, 0, 0),
    visualRadius: 1.06,
    textures: { dayMap: "/assets/solar/mars.jpg" },
  },
  {
    id: "jupiter",
    namePt: "Júpiter",
    nameEn: "Jupiter",
    category: "planet",
    massKg: 1.89813e27,
    radiusKm: 69_911,
    semiMajorAxisAu: 5.20336301,
    orbitalPeriodDays: 4_332.589,
    rotationPeriodHours: 9.925,
    axialTiltDeg: 3.13,
    effectiveTempK: 125.57, // Cassini-derived effective temperature (doi:10.1029/2012JE004191).
    albedo: 0.343,
    positionScene: new Vector3(64, 0, 0),
    visualRadius: 4.8,
    textures: { dayMap: scopeThumbnail("jupiter", "b/be") },
  },
  {
    id: "planet_x_candidate",
    namePt: "Candidato a Planeta X",
    nameEn: "Planet X Candidate",
    category: "tno_candidate",
    // Hypothetical scenario. The orbital period follows Kepler's third law.
    // Zero spin and tilt leave the initial rendering unposed.
    massKg: 3.702e25,
    radiusKm: 19_500,
    semiMajorAxisAu: PLANET_X_ORBIT_AU,
    orbitalPeriodDays: 365.256 * PLANET_X_ORBIT_AU ** 1.5,
    rotationPeriodHours: 0,
    axialTiltDeg: 0,
    effectiveTempK: 47,
    positionScene: new Vector3(115, 0, 0),
    visualRadius: 2.75,
    // Neptune's map illustrates the candidate without implying an observed surface.
    textures: { dayMap: scopeThumbnail("neptune", "1/1e") },
  },
];
