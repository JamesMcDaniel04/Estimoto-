# Live customer preview — September 13, 2026

Estimoto + is deployed at https://estimoto-plus-api.fly.dev with dedicated customer authentication/storage and a production bridge to Estimoto. It is a live customer preview; the remaining checks below prevent a blanket production-readiness claim.

## Delivered surfaces

| Surface | Verified state |
| --- | --- |
| Customer web/API | Live source `ec2dafffbd62b424ddd1b6928268b6ecce547365`; `/ready` 200, PostgreSQL schema `e21870f6a94b` |
| Original Estimoto API | Live source `4f12933c241018f201f1f8f847f200619a5e03d3`; `/ready` 200; migration `0212_estimoto_plus_bridge` |
| Staff dashboard | https://www.estimoto.io; asset source `906ccdf11f08f362dad41b89a854a579067bae51`; Plus inbox, opt-in listing and owner-only contributed insights |
| Android customer app | Signed 0.1.0 (5), CarsXE/private photos and rounded/adaptive icon; public APK and AAB hashes verified; installed and launched in Android emulator |
| iOS customer app | Separate App Store Connect app 6811678079; 0.1.0 (5) processed VALID, notes and both tester groups attached; first external review for build 2 pending |
| Original Estimoto mobile | Estibot presets plus CRM-entitled texting in 1.1.12 (231), source `b3e4a5241d0be49377aa7700b133a10d22f0a831`; TestFlight VALID and external beta approved; Android served hashes verified |

[Download Android](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.5) · [Mobile delivery details](mobile-release.md)

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

The vehicle-photo backend suite passed **168 tests with zero skipped**, including actual original-source bridge contracts and isolated PostgreSQL; fresh SQLite/PostgreSQL migrations passed. Flutter passed **68 tests** and clean analysis, including narrow/large-text layouts, account/vehicle changes and interrupted capture destination isolation. The rounded icon passed native AAPT resource checks.

Real local sockets connected the customer API to the actual Estimoto receiver and PostgreSQL, exercising request replay, cancellation, staff status return and required photo packages. The reviewed amount fixture in that scenario was synthetic, not a generated production estimate. See [socket proof](launch/2026-09-13-socket-proof.md).

Production synthetic checks established authenticated customer isolation, missing/invalid token denial, private photo exact-byte readback, cross-account photo denial, anon Data API denial and RLS/restricted-role configuration. Live browser checks at 390×844 signed in through the email-code form, created a private shop and unsent scheduling draft, recorded service/parts history, retrieved the exact recorded parts source through Estibot, and found Demolition Dent in ZIP 80221. These did not contact a shop or create a production CRM job. Live vehicle-image checks verified CarsXE, upload priority, digest/readback, replacement, removal, and a second authenticated customer being denied read/write/delete. The signed Android build used its real camera and system photo picker in an emulator; uploads appeared in the UI and removal restored CarsXE. An Android process-death test recovered the saved camera photo to its original vehicle and required explicit retry. Physical-device evidence remains distinct.

Synthetic customer records and their private photo files were removed after verification. No real shop contact was made.

The user-requested Android build-4 invite was accepted by Resend and its provider event became `delivered`; build 5 is now available at the updated release link. This proves that invite's delivery, not delivery of every future authentication or scheduling email.

Original Estimoto now requires CRM entitlement for platform texting, provisioning, queues and voice. Assigned technicians connected to an eligible CRM shop retain its delivery path; others prepare customer links and open the native phone messenger. The live audit found four active number leases and zero ineligible shops. No real SMS/calls were sent, and physical composer behavior remains unverified.

## Participants and remaining launch checks

Demolition Dent is published and accepting PDR/collision in its saved ZIP **80221**, with its existing business address and phone. Production bridge sync and actual customer matching both passed. PDR LINX is authorized as the second participant, but its account has no address/service ZIP and its phone did not match the official public contact page; its location routing awaits the user's ZIP information. No unrelated shops or technicians were opted in.

Remaining: physical iOS/Android sign-in and camera/recovery QA; first real customer-to-shop handoff and shop acceptance; actual authentication-email inbox verification; Apple external beta approval. Google Play listing/publication is not performed. CARFAX, push reminder delivery, automated phone/SMS booking and corpus-wide model training are not connected. YouTube links are labeled searches, not individually vetted videos.

The target customer sharing time is September 14, 2026, at 2 p.m. America/Denver. Apple review timing is external to this deployment.
