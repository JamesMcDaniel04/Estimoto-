import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { expect, it, vi } from "vitest";
import { CaptureApp } from "./CaptureApp";
import type { CaptureRPC } from "./rpc";
import type { PhotoStep } from "./shared/template";

vi.mock("./shared/GuidedCamera", () => ({ default: (props: {
  steps: PhotoStep[]; needsDamagePanel?: boolean; onDamagePanel?: (panel: string) => void;
}) => <div data-testid="guided-camera">
  <span>{props.steps.map((step) => step.key).join(",")}</span>
  {props.needsDamagePanel && <button onClick={() => props.onDamagePanel?.("hood")}>Choose hood</button>}
</div> }));

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
