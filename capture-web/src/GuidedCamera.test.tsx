import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import GuidedCamera from "./shared/GuidedCamera";
import { requiredStepsFor } from "./shared/template";
vi.mock("./shared/VehicleGuide", () => ({ BODY_STYLES: ["sedan"], bodyLabel: () => "Sedan", bodyStyleFor: () => "sedan", VehicleGuide: () => <div>3D target</div> }));
afterEach(cleanup);

it.each([undefined, "image/*"])("offers the configured photo picker without weakening file validation (%s)", async (photoAccept) => {
  const save = vi.fn(async () => true);
  render(<GuidedCamera steps={requiredStepsFor("collision")} uploaded={{}} body="sedan"
    photoAccept={photoAccept} onBodyChange={vi.fn()} checkFrame={vi.fn()}
    onCapture={save} onClose={vi.fn()} />);
  await screen.findByRole("alert"); // Camera unavailable: a photo remains usable.
  const picker = screen.getByLabelText("Upload photo for current view");
  expect(picker).toHaveAttribute("accept", photoAccept ?? "image/jpeg,image/png,image/webp");
  for (const file of [new File(["photo"], "photo.heic", { type: "image/heic" }),
    new File([new Uint8Array(8 * 1024 * 1024 + 1)], "huge.jpg", { type: "image/jpeg" })]) {
    fireEvent.change(picker, { target: { files: [file] } });
    expect(screen.getByText("Choose a JPEG, PNG or WebP photo smaller than 8 MB.")).toBeVisible();
    expect(save).not.toHaveBeenCalled();
  }
  const photo = new File(["photo"], "photo.jpg", { type: "image/jpeg" });
  fireEvent.change(picker, { target: { files: [photo] } });
  await waitFor(() => expect(save).toHaveBeenCalledWith("odometer", "odometer", photo));
  await screen.findByRole("heading", { name: "VIN at driver’s door jamb" }); // the step strip also names the view
});
