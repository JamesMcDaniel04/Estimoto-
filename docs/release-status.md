# Live customer preview — September 13, 2026

Estimoto + is deployed at https://estimoto-plus-api.fly.dev with dedicated customer authentication/storage and a production bridge to Estimoto. It is a live customer preview; the remaining checks below prevent a blanket production-readiness claim.

## Delivered surfaces

| Surface | Verified state |
| --- | --- |
| Customer web/API | Live source `a5403daf8f71f5820671388f049588a84b840196`; `/ready` 200, PostgreSQL schema `c54d09a2f173` |
| Original Estimoto API | Live source `906ccdf11f08f362dad41b89a854a579067bae51`; `/ready` 200; migration `0212_estimoto_plus_bridge` |
| Staff dashboard | https://www.estimoto.io; asset source `906ccdf11f08f362dad41b89a854a579067bae51`; Plus inbox, opt-in listing and owner-only contributed insights |
| Android customer app | Signed 0.1.0 (4), rounded/adaptive icon; public APK and AAB hashes verified; installed and launched in Android emulator |
| iOS customer app | Separate App Store Connect app 6811678079; 0.1.0 (3) processed VALID, notes and both tester groups attached; first external review for build 2 pending |
| Original Estimoto mobile | Estibot preset UI update in 1.1.12 (230), TestFlight VALID and external beta approved; Android served hashes verified |

[Download Android](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.4) · [Mobile delivery details](mobile-release.md)

## Implemented customer workflows

- Confirmed-email sign-in with native encrypted session storage and memory-only web authentication. Existing email codes can be entered on another device without requesting another email.
- Saved contact, vehicle and optional insurance details; date/mileage reminders.
- PDR/Collision guided required-photo capture, private byte readback, interrupted-picker recovery and durable handoff to a selected shop. Existing billable-link and review/evidence requirements remain authoritative; customer screens do not invent estimate prices.
- Opt-in shop/technician directory, explicit customer requests, durable delivery/status sync, cancellation, and staff acceptance/scheduling/completion.
- Private My shops contacts; immutable scheduling drafts; exact-message/contact/time review; authorization before email dispatch; shop acceptance of an offered time before appointment confirmation. Phone-only entries provide a call action. Provider acceptance is distinct from inbox delivery.
- Customer-reported service/parts/shop history, a typed private GraphRAG projection with source references, and bounded Estibot retrieval/advice. Customer data is not turned into verified repair outcomes by inference.
- Optional contributed insights default off and can be revoked. Only coarse categories with at least ten consenting contributors are exposed; counts round down to multiples of five. Raw records, contacts and free-text supplier/shop names are not exposed to other shops.

See [automotive knowledge architecture](automotive-knowledge.md) for exact graph and sharing boundaries.

## Verification evidence

The final backend suite passed **135 tests with zero skipped**, including actual original-source bridge contracts and PostgreSQL first-sign-in concurrency. The final Flutter sign-in update passed **60 tests** and clean analysis. The icon update additionally passed native AAPT compile/link/resource checks; no Dart behavior changed in that update.

Real local sockets connected the customer API to the actual Estimoto receiver and PostgreSQL, exercising request replay, cancellation, staff status return and required photo packages. The reviewed amount fixture in that scenario was synthetic, not a generated production estimate. See [socket proof](launch/2026-09-13-socket-proof.md).

Production synthetic checks established authenticated customer isolation, missing/invalid token denial, private photo exact-byte readback, cross-account photo denial, anon Data API denial and RLS/restricted-role configuration. Live browser checks at 390×844 signed in through the email-code form, created a private shop and unsent scheduling draft, recorded service/parts history, retrieved the exact recorded parts source through Estibot, and found Demolition Dent in ZIP 80221. These did not contact a shop or create a production CRM job.

The user-requested Android invite was accepted by Resend and its provider event became `delivered`. This proves that invite's delivery, not delivery of every future authentication or scheduling email.

## Participants and remaining launch checks

Demolition Dent is published and accepting PDR/collision in its saved ZIP **80221**, with its existing business address and phone. Production bridge sync and actual customer matching both passed. PDR LINX is authorized as the second participant, but its account has no address/service ZIP and its phone did not match the official public contact page; its location routing awaits the user's ZIP information. No unrelated shops or technicians were opted in.

Remaining: physical iOS/Android sign-in and camera/recovery QA; first real customer-to-shop handoff and shop acceptance; actual authentication-email inbox verification; Apple external beta approval. Google Play listing/publication is not performed. CARFAX, push reminder delivery, automated phone/SMS booking and corpus-wide model training are not connected. YouTube links are labeled searches, not individually vetted videos.

The target customer sharing time is September 14, 2026, at 2 p.m. America/Denver. Apple review timing is external to this deployment.
