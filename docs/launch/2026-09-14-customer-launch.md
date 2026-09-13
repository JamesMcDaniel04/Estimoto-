# Customer launch — September 14, 2026 at 2 p.m. America/Denver

The live customer preview is at https://estimoto-plus-api.fly.dev/. Current source,
signed artifacts, provider states and remaining checks are recorded in
[release status](../release-status.md) and [mobile delivery](../mobile-release.md).
This record separates implemented behavior from real customer delivery.

## Connected and exercised

- Dedicated Supabase Auth/PostgreSQL, Fly API and private photo volume; verified
  email required, restricted database role, customer ownership and private bytes.
- Customer-to-Estimoto bridge deployed from the preserved original production
  baseline. Staff dashboard has a Plus inbox and explicit directory participation.
- Demolition Dent is published for PDR/collision in its saved ZIP 80221. Actual
  production matching and the authenticated customer directory both returned it.
- Live synthetic customer sign-in, garage, private shop contacts, unsent scheduling
  review, service/parts history and source-backed Estibot answers were exercised.
- Real local sockets and PostgreSQL exercised original Estimoto request delivery,
  replay, cancellation, required estimate evidence and staff status return. The
  reviewed amount was an explicit synthetic fixture, not a production estimate.
- Android build 4 was signed, publicly downloaded with matching hashes, installed
  in an emulator, and signed in through the normal code form. Its rounded launcher
  icon was visually checked. The requested invite email was delivered by Resend.
- Separate Apple app 6811678079 has processed builds, tester groups and James as
  an internal tester. External installation is gated by Apple's first beta review.

## Vehicle photo update

Backend migration e21870f6a94b and private upload/CarsXE routes passed 168 tests,
including actual original-source contracts and isolated PostgreSQL. Flutter photo
flows passed 68 tests and clean analysis, including narrow/large-text layouts,
late account/vehicle responses and Android recovery destination separation.
Build 5 is the vehicle-photo candidate; deployment and installed-device proof
must be added to release status after they complete.

## Customer rollout checks still distinct

- PDR LINX is the second authorized participant; its existing account has no
  service ZIP/address. Publishing its location routing awaits the user's ZIPs.
- Physical iOS/Android sign-in, camera and interrupted-picker recovery.
- First real customer-to-shop handoff and shop acceptance; no synthetic test sent
  a real shop message or created a production CRM job.
- Actual authentication email inbox verification. The delivered Android invite
  proves that email only; SMTP configuration and API sign-in checks are separate.
- Apple external beta approval and Google Play listing/publication.

CARFAX, push reminders, autonomous phone/SMS booking, and corpus-wide model
training are not connected. The graph is private, typed, customer-reported history
with source references; optional coarse contributed insights are off by default.
YouTube links are labeled searches. See [automotive knowledge](../automotive-knowledge.md).
