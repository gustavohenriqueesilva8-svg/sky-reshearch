import type { Vector3 } from "three";

export const EducationLevel = {
  ELEMENTARY: "ELEMENTARY",
  HIGH_SCHOOL: "HIGH_SCHOOL",
  HIGHER_ED: "HIGHER_ED",
  SCIENTIFIC: "SCIENTIFIC",
} as const;

export type EducationLevel = (typeof EducationLevel)[keyof typeof EducationLevel];

export interface CelestialBodyData {
  id: string;
  namePt: string;
  nameEn: string;
  category: "star" | "planet" | "dwarf_planet" | "moon" | "tno_candidate";
  massKg: number;
  radiusKm: number;
  semiMajorAxisAu: number;
  orbitalPeriodDays: number;
  /** Negative for retrograde rotation. Zero when the catalog has no spin model. */
  rotationPeriodHours: number;
  axialTiltDeg: number;
  effectiveTempK?: number;
  /** Bond albedo as a fraction of incident energy. */
  albedo?: number;
  /** Initial placement in scene units. */
  positionScene: Vector3;
  visualRadius: number;
  textures: {
    dayMap: string;
    nightMap?: string;
  };
}

export interface MutualGravityAnalysis {
  primaryBody: CelestialBodyData;
  targetBody: CelestialBodyData;
  distanceMeters: number;
  distanceAu: number;
  gravitationalForceNewtons: number;
  targetSurfaceGravityMs2: number;
  targetEscapeVelocityKms: number;
  accelerationOnTargetMs2: number;
  accelerationOnPrimaryMs2: number;
  accelerationRatio: number;
  barycenterOffsetFromPrimaryKm: number;
  isBarycenterOutsidePrimary: boolean;
  forceVectorPrimaryToTarget: Vector3;
  forceVectorTargetToPrimary: Vector3;
}
