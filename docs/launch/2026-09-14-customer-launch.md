# Customer preview readiness — September 13, 2026 snapshot

The planned sharing time was **September 14, 2026 at 2 p.m. America/Denver**.
The filename identifies that target; it is not evidence that a launch occurred
at a future time. This page records the September 13 preview evidence and the
checks still separate from it. Later release work is tracked in
[release status](../release-status.md) and [mobile delivery](../mobile-release.md).

## Latest deployment recorded in this snapshot

The [build-7 evidence](../releases/2026-09-13-build7.json) records:

- Customer web/API at https://estimoto-plus-api.fly.dev/, source
  `ebb7f47275b018f276744322bbb2c191438e4f7a`, with `/ready` and `/version` returning
  200 and PostgreSQL schema `a63e90b72d14`.
- Original Estimoto API source `ca5241a82136de7a49fd98f772775fc245a1c304`, with
  readiness/version checks passing. Participating provider publication and the
  customer-to-shop bridge are implemented; publication is explicit opt-in.
- Signed Android 0.1.0 (7), public APK/AAB bytes and signer verified. An emulator
  upgrade preserved the session and displayed the cost rollup and private PDF.
  This does not establish physical-device camera or receipt behavior.
- Separate Apple app 6811678079, build 7 processed as `VALID`, internal testing
  active, and both tester groups attached. External build-7 submission was
  blocked by the existing build-2 review; external installation was unverified.
- Release validation recorded 176 Flutter tests and clean analysis, plus 320
  unique backend cases exercised across a full run and an original-source
  contract follow-up. Overlapping focused runs are not added to these totals.

The late September 13 audit independently reported the same build-7 live source
and schema. Its separate local run covered 286 backend tests with 34 environment-
gated skips and 176 Flutter tests. Those counts describe that audit invocation,
not a replacement for the release's separately configured validation record.

## Implemented behavior and its evidence

Customer estimates can be submitted through the live bridge after explicit
review/consent and required private evidence. The server freezes contact,
vehicle, provider, ZIP/mode and photo manifest, then delivers through a durable
outbox. Upstream receipt, processing completion and an authoritative quoted
amount are separate states. Plus does not create a price from the presence of
photos. Guided capture includes VIN confirmation and nine documentation views;
PDR damage views remain evidence, not automatic pricing rows.

Garage photos, representative vehicle imagery, explicit vehicle valuation,
private service history/costs/receipts, reviewed saved-shop scheduling and
customer-owned discovery choices are implemented. Live synthetic checks in the
build-7 record exercised private receipt upload/readback, vehicle isolation,
cost totals, cached CarsXE data and the participating Demolition Dent logo.
They created no shop request/submission or outbound shop message.

The [local socket proof](2026-09-13-socket-proof.md) separately exercised real
Plus/original-Estimoto APIs for delivery, replay, cancellation, required estimate
evidence and returned staff status. Its reviewed amount was an explicit synthetic
fixture. That proves transport and state handling, not a production repair quote
or real shop acceptance.

## Earlier evidence, superseded as a deployment description

Build 4's signed download, emulator sign-in and requested invite delivery were
earlier milestones. The [build-5 record](../releases/2026-09-13-build5.json)
records migration `e21870f6a94b`, 168 backend/68 Flutter tests, and Android-emulator
camera/gallery upload, replacement, removal and process-death recovery against
the API. Those figures and artifacts belong to build 5; build 7 is the later
deployment recorded above. An invite email, API sign-in, emulator sign-in and a
real customer's inbox/code entry are distinct evidence.

## Changes prepared after this snapshot

The source prepared for build 8 includes a curated directory capped at 30
combined results, reviewed official business contact/artwork profiles, corrected
unavailable-screen navigation, phone-only demo calling, first-save device time
zones, a Denver sample calendar, fictional demo valuation and revised icon
artwork. See the [current API contract](../api-contract.md) for source behavior.
This page does **not** claim build 8 was deployed, distributed or installed.

## Checks still separate at the snapshot

- A first real customer-to-shop handoff and actual shop acceptance.
- A real customer's authentication inbox/code flow and physical iOS/Android
  sign-in, camera, receipt viewing and interrupted-picker recovery.
- Apple's external beta approval and Google Play publication.
- Customer Google Calendar setup and actual authorized provider use. The
  integration existed in source but was disabled pending verified provider setup;
  synthetic availability or demo slots do not prove a real connection/event.
- PDR LINX location/service ZIPs before publishing location-based routing.

CARFAX, push reminder delivery, automated phone/SMS booking and corpus-wide model
training were not connected. Customer service history is private, typed,
customer-reported evidence; optional coarse contributed insights are off by
default. See [automotive knowledge](../automotive-knowledge.md).
