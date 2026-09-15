import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

/** Original, local geometry. These are body-category guides, not model replicas. */
export interface VehicleScene {
  setView(body: string, target: string): void;
  dispose(): void;
  snapshot(): string;
}
type Spec = {
  length: number; width: number; belt: number; height: number;
  frontAxle: number; rearAxle: number; radius: number;
  glassFront: number; roofFront: number; roofRear: number; glassRear: number;
  rearHeight: number; doors: number; open?: boolean; bed?: boolean;
  /** Greenhouse and beltline proportions: roof width as a share of the body
   * half-width (tumblehome), beltline rise from cowl to tail, roof drop from
   * the front of the roof to its rear, rocker (sill) height, cross-section
   * boxiness (superellipse exponent) and how far the nose sits below the cowl. */
  tumblehome: number; beltRise: number; roofDrop: number; sill: number; boxiness: number; noseDrop: number;
};
const SPECS: Record<string, Spec> = {
  sedan: { length: 4.8, width: 1.86, belt: 1.08, height: 1.55, frontAxle: -1.48, rearAxle: 1.48, radius: .36, glassFront: -.99, roofFront: -.34, roofRear: .75, glassRear: 1.5, rearHeight: 1.08, doors: 4, tumblehome: .73, beltRise: .03, roofDrop: .045, sill: .24, boxiness: 4, noseDrop: .15 },
  coupe: { length: 4.64, width: 1.89, belt: 1.02, height: 1.42, frontAxle: -1.43, rearAxle: 1.4, radius: .36, glassFront: -.8, roofFront: -.19, roofRear: .60, glassRear: 1.48, rearHeight: 1.0, doors: 2, tumblehome: .68, beltRise: .06, roofDrop: .10, sill: .22, boxiness: 3.6, noseDrop: .17 },
  hatchback: { length: 4.12, width: 1.8, belt: 1.08, height: 1.53, frontAxle: -1.3, rearAxle: 1.28, radius: .35, glassFront: -.94, roofFront: -.42, roofRear: .92, glassRear: 1.61, rearHeight: 1.1, doors: 4, tumblehome: .75, beltRise: .05, roofDrop: .03, sill: .24, boxiness: 4, noseDrop: .13 },
  wagon: { length: 4.92, width: 1.87, belt: 1.09, height: 1.56, frontAxle: -1.5, rearAxle: 1.52, radius: .36, glassFront: -1.04, roofFront: -.4, roofRear: 1.54, glassRear: 2.02, rearHeight: 1.12, doors: 4, tumblehome: .78, beltRise: .02, roofDrop: .015, sill: .24, boxiness: 4.4, noseDrop: .13 },
  suv: { length: 4.8, width: 1.97, belt: 1.31, height: 1.94, frontAxle: -1.47, rearAxle: 1.46, radius: .43, glassFront: -1.01, roofFront: -.46, roofRear: 1.37, glassRear: 1.95, rearHeight: 1.33, doors: 4, tumblehome: .81, beltRise: .02, roofDrop: 0, sill: .34, boxiness: 5, noseDrop: .10 },
  pickup: { length: 5.5, width: 2.02, belt: 1.36, height: 1.99, frontAxle: -1.73, rearAxle: 1.71, radius: .44, glassFront: -1.16, roofFront: -.62, roofRear: .68, glassRear: .89, rearHeight: 1.34, doors: 4, bed: true, tumblehome: .80, beltRise: 0, roofDrop: 0, sill: .40, boxiness: 5.5, noseDrop: .10 },
  van: { length: 5.05, width: 2.00, belt: 1.22, height: 2.08, frontAxle: -1.54, rearAxle: 1.58, radius: .40, glassFront: -1.72, roofFront: -1.1, roofRear: 1.81, glassRear: 2.16, rearHeight: 1.28, doors: 4, tumblehome: .87, beltRise: 0, roofDrop: 0, sill: .30, boxiness: 6, noseDrop: .05 },
  convertible: { length: 4.5, width: 1.9, belt: 1.02, height: 1.43, frontAxle: -1.39, rearAxle: 1.37, radius: .36, glassFront: -.88, roofFront: -.34, roofRear: .53, glassRear: 1.12, rearHeight: 1.02, doors: 2, open: true, tumblehome: .70, beltRise: .05, roofDrop: 0, sill: .22, boxiness: 3.6, noseDrop: .17 },
};
const normalBody = (body: string) => Object.hasOwn(SPECS, body) ? body : "sedan";
const v = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z);
// The driver door opening runs from just behind the windshield base to the
// B-pillar; the certification/VIN label lives on that rear pillar beside the
// driver's seat, where the door latches, not up by the dashboard.
const driverDoorEnd = (spec: Spec) => spec.doors === 2 ? .70 : .22;
const vinDoorJambPoint = (spec: Spec) => v(driverDoorEnd(spec) + .05, spec.belt - .31, spec.width * .41);

function surface(fn: (u: number, v: number) => THREE.Vector3, nu = 20, nv = 12) {
  const positions: number[] = [], indices: number[] = [];
  for (let i = 0; i <= nu; i++) for (let j = 0; j <= nv; j++) positions.push(...fn(i / nu, j / nv).toArray());
  for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) {
    const a = i * (nv + 1) + j, b = a + nv + 1;
    indices.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices); geometry.computeVertexNormals();
  return geometry;
}

