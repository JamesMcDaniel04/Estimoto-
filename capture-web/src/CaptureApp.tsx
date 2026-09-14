import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GuidedCamera from "./shared/GuidedCamera";
import { DAMAGE_AREAS, HAIL_AREAS, hailAreaSteps, requiredStepsFor, type PhotoStep } from "./shared/template";
import { CaptureRPC, encodedPhoto, RPCError } from "./rpc";

type Photo = { id: string; label: string; sha256: string; quality: "framing_checked" | "not_checked" };
type Suggestion = { photo_id: string; suggested_vin: string | null; confidence: number | null };
type CaptureState = { estimate_id: string; discipline: "pdr" | "collision"; vehicle: { year: number; make: string; model: string; vin: string }; photos: Photo[]; vin_suggestion: Suggestion | null };
type SaveResult = { id: string; label: string; quality: Photo["quality"]; warning?: string | null };
type Guidance = { ready: boolean; available: boolean; instruction: string };
type CaptureHostAPI = Pick<CaptureRPC, "request" | "ready" | "close">;
const operationIds = new WeakMap<File, string>();

function CaptureHelp({ keyName, rpc }: { keyName: string; rpc: CaptureHostAPI }) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  return <form className="capture-help" onSubmit={(event) => {
    event.preventDefault();
    if (!question.trim() || busy) return;
    setBusy(true);
    void rpc.request<{ reply: string }>("askCaptureHelp", { capture_key: keyName, question: question.trim().slice(0, 500) })
      .then((answer) => setReply(answer.reply)).catch(() => setReply("Capture help is unavailable. Follow the on-screen guide or use an existing photo."))
      .finally(() => setBusy(false));
  }}>
    <label htmlFor="capture-question">Ask Estibot about this photo</label>
    <div><input id="capture-question" value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} placeholder="How do I avoid glare?" /><button disabled={busy || !question.trim()}>Ask</button></div>
    {reply && <p role="status">{reply}</p>}
  </form>;
}

