# Foundation release status — 2026-09-13

This is the first runnable Estimoto + app/API milestone. Source is independent of the Estimoto staff app. It is not a production customer launch.

## Verification

The app source was built at `a6f8d85`; the subsequent backend cancellation fix is `929eded`. Documentation and test-runner changes follow these commits. Migration head: `d752dbef8104`.

| Evidence | Result |
| --- | --- |
| Flutter static analysis | Passed, no issues |
| Flutter tests | 16 passed: customer journeys, transport, consent/cancel, uncertain-send recovery, account changes and refresh ordering |
| API tests | 55 passed: customer isolation, auth, private uploads, bridge state transitions/replay, races/leases, cancellations and migrations |
| Fresh migration + schema comparison | Passed on SQLite, including a populated legacy cancellation upgrade |
| Python/Dart socket smoke | Passed against a migrated API and fictional local auth/provider receiver; private photos, two-customer isolation, durable requests and restart persistence |
| Web release build | Passed; rendered at 390×844 and 1280×900; navigation, matching, consent review and sample request status inspected |
| iOS simulator build | Passed with `io.estimoto.plus`; installed, launched and screenshot inspected |
| Native bundle identity test | `RunnerTests.testCustomerBundleIdentity` passed through xcodebuild on iOS 26.5 simulator |
| Android debug APK | Passed on final app source; no Android device install claimed |
| Live Supabase, Estimoto receiver and customer sends | Not performed |
| Store distribution / physical devices | Not performed |

The browser preview explicitly labels fictional sample records. The API smoke uses actual sockets but only a local identity fixture and fictional provider receiver; it is not evidence of production delivery. SQLite concurrency checks do not establish PostgreSQL production behavior. The native identity test verifies the app identity, not camera, authentication or secure-storage behavior.

Current toolchain warnings: the pinned secure-storage plugin uses CocoaPods and does not support WebAssembly; the JavaScript web build and iOS build succeed. Xcode emits dependency deployment-target/stale-product warnings during the native test. The API test dependency emits a Starlette/AnyIO deprecation warning. These are recorded rather than represented as warning-free native/backend runs.

## Implemented behavior

Saved profile/vehicle/insurance fields, PDR/Collision drafts and private photo uploads, reminders, provider filtering and map links for published addresses, authenticated estimate/repair snapshots and an assistant-guided service-request workflow. The assistant currently uses deterministic guidance and structured matching, with clearly labeled YouTube search links.

The app handles offline auth stream errors, replaces data on account changes, rejects stale refresh completions and keeps an interrupted request's approved body/key in account-scoped encrypted storage. Repairs provides recovery for that unresolved send; restoring it does not automatically send. The server snapshots approved contact/vehicle/ZIP data, retries under a database lease and only marks delivery after a durable receipt. Cancellation events can safely precede a delayed creation when the receiver honors the documented tombstone contract.

## Remaining launch work

1. Provision a private PostgreSQL database and persistent photo storage, deploy the customer service, configure its Supabase Auth project/redirects and prove email sign-in, deep links, logout/session expiry and encrypted storage on physical devices.
2. Implement and deploy the Estimoto-side receiver and opt-in provider publishing. Explicitly link consumer records to estimate/repair histories, drive authoritative updates, and verify delivery/cancellation under PostgreSQL and real provider workflows.
3. Finish guided native capture, Android interrupted-picker recovery, thumbnail/readback UX and PDR/Collision estimator submission. Draft creation currently does not submit to the production estimator or generate a price.
4. Add push notifications and date/mileage reminder delivery. Current reminders persist and display in-app; they do not yet send alerts or read a vehicle's odometer automatically.
5. Add model-backed Estibot and retrieved/curated video results, with evaluations for common repair questions and technician matching. Current search links are not verified individual videos.
6. Confirm CARFAX partner access, data rights, coverage and mapping before implementing service-history ingestion and automatic maintenance alerts. No CARFAX integration is claimed.
7. Finish app icons/store assets, signing, accessibility/device QA, privacy disclosures and store distribution. Generated launch icons are placeholders.

## Reproduce

See [README](../README.md), [app instructions](../app/README.md), [backend instructions](../backend/README.md), and `scripts/smoke_api.py --flutter-client`. CI runs analysis, tests, the web build and isolated socket checks; CI runner execution is separate from local checks.
