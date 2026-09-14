import { afterEach, expect, it, vi } from "vitest";
import { CaptureRPC, CHANNEL, encodedPhoto, RPCError } from "./rpc";

afterEach(() => {
  delete (window as unknown as { CaptureHost?: unknown }).CaptureHost;
  vi.restoreAllMocks();
});

it("sends only a narrow RPC request and accepts an exact correlated native reply", async () => {
  const posted: string[] = [];
  const host = window as typeof window & { CaptureHost?: { postMessage: (value: string) => void }; EstimotoPlusCapture?: { receive: (value: unknown) => void } };
  host.CaptureHost = { postMessage: (value) => posted.push(value) };
  const bridge = new CaptureRPC(host);
  const promise = bridge.request("captureState");
  const outbound = JSON.parse(posted[0]);
  expect(outbound).toMatchObject({ channel: CHANNEL, method: "captureState", params: {} });
  expect(posted[0]).not.toMatch(/token|authorization|customer_id|estimate_id/i);
  host.EstimotoPlusCapture!.receive(JSON.stringify({ channel: CHANNEL, id: outbound.id, result: { photos: [] } }));
  await expect(promise).resolves.toEqual({ photos: [] });
  bridge.close();
});

it("ignores an uncorrelated reply and rejects pending requests on close", async () => {
  const posted: string[] = [];
  const host = window as typeof window & { CaptureHost?: { postMessage: (value: string) => void }; EstimotoPlusCapture?: { receive: (value: unknown) => void } };
  host.CaptureHost = { postMessage: (value) => posted.push(value) };
  const bridge = new CaptureRPC(host);
  const promise = bridge.request("captureState");
  host.EstimotoPlusCapture!.receive(JSON.stringify({ channel: CHANNEL, id: "wrong", result: { photos: ["leak"] } }));
  bridge.close();
  await expect(promise).rejects.toThrow("Capture is closed");
});

it("preserves a definitive photo rejection status for retake behavior", async () => {
  const posted: string[] = [];
  const host = window as typeof window & { CaptureHost?: { postMessage: (value: string) => void }; EstimotoPlusCapture?: { receive: (value: unknown) => void } };
  host.CaptureHost = { postMessage: (value) => posted.push(value) };
  const bridge = new CaptureRPC(host);
  const pending = bridge.request("saveCapture", { operation_id: "stable" });
  const id = JSON.parse(posted[0]).id;
  host.EstimotoPlusCapture!.receive(JSON.stringify({ channel: CHANNEL, id, error: { status: 422, message: "Retake this photo." } }));
  await expect(pending).rejects.toMatchObject({ status: 422, message: "Retake this photo." } satisfies Partial<RPCError>);
  bridge.close();
});

it("encodes bounded image bytes and rejects oversized handoffs before host I/O", async () => {
  const encoded = await encodedPhoto(new File([new Uint8Array([0, 1, 255])], "door.png", { type: "image/png" }));
  expect(encoded).toEqual({ base64: "AAH/", mime_type: "image/png" });
  await expect(encodedPhoto(new File([new Uint8Array(8 * 1024 * 1024 + 1)], "large.png", { type: "image/png" }))).rejects.toThrow("under 8 MB");
});

it.each([
  [409, "capture_superseded", "capture_superseded"],
  [409, "unknown_conflict", null],
  [503, "capture_superseded", null],
])("only preserves a verified superseded conflict code (%s/%s)", async (status, code, expected) => {
  const posted: string[] = [];
  const host = window as typeof window & { CaptureHost?: { postMessage: (value: string) => void }; EstimotoPlusCapture?: { receive: (value: unknown) => void } };
  host.CaptureHost = { postMessage: (value) => posted.push(value) };
  const bridge = new CaptureRPC(host);
  const pending = bridge.request("saveCapture", { operation_id: "stable" });
  const id = JSON.parse(posted[0]).id;
  host.EstimotoPlusCapture!.receive({ channel: CHANNEL, id, error: { status, code, message: "Review photo status." } });
  await expect(pending).rejects.toMatchObject({ status, code: expected });
  bridge.close();
});
