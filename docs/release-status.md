# Live customer preview — build 8, September 14, 2026

Estimoto + build 8 is published at https://estimoto-plus-api.fly.dev/ and the
permanent Android download. Its artifact source is
`e5d0e4ad40ba93866e1905f55c6046d6b4824588`. The current verified API/web deployment
uses that same source and schema `a63e90b72d14`. Forthcoming build 9 combines
shop-card taps that open the profile with the hashed brand asset for returning
browsers. Build 9 has not yet been verified as distributed. Android/iOS build-8
artwork is already correct; its delivery evidence remains recorded below.

[Download latest Android](https://estimoto-plus-api.fly.dev/android/download) ·
[Mobile delivery](mobile-release.md) · [Build-8 evidence](releases/2026-09-14-build8.json) ·
[Audit follow-up](qa/2026-09-13-audit-closure.md)

## Delivered surfaces

| Surface | Verified state |
| --- | --- |
| Customer API/web | `/version` matched `e5d0e4a` before and after live checks; `/ready` 200, schema `a63e90b72d14`. Served shell/capture bytes matched the local build. The brand-cache follow-up is included in forthcoming build 9. |
| Android customer app | Signed 0.1.0 (8); exact public APK hash checked and installed over build 7 on an emulator. Version, launcher/splash/welcome/home artwork, synthetic sign-in, live directory logo and mini profile verified. |
| iOS customer app | App 6811678079, build 8 processed VALID; 1,960-character notes and both groups attached. Read-only Apple verification at 06:22:53 UTC confirmed exact notes/groups, internal testing and no build-8 review submission; the build-2 review is preserved. |
| Repository | `main` and `origin/main` were fast-forwarded from the old `1a69205` history and contain artifact source `e5d0e4a`; no force-push. |
| Hosted CI | Main run `34811930282`: all four jobs failed to start because of GitHub account billing. Local gate success does not establish hosted CI success. |
| Original Estimoto mobile | Separate build 232, source `a0a2af9cfb8c88cb3b7eb9860a42554dcf57714f`, shipped with 38 exact-tab tests and external approval. Its approval does not approve Plus. |

## Forthcoming build 9

Tapping a shop card will open its profile. Call, Website, Google Maps/reviews,
dedicated-shop saving and available request/contact actions will be in that
profile. The same release includes a generated content-hashed brand asset to
refresh older browser artwork. See the [build-9 notes](releases/0.1.0-9-beta-notes.md).
Android build 9 will use the same permanent download URL; the delivered build-8
invite already contains that URL, so no duplicate email is planned. Build-9
source, artifact hashes and live/device verification will be recorded after
publication.

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

The shipped `e5d0e4a` adds only the Android publisher's repository-rename redirect
fix and its regression. Its 16 focused tests passed; these overlap other tests
and are not added to the full-suite total. The full gate was not rerun on that
publisher-only follow-up. Exact SHAs, bounds and evidence hashes are in the
[build-8 record](releases/2026-09-14-build8.json).

Twenty live surface checks passed, including production docs 404s, security and
revalidation headers, conditional shell 304, current capture bytes, invalid/missing
authentication 401s and the disabled production dev-session route. Browser QA
signed in a synthetic account and rendered all 27 shop images and a mini profile.
An existing browser cache retained older brand artwork despite current server
bytes, prompting the content-hash fix included in forthcoming build 9. Its final
refresh verification remains outstanding. Native Android QA loaded the live directory, displayed Bronco's
Muffler's real logo and opened its mini profile. No shop was contacted and no
request was created; raw screenshots/logs stay private.

The build-8 synthetic QA account was globally signed out, then its Auth account,
profile and rate rows were removed. Other customer-owned tables were confirmed
empty before cleanup. The old token received 401 on a write and a subsequent GET;
the real customer account was untouched. No private files were uploaded. Native
Android displayed the ended-session screen, then signing out returned to welcome.

A fresh requested Android invite was sent once. Resend accepted it at
06:16:05 UTC and provider readback confirmed **delivered** at 06:16:26 UTC on
September 14. It contains the permanent URL that served the verified build-8
APK at delivery and will serve build 9 after publication. Recipient opening,
installation on the user's device and normal sign-in
code entry are not established by delivery. A normal sign-in code was requested
through the UI; real inbox/code-entry completion is still pending.

## Remaining checks

- GitHub account billing must be resolved before hosted CI can run.
- Plus external TestFlight access still awaits Apple's preserved build-2 review;
  final readback confirmed build 8 remains `READY_FOR_BETA_SUBMISSION`.
- Real mailbox/code-entry completion and physical iOS/Android installation,
  camera, receipt and interrupted-picker behavior remain unverified.
- Build-9 publication and final browser branding refresh remain outstanding;
  build-8 synthetic cleanup and native ended-session/sign-out UI checks are complete.
- The first real customer-to-shop handoff and actual shop acceptance remain
  unverified. No automated test is counted as a real shop send.
- Google Calendar customer connection remains disabled pending verified provider
  setup. Demo/local checks do not prove a real Google event.
- PDR LINX location/service ZIP information is still required for routing.
  Google Play, CARFAX, push delivery, automated phone/SMS booking and corpus-wide
  model training are not connected.

The customer sharing target remains September 14 at 2 p.m. America/Denver.
The [September 13 readiness snapshot](launch/2026-09-14-customer-launch.md) and
[build-7 evidence](releases/2026-09-13-build7.json) retain earlier milestones.