function buildVehicle(spec: Spec) {
  const group = new THREE.Group(), shell = new THREE.Group(), interior = new THREE.Group();
  group.add(shell, interior);
  const materials: THREE.Material[] = [];
  const textures: THREE.Texture[] = [];
  const paint = new THREE.MeshPhysicalMaterial({ color: 0x91b2c1, metalness: .22, roughness: .40, clearcoat: .75, clearcoatRoughness: .3, side: THREE.DoubleSide });
  const glass = new THREE.MeshPhysicalMaterial({ color: 0x253e4f, metalness: .15, roughness: .28, clearcoat: .8, envMapIntensity: .75, side: THREE.DoubleSide });
  const rubber = new THREE.MeshStandardMaterial({ color: 0x151920, roughness: .84 });
  const trim = new THREE.MeshStandardMaterial({ color: 0x222b34, roughness: .42, metalness: .35 });
  const chrome = new THREE.MeshStandardMaterial({ color: 0xc1cdd5, metalness: .68, roughness: .35 });
  const brake = new THREE.MeshStandardMaterial({ color: 0x65717a, metalness: .8, roughness: .53 });
  const seatMaterial = new THREE.MeshStandardMaterial({ color: 0x393337, roughness: .92 });
  // Double-sided: the well is seen from oblique angles through the arch, so both faces must block the view.
  const wellMaterial = new THREE.MeshStandardMaterial({ color: 0x4d575f, roughness: .96, side: THREE.DoubleSide });
  const light = new THREE.MeshStandardMaterial({ color: 0xf2faff, emissive: 0xdaedff, emissiveIntensity: 1.15, roughness: .16, metalness: .25 });
  const tailLight = new THREE.MeshStandardMaterial({ color: 0xa70d22, emissive: 0xd90920, emissiveIntensity: .55, roughness: .23 });
  const highlightMaterial = new THREE.MeshBasicMaterial({ color: 0x06aeda, transparent: true, opacity: .13, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2 });
  const vinOutline = new THREE.MeshBasicMaterial({ color: 0x009f91, depthTest: false, depthWrite: false });
  const vinPaper = new THREE.MeshBasicMaterial({ color: 0xf5ffff, depthTest: false, depthWrite: false });
  materials.push(paint, glass, rubber, trim, chrome, brake, seatMaterial, wellMaterial, light, tailLight, highlightMaterial, vinOutline, vinPaper);
  const highlights = new Map<string, THREE.Object3D[]>();
  function mesh(geometry: THREE.BufferGeometry, material: THREE.Material, parent: THREE.Object3D = group) {
    const object = new THREE.Mesh(geometry, material); object.castShadow = true; object.receiveShadow = false; parent.add(object); return object;
  }
  function rounded(w: number, h: number, d: number, radius: number, material: THREE.Material, position: THREE.Vector3, parent = group) {
    const object = mesh(new RoundedBoxGeometry(w, h, d, 5, Math.min(radius, w / 2, h / 2, d / 2)), material, parent); object.position.copy(position); return object;
  }
  function line(points: THREE.Vector3[], material: THREE.Material = trim, radius = .009, parent: THREE.Object3D = group) {
    return mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), Math.max(8, points.length * 5), radius, 8, false), material, parent);
  }
  function focus(part: string, geometry: THREE.BufferGeometry, parent: THREE.Object3D = group) {
    const object = mesh(geometry, highlightMaterial, parent); object.visible = false; object.castShadow = false;
    highlights.set(part, [...highlights.get(part) ?? [], object]); return object;
  }
  const half = spec.length / 2, width = spec.width / 2, wheelY = spec.radius + .04;
  // The nose sits lower than the cowl and the plan narrows toward it, so the
  // hood reads as a sloping panel rather than one blunt loaf end.
  const frontDrop = (x: number) => spec.noseDrop * Math.pow(Math.max(0, -x / half), 2.5);
  // The beltline climbs from the cowl toward the tail on wedge-shaped bodies.
  const rise = (x: number) => spec.beltRise * Math.min(1, Math.max(0, (x - spec.glassFront) / (half - spec.glassFront)));
  const beltAt = (x: number) => spec.belt + rise(x);
  const planW = (x: number) => width * (1 - .09 * Math.pow(Math.max(0, -x / half), 3));
  const loftScale = (x: number) => Math.max(0, 1 - (Math.abs(x) / half) ** 10) ** .1;
  // Superellipse exponent: ~4 is a rounded sedan section, 5-6 a boxy van.
  const n = spec.boxiness, e = 2 / n;
  const bodyWidth = (x: number) => planW(x) * (1 - .12 * Math.pow(Math.abs(x / half), 6));
  const sideProfile = (x: number, y: number) => {
    const t = (topY(x) - y) / (topY(x) - .23);
    return bodyWidth(x) * (.86 + .14 * Math.sin(Math.min(1, Math.max(0, t)) ** .65 * Math.PI * .8));
  };
  const topY = (x: number) => beltAt(x) - frontDrop(x) - .04 * Math.pow(Math.max(0, -x / half), 5) + (spec.rearHeight - spec.belt) * Math.max(0, x / half);
  const archY = (x: number) => {
    let y = spec.sill;
    for (const axle of [spec.frontAxle, spec.rearAxle]) {
      const dx = Math.abs(x - axle), r = spec.radius + .065;
      if (dx < r) y = Math.max(y, wheelY + Math.sqrt(r * r - dx * dx));
    }
    return y;
  };
  // One smooth body loft, including the nose and tail. Rounded cross-sections
  // share normals across the shoulder and fascia rather than meeting as sheets.
  // The hood pivots on a line just under its own rear edge, so nothing swings away from the cowl.
  const hingeX = spec.glassFront - .03, hingeY = topY(hingeX) - .035, hood = new THREE.Group(); hood.position.set(hingeX, hingeY, 0); group.add(hood);
  const bottom = spec.sill;
  const midBody = (spec.belt + bottom) / 2, bodyH = (spec.belt - bottom) / 2;
  // Whether a point lies inside the lofted body; the upper half carries the nose drop.
  const insideLoft = (x: number, y: number, z: number) => {
    const scale = loftScale(x); if (scale <= 0) return false;
    const u = Math.abs(y - midBody) / Math.max(1e-6, bodyH * scale + (y > midBody ? rise(x) - frontDrop(x) : 0));
    const w = Math.abs(z) / (planW(x) * scale);
    return u ** n + w ** n <= 1;
  };
  // How far toward `end` the skin reaches at a given height and offset.
  const bodyX = (y: number, z: number, end: number) => {
    if (!insideLoft(0, y, z)) return 0;
    let lo = 0, hi = half;
    for (let i = 0; i < 36; i++) { const mid = (lo + hi) / 2; if (insideLoft(end * mid, y, z)) lo = mid; else hi = mid; }
    return lo;
  };
  // Half-width of the lofted section at a given station and height.
  const sectionZ = (x: number, y: number) => {
    const scale = loftScale(x); if (scale <= 0) return 0;
    const u = Math.abs(y - midBody) / Math.max(1e-6, bodyH * scale + (y > midBody ? rise(x) - frontDrop(x) : 0));
    return planW(x) * scale * Math.pow(Math.max(0, 1 - u ** n), 1 / n);
  };
  const doorStart = spec.glassFront + .10, doorEnd = driverDoorEnd(spec);
  // The door hinge sits on the skin line at the front edge, so the open door stays attached.
  const driverDoor = new THREE.Group(); driverDoor.position.set(doorStart, spec.belt, sectionZ(doorStart, spec.belt - .34) - .012); group.add(driverDoor);
  // Parts are authored in vehicle coordinates so the closed door matches the
  // surrounding skin exactly, then moved onto its front hinge.
  function onDoor<T extends THREE.Object3D>(object: T, moves: boolean) {
    if (moves) { object.position.sub(driverDoor.position); driverDoor.add(object); }
    return object;
  }
  const positions: number[] = [], bodyIndices: number[] = [], hoodIndices: number[] = [], doorIndices: number[] = [];
  // Stations land exactly on the hood hinge and door edges, and the hood and
  // door are cut along grid lines, so every panel edge is a clean curve.
  // The hood ends at the grille top rather than wrapping over the nose tip.
  const hoodFront = -half + .17, archR = spec.radius + .055;
  const nr = 128, bodyStations = Array.from(new Set([...Array.from({ length: 225 }, (_, i) => -half * Math.cos(Math.PI * i / 224)), hingeX, hoodFront, doorStart, doorEnd])).sort((p, q) => p - q);
  const nx = bodyStations.length - 1, ringStep = Math.PI * 2 / nr;
  const jHood = Math.round(Math.asin(Math.pow(.78, n / 2)) / ringStep);
  const jDoorTop = Math.ceil((Math.PI / 2 - Math.asin(Math.pow(.72, n / 2))) / ringStep);
  const jDoorBottom = Math.floor((Math.PI / 2 + Math.asin(Math.pow(Math.min(1, Math.max(0, (midBody - .35) / bodyH)), n / 2))) / ringStep);
  for (let i = 0; i <= nx; i++) {
    const x = bodyStations[i];
    const scale = loftScale(x);
    for (let j = 0; j <= nr; j++) {
      const angle = j / nr * Math.PI * 2, c = Math.cos(angle), sn = Math.sin(angle);
      const up = Math.max(0, c) ** e;
      positions.push(x, midBody + bodyH * scale * Math.sign(c) * Math.abs(c) ** e + (rise(x) - frontDrop(x)) * up,
        planW(x) * scale * Math.sign(sn) * Math.abs(sn) ** e);
    }
  }
  // Wheel arches: skin vertices inside the arch circle snap onto it, so the
  // opening is an exact circle instead of a stair-stepped hole.
  const original = positions.slice();
  for (let k = 0; k < positions.length; k += 3) {
    const x = original[k], y = original[k + 1], z = original[k + 2];
    if (Math.abs(z) < width * .60) continue;
    for (const axle of [spec.frontAxle, spec.rearAxle]) {
      const dx = x - axle, dy = y - wheelY, d = Math.hypot(dx, dy);
      // Only the fender edge snaps; the underside keeps its shape so nothing hangs below the arch.
      if (d < archR && d > 1e-6 && y >= wheelY - .05) {
        const nx2 = axle + dx / d * archR, ny2 = wheelY + dy / d * archR, was = sectionZ(x, y);
        positions[k] = nx2; positions[k + 1] = ny2;
        // Keep the moved vertex on the body section at its new station and height.
        if (was > 1e-4) positions[k + 2] = z * sectionZ(nx2, ny2) / was;
      }
    }
  }
  for (let i = 0; i < nx; i++) for (let j = 0; j < nr; j++) {
    const a = i * (nr + 1) + j, b = a + nr + 1;
    const ids = [a, b, a + 1, b, b + 1, a + 1];
    const x = (bodyStations[i] + bodyStations[i + 1]) / 2;
    const y = (original[a * 3 + 1] + original[(b + 1) * 3 + 1]) / 2;
    const z = (original[a * 3 + 2] + original[(b + 1) * 3 + 2]) / 2;
    // A quad leaves the skin only when all four corners sit inside an arch; quads
    // straddling the edge stay and their inner corners were snapped onto the circle.
    const inArch = (k: number) => Math.abs(original[k * 3 + 2]) > width * .63 && [spec.frontAxle, spec.rearAxle].some(axle => (original[k * 3] - axle) ** 2 + (original[k * 3 + 1] - wheelY) ** 2 < archR ** 2);
    if ([a, b, a + 1, b + 1].every(inArch)) continue;
    const isTop = y > topY(x) - .14 && Math.abs(z) < width * .82;
    if (isTop && x > hingeX && x < spec.glassRear) continue;
    if (isTop && x >= spec.glassRear && spec.bed) continue;
    // The hood is a shallow lid on top of the fenders; the door is the side skin below the shoulder.
    const isHood = x < hingeX && x > hoodFront && (j < jHood || j >= nr - jHood);
    const isDriverDoor = x > doorStart && x < doorEnd && j >= jDoorTop && j < jDoorBottom;
    (isHood ? hoodIndices : isDriverDoor ? doorIndices : bodyIndices).push(...ids);
  }
  const bodyGeometry = new THREE.BufferGeometry(); bodyGeometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  // Compute normals before separating moving panels so closed joins stay smooth.
  bodyGeometry.setIndex([...bodyIndices, ...hoodIndices, ...doorIndices]); bodyGeometry.computeVertexNormals();
  const hoodGeometry = bodyGeometry.clone(); hoodGeometry.setIndex(hoodIndices); hoodGeometry.translate(-hingeX, -hingeY, 0);
  const doorGeometry = bodyGeometry.clone(); doorGeometry.setIndex(doorIndices);
  bodyGeometry.setIndex(bodyIndices); mesh(bodyGeometry, paint); mesh(hoodGeometry, paint, hood); focus("hood", hoodGeometry, hood);
  onDoor(mesh(doorGeometry, paint), true);
  const doorLining = new THREE.Group(); driverDoor.add(doorLining);
  const doorLength = doorEnd - doorStart;
  rounded(doorLength - .05, spec.belt - .40, .055, .035, seatMaterial, v(doorLength / 2, (.37 - spec.belt) / 2, -.025), doorLining);
  rounded(doorLength * .66, .065, .12, .025, trim, v(doorLength * .54, -.24, -.075), doorLining);
  rounded(.16, .025, .025, .01, chrome, v(doorLength * .38, -.13, -.06), doorLining);
  // An unnumbered marker shows where a real door-jamb VIN label lives. It is
  // geometry only: no actual or invented VIN is rendered into the guide.
  const vinMarker = new THREE.Group(); vinMarker.position.copy(vinDoorJambPoint(spec)); group.add(vinMarker);
  // Face the label forward and outward, toward someone standing in the open doorway.
  vinMarker.rotation.y = -Math.PI * .42;
  rounded(.48, .26, .014, .012, vinOutline, v(0, 0, .018), vinMarker);
  rounded(.38, .17, .018, .008, vinPaper, v(0, 0, .035), vinMarker);
  for (let row = 0; row < 3; row++) rounded(.28, .009, .021, .003, vinOutline,
    v(0, .043 - row * .041, .049), vinMarker);
  // A short pointer marks the representative jamb area even on a small screen.
  line([v(-.34, .31, .04), v(-.22, .14, .04)], vinOutline, .017, vinMarker);
  rounded(.075, .075, .022, .011, vinOutline, v(-.35, .32, .04), vinMarker);
  vinMarker.traverse(object => { if (object instanceof THREE.Mesh) object.renderOrder = 10; });
  for (const side of [-1, 1]) {
    for (const axle of [spec.frontAxle, spec.rearAxle]) {
      const points = Array.from({length:49}, (_, i) => {
        const a = Math.PI * i / 48, x = axle + (spec.radius + .064) * Math.cos(a), y = wheelY + (spec.radius + .064) * Math.sin(a);
        return v(x, y, side * sectionZ(x, y));
      });
      line(points, spec.radius > .4 ? trim : paint, spec.radius > .4 ? .026 : .019);
      // A dark wheel-well liner closes the cavity behind the arch.
      const innerZ = width * .655, liner = mesh(surface((u, t) => {
        const a = Math.PI * u, x = axle + (archR - .01) * Math.cos(a), y = wheelY + (archR - .01) * Math.sin(a);
        return v(x, y, side * THREE.MathUtils.lerp(innerZ, Math.max(innerZ + .02, sectionZ(x, y) - .05), t));
      }, 20, 4), wellMaterial); liner.castShadow = false;
      const wall = mesh(new THREE.CircleGeometry(archR - .015, 28, 0, Math.PI), wellMaterial); wall.position.set(axle, wheelY, side * innerZ); wall.rotation.y = side > 0 ? 0 : Math.PI; wall.castShadow = false;
    }
  }
  // Deck and cabin floor; pickup bed has an open ribbed load box.
  const deckStart = spec.bed ? spec.glassRear : spec.glassRear + .02;
  const deckGeometry = surface((u, t) => {
    const x = THREE.MathUtils.lerp(deckStart, half - .035, u);
    return v(x, topY(x) + .022 * Math.sin(Math.PI * t), (t * 2 - 1) * bodyWidth(x) * .868);
  }, 20, 14);
  if (!spec.bed) { focus("trunk", deckGeometry); }
  else {
    deckGeometry.dispose();
    rounded(half - deckStart, .1, spec.width * .8, .02, trim, v((half + deckStart) / 2, .82, 0));
    for (const side of [-1, 1]) rounded(half - deckStart, .07, .14, .025, paint, v((half + deckStart) / 2, spec.belt, side * width * .85));
    for (let i = -5; i <= 5; i++) rounded(half - deckStart - .14, .025, .03, .009, trim, v((half + deckStart) / 2, .882, i * .13));
    rounded(.09, .47, spec.width * .82, .035, paint, v(half - .055, 1.09, 0));
  }
  // The cabin floor stays inboard of the wheel wells so it never shows through an arch.
  rounded(spec.glassRear - spec.glassFront, .1, spec.width * .60, .03, trim, v((spec.glassFront + spec.glassRear) / 2, spec.belt - .62, 0), interior);

  const skinY = (x: number, z: number) => {
    const scale = loftScale(x);
    const f = Math.max(0, scale ** n - (Math.abs(z) / planW(x)) ** n) ** (1 / n);
    return midBody + bodyH * f + (rise(x) - frontDrop(x)) * f / Math.max(scale, 1e-6);
  };
  // Blend the cabin sill into the curved body; the cabin loft starts exactly where the sills end.
  const cabinLift = .045, sillW = width * .86, clamp01 = (t: number) => Math.min(1, Math.max(0, t));
  const cabinBase = (x: number) => topY(x) + cabinLift;
  for (const side of [-1, 1]) {
    const segments = side === 1 ? [[spec.glassFront, doorStart], [doorStart, doorEnd], [doorEnd, spec.glassRear]] : [[spec.glassFront, spec.glassRear]];
    for (const [start, end] of segments) onDoor(mesh(surface((u, t) => {
      const x = THREE.MathUtils.lerp(start, end, u);
      const z = side * width * (.90 - .04 * t);
      return v(x, THREE.MathUtils.lerp(skinY(x, side * width * .90), cabinBase(x), t), z);
    }, 24, 10), paint, shell), side === 1 && start === doorStart);
  }
  mesh(surface((u, t) => {
    const z = (u * 2 - 1) * sillW;
    const x = spec.glassFront - .025 * Math.sin(u * Math.PI) - .03 * (1 - t);
    return v(x, THREE.MathUtils.lerp(skinY(x, z), cabinBase(spec.glassFront) + .012 * Math.sin(u * Math.PI), t), z);
  }, 40, 8), paint, shell);

  // One closed greenhouse loft: up the near sill, across the roof, down the far
  // sill, from the cowl to the rear deck. Glass and pillars are painted onto
  // this single surface, so every window meets its sill, pillar and roof rail
  // by construction, and the driver's window frame is cut from the same skin.
  const roofW = width * spec.tumblehome, roofY = spec.height;
  // Fastback roofs fall away toward the rear; boxy roofs stay level.
  const roofAt = (x: number) => roofY - spec.roofDrop * clamp01((x - spec.roofFront) / Math.max(.01, spec.roofRear - spec.roofFront));
  const cabinEnd = spec.open ? spec.roofFront : spec.glassRear + .02;
  const roofTopFront = roofAt(spec.roofFront) - .02, roofTopRear = roofAt(spec.roofRear) - .02, cabinTail = topY(cabinEnd) + .012;
  const capY = (x: number) => {
    let y: number;
    if (x <= spec.roofFront) y = THREE.MathUtils.lerp(cabinBase(spec.glassFront), roofTopFront, Math.sin(clamp01((x - spec.glassFront) / (spec.roofFront - spec.glassFront)) * Math.PI / 2));
    else if (x <= spec.roofRear) y = roofAt(x) - .02;
    else y = THREE.MathUtils.lerp(roofTopRear, cabinTail, 1 - Math.cos(clamp01((x - spec.roofRear) / Math.max(.01, cabinEnd - spec.roofRear)) * Math.PI / 2));
    return Math.max(y, cabinBase(x));
  };
  // Rows are shared out as wall / top / wall with fixed counts, so the roof
  // corners are exact mesh rows at every station: the door frame and the roof
  // edge meet on one clean crease.
  const cnv = 120, wallRows = 33, wallShare = wallRows / cnv;
  const cabinPoint = (x: number, r: number) => {
    const base = cabinBase(x), top = capY(x), h = Math.max(0, top - base);
    const wTop = THREE.MathUtils.lerp(sillW, roofW, clamp01(h / Math.max(.05, roofY - spec.belt)));
    const crown = (x > spec.roofFront && x < spec.roofRear ? .05 : .018) * Math.min(1, h / .3);
    if (r >= wallShare && r <= 1 - wallShare) { const q = (r - .5) / (.5 - wallShare); return { y: top + crown * Math.cos(q * Math.PI / 2), z: q * wTop, top: true, q }; }
    const side = r < .5 ? -1 : 1, vfrac = clamp01(side < 0 ? r / wallShare : (1 - r) / wallShare);
    return { y: base + h * Math.pow(vfrac, .92), z: side * THREE.MathUtils.lerp(sillW, wTop, Math.pow(vfrac, 1.35)), top: false, q: side };
  };
  // Stations where the windshield and rear glass reach a given height: the A- and C-pillars follow them.
  const xAtWindshield = (y: number) => spec.glassFront + Math.asin(clamp01((y - cabinBase(spec.glassFront)) / Math.max(.01, roofTopFront - cabinBase(spec.glassFront)))) * 2 / Math.PI * (spec.roofFront - spec.glassFront);
  const xAtBackglass = (y: number) => spec.roofRear + Math.acos(1 - clamp01((roofTopRear - y) / Math.max(.01, roofTopRear - cabinTail))) * 2 / Math.PI * (cabinEnd - spec.roofRear);
  const pillarX = spec.doors === 2 ? .52 : .20, longRoof = spec.roofRear > 1.1;
  // Stations land exactly on the door edges so the door frame parts cleanly.
  const cnu = 96;
  const stations = Array.from(new Set([...Array.from({ length: cnu + 1 }, (_, i) => THREE.MathUtils.lerp(spec.glassFront, cabinEnd, i / cnu)), ...(spec.open ? [] : [doorStart, doorEnd])].filter(x => x >= spec.glassFront && x <= cabinEnd))).sort((p, q) => p - q);
  const cabinPositions: number[] = [];
  for (const x of stations) for (let j = 0; j <= cnv; j++) { const p = cabinPoint(x, j / cnv); cabinPositions.push(x, p.y, p.z); }
  const shellIndex: number[] = [], doorIndex: number[] = [], roofIndex: number[] = [];
  for (let i = 0; i < stations.length - 1; i++) for (let j = 0; j < cnv; j++) {
    const a0 = i * (cnv + 1) + j, b0 = a0 + cnv + 1, ids = [a0, b0, a0 + 1, b0, b0 + 1, a0 + 1];
    const x = (stations[i] + stations[i + 1]) / 2, r = (j + .5) / cnv, p = cabinPoint(x, r);
    if (p.top && x > spec.roofFront && x <= spec.roofRear) roofIndex.push(...ids);
    // The driver's door frame is the whole near wall between the door edges, up to the roof crease.
    const door = !spec.open && !p.top && r > .5 && x > doorStart && x < doorEnd;
    (door ? doorIndex : shellIndex).push(...ids);
  }
  const cabinGeometry = new THREE.BufferGeometry();
  cabinGeometry.setAttribute("position", new THREE.Float32BufferAttribute(cabinPositions, 3));
  cabinGeometry.setIndex([...shellIndex, ...doorIndex]); cabinGeometry.computeVertexNormals();
  const cabinSubset = (index: number[]) => { const geometry = cabinGeometry.clone(); geometry.setIndex(index); return geometry; };
  mesh(cabinSubset(shellIndex), paint, shell);
  if (doorIndex.length) onDoor(mesh(cabinSubset(doorIndex), paint, shell), true);
  if (roofIndex.length) focus("roof", cabinSubset(roofIndex), shell);
  cabinGeometry.dispose();
  // Windows are exact-edged panes laid on the same loft surface, so their edges
  // follow the pillars instead of the mesh grid and never leave the skin.
  const paneGlass = glass.clone(); paneGlass.polygonOffset = true; paneGlass.polygonOffsetFactor = -2; paneGlass.polygonOffsetUnits = -2; materials.push(paneGlass);
  const wallPoint = (x: number, y: number, side: number) => {
    const base = cabinBase(x), top = capY(x), h = Math.max(1e-3, top - base);
    const wTop = THREE.MathUtils.lerp(sillW, roofW, clamp01(h / Math.max(.05, roofY - spec.belt)));
    const vfrac = Math.pow(clamp01((y - base) / h), 1 / .92);
    return v(x, y, side * THREE.MathUtils.lerp(sillW, wTop, Math.pow(vfrac, 1.35)));
  };
  const topPane = (x0: number, x1: number) => surface((u, t) => {
    const x = THREE.MathUtils.lerp(x0, x1, u), p = cabinPoint(x, .5 + (2 * t - 1) * .93 * (.5 - wallShare));
    return v(x, p.y, p.z);
  }, 48, 32);
  const windshieldGeometry = topPane(spec.glassFront + .025, spec.roofFront - .004);
  mesh(windshieldGeometry, paneGlass, shell); focus("windshield", windshieldGeometry, shell);
  if (!spec.open) {
    mesh(topPane(spec.roofRear + .004, cabinEnd - .03), paneGlass, shell);
    const sidePane = (side: number, xFront: (y: number) => number, xRear: (y: number) => number, moves: boolean) => {
      const yLow = (x: number) => cabinBase(x) + .04, yHigh = (x: number) => capY(x) - .045;
      const geometry = surface((u, t) => {
        const yGuess = THREE.MathUtils.lerp(yLow(pillarX), yHigh(pillarX), t);
        const xGuess = THREE.MathUtils.lerp(xFront(yGuess), xRear(yGuess), u);
        const y = THREE.MathUtils.lerp(yLow(xGuess), yHigh(xGuess), t);
        return wallPoint(THREE.MathUtils.lerp(xFront(y), xRear(y), u), y, side);
      }, 36, 24);
      if (xRear(yLow(pillarX)) - xFront(yLow(pillarX)) < .12 && xRear(yHigh(pillarX)) - xFront(yHigh(pillarX)) < .12) { geometry.dispose(); return; }
      onDoor(mesh(geometry, paneGlass, shell), moves);
    };
    for (const side of [-1, 1]) {
      sidePane(side, (y) => Math.max(xAtWindshield(y) + .075, spec.glassFront + .06), () => pillarX - .035, side === 1);
      sidePane(side, () => pillarX + .035, (y) => Math.min(xAtBackglass(y) - .08, longRoof ? 1.08 - .03 : Infinity, cabinEnd - .11), false);
      if (longRoof) sidePane(side, () => 1.08 + .03, (y) => Math.min(xAtBackglass(y) - .08, cabinEnd - .11), false);
    }
  }
  if (spec.open) {
    const header = cabinPoint(spec.roofFront, .5);
    line([v(spec.roofFront, header.y - .01, -roofW * .98), v(spec.roofFront - .01, header.y + .008, 0), v(spec.roofFront, header.y - .01, roofW * .98)], paint, .028, shell);
  } else {
    // A short lip carries the rear glass base down onto the deck.
    mesh(surface((u, t) => { const z = (u * 2 - 1) * sillW * .98; const x = cabinEnd + .015 * t; return v(x, THREE.MathUtils.lerp(cabinBase(cabinEnd), topY(x) + .022 * Math.sin(u * Math.PI), t), z); }, 24, 4), paint, shell);
  }
  // Wiper rests and cowl trim at the windshield base.
  line([v(spec.glassFront - .015, cabinBase(spec.glassFront) - .01, -sillW), v(spec.glassFront - .034, cabinBase(spec.glassFront) + .01, 0), v(spec.glassFront - .015, cabinBase(spec.glassFront) - .01, sillW)], trim, .017, shell);
  for (const side of [-1, 1]) line([v(spec.glassFront + .02, cabinBase(spec.glassFront) + .02, side * .12), v(spec.glassFront + .09, cabinBase(spec.glassFront) + .07, side * .51)], trim, .009, shell);
  if (["suv", "wagon"].some(key => SPECS[key] === spec)) for (const side of [-1, 1]) line([spec.roofFront + .18, .4, spec.roofRear - .1].map(x => { const p = cabinPoint(x, .5 + .82 * (.5 - wallShare)); return v(x, p.y + .022, side * p.z); }), chrome, .02, shell);
  // Separate inset seams and flush handles give doors tangible scale.
  for (const side of [-1, 1]) {
    const suffix = side === 1 ? "left" : "right", split = spec.doors === 2 ? .70 : .22;
    const doorEnd = spec.bed ? .87 : Math.min(spec.rearAxle - .18, spec.glassRear - .08);
    const doors = [[spec.glassFront + .10, split, "front_door"], ...(spec.doors === 4 ? [[split + .015, doorEnd, "rear_door"]] : [])] as [number, number, string][];
    for (const [start, end, name] of doors) {
      const seamPoints = [[start, spec.belt - .035], [start - .018, .62], [start + .07, .35], [end - .055, .35], [end, .65], [end, spec.belt - .035]].map(([x, y]) => v(x, y, side * (sideProfile(x, y) + .012)));
      void seamPoints;
      const doorGeometry = surface((u, t) => {
        const x = THREE.MathUtils.lerp(start + .03, end - .02, u), upper = topY(x), lower = archY(x), y = THREE.MathUtils.lerp(upper - .055, Math.max(lower + .025, .37), t);
        return v(x, y, side * (sideProfile(x, y) + .004));
      }, 10, 8); focus(`${name}_${suffix}`, doorGeometry);
      onDoor(rounded(.155, .024, .032, .009, chrome, v(end - .15, beltAt(end - .15) - .105, side * width * .947)), side === 1 && name === "front_door");
    }
    const mirror = rounded(.27, .105, .18, .045, paint, v(spec.glassFront + .12, spec.belt + .12, side * (width + .03)));
    onDoor(mirror, side === 1); mirror.rotation.y = side * .10;
    onDoor(rounded(.18, .065, .017, .014, glass, v(spec.glassFront + .145, spec.belt + .124, side * (width + .116))), side === 1);
    onDoor(line([v(spec.glassFront + .16, spec.belt + .07, side * sillW), v(spec.glassFront + .12, spec.belt + .10, side * width)], trim, .032), side === 1);
    const mirrorFocus = focus("mirrors", new THREE.SphereGeometry(.19, 16, 10)); mirrorFocus.position.set(spec.glassFront + .12, spec.belt + .12, side * (width + .03)); mirrorFocus.scale.set(1, .55, .75);
    for (const [axle, part] of [[spec.frontAxle, "fender"], [spec.rearAxle, "quarter"]] as const) {
      const geo = surface((u, t) => {
        const x = axle + (u - .5) * .97, upper = topY(x), lower = archY(x), y = THREE.MathUtils.lerp(upper, lower + .018, t);
        return v(x, y, side * (sideProfile(x, y) + .005));
      }, 22, 8); focus(`${part}_${suffix}`, geo);
    }
  }
  // Smooth, continuous fascia. Lamps and the intake follow its curvature;
  // neither sits on a protruding rectangular bumper or chrome stack.
  for (const end of [-1, 1]) {
    const lower = bottom + .01;
    const upper = topY(end * (half - .045)), mid = (upper + lower) / 2;
    const fasciaX = (z: number, y: number) => end * bodyX(y, z, end);
    const fascia = surface((u, t) => {
      const y = THREE.MathUtils.lerp(lower, upper, u);
      const z = (t * 2 - 1) * sideProfile(end * (half - .045), y);
      return v(fasciaX(z, y), y + (end < 0 ? .07 : .022) * Math.sin(t * Math.PI) * u, z);
    }, 28, 42);
    focus(end < 0 ? "front_bumper" : "rear_bumper", fascia);
    const inset = (y: number, w: number, h: number, material: THREE.Material) => {
      const geometry = surface((u, t) => {
        const dy = (t - .5) * h;
        const z = (u * 2 - 1) * (w / 2 - h / 2 + Math.sqrt(Math.max(0, h * h / 4 - dy * dy)));
        const yy = y + dy;
        const crown = 0;
        return v(fasciaX(z, yy) + end * .012, yy + crown, z);
      }, 36, 12);
      const item = mesh(geometry, material); item.castShadow = false;
      return geometry;
    };
    const intakeY = lower + (upper - lower) * .27;
    inset(intakeY, spec.width * .62, .14, trim);
    if (end < 0) focus("grille", inset(intakeY, spec.width * .62, .14, trim));
    inset(mid + .04, .29, .065, chrome);
    for (const side of [-1, 1]) {
      const lampY = upper - .125, center = side * width * .57;
      const points = Array.from({ length: 12 }, (_, i) => {
        const z = center + (i / 11 - .5) * width * .49;
        const y = lampY + .04 * Math.abs(z / width);
        return v(fasciaX(z, y) + end * .012, y, z);
      });
      const housing = line(points, glass, .036); housing.castShadow = false;
      const lamp = line(points.map(point => point.clone().add(v(end * .023, .007, 0))), end < 0 ? light : tailLight, .014);
      lamp.castShadow = false;
      focus(end < 0 ? "headlamps" : "tail_lamps", housing.geometry);
    }
  }
  // Tires, machined twin spokes, inset vented discs, and individual tread blocks.
  for (const axle of [spec.frontAxle, spec.rearAxle]) for (const side of [-1, 1]) {
    const r = spec.radius, tireWidth = .225, face = side * (tireWidth / 2 + .012);
    // The tire's outer face sits just inside the fender lip.
    const wheel = new THREE.Group(); wheel.position.set(axle, wheelY, side * (sectionZ(axle, wheelY + r * .9) - .135)); group.add(wheel);
    const tire = mesh(new THREE.TorusGeometry(r - .084, .087, 12, 56), rubber, wheel); tire.scale.z = 1.42;
    for (const s of [-1, 1]) {
      const sidewall = mesh(new THREE.RingGeometry(r * .67, r * .96, 56), rubber, wheel); sidewall.position.z = s * tireWidth / 2; if (s < 0) sidewall.rotation.y = Math.PI;
      const bead = mesh(new THREE.TorusGeometry(r * .72, .013, 6, 48), rubber, wheel); bead.position.z = s * tireWidth / 2;
    }
    const treadGeometry = new THREE.BoxGeometry(.043, .010, .061);
    const tread = new THREE.InstancedMesh(treadGeometry, rubber, 144); tread.castShadow = true; wheel.add(tread);
    const dummy = new THREE.Object3D();
    for (let i = 0; i < 48; i++) for (let j = 0; j < 3; j++) {
      const a = (i + (j % 2) * .42) * Math.PI * 2 / 48;
      dummy.position.set(Math.sin(a) * (r + .003), Math.cos(a) * (r + .003), (j - 1) * .066); dummy.rotation.set(0, 0, -a); dummy.updateMatrix(); tread.setMatrixAt(i * 3 + j, dummy.matrix);
    }
    const disc = mesh(new THREE.CylinderGeometry(r * .61, r * .61, .025, 48), brake, wheel); disc.rotation.x = Math.PI / 2; disc.position.z = face * .63;
    const barrel = mesh(new THREE.TorusGeometry(r * .72, .018, 8, 48), chrome, wheel); barrel.position.z = face;
    const darkBarrel = mesh(new THREE.CylinderGeometry(r * .73, r * .73, .06, 48, 1, true), trim, wheel); darkBarrel.rotation.x = Math.PI / 2; darkBarrel.position.z = face * .7;
    for (let i = 0; i < 5; i++) for (const offset of [-.12, .12]) {
      const a = i * Math.PI * 2 / 5 + offset;
      const spoke = rounded(.033, r * .62, .037, .009, chrome, v(Math.sin(a) * r * .38, Math.cos(a) * r * .38, face), wheel); spoke.rotation.z = -a;
    }
    const hub = mesh(new THREE.CylinderGeometry(.058, .058, .035, 20), chrome, wheel); hub.rotation.x = Math.PI / 2; hub.position.z = face + side * .012;
    for (let i = 0; i < 5; i++) {
      const a = i * Math.PI * 2 / 5, bolt = mesh(new THREE.SphereGeometry(.011, 6, 5), trim, wheel); bolt.position.set(Math.sin(a) * .039, Math.cos(a) * .039, face + side * .034);
    }
    rounded(.06, .15, .045, .015, trim, v(-r * .45, 0, face * .76), wheel);
  }
  // Interior is modeled even when obscured by the roof.
  const seatBaseY = spec.belt - .41;
  // Seats stay inboard of the wheel wells on cab-forward bodies.
  for (const x of [spec.glassFront + .77, Math.min(spec.glassRear - .49, .85)]) for (const side of [-1, 1]) {
    const z = side * width * .40;
    rounded(.48, .13, .46, .055, seatMaterial, v(x, seatBaseY, z), interior);
    const back = rounded(.13, .53, .47, .065, seatMaterial, v(x + .20, seatBaseY + .27, z), interior); back.rotation.z = .14;
    rounded(.10, .17, .26, .041, seatMaterial, v(x + .23, seatBaseY + .61, z), interior);
    for (const zs of [-.17, .17]) rounded(.105, .44, .07, .03, seatMaterial, v(x + .12, seatBaseY + .29, z + zs), interior);
  }
  rounded(.91, .18, .20, .04, trim, v(.01, seatBaseY - .02, 0), interior);
  rounded(.06, .16, .045, .018, chrome, v(-.14, seatBaseY + .11, 0), interior);
  rounded(.28, .18, spec.width * .75, .06, trim, v(spec.glassFront + .17, spec.belt - .08, 0), interior);
  const cluster = new THREE.Group(); cluster.position.set(spec.glassFront + .36, spec.belt + .13, width * .43); group.add(cluster);
  const clusterCanvas = document.createElement("canvas"); clusterCanvas.width = 768; clusterCanvas.height = 320;
  const ctx = clusterCanvas.getContext("2d");
  if (ctx) {
    ctx.fillStyle = "#09121c"; ctx.fillRect(0, 0, 768, 320);
    for (const center of [163, 605]) {
      ctx.strokeStyle = "#596a7c"; ctx.lineWidth = 8; ctx.beginPath(); ctx.arc(center, 141, 105, .7, Math.PI * 2 + .3); ctx.stroke();
      for (let i = 0; i < 11; i++) {
        const a = .65 + i * 5 / 10; ctx.strokeStyle = "#b2c6d5"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(center + Math.cos(a) * 89, 141 + Math.sin(a) * 89); ctx.lineTo(center + Math.cos(a) * 99, 141 + Math.sin(a) * 99); ctx.stroke();
      }
      ctx.strokeStyle = "#24baf0"; ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(center, 141); ctx.lineTo(center - 61, 186); ctx.stroke();
    }
    ctx.textAlign = "center"; ctx.fillStyle = "#eaf6ff"; ctx.font = "500 47px system-ui"; ctx.fillText("0", 384, 101);
    ctx.font = "18px system-ui"; ctx.fillStyle = "#a4b7c8"; ctx.fillText("MPH", 384, 130);
    ctx.fillStyle = "#0d4549"; ctx.fillRect(258, 163, 252, 63);
    ctx.strokeStyle = "#5ef4cf"; ctx.lineWidth = 5; ctx.strokeRect(258, 163, 252, 63);
    ctx.fillStyle = "#eaf6ff"; ctx.font = "500 37px monospace"; ctx.fillText("42,680 mi", 384, 209);
    ctx.font = "16px system-ui"; ctx.fillStyle = "#92a8bb"; ctx.fillText("EXAMPLE ODOMETER", 384, 248);
    ctx.fillStyle = "#40dfba"; ctx.font = "22px system-ui"; ctx.fillText("P", 384, 287);
  }
  const clusterTexture = new THREE.CanvasTexture(clusterCanvas); clusterTexture.colorSpace = THREE.SRGBColorSpace; textures.push(clusterTexture);
  const clusterMaterial = new THREE.MeshBasicMaterial({ map: clusterTexture }); materials.push(clusterMaterial);
  rounded(.058, .29, .65, .04, trim, v(0, 0, 0), cluster);
  const display = mesh(new THREE.PlaneGeometry(.59, .246), clusterMaterial, cluster); display.rotation.y = Math.PI / 2; display.position.x = .035;
  const steering = new THREE.Group(); steering.position.set(spec.glassFront + .61, spec.belt + .025, width * .43); steering.rotation.z = -.24; interior.add(steering);
  const rim = mesh(new THREE.TorusGeometry(.16, .017, 10, 36), trim, steering); rim.rotation.y = Math.PI / 2;
  rounded(.035, .075, .10, .024, trim, v(0, 0, 0), steering);
  for (const side of [-1, 1]) line([v(0, 0, 0), v(0, -.045, side * .13)], trim, .021, steering);
  line([v(0, -.03, 0), v(0, -.15, 0)], trim, .022, steering);
  // Underhood compartment: an inset bay, cast engine cover, hoses and fluid caps.
  const engine = new THREE.Group(); group.add(engine);
  const engineX = (spec.glassFront - half) / 2;
  rounded(Math.max(.5, spec.glassFront + half - .1), .15, spec.width * .75, .04, trim, v(engineX, spec.belt - .23, 0), engine);
  rounded(.58, .14, .66, .045, trim, v(engineX + .07, spec.belt - .09, -.03), engine);
  for (let i = -3; i <= 3; i++) rounded(.35, .018, .025, .005, chrome, v(engineX + .07, spec.belt - .011, i * .066), engine);
  rounded(.29, .17, .30, .025, rubber, v(engineX - .05, spec.belt - .1, -width * .62), engine);
  const capMaterial = new THREE.MeshStandardMaterial({ color: 0xcbb568, metalness: .3, roughness: .5 }); materials.push(capMaterial);
  const cap = mesh(new THREE.CylinderGeometry(.055, .055, .034, 16), capMaterial, engine); cap.position.set(engineX + .16, spec.belt - .002, width * .55);
  for (const side of [-1, 1]) line([v(engineX - .31, spec.belt - .14, side * .2), v(engineX - .26, spec.belt - .035, side * .39), v(engineX + .22, spec.belt - .14, side * .49)], rubber, .034, engine);

  function setTarget(target: string) {
    const key = target.replace(/^panel_/, "");
    // The actual doorway, seats, wheel and dashboard remain together. The
    // instructional mileage is explicitly labeled, never customer vehicle data.
    shell.visible = true;
    interior.visible = true;
    cluster.visible = target === "odometer" || target === "interior" || !!spec.open;
    doorLining.visible = target === "odometer" || target === "interior" || target === "vin";
    vinMarker.visible = target === "vin";
    engine.visible = target === "engine_bay";
    highlights.forEach((objects, part) => objects.forEach(object => { object.visible = part === key; }));
  }
  return { group, shell, hood, driverDoor, cluster, spec, highlights, materials, textures, setTarget };
}

