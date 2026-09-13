# Estimoto + Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver the first runnable, tested Estimoto + customer app and persistent API in the new repository.

**Architecture:** Flutter customer UI consumes a repository interface, with explicit demo and HTTP implementations. A standalone FastAPI customer service owns consumer records and a trusted integration bridge connects existing Estimoto shop workflows.

**Tech Stack:** Flutter 3.44.1 / Dart 3.12.1, FastAPI, SQLAlchemy, Alembic, SQLite local / PostgreSQL deployment, Supabase Auth.

**Spec:** `docs/superpowers/specs/2026-09-13-estimoto-plus-design.md`

## Global Constraints

- Product name `Estimoto +`; application ID `io.estimoto.plus`.
- Bottom tabs: Garage, Estimates, Estibot, Repairs, Find Help; estimate disciplines pdr/collision.
- Contract: `docs/api-contract.md`; no production data, tokens or credentials in source.
- Demo requires explicit entry and always shows its identity; no simulated real delivery.
- No customer access to staff roles, arbitrary customer records or provider mutations.
- General AI, Estimoto production bridge, push delivery and CARFAX require separately verified deployment configuration.

### Task 1: Persistent customer API and request workflow

**Files:** Create `backend/pyproject.toml`, `backend/estimoto_plus/` modules for config/auth/db/models/routes/assistant/bridge, `backend/alembic/`, `backend/tests/`, `backend/README.md`, `backend/.env.example`.

**Interfaces:** Produces every `/v1` route and snake_case shape in `docs/api-contract.md`; `create_app(settings)` supports isolated test databases and injected auth/transport. UI consumes bootstrap, garage mutations, estimate drafts/photos, providers, requests, reminders and assistant responses.

- [x] Write focused API acceptance and regression tests, including this acceptance contract:
```python
response = customer.post('/v1/requests', headers={'Idempotency-Key': 'first-request'}, json=request_body)
assert response.status_code == 201
assert response.json()['status'] == 'requested'
assert other_customer.get('/v1/requests').json() == []
assert customer.post('/v1/requests', headers={'Idempotency-Key': 'first-request'}, json=request_body).json()['id'] == response.json()['id']
```
- [x] Run the tests, record the missing-behavior failure, implement the customer-scoped schema/auth/API and run them green.
- [x] Test bridge request delivery with HTTP transport fixture, replayed/out-of-order events, missing bridge, opted-out providers, invalid photo type and cross-customer IDs.
- [x] Add a migration, locked dependencies and backend run/deployment instructions; commit only backend files.

### Task 2: Flutter app, domain models and customer journeys

**Files:** Create generated `app/` iOS/Android/web targets; `app/lib/domain/`, `app/lib/data/`, `app/lib/state/`, `app/lib/screens/`, `app/lib/widgets/`, `app/test/`.

**Interfaces:** Consumes `docs/api-contract.md`. Produces `EstimotoPlusApp`, `PlusController`, `PlusRepository`, demo and HTTP repositories. Explicit startup configuration controls Supabase authentication and API base URL; no cloud secrets.

- [x] Generate platform files and add meaningful model/repository/widget acceptance tests (strict test-before-implementation chronology is not claimed for every file):
```dart
await tester.pumpWidget(EstimotoPlusApp(controller: demoController));
expect(find.text('Garage'), findsWidgets);
await tester.tap(find.text('Estimates').last);
await tester.pumpAndSettle();
expect(find.text('PDR'), findsOneWidget);
expect(find.text('Collision'), findsOneWidget);
```
- [x] Implement models/transport/controller and signed-in or explicit-demo startup. A failed network request remains an error and cannot enter demo.
- [x] Build the approved five-tab UI and full add/edit vehicle, estimate draft/photo, provider request review/send/cancel and reminder flows. Submit only after the customer's specific send action and display pending provider response.
- [x] Implement Supabase email sign-in with a separate app redirect, sanitized errors, account edit/sign-out and safe session refresh. Run widget and controller tests.
- [x] Inspect rendered app at narrow/wide sizes; build web and simulator targets and commit app files.

### Task 3: Contract integration, verification and repository delivery

**Files:** Create `README.md`, `docs/release-status.md`, `scripts/smoke_api.py`, `.github/workflows/ci.yml` and local preview configuration.

**Interfaces:** Consumes real API + Flutter HTTP transport. Produces reproducible developer commands and verified build evidence.

- [x] Boot backend on loopback with a temporary persistent database and explicit demo mode; run real-socket smoke with this persistence check:
```python
vehicle = client.post('/v1/vehicles', json={'year': 2024, 'make': 'Toyota', 'model': 'Camry'}).json()
assert any(row['id'] == vehicle['id'] for row in client.get('/v1/bootstrap').json()['vehicles'])
```
- [x] Exercise owned-vehicle request creation, idempotency, cancellation and photo ownership through the socket; verify a fictional bridge receiver separately.
- [x] Review API/UI contract and cross-customer security, fix findings and run required checks.
- [x] Publish verified source to the supplied repository and show the app preview. Initial `main` publication verified at `9d08a44`; local demo served at port 4318. Final review approved the first runnable milestone, with production integrations separately documented.
