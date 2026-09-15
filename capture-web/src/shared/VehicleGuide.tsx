import { useEffect, useRef, useState } from "react";
import { SELF_PAY_STEPS, SUPPORTED_VEHICLE_STEPS } from "./template";
import type { createVehicleScene } from "./vehicleScene";

export const BODY_STYLES = ["sedan", "coupe", "hatchback", "wagon", "suv", "pickup", "van", "convertible"] as const;
export type BodyStyle = typeof BODY_STYLES[number];
export const bodyLabel = (body: BodyStyle) => body === "suv" ? "SUV / crossover" : body.charAt(0).toUpperCase() + body.slice(1);

export function bodyStyleFor(value: string | null | undefined): BodyStyle | null {
  const body = (value ?? "").toLowerCase();
  if (/pickup|pick.up|truck/.test(body)) return "pickup";
  if (/minivan|mini.van|van/.test(body)) return "van";
  if (/sport.utility|suv|crossover|multipurpose|multi.purpose|mpv/.test(body)) return "suv";
  if (/convertible|cabrio|roadster/.test(body)) return "convertible";
  if (/wagon|estate/.test(body)) return "wagon";
  if (/hatchback|hatch|liftback/.test(body)) return "hatchback";
  if (/coupe|coupé/.test(body)) return "coupe";
  if (/sedan|saloon/.test(body)) return "sedan";
  return null;
}

// Side-profile framing guides. Fixed vehicle proportions are intentional: the
// outline indicates body category, never a claimed exact model reconstruction.
const outlines: Record<BodyStyle, string> = {
  sedan: "M28 120 L36 96 L98 86 L139 50 Q145 45 158 45 L224 45 Q237 46 246 56 L278 85 L328 96 L335 120 Z",
  coupe: "M28 120 L37 97 L112 86 L157 50 Q166 43 190 43 Q226 43 249 65 L279 89 L328 99 L335 120 Z",
  hatchback: "M28 120 L35 95 L98 84 L136 44 Q141 39 158 39 L242 39 Q255 41 260 55 L293 107 L290 120 Z",
  wagon: "M28 120 L35 96 L97 86 L139 47 L293 47 L321 86 L328 120 Z",
  suv: "M25 120 L30 82 L95 73 L124 30 Q131 25 146 25 L285 25 L319 70 L331 120 Z",
  pickup: "M25 120 L30 83 L92 73 L122 28 L205 28 L221 80 L326 80 L331 120 Z",
  van: "M26 120 L31 70 L80 22 Q86 17 98 17 L302 17 Q315 20 319 35 L330 120 Z",
  convertible: "M28 120 L36 97 L105 86 L142 47 L150 47 L146 85 L239 85 L258 75 L280 87 L330 98 L335 120 Z",
};

export function VehicleGuide({ body, target: requestedTarget, className = "h-44" }: { body: BodyStyle; target: string; className?: string }) {
  const target = requestedTarget.replace(/^hail_(?:close|raking)_/, "panel_");
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<ReturnType<typeof createVehicleScene> | null>(null);
  const latest = useRef({ body, target });
  useEffect(() => { latest.current = { body, target }; }, [body, target]);
  const [rendered, setRendered] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!host.current || typeof WebGL2RenderingContext === "undefined") return;
    void import("./vehicleScene").then(({ createVehicleScene: create }) => {
      if (cancelled || !host.current) return;
      try {
        scene.current = create(host.current, {
          ...latest.current,
          onError: () => { if (!cancelled) setRendered(false); },
        });
        setRendered(true);
      } catch { setRendered(false); }
    }).catch(() => { if (!cancelled) setRendered(false); });
    return () => {
      cancelled = true;
      scene.current?.dispose();
      scene.current = null;
    };
  }, []);
  useEffect(() => { scene.current?.setView(body, target); }, [body, target]);
  const label = [...SUPPORTED_VEHICLE_STEPS, ...SELF_PAY_STEPS].find((step) => step.key === target)?.label ?? "Requested area";
  return (
    <div className={`relative w-full ${className}`} role="img" aria-label={`${bodyLabel(body)} guide: ${label}`}>
      <div ref={host} aria-hidden="true" className={`absolute inset-0 ${rendered ? "" : "invisible"}`} />
      {!rendered && <div className="flex h-full items-center" aria-hidden="true"><VehicleGuideFallback body={body} target={target} /></div>}
      {rendered && <span className="absolute bottom-1 left-0 right-0 mx-auto w-fit max-w-[calc(100%-1rem)] rounded-md bg-white/90 px-2 py-0.5 text-center text-xs text-slate-700">{target === "odometer" ? "Mileage display · behind the steering wheel" : target === "vin" ? "VIN label · door jamb beside the driver’s seat" : target === "interior" ? "Driver’s doorway · seats and dashboard" : `${bodyLabel(body)} · ${label}`}</span>}
    </div>
  );
}

