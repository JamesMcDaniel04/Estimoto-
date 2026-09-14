import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Camera, Check, X } from "lucide-react";
import { BODY_STYLES, bodyLabel, bodyStyleFor, VehicleGuide } from "./VehicleGuide";
import { HAIL_AREAS, type PhotoStep } from "./template";

type Guidance = { ready: boolean; instruction: string; available?: boolean };
const AUTO_CAPTURE_INTERVAL_MS = 12_000;

function waitForSteadyFrame(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const cancel = () => { window.clearTimeout(timer); reject(new DOMException("Capture paused", "AbortError")); };
    const timer = window.setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, 1000);
    if (signal.aborted) cancel();
    else signal.addEventListener("abort", cancel, { once: true });
  });
}
type Props = {
  steps: PhotoStep[];
  uploaded: Record<string, boolean>;
  body: string;
  onBodyChange: (value: string) => void;
  checkFrame: (file: File, key: string, body: string, signal: AbortSignal) => Promise<Guidance>;
  onCapture: (key: string, panel: string, file: File) => Promise<boolean>;
  onClose: () => void;
  brandName?: string;
  renderAssist?: (context: { capture_key: string; body_style: string }, disabled: boolean) => ReactNode;
  onComplete?: () => void;
  completing?: boolean;
  error?: string | null;
  needsDamagePanel?: boolean;
  onDamagePanel?: (panel: string) => void;
};

