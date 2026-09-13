# Customer launch work — September 14, 2026 at 2 p.m. America/Denver

The user expanded the demo milestone to a usable customer launch. This document tracks work, not a production-readiness claim.

## Working scope

- Separate Estimoto + identity, original Estimoto cradled bottom navigation.
- Real confirmed-email sign-in; account-scoped secure sessions, saved contact/vehicle/insurance details.
- Guided eight-photo PDR/Collision capture, private readback, interrupted-picker recovery and explicit selected-shop sharing consent. PDR also requires a supported damaged-panel photo.
- Durable estimate handoff to the existing Estimoto intake/review pipeline, with existing evidence and billing gates. Human-reviewed amounts only.
- Explicit opt-in shop/technician discovery, customer requests, staff acceptance/scheduling, customer delivery/status tracking.
- Useful bounded Estibot advice and matching. Requests remain customer-confirmed.
- Signed customer mobile builds, TestFlight processing/distribution and permanent web fallback.
- CARFAX requires partner access; no connected-history or automatic-service claim until verified.

## Provisioned resources

- Dedicated Supabase project `nqaymvmqiwcmdtliwstu`, Estimoto Plus, us-east-1, PostgreSQL 17. Direct TLS connection verified.
- Fly app `estimoto-plus-api`; encrypted `plus_photos` volume, 10 GB, iad, automatic snapshots with 14-day retention.
- Customer auth redirects: `io.estimoto.plus://login-callback/` and `https://estimoto-plus-api.fly.dev/`. Confirmed email required, anonymous sign-in disabled, 8-digit codes expire after 10 minutes. Custom Resend SMTP configured; TLS/authentication verified, actual inbox delivery pending.
- Apple app record created in signed-in Chrome: `6811678079`, name Estimoto +, bundle `io.estimoto.plus`, SKU `estimotoplusios`. No build uploaded at this checkpoint.
- Credentials are kept outside version control. Mobile config contains only the server origin and publishable auth key.

## Source ownership and release baselines

- Plus repo: `90852a5` contains the cradled navigation and keyboard/composer regression. Production backend/capture integration in progress.
- Original Estimoto UI: `88be72c1` on the existing mobile branch (patch from `44ef7f0e`); 193 focused tests and analyzer passed. Physical release pending.
- Original production API observed at `bd7d1d3e1a79119a7f6eca36580cd41a6bcfe546`. Integration must preserve that baseline, including migrations 0209–0211. Do not deploy the older mobile branch's backend.

## Required verification before customer-ready claim

- Migrations on PostgreSQL; private API tables inaccessible to public Supabase roles.
- Real Supabase sign-in and expired/revoked token checks; no cross-customer data or late photo attachment after account change.
- Customer-to-staff delivery, replay/tombstone races, required capture validation, staff actions and return status over deployed services.
- Restart recovery for requests, estimates, uploads and background delivery; clear errors for unavailable services.
- Mobile analysis/tests, native build identities/signatures, installed simulator flows; physical-device evidence reported separately.
- Apple VALID processing, notes/groups and external beta review recorded separately. Android delivered hashes verified.
- First participating shop/technicians: user clarification pending. No provider is opted in automatically.