export function CaptureApp({ rpc }: { rpc: CaptureHostAPI }) {
  const [state, setState] = useState<CaptureState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [cameraSteps, setCameraSteps] = useState<PhotoStep[] | null>(null);
  const [bodyStyle, setBodyStyle] = useState("sedan");
  const [selectedPanel, setSelectedPanel] = useState("");
  const [vinInput, setVinInput] = useState("");
  const [working, setWorking] = useState(false);
  const [paused, setPaused] = useState(false);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    const next = await rpc.request<CaptureState>("captureState", {}, 12_000);
    if (!alive.current) return next;
    if (!next || !Array.isArray(next.photos) || !["pdr", "collision"].includes(next.discipline)) throw new Error("Capture state is unavailable.");
    setState(next);
    return next;
  }, []);

  useEffect(() => {
    alive.current = true;
    const pause = () => { setPaused(true); setCameraSteps(null); };
    const resume = () => { setPaused(false); void refresh().catch(() => setError("Refresh your garage and reopen capture.")); };
    window.addEventListener("capture:pause", pause);
    window.addEventListener("capture:resume", resume);
    try {
      rpc.ready();
      void refresh().catch((cause) => setError(cause instanceof Error ? cause.message : "Open capture from your Estimoto + garage."));
    } catch { setError("Open capture from your Estimoto + garage."); }
    return () => { alive.current = false; window.removeEventListener("capture:pause", pause); window.removeEventListener("capture:resume", resume); rpc.close(); };
  }, [refresh]);

  const saved = useMemo(() => Object.fromEntries((state?.photos ?? []).map((photo) => [photo.label, true])), [state]);
  const required = useMemo(() => requiredStepsFor(state?.discipline === "pdr" ? "hail" : "collision"), [state?.discipline]);
  const requiredCount = required.filter((step) => saved[step.key]).length;
  const paired = useMemo(() => HAIL_AREAS.some((area) => saved[`hail_close_${area.key}`] && saved[`hail_raking_${area.key}`]), [saved]);
  const legacyPanel = useMemo(() => HAIL_AREAS.some((area) => saved[`panel_${area.key}`]), [saved]);
  const needsDamagePanel = state?.discipline === "pdr" && !paired && !legacyPanel && !!cameraSteps && !cameraSteps.some((step) => step.key.startsWith("hail_") || step.key.startsWith("panel_"));
  const vinPhoto = state?.photos.find((photo) => photo.label === "vin");
  const currentSuggestion = vinPhoto && state?.vin_suggestion?.photo_id === vinPhoto.id ? state.vin_suggestion : null;

  const startRequired = () => {
    setError(null);
    setWarning(null);
    setCameraSteps(required);
  };

  const startPanel = () => {
    if (!state || !selectedPanel) return;
    const catalog = state.discipline === "pdr" ? HAIL_AREAS : DAMAGE_AREAS;
    if (!catalog.some((row) => row.key === selectedPanel)) return;
    setCameraSteps(state.discipline === "pdr" ? hailAreaSteps(selectedPanel) : [{ key: `panel_${selectedPanel}`, panel: selectedPanel,
      label: catalog.find((row) => row.key === selectedPanel)?.label ?? "Damaged panel", hint: "Fit the panel and surrounding edges in frame. Avoid glare and hold steady." }]);
    setError(null);
  };

  const checkFrame = useCallback(async (file: File, key: string, body: string, _signal: AbortSignal): Promise<Guidance> => {
    const photo = await encodedPhoto(file);
    return rpc.request<Guidance>("checkFrame", { capture_key: key, body_style: body || "sedan", photo }, 25_000);
  }, []);

  const saveFrame = useCallback(async (key: string, _panel: string, file: File) => {
    const operation = operationIds.get(file) ?? crypto.randomUUID();
    operationIds.set(file, operation);
    const photo = await encodedPhoto(file);
    let result: SaveResult;
    try { result = await rpc.request<SaveResult>("saveCapture", { capture_key: key, body_style: bodyStyle, operation_id: operation, photo }, 50_000); }
    catch (cause) {
      if (cause instanceof RPCError && cause.status === 422) {
        const rejected = new Error(cause.message);
        rejected.name = "PhotoRejected";
        throw rejected;
      }
      throw cause;
    }
    if (!result?.id || result.label !== key) throw new Error("Photo status is uncertain. Retry saving the same photo.");
    if (result.warning) setWarning(result.warning);
    await refresh();
    return true;
  }, [bodyStyle, refresh]);

  const recognizeVin = () => {
    if (!vinPhoto || working) return;
    setWorking(true);
    setError(null);
    void rpc.request("recognizeVin", { photo_id: vinPhoto.id }, 40_000)
      .then(() => refresh()).catch((cause) => setError(cause instanceof Error ? cause.message : "VIN recognition is unavailable."))
      .finally(() => setWorking(false));
  };

  const confirmVin = () => {
    if (!vinPhoto || !state || working) return;
    const vin = vinInput.trim().toUpperCase();
    if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) { setError("Enter the 17 VIN characters shown on the label."); return; }
    setWorking(true);
    setError(null);
    void rpc.request("confirmVin", { photo_id: vinPhoto.id, photo_sha256: vinPhoto.sha256,
      expected_vin: state.vehicle.vin ?? "", vin }, 30_000)
      .then(() => { setVinInput(""); return refresh(); })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "VIN confirmation failed. Review the photo and try again."))
      .finally(() => setWorking(false));
  };

  const close = () => { setCameraSteps(null); void rpc.request("close").catch(() => undefined); };

  if (error && !state) return <main className="capture-page"><h1>Vehicle photo capture</h1><p role="alert">{error}</p><p>Open this guide from your Estimoto + garage.</p></main>;
  if (!state) return <main className="capture-page"><h1>Vehicle photo capture</h1><p role="status">Loading your saved photo walk…</p></main>;
  const panelOptions = state.discipline === "pdr" ? HAIL_AREAS : DAMAGE_AREAS;
  return <main className="capture-page">
    <header><span className="capture-brand">estimoto +</span><button type="button" onClick={close}>Close</button></header>
    <h1>Photograph your vehicle</h1>
    <p>{state.vehicle.year} {state.vehicle.make} {state.vehicle.model}</p>
    <p>{requiredCount} of {required.length} required photos saved. This only saves evidence; submitting to a shop happens after review.</p>
    <button className="capture-primary" type="button" onClick={startRequired} disabled={paused}>{requiredCount === required.length ? "Review required photos" : "Open guided camera"}</button>
    {paused && <p role="status">Capture paused. Return to Estimoto + to resume.</p>}
    <ul className="capture-list">{required.map((step) => <li key={step.key}><span>{step.label}</span><strong>{saved[step.key] ? "Saved" : "Needed"}</strong></li>)}</ul>
    {state.photos.some((photo) => photo.quality === "not_checked") && <p className="capture-note">Some saved photos have not had framing checked. Review them before submitting.</p>}
    {warning && <p role="status">{warning}</p>}
    <section className="capture-panel"><h2>{state.discipline === "pdr" ? "Damaged PDR area" : "Additional damaged panel"}</h2>
      <p>{state.discipline === "pdr" ? "Add a close-up and an angled-light photo of the same damaged panel. The angled-light photo supports dent assessment." : "Add a close view of any damaged panel."}</p>
      <select aria-label="Damaged panel" value={selectedPanel} onChange={(event) => setSelectedPanel(event.target.value)}><option value="">Choose a panel</option>{panelOptions.map((row) => <option key={row.key} value={row.key}>{row.label}</option>)}</select>
      <button type="button" disabled={!selectedPanel || paused} onClick={startPanel}>Capture selected panel</button>
      {state.discipline === "pdr" && <p role="status">{paired || legacyPanel ? "Damage evidence saved" : "A matching close-up and angled-light pair is still needed."}</p>}
    </section>
    {vinPhoto && <section className="capture-panel"><h2>Confirm the door-jamb VIN</h2>
      <p>Your VIN photo is saved. Any OCR result is a suggestion until you compare it with the physical label and confirm it.</p>
      {currentSuggestion ? <p role="status">Suggested VIN: <strong>{currentSuggestion.suggested_vin ?? "No readable VIN found"}</strong></p> : <button type="button" disabled={working} onClick={recognizeVin}>Read VIN from saved photo</button>}
      <label htmlFor="confirmed-vin">VIN shown on the label</label><input id="confirmed-vin" maxLength={17} autoCapitalize="characters" value={vinInput} onChange={(event) => setVinInput(event.target.value.replace(/[^a-zA-Z0-9]/g, "").toUpperCase())} placeholder="Enter 17 characters" />
      <button type="button" disabled={working || vinInput.length !== 17} onClick={confirmVin}>Confirm this VIN for my vehicle</button>
      {state.vehicle.vin && <p>Saved vehicle VIN: {state.vehicle.vin}</p>}
    </section>}
    {error && <p role="alert">{error}</p>}
    {cameraSteps && !paused && <GuidedCamera steps={cameraSteps} uploaded={saved} body={bodyStyle} brandName="Estimoto +" onBodyChange={setBodyStyle}
      checkFrame={checkFrame} onCapture={saveFrame} onClose={() => setCameraSteps(null)} onComplete={() => setCameraSteps(null)}
      needsDamagePanel={needsDamagePanel}
      onDamagePanel={(panel) => setCameraSteps([...required, ...hailAreaSteps(panel)])}
      renderAssist={(context) => <CaptureHelp keyName={context.capture_key} rpc={rpc} />}
    />}
  </main>;
}
