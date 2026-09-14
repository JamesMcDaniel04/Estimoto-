# Customer capture integration brief

The original Estimoto customer camera remains the source of truth for the continuous rear-camera walk, 3D body guide, SVG fallback, framing behavior and photo-step catalog. `scripts/sync_capture_ui.sh ORIGINAL_REPOSITORY_ROOT` copies the four exact original TypeScript sources and original camera CSS into `capture-web/src/shared/`, recording their SHA-256 digests and the original source commit in `source-manifest.json`. `scripts/build_capture.sh` verifies those digests before building. The checked-in copy lets a Plus-only GitHub checkout build without the original repository. Change the original camera first, commit it, then sync and review the generated Plus diff.

The Plus capture site is a standalone Vite entry at `/capture/` on the Plus API's first-party HTTPS origin. It contains only the photo walk and VIN confirmation. It does not load the public intake funnel, payment form, CRM details or any access token. The Flutter host binds the active authenticated customer and estimate; the capture page cannot choose an estimate ID. A web iframe accepts replies only from its exact same-origin parent. Native replies arrive through `window.EstimotoPlusCapture.receive(JSON)` and outbound messages use `CaptureHost.postMessage(JSON)`.

Outbound RPC is `{channel:"estimoto-plus-capture",id,method,params}` and the host returns `{channel,id,result}` or `{channel,id,error:{status,message}}`. The page starts with `{channel,type:"ready",version:1}`; the host can send `{channel,type:"pause"}` and `{channel,type:"resume"}`. `pause` unmounts and stops the camera. No VIN, photo bytes, account ID or credential appears in the URL, browser storage, or ready message. Methods:

| Method | Params | Server action |
| --- | --- | --- |
| `captureState` | `{}` | GET owner-bound draft/photo state |
| `checkFrame` | `{capture_key,body_style,photo:{base64,mime_type}}` | Bounded transient framing guidance |
| `saveCapture` | Same plus `operation_id` UUID | Idempotent private photo save; same File retains operation ID on timeout |
| `recognizeVin` | `{photo_id}` | OCR of the current saved private VIN photo |
| `confirmVin` | `{photo_id,photo_sha256,expected_vin,vin}` | Explicit optimistic compare-and-set of the saved vehicle VIN |
| `askCaptureHelp` | `{capture_key,question}` | Text-only capture help |
| `close` | `{}` | Return to the garage |

Files are capped at 8 MB before base64 transfer, and the host and API must enforce the same bound. `saveCapture` HTTP 422 is definitive framing rejection, so the page offers a new frame. Timeout, 408, 409, 429 and 5xx retain the exact file and UUID for retry. The host must preserve the HTTP status in the structured error envelope and never echo private headers or body in errors.

The required documentation sequence is odometer, **driver-door-jamb VIN**, engine bay, interior, tire tread, then front/driver/rear/passenger exterior views. All nine are documentary evidence; the VIN step never prices damage. The original public link uses the same requirement, while a persisted version-1 Plus machine receipt may finish its frozen legacy eight-photo intake. New Plus submissions use capture version 2. PDR uses a matching `hail_close_<panel>` and `hail_raking_<panel>` pair; the raking view supports dent assessment. A legacy `panel_<panel>` remains a valid assessable alternative, without adding a duplicate panel to a new pair. Collision close-ups use its 18-panel catalog.

The original machine bridge endpoints are `POST /bridge/plus/capture/guidance` and `POST /bridge/plus/capture/vin-photo`, both with the existing `X-Bridge-Key` and bounded multipart `photo` field. Guidance also takes `capture_key` and `body_style`, and returns `{ready,available,instruction}`. VIN recognition returns `{suggested_vin,confidence,requires_confirmation:true,confirmation_reason}`. They create no job/intake or pricing row and do not mutate a VIN. The Plus API owns customer binding, quotas, saved evidence and confirm checks. A saved photo marked `framing_checked` has passed a frame check only; `not_checked` still means saved, and neither state claims AI damage verification or a quote. Original voice stays with the original intake session. Plus capture only offers text help in this version.
