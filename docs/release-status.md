# Live customer preview — September 13, 2026

Estimoto + is deployed at https://estimoto-plus-api.fly.dev with dedicated customer authentication/storage and a production bridge to Estimoto. It is a live customer preview; the remaining checks below prevent a blanket production-readiness claim.

## Delivered surfaces

| Surface | Verified state |
| --- | --- |
| Customer web/API | Live source `08c156de08b626da9de1ba10975f214a2a89d41b`; `/ready` 200, PostgreSQL schema `32ac7f618b90` |
| Original Estimoto API | Live source `ca5241a82136de7a49fd98f772775fc245a1c304`; `/ready` 200; migration `0212_estimoto_plus_bridge` |
| Staff dashboard | https://www.estimoto.io; asset source `82b52bcbbdb801e952ec144d056c80dbd17af51e`; Plus inbox, opt-in listing and owner-only contributed insights |
| Android customer app | Signed 0.1.0 (6), 100-result local directory and shared 3D/VIN capture; permanent-link APK and AAB hashes verified; build-5 upgrade preserved synthetic login/draft in Android emulator |
| iOS customer app | Separate App Store Connect app 6811678079; 0.1.0 (6) processed VALID, notes and both tester groups attached; first external review for build 2 pending |
| Original Estimoto mobile | Estibot presets plus CRM-entitled texting in 1.1.12 (231), source `b3e4a5241d0be49377aa7700b133a10d22f0a831`; TestFlight VALID and external beta approved; Android served hashes verified |

[Download latest Android](https://estimoto-plus-api.fly.dev/android/download) · [Mobile delivery details](mobile-release.md)

## Implemented customer workflows

- Confirmed-email sign-in with native encrypted session storage and memory-only web authentication. Existing email codes can be entered on another device without requesting another email.
- Saved contact, vehicle and optional insurance details; date/mileage reminders. Representative CarsXE vehicle images are matched conservatively to year/make/model. Private camera/gallery uploads take priority; removal restores stock. Garage photos remain separate from estimate evidence.
- PDR/Collision guided required-photo capture, private byte readback, interrupted-picker recovery and durable handoff to a selected shop. Existing billable-link and review/evidence requirements remain authoritative; customer screens do not invent estimate prices.
- Opt-in shop/technician directory, explicit customer requests, durable delivery/status sync, cancellation, and staff acceptance/scheduling/completion.
- Private My shops contacts; immutable scheduling drafts; exact-message/contact/time review; authorization before email dispatch; shop acceptance of an offered time before appointment confirmation. Phone-only entries provide a call action. Provider acceptance is distinct from inbox delivery.
- Customer-reported service/parts/shop history, a typed private GraphRAG projection with source references, and bounded Estibot retrieval/advice. Customer data is not turned into verified repair outcomes by inference.
- Optional contributed insights default off and can be revoked. Only coarse categories with at least ten consenting contributors are exposed; counts round down to multiples of five. Raw records, contacts and free-text supplier/shop names are not exposed to other shops.

See [automotive knowledge architecture](automotive-knowledge.md) for exact graph and sharing boundaries.

## Verification evidence

Build 6 backend verification passed **271 tests with zero skipped**, including actual original-source bridge contracts and isolated PostgreSQL; Flutter passed **144 tests** plus focused final-capture checks and clean analysis. Guided-capture live smoke passed 72 checks across 44 HTTP requests. Android upgrade, explicit interrupted-photo recovery, VIN confirmation and photo-helper interaction were exercised in the emulator. iOS native and guided Photo Library pickers opened with the same synthetic fixture. The rounded icon passed native AAPT resource checks. Build 7 receipt/valuation checks are recorded separately when released.

Real local sockets connected the customer API to the actual Estimoto receiver and PostgreSQL, exercising request replay, cancellation, staff status return and required photo packages. The reviewed amount fixture in that scenario was synthetic, not a generated production estimate. See [socket proof](launch/2026-09-13-socket-proof.md).

Production synthetic checks established authenticated customer isolation, missing/invalid token denial, private photo exact-byte readback, cross-account photo denial, anon Data API denial and RLS/restricted-role configuration. Live browser checks at 390×844 signed in through the email-code form, created a private shop and unsent scheduling draft, recorded service/parts history, retrieved the exact recorded parts source through Estibot, and found Demolition Dent in ZIP 80221. These did not contact a shop or create a production CRM job. Live vehicle-image checks verified CarsXE, upload priority, digest/readback, replacement, removal, and a second authenticated customer being denied read/write/delete. The signed Android build used its real camera and system photo picker in an emulator; uploads appeared in the UI and removal restored CarsXE. An Android process-death test recovered the saved camera photo to its original vehicle and required explicit retry. Physical-device evidence remains distinct.

Earlier synthetic customer records and private photos were removed after their completed checks. The marked build-6/7 QA cohort is retained temporarily for receipt and release checks and is separate from the real customer account. No real shop contact was made.

The requested replacement Android invite was delivered to `j.mcdan@anonymousventures.org` with the permanent `/android/download` URL. This public URL resolves a freshly read release pointer to the verified versioned APK; `/android/current` exposes its version and digest. Downloading through the permanent URL returned the exact signed build-5 bytes. Future release publishing advances the pointer without changing the emailed URL or redeploying the API. Installation remains customer initiated; this is not an automatic in-app updater.

The user-requested `hello@estimoto.io` account exists as a normal live customer (`demo=false`) with no fabricated vehicles or jobs. Its normal Supabase confirmation email was delivered through the configured sender. Email verification/sign-in still requires the customer's code; no confirmation bypass or session impersonation was performed. This persistent customer account is not part of the cleaned synthetic QA fixtures.

Original Estimoto now requires CRM entitlement for platform texting, provisioning, queues and voice. Assigned technicians connected to an eligible CRM shop retain its delivery path; others prepare customer links and open the native phone messenger. The live audit found four active number leases and zero ineligible shops. No real SMS/calls were sent, and physical composer behavior remains unverified.

## Participants and remaining launch checks

Demolition Dent is published and accepting PDR/collision in its saved ZIP **80221**, with its existing business address and phone. Production bridge sync and actual customer matching both passed. PDR LINX is authorized as the second participant, but its account has no address/service ZIP and its phone did not match the official public contact page; its location routing awaits the user's ZIP information. No unrelated shops or technicians were opted in.

Remaining: physical iOS/Android sign-in and camera/recovery QA; first real customer-to-shop handoff and shop acceptance; customer confirmation-code entry; Apple external beta approval. Authentication-email provider delivery is verified, but the customer's reading/sign-in is separate. Google Play listing/publication is not performed. CARFAX, push reminder delivery, automated phone/SMS booking and corpus-wide model training are not connected.

The target customer sharing time is September 14, 2026, at 2 p.m. America/Denver. Apple review timing is external to this deployment.