function VehicleGuideFallback({ body, target }: { body: BodyStyle; target: string }) {
  const front = target === "front" || target === "engine_bay" || target.includes("corner_f");
  const rear = target === "rear" || target.includes("corner_r");
  const panel = target.replace(/^panel_/, "");
  const label = [...SUPPORTED_VEHICLE_STEPS, ...SELF_PAY_STEPS].find((step) => step.key === target)?.label ?? "Requested area";
  if (target === "odometer" || target === "interior" || target === "vin") return (
    <svg viewBox="0 0 360 162" role="img" aria-label={`Open driver’s door: ${label}`} className="h-full w-full">
      <path d="M81 128 V53 Q91 20 122 17 H283 Q314 23 317 54 V133" fill="#dce7ed" stroke="#91aaba" strokeWidth="4" />
      <path d="M112 54 L130 28 H272 L293 54 Z" fill="#91afc1" />
      <path d="M104 63 Q189 50 301 66 L295 89 H109 Z" fill="#334756" />
      <rect x="119" y="60" width="58" height="24" rx="5" fill="#142939" />
      <rect x="131" y="65" width="35" height="11" rx="2" fill="#bff7e5" />
      <circle cx="150" cy="88" r="22" fill="none" stroke="#253441" strokeWidth="7" />
      <path d="M132 91 H168 M150 88 V109" stroke="#253441" strokeWidth="5" />
      <path d="M95 141 L105 117 Q128 107 159 117 L170 141 M227 141 L238 111 Q258 97 282 111 L296 141" fill="#627080" stroke="#405163" strokeWidth="3" />
      <path d="M101 53 L40 76 L43 136 L100 125 Z" fill="#a9c4d2" stroke="#7594a6" strokeWidth="3" />
      <path d="M92 64 L49 81 L51 102 L92 91 Z" fill="#3c5c71" />
      <path d="M55 117 L84 109" stroke="#405b6c" strokeWidth="5" strokeLinecap="round" />
      {target === "odometer" ? <g><rect x="123" y="60" width="52" height="23" rx="5" fill="none" stroke="#0c9d83" strokeWidth="3" /><path d="M192 37 L168 59 M168 59 L170 50 M168 59 L178 57" fill="none" stroke="#087b69" strokeWidth="3" /><text x="194" y="34" fill="#125b52" fontSize="12">Mileage display</text></g> : null}
      {target === "vin" ? <g><rect x="303" y="92" width="23" height="13" rx="2" fill="#fff" stroke="#0c9d83" strokeWidth="2" /><path d="M310 96h10m-10 3h10m-10 3h8" stroke="#334155" strokeWidth="1" /><path d="M262 44L306 91" stroke="#087b69" strokeWidth="3" /><text x="258" y="40" textAnchor="end" fill="#125b52" fontSize="12">VIN label · door jamb</text></g> : null}
      <text x="180" y="158" textAnchor="middle" fill="currentColor" fontSize="11">Open the driver’s door · {target === "odometer" ? "look behind the steering wheel" : target === "vin" ? "find the VIN label on the jamb beside the seat" : "include the seats and dashboard"}</text>
    </svg>
  );
  const highlight = target === "roof" || target === "panel_roof" ? [130, 20, 130, 40]
    : target === "driver" || target === "passenger" ? [22, 20, 314, 126]
    : target === "tire_tread" ? [54, 100, 58, 48]
    : target === "odometer" ? [121, 66, 35, 28]
    : target === "interior" ? [122, 51, 120, 69]
    : panel === "hood" ? [29, 78, 84, 26]
    : panel.startsWith("fender_") ? [52, 85, 68, 46]
    : panel.startsWith("front_door_") ? [113, 69, 63, 62]
    : panel.startsWith("rear_door_") ? [178, 69, 61, 62]
    : panel.startsWith("quarter_") ? [242, 81, 72, 50]
    : panel === "trunk" ? [267, 78, 65, 32]
    : front ? [22, 65, 85, 67] : rear ? [259, 55, 76, 77] : [99, 63, 156, 70];
  return (
    <svg viewBox="0 0 360 162" role="img" aria-label={`${bodyLabel(body)} guide: ${label}`} className="h-full w-full">
      <path data-vehicle-outline d={outlines[body]} fill="#e2e8f0" stroke="#94a3b8" strokeWidth="3" strokeLinejoin="round" />
      <path d="M109 80 L145 51 L206 51 L206 80 Z" fill="#334155" opacity=".7" />
      {body === "pickup" ? <path d="M230 86 H317 V107 H230 Z" fill="#94a3b8" /> : <path d="M215 52 H237 L261 80 H215 Z" fill="#334155" opacity=".7" />}
      {[82, 280].map((x) => <g key={x}><circle cx={x} cy="123" r="23" fill="#0f172a" /><circle cx={x} cy="123" r="11" fill="#94a3b8" /></g>)}
      <rect x={highlight[0]} y={highlight[1]} width={highlight[2]} height={highlight[3]} rx="12" fill="#22d3ee" fillOpacity=".18" stroke="#22d3ee" strokeWidth="3" strokeDasharray="6 4" />
      <text x="180" y="159" textAnchor="middle" fill="currentColor" fontSize="11">{bodyLabel(body)} · {label}</text>
    </svg>
  );
}