async function snapshot(video: HTMLVideoElement, key: string): Promise<File> {
  if (!video.videoWidth || !video.videoHeight) throw new Error("Camera is still starting. Try again in a moment.");
  const canvas = document.createElement("canvas");
  // Match object-fit: cover. The AI and saved evidence must see the same
  // framing the customer aligned, including on portrait phone cameras.
  const bounds = video.getBoundingClientRect();
  const aspect = bounds.width > 0 && bounds.height > 0 ? bounds.width / bounds.height : video.videoWidth / video.videoHeight;
  const sourceWidth = Math.min(video.videoWidth, video.videoHeight * aspect);
  const sourceHeight = Math.min(video.videoHeight, video.videoWidth / aspect);
  const sourceX = (video.videoWidth - sourceWidth) / 2;
  const sourceY = (video.videoHeight - sourceHeight) / 2;
  const scale = Math.min(1, 1920 / Math.max(sourceWidth, sourceHeight));
  canvas.width = Math.round(sourceWidth * scale);
  canvas.height = Math.round(sourceHeight * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser cannot capture a frame. Use the photo upload option.");
  context.drawImage(video, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
  if (!blob) throw new Error("Could not capture this frame. Try the photo upload option.");
  return new File([blob], `${key}.jpg`, { type: "image/jpeg" });
}

export default function GuidedCamera({ steps, uploaded, body, onBodyChange, checkFrame, onCapture, onClose, brandName = "Estimoto", renderAssist, onComplete, completing, error, needsDamagePanel, onDamagePanel }: Props) {
  const [index, setIndex] = useState(() => Math.max(0, steps.findIndex((step) => !uploaded[step.key])));
  const [saved, setSaved] = useState<Record<string, boolean>>({ ...uploaded });
  const [skipped, setSkipped] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState(false);
  const [automatic, setAutomatic] = useState(true);
  const [busy, setBusy] = useState(false);
  const [savingFrame, setSavingFrame] = useState(false);
  const [paused, setPaused] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [retry, setRetry] = useState(false);
  const [capturedThisWalk, setCapturedThisWalk] = useState(false);
  const [cameraRun, setCameraRun] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const media = useRef<MediaStream | null>(null);
  const alive = useRef(false);
  const inflight = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const autoGeneration = useRef(0);
  const attempts = useRef<Record<string, number>>({});
  const pending = useRef<File | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const manualInput = useRef<HTMLInputElement>(null);
  const step = steps[index];
  const style = bodyStyleFor(body);
  const pauseAutomatic = () => {
    if (pending.current) return;
    autoGeneration.current += 1;
    abort.current?.abort();
    setAutomatic(false);
    setInstruction("Auto-capture paused. Choose your guide, then turn auto-capture back on or take a photo.");
  };
  useEffect(() => { autoGeneration.current += 1; abort.current?.abort(); }, [style, index]);
  const complete = steps.every((item) => saved[item.key] || (item.optional && skipped[item.key]));
  const required = steps.filter((item) => !item.optional);
  const requiredSaved = required.filter((item) => saved[item.key]).length;
  useEffect(() => { content.current?.scrollTo?.({ top: 0, behavior: "instant" }); }, [index, needsDamagePanel]);
  const skipOptional = () => {
    if (!step?.optional || inflight.current || pending.current) return;
    const nextSkipped = { ...skipped, [step.key]: true };
    setSkipped(nextSkipped);
    const next = steps.findIndex((item, candidate) => candidate > index && !saved[item.key] && !nextSkipped[item.key]);
    if (next >= 0) setIndex(next);
    setInstruction("");
  };

  const stop = useCallback(() => {
    generation.current += 1;
    abort.current?.abort();
    media.current?.getTracks().forEach((track) => track.stop());
    media.current = null;
  }, []);
  const close = useCallback(() => { stop(); onClose(); }, [onClose, stop]);

  useEffect(() => {
    const focus = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    return () => { document.body.style.overflow = overflow; focus?.focus(); };
  }, []);

  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    const openRun = generation.current;
    const hide = () => {
      if (document.hidden) { stop(); setPaused(true); setLoaded(false); }
    };
    document.addEventListener("visibilitychange", hide);
    const pageHide = () => { stop(); setPaused(true); setLoaded(false); };
    window.addEventListener("pagehide", pageHide);
    const open = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access is unavailable. Use the photo upload option below the guide.");
        const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } } });
        if (cancelled || document.hidden || generation.current !== openRun) { stream.getTracks().forEach((track) => track.stop()); return; }
        media.current = stream;
        if (video.current) { video.current.srcObject = stream; await video.current.play(); }
      } catch (error) {
        if (cancelled) return;
        stop();
        setCameraError(error instanceof Error && error.name !== "NotAllowedError" ? error.message : "Allow camera access in your browser, or close this guide and upload photos.");
      }
    };
    void open();
    return () => { cancelled = true; alive.current = false; stop(); document.removeEventListener("visibilitychange", hide); window.removeEventListener("pagehide", pageHide); };
  }, [cameraRun, stop]);

  // Session state can reconcile an upload while the camera is backgrounded.
  // Adopt that confirmed evidence before allowing another capture on resume.
  useEffect(() => {
    setSaved((previous) => {
      const additions = Object.keys(uploaded).filter((key) => uploaded[key] && !previous[key]);
      return additions.length ? { ...previous, ...uploaded } : previous;
    });
    if (step && uploaded[step.key]) {
      pending.current = null;
      setRetry(false);
      const next = steps.findIndex((item, candidate) => candidate > index && !uploaded[item.key] && !saved[item.key] && !skipped[item.key]);
      if (next >= 0) setIndex(next);
    }
  }, [uploaded, steps, index, step, saved, skipped]);

  const saveFrame = useCallback(async (file: File, run: number) => {
    if (!step?.panel) return;
    pending.current = file;
    setSavingFrame(true);
    setInstruction("Saving your photo…");
    let ok: boolean;
    try { ok = await onCapture(step.key, step.panel, file); }
    finally { if (alive.current) setSavingFrame(false); }
    if (!alive.current || document.hidden || generation.current !== run) return;
    if (!ok) {
      setAutomatic(false); setRetry(true);
      setInstruction("This photo has not been confirmed saved. Retry saving it before moving on.");
      return;
    }
    pending.current = null;
    setRetry(false);
    const nextSaved = { ...saved, [step.key]: true };
    setSaved(nextSaved);
    setCapturedThisWalk(true);
    const next = steps.findIndex((item, candidate) => candidate > index && !nextSaved[item.key] && !skipped[item.key]);
    if (next >= 0) { setIndex(next); setInstruction(`Photo saved. Move to ${steps[next].label.toLowerCase()}.`); }
    else { setInstruction("Required photos saved. Review them before submitting your estimate."); }
  }, [step, onCapture, saved, steps, index, skipped]);

  const capture = useCallback(async (auto: boolean) => {
    if (inflight.current || !loaded || paused || document.hidden || !media.current || complete || !video.current || !step) return;

    inflight.current = true; setBusy(true);
    const run = generation.current;
    const autoRun = autoGeneration.current;
    const isCurrent = () => alive.current && !document.hidden && !!media.current && generation.current === run && (!auto || autoGeneration.current === autoRun);
    try {
      let file = pending.current ?? await snapshot(video.current, step.key);
      if (!isCurrent()) return;
      if (auto) {
        const controller = new AbortController();
        abort.current = controller;
        const accepted = async (frame: File) => {
          const count = attempts.current[step.key] ?? 0;
          if (count >= 8) { setAutomatic(false); setInstruction("Auto-capture is paused. Follow the guide and tap Take photo now."); return false; }
          attempts.current[step.key] = count + 1;
          setInstruction("Checking framing, focus and lighting…");
          const result = await checkFrame(frame, step.key, style ?? "", controller.signal);
          if (!isCurrent()) return false;
          setInstruction(result.instruction);
          if (result.available === false) { setAutomatic(false); return false; }
          return result.ready === true;
        };
        if (!await accepted(file)) return;
        for (let seconds = 3; seconds > 0; seconds--) {
          setInstruction(`Hold steady · checking a fresh photo in ${seconds}…`);
          await waitForSteadyFrame(controller.signal);
          if (!isCurrent()) return;
        }
        file = await snapshot(video.current, step.key);
        if (!isCurrent() || !await accepted(file)) return;
      }
      await saveFrame(file, run);
    } catch (error) {
      if (!isCurrent()) return;
      setAutomatic(false);
      if (error instanceof Error && error.name === "PhotoRejected") {
        pending.current = null;
        setRetry(false);
      } else if (pending.current) setRetry(true);
      setInstruction(error instanceof Error ? error.message : "Automatic guidance is unavailable. Take a photo using the guide.");
    } finally {
      inflight.current = false;
      if (alive.current) setBusy(false);
    }
  }, [loaded, paused, complete, step, style, checkFrame, saveFrame]);

  const uploadManually = async (file: File | null) => {
    if (!file || inflight.current || complete || !step) return;
    if (!(["image/jpeg", "image/png", "image/webp"].includes(file.type)) || file.size > 8 * 1024 * 1024) {
      setInstruction("Choose a JPEG, PNG or WebP photo smaller than 8 MB.");
      return;
    }
    inflight.current = true;
    setBusy(true);
    try { await saveFrame(file, generation.current); }
    catch (error) {
      setInstruction(error instanceof Error ? error.message : "The photo could not be saved. Try again.");
    } finally {
      inflight.current = false;
      if (alive.current) setBusy(false);
    }
  };

  useEffect(() => {
    if (!automatic || !loaded || paused || complete) return;
    const timer = window.setInterval(() => void capture(true), AUTO_CAPTURE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [automatic, loaded, paused, complete, style, capture]);

  useEffect(() => { if (complete && capturedThisWalk && !needsDamagePanel) onComplete?.(); }, [complete, capturedThisWalk, needsDamagePanel, onComplete]);

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label="Guided vehicle camera" className="customer-camera fixed inset-0 z-[100] text-slate-900" onKeyDown={(event) => {
      if (event.key === "Escape") close();
      if (event.key === "Tab") {
        const nodes = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex="0"]')).filter(node => node.getClientRects().length > 0);
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
      <div className="camera-shell">
        <header className="camera-header">
          <div className="journey-brand"><strong className="journey-wordmark" aria-label={brandName}>{brandName.toLowerCase()}</strong><span>Customer photos</span><button ref={closeButton} type="button" onClick={close} aria-label="Close camera" className="camera-close"><X /></button></div>
          <div className="camera-progress"><p>{complete ? needsDamagePanel ? "Damage close-up" : "Capture complete" : `Photo ${index + 1} of ${steps.length}`}</p><p>{required.length ? `${requiredSaved} of ${required.length} saved` : `${steps.filter(item => saved[item.key]).length} saved · optional`}</p></div>
          <div role="progressbar" aria-label="Photos saved" aria-valuenow={requiredSaved} aria-valuemin={0} aria-valuemax={Math.max(1, required.length)} className="camera-progress-track"><span style={{ width: `${required.length ? requiredSaved / required.length * 100 : 0}%` }} /></div>
        </header>
        <div ref={content} className="camera-content">
        <div className="camera-step-copy" key={step?.key}>
        <h2>{complete ? needsDamagePanel ? "One close-up of the damage" : "Photos saved" : step?.label === "Front of car" ? "Front of your vehicle" : step?.label === "Back of car" ? "Rear of your vehicle" : step?.label === "Driver side of car" ? "Driver side of your vehicle" : step?.label === "Passenger side of car" ? "Passenger side of your vehicle" : step?.label}</h2>
        {step?.optional && !complete && <p className="mt-1 px-5 text-sm font-semibold text-slate-500">Optional · skip if unavailable</p>}
        <p className="camera-step-hint">{complete ? needsDamagePanel ? "Choose a damaged panel for assessment. Your camera stays open." : "Your required photos are saved. Review your estimate before submitting." : step?.hint}</p>
        </div>
        <VehicleGuide className="capture-vehicle-guide" body={style ?? "sedan"} target={step?.key ?? "front"} />
        {complete && needsDamagePanel && <label className="m-5 text-lg font-semibold">Where are the dents?
          <select aria-label="Damaged panel for dent detection" className="mt-3 block w-full rounded-xl border border-slate-300 bg-white p-4 text-base" value="" onChange={(event) => onDamagePanel?.(event.target.value)}>
            <option value="">Choose a damaged panel</option>{HAIL_AREAS.map((area) => <option key={area.key} value={area.key}>{area.label}</option>)}
          </select>
        </label>}
        <div className="capture-viewfinder">
          <video ref={video} autoPlay playsInline muted aria-label="Live camera" onLoadedData={() => setLoaded(true)} className="capture-live-video" />
          <p aria-live="polite" className="capture-coaching">{instruction || "Keep the whole view in frame. Step back if an edge is cut off, then hold steady."}</p>
          <div aria-hidden="true" className="pointer-events-none absolute inset-[9%] rounded-xl border-2 border-dashed border-white/60" />
          {!loaded && !cameraError && !paused && <p className="absolute inset-0 grid place-items-center bg-black/70 text-white">Opening camera…</p>}
        </div>
        {cameraError && <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{cameraError}</p>}
        {paused && <button type="button" className="rounded-xl bg-brand p-3 font-semibold text-white" onClick={() => { setPaused(false); setCameraError(null); setCameraRun((value) => value + 1); }}>Resume camera</button>}
        {error && <p role="alert" className="mx-5 rounded-xl bg-amber-50 p-4 text-base text-amber-900">{error}</p>}
        </div>
        <div className="capture-actions">
        <div className="capture-settings-row"><label className="camera-body-select"><span className="sr-only">Vehicle body</span>
            <select aria-label="Guide body style" disabled={savingFrame || retry} value={style ?? ""} onFocus={pauseAutomatic} onPointerDown={pauseAutomatic} onChange={(event) => { if (!pending.current) { pauseAutomatic(); onBodyChange(event.target.value); } }}>
              {!style && <option value="">Sedan (default)</option>}{BODY_STYLES.map((item) => <option key={item} value={item}>{bodyLabel(item)}</option>)}
            </select>
          </label>
          <label className="camera-auto-toggle"><input type="checkbox" checked={automatic} disabled={savingFrame || retry} onChange={(event) => { if (!event.target.checked) pauseAutomatic(); else { setInstruction("Take your time positioning the camera. Auto-capture will check focus before saving."); setAutomatic(true); } }} />Auto-capture</label></div>
        {!complete && !cameraError && <>
          <button type="button" disabled={!loaded || busy || paused} onClick={() => void capture(false)} className="capture-shutter"><Camera className="h-5 w-5" />{busy ? "Checking / saving…" : retry ? "Retry saving photo" : "Take photo now"}</button>
        </>}
        {!complete && <><input ref={manualInput} className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" aria-label="Upload photo for current view" onChange={(event) => { const file = event.currentTarget.files?.[0] ?? null; event.currentTarget.value = ""; void uploadManually(file); }} /><button type="button" disabled={busy} className="mt-2 rounded-full border border-slate-300 p-3 text-sm font-semibold text-brand disabled:opacity-50" onClick={() => manualInput.current?.click()}>Upload a photo instead</button></>}
        {!complete && step?.optional && <button type="button" disabled={busy || retry} onClick={skipOptional} className="mt-2 rounded-full border border-slate-300 p-3 text-sm font-semibold text-brand disabled:opacity-50">Skip optional photo</button>}
        {complete && !needsDamagePanel && <button type="button" disabled={completing} onClick={onComplete ?? close} className="flex w-full items-center justify-center gap-2 rounded-full bg-brand p-4 text-base font-semibold text-white"><Check />{completing ? "Preparing your estimate…" : onComplete ? "Continue to estimate" : "Done"}</button>}
        <p className="capture-footnote">{complete ? "Photo capture is complete. Review before submitting." : "Driver side is the side with the steering wheel."}</p>
        {renderAssist && <div className="capture-footer-tools">{renderAssist({ capture_key: step?.key ?? "front", body_style: style ?? "" }, paused || !loaded || !!cameraError)}</div>}
        </div>
      </div>
    </div>, document.body,
  );
}
