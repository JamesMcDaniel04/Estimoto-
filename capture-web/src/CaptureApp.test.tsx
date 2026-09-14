import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { expect, it, vi } from "vitest";
import { CaptureApp } from "./CaptureApp";
import { RPCError, type CaptureRPC } from "./rpc";
import type { PhotoStep } from "./shared/template";

const camera = vi.hoisted(() => ({ save: null as null | ((key: string, panel: string, file: File) => Promise<boolean>) }));
vi.mock("./shared/GuidedCamera", () => ({ default: (props: {
  steps: PhotoStep[]; needsDamagePanel?: boolean; onDamagePanel?: (panel: string) => void;
  onCapture: (key: string, panel: string, file: File) => Promise<boolean>;
}) => { camera.save = props.onCapture; return <div data-testid="guided-camera">
  <span>{props.steps.map((step) => step.key).join(",")}</span>
  {props.needsDamagePanel && <button onClick={() => props.onDamagePanel?.("hood")}>Choose hood</button>}
</div>; } }));

function host(state: object) {
  const request = vi.fn(async (method: string) => {
    if (method === "captureState") return state;
    if (method === "confirmVin") return { confirmed: true };
    throw new Error("Unexpected method " + method);
  });
  return { api: { request, ready: vi.fn(), close: vi.fn() } as unknown as Pick<CaptureRPC, "request" | "ready" | "close">, request };
}

const vehicle = { year: 2020, make: "Example", model: "Car", vin: "" };

it("uses the exact nine shared required steps and preserves PDR close/raking pairs", async () => {
  const fake = host({ estimate_id: "draft", discipline: "pdr", vehicle, photos: [], vin_suggestion: null });
  render(<CaptureApp rpc={fake.api} />);
  await screen.findByText("0 of 9 required photos saved. This only saves evidence; submitting to a shop happens after review.");
  fireEvent.click(screen.getByRole("button", { name: "Open guided camera" }));
  expect(screen.getByTestId("guided-camera")).toHaveTextContent("odometer,vin,engine_bay,interior,tire_tread,front,driver,rear,passenger");
  fireEvent.click(screen.getByRole("button", { name: "Choose hood" }));
  expect(screen.getByTestId("guided-camera")).toHaveTextContent("hail_close_hood,hail_raking_hood");
  expect(screen.getByTestId("guided-camera")).not.toHaveTextContent("panel_hood");
  expect(fake.request).toHaveBeenCalledWith("captureState", {}, 12_000);
  expect(fake.request).not.toHaveBeenCalledWith("saveCapture", expect.anything(), expect.anything());
});

it("does not change a VIN from an OCR suggestion until explicit confirmation of its photo hash", async () => {
  const state = { estimate_id: "draft", discipline: "collision", vehicle, photos: [
    { id: "photo-1", label: "vin", sha256: "a".repeat(64), quality: "not_checked" }],
    vin_suggestion: { photo_id: "photo-1", suggested_vin: "1HGBH41JXMN109186", confidence: .99 } };
  const fake = host(state);
  render(<CaptureApp rpc={fake.api} />);
  await screen.findByText("Suggested VIN:", { exact: false });
  expect(fake.request.mock.calls.every(([method]) => method === "captureState")).toBe(true);
  fireEvent.change(screen.getByLabelText("VIN shown on the label"), { target: { value: "1HGBH41JXMN109186" } });
  fireEvent.click(screen.getByRole("button", { name: "Confirm this VIN for my vehicle" }));
  await waitFor(() => expect(fake.request).toHaveBeenCalledWith("confirmVin", {
    photo_id: "photo-1", photo_sha256: "a".repeat(64), expected_vin: "", vin: "1HGBH41JXMN109186",
  }, 30_000));
});

it("shows the owner-bound entry instruction when opened without a host", async () => {
  const fake = host({ estimate_id: "draft", discipline: "collision", vehicle, photos: [], vin_suggestion: null });
  (fake.api.ready as ReturnType<typeof vi.fn>).mockImplementation(() => { throw new Error("No host"); });
  render(<CaptureApp rpc={fake.api} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Open capture from your Estimoto + garage.");
  expect(fake.request).not.toHaveBeenCalled();
});

it("rejects a saved operation receipt superseded by a newer photo of the same step", async () => {
  const current = { estimate_id: "draft", discipline: "collision", vehicle, photos: [
    { id: "same-photo-row", label: "vin", sha256: "b".repeat(64), quality: "framing_checked" }], vin_suggestion: null };
  const request = vi.fn(async (method: string) => method === "captureState" ? current :
    method === "saveCapture" ? { id: "same-photo-row", label: "vin", sha256: "a".repeat(64), quality: "framing_checked" } : null);
  const view = render(<CaptureApp rpc={{ request, ready: vi.fn(), close: vi.fn() } as unknown as Pick<CaptureRPC, "request" | "ready" | "close">} />);
  await within(view.container).findByText("1 of 9 required photos saved. This only saves evidence; submitting to a shop happens after review.");
  fireEvent.click(within(view.container).getByRole("button", { name: "Open guided camera" }));
  const file = new File(["sample"], "vin.jpg", { type: "image/jpeg" });
  await expect(camera.save!("vin", "vin", file)).rejects.toMatchObject({
    name: "PhotoRejected", message: expect.stringContaining("newer photo"),
  });
  expect(request).toHaveBeenCalledWith("captureState", {}, 12_000);
});

it.each([true, false])("releases only a proven superseded photo and preserves uncertain retry (%s)", async (superseded) => {
  const state = { estimate_id: "draft", discipline: "collision", vehicle, photos: [], vin_suggestion: null };
  const operations: string[] = [];
  const request = vi.fn(async (method: string, params: Record<string, unknown>) => {
    if (method === "captureState") return state;
    if (method === "saveCapture") {
      operations.push(params.operation_id as string);
      throw new RPCError("Review photo status.", 409, superseded ? "capture_superseded" : null);
    }
    throw new Error("Unexpected method");
  });
  const view = render(<CaptureApp rpc={{ request, ready: vi.fn(), close: vi.fn() } as unknown as Pick<CaptureRPC, "request" | "ready" | "close">} />);
  await within(view.container).findByText("0 of 9 required photos saved. This only saves evidence; submitting to a shop happens after review.");
  fireEvent.click(within(view.container).getByRole("button", { name: "Open guided camera" }));
  const file = new File(["sample"], "vin.jpg", { type: "image/jpeg" });
  for (let attempt = 0; attempt < 2; attempt++) {
    await expect(camera.save!("vin", "vin", file)).rejects.toMatchObject({ name: superseded ? "PhotoRejected" : "Error" });
  }
  expect(operations).toHaveLength(2);
  if (superseded) expect(operations[1]).not.toBe(operations[0]);
  else expect(operations[1]).toBe(operations[0]);
  expect(request.mock.calls.filter(([method]) => method === "captureState")).toHaveLength(superseded ? 3 : 1);
});