type View = { position: THREE.Vector3; look: THREE.Vector3; fov: number };
function viewFor(spec: Spec, target: string): View {
  const side = target.includes("right") || target === "passenger" || /corner_[fr]r$/.test(target) ? -1 : 1;
  const d = spec.length * 1.23, y = spec.height * 1.53, look = v(0, spec.height * .47, 0);
  let position = v(-d * .8, y, d * .77), fov = 34;
  if (target === "front") position = v(-d * 1.03, spec.height * 1.1, d * .20);
  else if (target === "rear") position = v(d * 1.03, spec.height * 1.08, -d * .20);
  else if (target === "driver" || target === "passenger") position = v(-d * .20, spec.height * 1.03, side * d * 1.1);
  else if (target.startsWith("corner_")) position = v((target.includes("corner_f") ? -1 : 1) * d * .81, y, side * d * .84);
  else if (target === "roof" || target === "panel_roof") { position = v(-d * .31, d * 1.13, d * .26); look.y = spec.belt; }
  else if (target === "engine_bay") { position = v(-spec.length * .77, spec.height * 2.2, spec.width * 1.09); look.set((spec.glassFront - spec.length / 2) / 2, spec.belt, 0); fov = 38; }
  else if (target === "interior") { position = v(spec.glassFront + 1.25, spec.belt + .50, spec.width * 1.55); look.set(spec.glassFront + .48, spec.belt - .08, 0); fov = 44; }
  else if (target === "odometer") { position = v(spec.glassFront + 1.12, Math.min(spec.belt + .42, spec.height - .07), spec.width * .44); look.set(spec.glassFront + .36, spec.belt + .095, spec.width * .215); fov = 49; }
  else if (target === "vin") {
    const marker = vinDoorJambPoint(spec);
    // Stand forward of the pillar, outside the sill, looking back at the latch-side jamb.
    position = marker.clone().add(v(-.62, .30, 1.18));
    look.copy(marker); fov = 36;
  }
  else if (target === "tire_tread") { position = v(spec.frontAxle - .92, spec.radius + .76, spec.width * .5 + 1.05); look.set(spec.frontAxle, spec.radius + .08, spec.width * .46); fov = 39; }
  else if (target.startsWith("panel_")) {
    const panel = target.slice(6), close = spec.length * .84;
    if (["hood", "windshield"].includes(panel)) { position = v(-close, spec.height * 2.3, close * .46); look.set(spec.glassFront - .5, spec.belt, 0); }
    else if (["front_bumper", "grille", "headlamps"].includes(panel)) { position = v(-close - 1, spec.belt + .7, close * .44); look.set(-spec.length * .36, spec.belt * .6, 0); }
    else if (["rear_bumper", "trunk", "tail_lamps"].includes(panel)) { position = v(close + .6, spec.height * 1.7, -close * .5); look.set(spec.length * .32, spec.belt * .8, 0); }
    else {
      const x = panel.startsWith("fender") ? spec.frontAxle : panel.startsWith("quarter") ? spec.rearAxle : panel.startsWith("rear_door") ? .7 : panel === "mirrors" ? spec.glassFront + .12 : -.3;
      position = v(x - 1.45, spec.height * 1.25, side * spec.width * 2.5); look.set(x, spec.belt * .73, 0);
    }
  }
  return { position, look, fov };
}

