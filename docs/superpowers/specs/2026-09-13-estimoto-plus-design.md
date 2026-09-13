# Estimoto + customer app

Approved in conversation on 2026-09-13: a separate customer app named Estimoto + in JamesMcDaniel04/Estimoto-, with Garage, Estimates, Estibot, Repairs and Find Help navigation; PDR and Collision tabs; saved contact, insurance and vehicles; status tracking; provider discovery; and conversational service requests.

## First implementation milestone

Build a runnable Flutter iOS/Android app (web preview also supported), a persistent customer API, an explicit demo environment, and a tested integration contract for the existing Estimoto backend. The user requested starting the build, not an App Store launch in this turn. Deliver source, executable flows, verification and a truthful record of remaining production integration work.

The first milestone includes profile and garage CRUD, estimate drafts with incident-specific fields and private photo attachments, estimate/repair history supplied by a trusted Estimoto bridge, provider discovery with specialty/postal-code/mobile-service filters, service-request creation and cancellation, provider response ingestion, reminders stored by date/mileage, and Estibot structured triage and matching. General AI answers and CARFAX are provider capabilities, never simulated as live integrations. A deterministic Estibot handles common topics and request drafting without a paid model dependency.

## Architecture and isolation

- `app/`: Flutter 3.44.1 / Dart 3.12.1 client. Shared Estimoto design language; separate application ID `io.estimoto.plus`, app name `Estimoto +`, and release configuration. Domain models and a repository separate UI from transport. No dependency on the sibling checkout at runtime.
- `backend/`: FastAPI customer service with SQLAlchemy persistence, Alembic migration and authenticated `/v1` routes. SQLite supports local development; a dedicated private PostgreSQL database/schema supports deployment. No direct browser access to customer tables.
- Reuse Supabase Auth with an explicit URL and publishable key; verify bearer identities against Auth's server endpoint. Never provision a shop, trust user-editable roles, auto-link by VIN/email, or use a service-role key in the app.
- A fixed, authenticated Estimoto bridge owns opt-in provider publishing, customer estimate/repair snapshots, request delivery receipts and provider decisions. Customer clients cannot write quote amounts, repair progress, provider availability or acceptance.
- Demo data is explicitly entered through “Explore demo.” It uses fictional customers/providers, never sends external requests, and is visibly labeled on every tab. No live-to-demo fallback after authentication/network errors.
- New code stays in the new repository. Integration of the bridge into the existing Estimoto deployment is a separately tracked rollout dependency; first milestone uses a contract fixture over a real socket for verification.

## Data and behavior

Customer profile stores name, phone, postal code and preferred contact method. Verified email comes from authentication. Vehicles store year/make/model, nickname, VIN, mileage, insurer and policy number. Claim/date-of-loss/damage fields are attached to each estimate. A customer selects a saved vehicle and never repeats stable information per request.

Estimate drafts have discipline `pdr` or `collision`, customer description, claim details and attached photographs. They remain drafts until an estimating integration accepts them. No price is generated locally. Repair timelines show authoritative status and update timestamps.

Provider discovery exposes only opted-in public business information; records identify shops or technicians and have specialties, service postcodes, mobile capability, accepting status and source shop/technician IDs. No invented precise distance, rating or availability. Maps launch a provider's verified public address through an external map URL in this milestone.

A request links one owned vehicle and one eligible provider, has specialty, description, preferred timing and explicit `share_contact=true`. Repeated submissions use an idempotency key; changed payloads with a reused key conflict. Creating a request does not book work. States: `requested`, `accepted`, `scheduled`, `declined`, `cancelled`, `completed`; scheduling requires an actual scheduled time. Declined/cancelled/completed requests cannot regress. Delivery is tracked independently as `local_preview`, `queued`, `delivered`, `failed` or `cancelled`. Live delivery is durable and retryable; a missing bridge returns an actionable unavailable response, never fictional success.

Estibot returns useful advice and a structured matching intent. It asks for missing specialty/vehicle/postal code and offers matching providers. A review screen shows the destination and shared data before the customer's send action. Estibot never sends by merely classifying a message. Sensitive repairs receive appropriate professional guidance. Videos are retrieved/curated URLs with provenance, not invented IDs; unconfigured search uses clearly labeled YouTube search links. CARFAX is visibly unconnected, with no invented service history.

## Visual direction

Colors: Estimoto blue `#1565C0`, navy `#0D3F7A`, teal `#00B8A9`, canvas `#F3F5F8`, ink `#172B4D`, white `#FFFFFF`. Use the system sans-serif face with clear 28/22/17/15/13 sizes. Left aligned page titles, an airy vehicle hero, compact actionable rows, and a prominent Estibot center button. Preserve PDR/Collision segmented tabs and tab state. Responsive content max-width 760; controls remain usable at 320px and enlarged text. Respect safe areas, keyboard insets and semantics.

## Verification and delivery

Test cross-customer denial, invalid/unverified identity, disabled demo in production, provider opt-in/eligibility, idempotent requests, state transitions, bridge authentication, photo ownership and transport failures. Test Flutter model parsing, repository contracts and real widget flows. Build web and an iOS simulator app, exercise the UI and inspect screenshots. Use a real-socket API smoke to prove persistence and request flow. Commit lockfiles, migrations, local run instructions, CI and a release-status document. Push verified source to the user-provided empty repository. Do not claim live provider delivery, live sign-in, production estimation, CARFAX access, push delivery or App Store distribution from local evidence.
