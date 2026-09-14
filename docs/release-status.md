# Live customer preview — build 10, September 14, 2026

Estimoto + build 10 is live on web and the permanent Android download, from
`62683757a569c3c82e37bbbf03be6658d780f77f`. Network shops accepting requests have a blue
Request help button on the card; tapping the rest of the card opens its profile.
This release also includes the concurrently merged Settings screen. iOS build 10
is VALID and available internally; external review remains pending.

[Download latest Android](https://estimoto-plus-api.fly.dev/android/download) ·
[Mobile delivery](mobile-release.md) · [Build-10 evidence](releases/2026-09-14-build10.json) ·
[Audit follow-up](qa/2026-09-13-audit-closure.md)

## Delivered surfaces

| Surface | Verified state |
| --- | --- |
| Customer API/web | `/version` matched `6268375`; `/ready` is ready at schema `a63e90b72d14`. Served JavaScript matches the local build. |
| Android customer app | Signed 0.1.0 (10); exact public APK installed over build 9 on an emulator. Card request button and separate profile navigation verified in demo. |
| iOS customer app | Build 10 VALID, exact 561-character notes and both groups verified. Internal `IN_BETA_TESTING`; external `READY_FOR_BETA_SUBMISSION`. Build 2 review preserved. |
| Repository | `main` includes the badge change, the concurrently merged Settings commits and release source `6268375`; no force-push. |
| Hosted CI | [Run 34815970821](https://github.com/JamesMcDaniel04/Estimoto-plus/actions/runs/34815970821) has no executed steps; check `103886600083` confirms the existing billing block. Local verification is recorded separately. |
| Original Estimoto mobile | Separate build 232, source `a0a2af9cfb8c88cb3b7eb9860a42554dcf57714f`, shipped with 38 exact-tab tests and external approval. Its approval does not approve Plus. |

## Customer editing in build 11

Reminders, estimate drafts and their photos, scheduling requests, service
history entries and valuation lookups can now be edited, withdrawn or deleted
from the app; shared estimates and confirmed appointments stay locked.
Reminders: tap to edit or delete, and Undo after marking one complete.
Estimates: edit details, delete the draft and remove saved photos while the
draft is unshared; afterwards the options menu explains the lock. Scheduling
requests: discard unsent drafts (including an interrupted device draft) and
withdraw sent ones, which turns the shop's confirmation link into a 410 with no
message to the shop. Service history: edit any field with receipts kept and the
private graph re-projected. Vehicle value: past lookups are kept per vehicle
(50 most recent), shown newest first and deletable. Estibot: conversations can
be cleared and an unanswered question offers the technician search. Demo:
drafts accept photos through the simple picker, the sample calendar can be
disconnected, and the guided camera reports a typed unavailable code.
Backend migration `b7f2c9d4e1a0` adds `vehicle_valuation_history`.

## Build 10 validation

All 217 app tests and analysis passed after integrating Settings; 19 capture-web
tests and the capture build passed. The exact public Android APK was installed
over build 9. Native demo checks verified the card's Request help button opens
the review form and that tapping the card body opens the profile. No real
request or shop contact was sent. Build-9 evidence below remains historical.
The delivered email already uses the permanent URL, which now serves build 10.

## What changed in build 9

Tapping a shop card opens its profile. Call, Website, Google Maps/reviews,
dedicated-shop saving and available request/contact actions are in the profile.
The generated content-hashed brand asset refreshes older browser artwork. See the
[build-9 notes](releases/0.1.0-9-beta-notes.md).

The returning browser displayed the new logo without clearing its cache. Web demo
QA opened a card, its profile and the saved PDR-shop choice; native Android demo
QA saved PDR from the profile choice dialog and saw “Your dedicated shop: PDR”
on the returned list. Both demo sessions were left at welcome and the owned QA
browser tab was closed. The real-owner code tab and user preview were preserved.
No new Auth account,
shop outreach or live customer mutation was used for build-9 checks. These demo
checks do not establish a live customer's saved-shop or request outcome.

Android build 10 uses the same permanent URL already present in the delivered
build-8 invite. No duplicate email was sent.

## What changed in build 8

Find Help now returns a curated list capped at 30 combined results within the
existing approximate 30-mile ZIP-centered radius. Live checks returned **26
reviewed independent businesses plus participating Demolition Dent**. All 27
had website/phone fields and loadable artwork: 26 logos and one owner-published
shop photo. All images decoded successfully; all 26 independent image digests
matched their fixed filenames. Mini profiles expose official business details
and review provenance. Google Maps opens for current reviews; unconfirmed numeric
ratings are not shown. This review does not rate workmanship or establish
appointment availability. Coverage is not exhaustive.

The darker sky-blue icon uses a white E, a smaller navy plus and a separate green
dot above-left of the plus. Unavailable/deleted records keep back navigation;
demo phone scheduling exposes the reviewed call action; demo valuation shows
explicitly fictional local values. Calendar setup suggests a validated device
IANA zone only for an unconfigured preference, preserves saved choices and uses
Denver time in the demo. Late-night availability, email validation and Estibot
capability copy are corrected.

Authentication now pools Supabase connections and briefly caches verified
GET/HEAD identities for at most 15 seconds, never beyond JWT expiry. Writes verify
fresh and invalidate cached reads. Errors and raw tokens are not cached. Production
interactive docs are disabled, main pages have HSTS/frame protection, and web
entry responses require revalidation. Guided capture retains same-origin embedding.

Existing private garage/photos, guided PDR/Collision evidence and VIN confirmation,
reviewed estimate/request handoff, service history/costs/receipts, explicit CarsXE
valuation and saved-shop scheduling remain available. Private evidence is not
public shop artwork; recorded spending is not added to market value. Shop
acceptance, bridge receipt, processing completion and a quoted amount remain
separate states. See the [API contract](api-contract.md) and
[automotive knowledge architecture](automotive-knowledge.md).

## Verification and its boundaries

The complete clean gate ran on `47f8eedfb749509d8540e8468b1cf0eada639308`:
**410 backend tests, zero skipped; 208 Flutter tests and clean analysis; 19
capture-web tests and a successful build; all API/pure-Dart, discovery and
calendar socket smokes**. All 34 previously gated backend cases ran using isolated
PostgreSQL and actual original bridge source. The test cluster was stopped and
removed. Source remained clean and unchanged during that run.

Build 8 (`e5d0e4a`) added only the Android publisher's repository-rename redirect
fix and its regression. Its 16 focused tests passed; these overlap other tests
and are not added to the full-suite total. The full gate was not rerun on that
publisher-only follow-up. Exact SHAs, bounds and evidence hashes are in the
[build-8 record](releases/2026-09-14-build8.json).

Build 9 passed **209 Flutter tests with clean analysis** and **19 capture-web
tests plus its build**. Its backend files are unchanged from build 8, so the full
backend/socket gate remains the `47f8eed` evidence above; it was not rerun as a
new build-9 gate.

Build-8 live checks passed 20 surface checks, including production docs 404s,
security/revalidation headers, shell 304, capture bytes, authentication 401s and
the disabled production dev-session route. Synthetic browser QA rendered all 27
shop images and a mini profile. Its native Android QA loaded the live directory,
displayed Bronco's Muffler's real logo and opened its mini profile. No shop was
contacted and no request was created. These historical signed-in checks remain
build-8 evidence; build-9 browser/native checks above used demo mode.

The build-9 live check at 06:39:10 UTC confirmed the deployed source, ready schema,
JavaScript bytes and exact brand image digest. The returning-browser check then
verified that the new artwork rendered without a cache clear. Raw logs and
screenshots stay private.

The build-8 synthetic QA account was globally signed out, then its Auth account,
profile and rate rows were removed. Other customer-owned tables were confirmed
empty before cleanup. The old token received 401 on a write and a subsequent GET;
the real customer account was untouched. No private files were uploaded. Native
Android displayed the ended-session screen, then signing out returned to welcome.

A fresh requested Android invite was sent once. Resend accepted it at
06:16:05 UTC and provider readback confirmed **delivered** at 06:16:26 UTC on
September 14. It contains the permanent URL that served the verified build-8
APK at delivery and now serves build 9. Recipient opening, installation on the
user's device and normal sign-in code entry are not established by delivery. A normal sign-in code was requested
through the UI; real inbox/code-entry completion is still pending.

## Remaining checks

- GitHub account billing must be resolved before hosted CI can run.
- Plus external TestFlight approval is unverified. Build-9 Apple readback at
  06:44:57 UTC confirmed internal testing and preserved build 2 `WAITING_FOR_REVIEW`.
- Real mailbox/code-entry completion and physical iOS/Android installation,
  camera, receipt and interrupted-picker behavior remain unverified.
- The first real customer-to-shop handoff and actual shop acceptance remain
  unverified. No automated test is counted as a real shop send.
- Google Calendar customer connection remains disabled pending verified provider
  setup. Demo/local checks do not prove a real Google event.
- PDR LINX location/service ZIP information is still required for routing.
  Google Play, CARFAX, push delivery, automated phone/SMS booking and corpus-wide
  model training are not connected.

The customer sharing target remains September 14 at 2 p.m. America/Denver.
The [September 13 readiness snapshot](launch/2026-09-14-customer-launch.md) and
[build-7 evidence](releases/2026-09-13-build7.json) and
[build-8 evidence](releases/2026-09-14-build8.json) retain earlier milestones,
including their then-current follow-up states.
