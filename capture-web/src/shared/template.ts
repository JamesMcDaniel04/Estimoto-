/** Customer capture uses stable panel IDs with customer-facing directions. */
export type IntakePath = "insurance" | "self_pay";

export type PhotoStep = {
  key: string;
  panel: string | null;
  label: string;
  hint: string;
  optional?: boolean;
};

const panelStep = (panel: string, label: string): PhotoStep => ({
  key: `panel_${panel}`,
  panel,
  label,
  hint: "Fit the complete panel in frame, move to an angle where light shows the dents, and hold steady",
});

export const SELF_PAY_STEPS: PhotoStep[] = [
  panelStep("front_bumper", "Front bumper"),
  panelStep("grille", "Grille"),
  panelStep("headlamps", "Headlamp"),
  panelStep("hood", "Hood"),
  panelStep("fender_left", "Driver-side front fender"),
  panelStep("front_door_left", "Driver-side front door"),
  panelStep("mirrors", "Mirror"),
  panelStep("rear_door_left", "Driver-side rear door"),
  panelStep("quarter_left", "Driver-side rear quarter"),
  panelStep("rear_bumper", "Rear bumper"),
  panelStep("tail_lamps", "Tail lamp"),
  panelStep("trunk", "Trunk / liftgate"),
  panelStep("quarter_right", "Passenger-side rear quarter"),
  panelStep("rear_door_right", "Passenger-side rear door"),
  panelStep("front_door_right", "Passenger-side front door"),
  panelStep("fender_right", "Passenger-side front fender"),
  panelStep("windshield", "Windshield"),
  panelStep("roof", "Roof"),
];

export const INSURANCE_STEPS = SELF_PAY_STEPS;

/** Job type values as the server knows them; "hail" is what the customer sees
 *  as "Hail / PDR". */
export type JobType = "collision" | "hail";
/** How the car is photographed: selected damaged areas, or exactly four
 *  whole-car views used for an immediate AI rough range. */
export type CaptureMode = "areas" | "full_car";

export const JOB_TYPE_CHOICES: { key: JobType; label: string; hint: string }[] = [
  { key: "collision", label: "Collision", hint: "Dents, scratches, a crash, or broken parts" },
  { key: "hail", label: "Hail / PDR", hint: "Small dents all over, paint intact" },
];

/** The complete optional 11-panel PDR walk. */
export const HAIL_STEPS: PhotoStep[] = [
  panelStep("hood", "Hood"),
  panelStep("fender_left", "Driver-side front fender"),
  panelStep("front_door_left", "Driver-side front door"),
  panelStep("rear_door_left", "Driver-side rear door"),
  panelStep("quarter_left", "Driver-side rear quarter"),
  panelStep("trunk", "Trunk / deck lid"),
  panelStep("quarter_right", "Passenger-side rear quarter"),
  panelStep("rear_door_right", "Passenger-side rear door"),
  panelStep("front_door_right", "Passenger-side front door"),
  panelStep("fender_right", "Passenger-side front fender"),
  panelStep("roof", "Roof"),
];

/** The customer-facing Full Car (4 panel) contract. It is deliberately the
 *  same four uploads for collision/PDR and insurance/self-pay. */
export const FULL_CAR_STEPS: PhotoStep[] = [
  { key: "front", panel: "vehicle_front", label: "Front of car", hint: "Fit the complete front of the car in frame" },
  { key: "driver", panel: "vehicle_driver_side", label: "Driver side of car", hint: "Stand back until both wheels and the full driver side are visible" },
  { key: "rear", panel: "vehicle_rear", label: "Back of car", hint: "Fit the complete back of the car in frame" },
  { key: "passenger", panel: "vehicle_passenger_side", label: "Passenger side of car", hint: "Stand back until both wheels and the full passenger side are visible" },
];

/** Optional oblique angles. These stay first-class rows beneath Full Car and
 * run the multi-panel AI assessor for both claim types when supplied. */
export const OPTIONAL_CORNER_STEPS: PhotoStep[] = [
  { key: "corner_fl", panel: "vehicle_corner_fl", label: "Front driver-side angle", hint: "Show the front and driver side together with reflections visible" },
  { key: "corner_fr", panel: "vehicle_corner_fr", label: "Front passenger-side angle", hint: "Show the front and passenger side together with reflections visible" },
  { key: "corner_rl", panel: "vehicle_corner_rl", label: "Rear driver-side angle", hint: "Show the rear and driver side together with reflections visible" },
  { key: "corner_rr", panel: "vehicle_corner_rr", label: "Rear passenger-side angle", hint: "Show the rear and passenger side together with reflections visible" },
];

export const OPTIONAL_ROOF_STEP: PhotoStep = { key: "roof", panel: "vehicle_roof", label: "Roof (optional)", hint: "Show the whole roof from a safe standing position. You may skip this view.", optional: true };

/** Required documentation for collision and PDR is evidence, never damage pricing. */
export const COLLISION_DOCUMENT_STEPS: PhotoStep[] = [
  { key: "odometer", panel: "odometer", label: "Odometer photo", hint: "With the vehicle parked, open the driver’s door. Move closer to the mileage display behind the steering wheel." },
  { key: "vin", panel: "vin", label: "VIN at driver’s door jamb", hint: "Open the driver’s door and photograph the VIN label on the door jamb. Keep all 17 characters sharp and in frame; confirm any suggested reading yourself." },
  { key: "engine_bay", panel: "engine_bay", label: "Engine bay", hint: "Open the hood. Step back and raise the camera until the whole engine compartment is visible." },
  { key: "interior", panel: "interior", label: "Interior", hint: "Open the driver’s door. Hold the camera outside the doorway and include the front seats and dashboard." },
  { key: "tire_tread", panel: "tire_tread", label: "Tire tread", hint: "With the vehicle parked, move close to a tire and aim at the tread grooves, not the sidewall." },
];
export const REQUIRED_CAPTURE_STEPS = [...COLLISION_DOCUMENT_STEPS, ...FULL_CAR_STEPS];
export const requiredStepsFor = (_jobType: JobType) => REQUIRED_CAPTURE_STEPS;
export const SUPPORTED_VEHICLE_STEPS = [...FULL_CAR_STEPS, ...OPTIONAL_CORNER_STEPS, OPTIONAL_ROOF_STEP, ...COLLISION_DOCUMENT_STEPS];

