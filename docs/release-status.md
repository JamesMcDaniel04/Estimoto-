# Live customer preview — September 13, 2026

Estimoto + is deployed at https://estimoto-plus-api.fly.dev with dedicated
customer authentication/storage and a production bridge to Estimoto. This is a
live customer preview; the remaining checks below prevent a blanket readiness claim.

## Delivered surfaces

| Surface | Verified state |
| --- | --- |
| Customer web/API | Live source `ebb7f47275b018f276744322bbb2c191438e4f7a`; `/ready` 200; PostgreSQL schema `a63e90b72d14` |
| Original Estimoto API | Live source `ca5241a82136de7a49fd98f772775fc245a1c304`; `/ready` 200; published partner logos gated by current opt-in |
| Staff dashboard | https://www.estimoto.io; previously verified source `82b52bcbbdb801e952ec144d056c80dbd17af51e`; Plus inbox, explicit listing controls and owner-only contributed insights |
| Android customer app | Signed 0.1.0 (7); permanent-link APK and AAB bytes/hashes verified; emulator upgrade retained authentication and displayed costs/private PDF |
| iOS customer app | App 6811678079, 0.1.0 (7) VALID; exact notes and both groups attached; internal testing active; external build-7 access awaits Apple review |
| Original Estimoto mobile | Previously verified 1.1.12 (231), source `b3e4a5241d0be49377aa7700b133a10d22f0a831`; Estibot presets and CRM-entitled texting; separate from the Plus build-7 release |

[Download latest Android](https://estimoto-plus-api.fly.dev/android/download) · [Mobile delivery details](mobile-release.md) · [Build-7 evidence](releases/2026-09-13-build7.json)

## Implemented customer workflows

- Confirmed-email sign-in with native encrypted session storage and memory-only
  web authentication. Existing email codes can be entered on another device.
- Saved contact, vehicle and optional insurance details; date/mileage reminders.
  Representative CarsXE vehicle images are matched conservatively to year/make/model.
  Private camera/gallery images take priority and remain separate from estimate evidence.
- Guided PDR/Collision required-photo capture, VIN confirmation, private byte
  readback, interrupted-picker recovery and durable handoff to a selected shop.
  Existing billing and evidence/review requirements remain authoritative.
- A directory within approximately 30 miles of the ZIP center, capped at 100
  combined results. Participating providers and public OpenStreetMap listings
  retain separate provenance; mobile-only results and shop-visit alternatives
  are labeled. Coverage is not claimed to be exhaustive. Vehicle-specific
  dedicated choices remain private. Available published logos and licensed
  Commons photos have attribution and a fallback when unavailable.
- Explicit service requests, durable delivery/status sync, cancellation and staff
  acceptance/scheduling/completion. Private My shops contacts support reviewed
  scheduling drafts, explicit email authorization and shop acceptance of an
  offered time. Provider acceptance is distinct from inbox delivery.
- Customer-reported repair, maintenance and modification history, integer USD
  costs and private receipt photos/PDFs. Upload retries preserve the original
  operation and bytes. Receipts can be viewed or deleted; pending attachments
  require review after restart. Receipts are not automatically sent to shops.
- CarsXE retail and wholesale estimates use the saved vehicle's VIN/mileage and
  the customer's selected state/condition. Exact-input caching, leases and
  provider-call budgets bound lookups. Recorded care, receipt coverage and costs
  are shown separately; spending is not added to the vehicle's estimated value.
- A typed private automotive graph with source references supports bounded
  Estibot retrieval. Customer-reported history does not establish verified
  workmanship. Receipt contents and calendar event text are not sent to this graph.
- Optional contributed insights default off and can be revoked. Only coarse
  groups with at least ten consenting contributors appear; counts round down
  to multiples of five. Raw contacts, records and free-text names remain private.

See [automotive knowledge architecture](automotive-knowledge.md) for graph and
sharing boundaries.

## Build-7 verification

The backend suite passed **313 tests**, with seven original-source contract cases
gated in that invocation. A separate actual-original-source contract run passed
**12 tests with zero skipped**, including all seven gated cases: **320 unique
backend cases were exercised**. Receipt/PDF/history and valuation focused checks
also passed, including isolated PostgreSQL, fresh migration/round-trip checks,
RLS/direct-access denial, concurrent replay and lost commit acknowledgment.
Flutter passed **176 tests**, with clean analysis. Focused and phone-size runs
are overlapping evidence, not added to the full-suite total.

The live receipt smoke passed **33 checks**. Synthetic web QA exercised the actual
PDF chooser/upload and private renderer, a $1,420 recorded-cost rollup with
missing-cost handling and vehicle isolation, a cached CarsXE result, and
Demolition Dent's real published logo. Android build 7 upgraded the prior app
without losing the synthetic session, displayed the rollup, and opened/closed a
private PDF from the live API. No shop request, estimate submission, customer
handoff or shop message was sent by these receipt checks.

The signed iOS IPA processed VALID and its notes/groups were independently read
back from Apple. The new simulator build succeeded, but Keychain/signing blocked
its login; native build-7 iOS receipt rendering remains unverified. Android emulator,
web and prior iOS picker evidence do not establish physical-device behavior.

Previous local socket checks connected Plus to the real Estimoto receiver and
isolated PostgreSQL for request replay, cancellation, status and photo-package
contracts. Their amount fixture was synthetic. See [socket proof](launch/2026-09-13-socket-proof.md)
and [backend validation details](releases/2026-09-13-receipt-backend-validation.json).

Synthetic release QA cleanup is complete. The two explicitly marked test accounts
were removed; verification found zero scoped owned rows across 30 tables and zero
known private files remaining. Old and freshly issued test tokens were denied
with HTTP 401; the Android UI then showed the ended session and returned to
sign-in after Sign out. The real customer account was excluded and left untouched.
Credentials, account identifiers, private receipts and cleanup journals remain
outside Git.

The previously requested Android email was delivered with `/android/download`.
Publishing build 7 advanced that same link to its verified APK; no new build-7
email was sent. Installation remains customer initiated, with no automatic updater.

## Participants and remaining launch checks

Demolition Dent is published with its existing business address/phone and accepts
PDR/collision requests. Mobile service continues to require published ZIP coverage;
nearby customers can choose the explicitly supported shop-visit mode. PDR LINX
is authorized as the second participant, but its saved account lacks location/
service ZIP information and the phone did not match the official public contact
page. Its location routing still awaits the user's ZIP information. No unrelated
shops or technicians were opted in.

Remaining checks and limits:

- Apple's build-2 review is still pending. Build 7 is internally testable but
  external access is blocked by `ANOTHER_BUILD_IN_REVIEW`; no review was reset.
- Native iOS build-7 receipt QA and physical iOS/Android sign-in, receipt/camera
  quality and recovery checks remain unverified.
- The first real customer-to-shop handoff and shop acceptance remain unverified.
  A delivered sign-in email does not prove the customer's code entry.
- Google Calendar customer connection remains disabled pending verified provider
  setup. No customer Google account was connected and no real calendar event was created.
- Google Play publication, CARFAX, push reminder delivery, automated phone/SMS
  booking and corpus-wide model training are not connected.
- Original Estimoto's CRM texting entitlement gate was separately verified;
  this Plus release did not send real SMS or calls.

The target customer sharing time is September 14, 2026, at 2 p.m. America/Denver.
Apple review timing is outside this deployment's control.