/** The VIN camera and unnumbered label share one representative door-jamb point. */
export function vinCameraView(body: string) {
  const spec = SPECS[normalBody(body)];
  return { marker: vinDoorJambPoint(spec), view: viewFor(spec, "vin") };
}

export function createVehicleScene(container: HTMLElement, options: { body: string; target: string; onError?: () => void }): VehicleScene {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "low-power", preserveDrawingBuffer: true });
  try { return initializeVehicleScene(renderer, container, options); }
  catch (error) { renderer.dispose(); renderer.forceContextLoss(); throw error; }
}

function initializeVehicleScene(renderer: THREE.WebGLRenderer, container: HTMLElement, options: { body: string; target: string; onError?: () => void }): VehicleScene {
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.03;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.style.cssText = "display:block;width:100%;height:100%;touch-action:pan-y";
  renderer.domElement.setAttribute("aria-hidden", "true");
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0xf5f8fa); scene.fog = new THREE.Fog(0xf5f8fa, 12, 38);
  const camera = new THREE.PerspectiveCamera(34, 1, .04, 70);
  const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment();
  const environment = pmrem.fromScene(room, .035); scene.environment = environment.texture; scene.environmentIntensity = .7;
  room.dispose(); pmrem.dispose();
  const ambient = new THREE.HemisphereLight(0xe6f3ff, 0x8495a1, 1.25); scene.add(ambient);
  const key = new THREE.DirectionalLight(0xfffaf5, 1.6); key.position.set(-3.5, 7, 4.5); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.camera.left = -4; key.shadow.camera.right = 4; key.shadow.camera.top = 4; key.shadow.camera.bottom = -4; key.shadow.normalBias = .025; key.shadow.bias = -.0001; key.shadow.radius = 4; scene.add(key);
  const edge = new THREE.DirectionalLight(0xdbeeff, .85); edge.position.set(3, 4, -5); scene.add(edge);
  const floorMaterial = new THREE.MeshStandardMaterial({ color: 0xf5f8fa, roughness: 1, metalness: 0 });
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), floorMaterial); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; floor.position.y = -.005; scene.add(floor);
  let body = normalBody(options.body), target = options.target, vehicle = buildVehicle(SPECS[body]); scene.add(vehicle.group);
  vehicle.setTarget(target);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const inside = () => target === "odometer" || target === "interior" || target === "vin";
  const entranceView = (): View => ({ position: v(vehicle.spec.glassFront + 2.1, vehicle.spec.height + .55, vehicle.spec.width * 2.4), look: v(vehicle.spec.glassFront + .5, vehicle.spec.belt, .1), fov: 38 });
  let entering = inside() && !reduced.matches, entranceTime = 0;
  let goal = entering ? entranceView() : viewFor(vehicle.spec, target);
  let displayedFov = goal.fov;
  const look = goal.look.clone(); camera.position.copy(goal.position); camera.fov = goal.fov; camera.lookAt(look);
  let disposed = false, lost = false, frame = 0, previous = 0, active = !document.hidden, intersecting = true, transition = true;
  let width = 1, height = 1;
  const applyAspect = () => {
    camera.aspect = width / height;
    // Preserve horizontal framing in a narrow portrait container.
    camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(displayedFov / 2)) / Math.min(1, camera.aspect / 1.52)));
    camera.updateProjectionMatrix();
  };
  function render() {
    if (disposed || lost) return;
    try { renderer.render(scene, camera); } catch { lost = true; options.onError?.(); }
  }
  function tick(now: number) {
    frame = 0;
    if (disposed || lost || !active || !intersecting) return;
    const dt = Math.min((now - previous) / 1000 || .016, .05); previous = now;
    if (entering) {
      entranceTime += dt;
      if (reduced.matches || entranceTime >= 1.6) { entering = false; goal = viewFor(vehicle.spec, target); applyAspect(); }
    }
    const t = reduced.matches ? 1 : 1 - Math.exp(-dt * (inside() ? 2.7 : 6.5));
    displayedFov = THREE.MathUtils.lerp(displayedFov, goal.fov, t); applyAspect();
    const currentOrbit = new THREE.Spherical().setFromVector3(camera.position.clone().sub(look));
    const goalOrbit = new THREE.Spherical().setFromVector3(goal.position.clone().sub(goal.look));
    const turn = THREE.MathUtils.euclideanModulo(goalOrbit.theta - currentOrbit.theta + Math.PI, Math.PI * 2) - Math.PI;
    currentOrbit.theta += turn * t;
    currentOrbit.phi = THREE.MathUtils.lerp(currentOrbit.phi, goalOrbit.phi, t);
    currentOrbit.radius = THREE.MathUtils.lerp(currentOrbit.radius, goalOrbit.radius, t);
    look.lerp(goal.look, t); camera.position.setFromSpherical(currentOrbit).add(look); camera.lookAt(look);
    const hoodAngle = target === "engine_bay" ? -.98 : 0;
    vehicle.hood.rotation.z += (hoodAngle - vehicle.hood.rotation.z) * t;
    const doorAngle = inside() ? -1.3 : 0;
    vehicle.driverDoor.rotation.y += (doorAngle - vehicle.driverDoor.rotation.y) * t;
    transition = entering || Math.abs(displayedFov - goal.fov) > .01 || Math.abs(doorAngle - vehicle.driverDoor.rotation.y) > .001 || camera.position.distanceToSquared(goal.position) > .000008 || look.distanceToSquared(goal.look) > .000008 || Math.abs(hoodAngle - vehicle.hood.rotation.z) > .001;
    render();
    // Only animate view transitions. Static scenes and off-screen guides consume no RAF.
    if (transition && !reduced.matches) frame = requestAnimationFrame(tick);
  }
  function wake() {
    if (!disposed && !lost && active && intersecting && !frame) { previous = performance.now(); frame = requestAnimationFrame(tick); }
  }
  function resize() {
    if (disposed) return;
    const bounds = container.getBoundingClientRect(); width = Math.max(1, Math.round(bounds.width)); height = Math.max(1, Math.round(bounds.height));
    renderer.setSize(width, height, false); applyAspect(); wake();
  }
  function visibility() { active = !document.hidden; if (!active && frame) { cancelAnimationFrame(frame); frame = 0; } else wake(); }
  function motion() { transition = true; wake(); }
  function contextLost(event: Event) { event.preventDefault(); if (disposed || lost) return; lost = true; if (frame) cancelAnimationFrame(frame); frame = 0; options.onError?.(); }
  const initialBounds = container.getBoundingClientRect();
  width = Math.max(1, Math.round(initialBounds.width)); height = Math.max(1, Math.round(initialBounds.height));
  renderer.setSize(width, height, false); applyAspect();
  vehicle.hood.rotation.z = target === "engine_bay" ? -.98 : 0;
  vehicle.driverDoor.rotation.y = inside() && reduced.matches ? -1.3 : 0;
  try { renderer.render(scene, camera); }
  catch (error) {
    freeVehicle(vehicle); floor.geometry.dispose(); floorMaterial.dispose(); environment.dispose(); key.shadow.dispose();
    throw error;
  }
  const resizeObserver = new ResizeObserver(resize); resizeObserver.observe(container);
  const intersectionObserver = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver(entries => {
    intersecting = entries[0]?.isIntersecting ?? true;
    if (!intersecting && frame) { cancelAnimationFrame(frame); frame = 0; } else wake();
  }, { rootMargin: "40px" }) : null;
  intersectionObserver?.observe(container);
  document.addEventListener("visibilitychange", visibility); reduced.addEventListener("change", motion); renderer.domElement.addEventListener("webglcontextlost", contextLost);
  container.appendChild(renderer.domElement); resize();
  function freeVehicle(old: ReturnType<typeof buildVehicle>) {
    const geometries = new Set<THREE.BufferGeometry>(); old.group.traverse(object => { if (object instanceof THREE.Mesh) geometries.add(object.geometry); if (object instanceof THREE.InstancedMesh) object.dispose(); }); geometries.forEach(geometry => geometry.dispose());
    old.materials.forEach(material => material.dispose()); old.textures.forEach(texture => texture.dispose()); scene.remove(old.group);
  }
  return {
    setView(nextBody, nextTarget) {
      if (disposed || lost) return;
      const key = normalBody(nextBody);
      if (key !== body) { freeVehicle(vehicle); body = key; vehicle = buildVehicle(SPECS[body]); scene.add(vehicle.group); }
      const enteringCabin = (nextTarget === "odometer" || nextTarget === "interior" || nextTarget === "vin") && !inside();
      target = nextTarget; vehicle.setTarget(target);
      entering = enteringCabin && !reduced.matches; entranceTime = 0;
      goal = entering ? entranceView() : viewFor(vehicle.spec, target); applyAspect(); transition = true; wake();
    },
    snapshot() {
      if (disposed || lost) return "";
      render(); return renderer.domElement.toDataURL("image/png");
    },
    dispose() {
      if (disposed) return; disposed = true; if (frame) cancelAnimationFrame(frame);
      resizeObserver.disconnect(); intersectionObserver?.disconnect(); document.removeEventListener("visibilitychange", visibility); reduced.removeEventListener("change", motion); renderer.domElement.removeEventListener("webglcontextlost", contextLost);
      freeVehicle(vehicle); floor.geometry.dispose(); floorMaterial.dispose(); environment.dispose(); key.shadow.dispose(); renderer.renderLists.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove();
    },
  };
}