/** The insurance/self-pay fork still routes the claim columns, but a hail job
 *  shoots the same walk on either path - that is the server contract. */
export function photoStepsFor(
  path: IntakePath | null,
  jobType: JobType = "collision",
  _captureMode: CaptureMode = "full_car",
): PhotoStep[] {
  if (!path) return [];
  if (jobType === "hail") return HAIL_STEPS;
  return path === "insurance" ? INSURANCE_STEPS : SELF_PAY_STEPS;
}

export const DAMAGE_AREAS: { key: string; label: string }[] = [
  { key: "front_bumper", label: "Front bumper" },
  { key: "grille", label: "Grille" },
  { key: "headlamps", label: "Headlamp" },
  { key: "hood", label: "Hood" },
  { key: "fender_left", label: "Driver-side front fender" },
  { key: "front_door_left", label: "Driver-side front door" },
  { key: "mirrors", label: "Mirror" },
  { key: "rear_door_left", label: "Driver-side rear door" },
  { key: "quarter_left", label: "Driver-side rear quarter" },
  { key: "rear_bumper", label: "Rear bumper" },
  { key: "tail_lamps", label: "Tail lamp" },
  { key: "trunk", label: "Trunk / liftgate" },
  { key: "quarter_right", label: "Passenger-side rear quarter" },
  { key: "rear_door_right", label: "Passenger-side rear door" },
  { key: "front_door_right", label: "Passenger-side front door" },
  { key: "fender_right", label: "Passenger-side front fender" },
  { key: "windshield", label: "Windshield" },
  { key: "roof", label: "Roof" },
];

/** The eleven PDR panels (backend PANEL_TYPES order), in customer words. */
export const HAIL_AREAS: { key: string; label: string }[] = [
  { key: "hood", label: "Hood" },
  { key: "fender_left", label: "Driver-side front fender" },
  { key: "front_door_left", label: "Driver-side front door" },
  { key: "rear_door_left", label: "Driver-side rear door" },
  { key: "quarter_left", label: "Driver-side rear quarter" },
  { key: "trunk", label: "Trunk / deck lid" },
  { key: "quarter_right", label: "Passenger-side rear quarter" },
  { key: "rear_door_right", label: "Passenger-side rear door" },
  { key: "front_door_right", label: "Passenger-side front door" },
  { key: "fender_right", label: "Passenger-side front fender" },
  { key: "roof", label: "Roof" },
];

/** Optional individual-panel photos use the complete mobile capture catalog,
 * never a reduced web-only subset. These supplement required documentation
 * and four whole-vehicle views. */
export const EXTRA_AREAS = DAMAGE_AREAS;
export const panelAreasFor = (jobType: JobType) =>
  jobType === "hail" ? HAIL_AREAS : DAMAGE_AREAS;

export function damageAreaLabel(panelType: string): string {
  return (
    HAIL_AREAS.find((a) => a.key === panelType)?.label ??
    DAMAGE_AREAS.find((a) => a.key === panelType)?.label ??
    panelType.replace(/_/g, " ")
  );
}

/** One marked hail area = two tiles on one server row: the close-up shows the
 *  panel, the angled-light frame is what the dent detector reads. */
export function hailAreaSteps(panel: string): [PhotoStep, PhotoStep] {
  const label = damageAreaLabel(panel);
  return [
    { key: `hail_close_${panel}`, panel, label: `${label}: close-up`, hint: "Fill the frame with the dented area" },
    { key: `hail_raking_${panel}`, panel, label: `${label}: angled light`, hint: "Hold the phone low so light rakes across the panel; the dents show as shadows" },
  ];
}

export function hailStepPanel(key: string): string | null {
  const m = /^hail_(?:close|raking)_(.+)$/.exec(key);
  return m ? m[1] : null;
}
export const isHailStepKey = (key: string): boolean => hailStepPanel(key) !== null;

/** Optional corners processed by the view assessor when supplied. */
export const VIEW_KEYS = new Set([...FULL_CAR_STEPS, ...OPTIONAL_CORNER_STEPS].map((step) => step.key));

export const FULL_CAR_HINT: Record<JobType, string> = {
  collision: "AI uses this view for the immediate rough range: fit the whole side in frame, in even light",
  hail: "AI uses this view for the immediate rough range: fit the whole side in frame, with light low across the car",
};

export const CAPTURE_MODES: { key: CaptureMode; label: string; hint: string }[] = [
  { key: "areas", label: "Selected damage areas", hint: "Choose damaged panels and photograph them up close" },
  { key: "full_car", label: "Full Car (4 panel)", hint: "Take front, driver side, back, and passenger side photos" },
];

/** Matches the server cap. Selected Areas can include the fixed insurance
 * walk plus all 18 mobile collision panels; retakes replace rows. */
export const MAX_PHOTOS = 32;

export const STEP_ORDER = ["details", "path", "photos", "estimate", "done"] as const;
export type IntakeStep = (typeof STEP_ORDER)[number];

export function isIntakeStep(value: string | undefined): value is IntakeStep {
  return !!value && (STEP_ORDER as readonly string[]).includes(value);
}
