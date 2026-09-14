# CRUD closure verification — September 14, 2026

Deployed application source: `a01ee14dfc48ca2fde0214592c6935c075c2334f`.
This commit includes the approved reminder, estimate/photo, outreach, history,
valuation, assistant and demo UI work, plus final reliability fixes.

## Final fixes

- Reject null or blank required update fields before they reach persistence.
- Serialize draft estimate mutations with submission and capture; handle a
  removed capture receipt without returning an unexpected server error.
- Preserve discarded outreach creation keys so a delayed retry cannot recreate
  the draft. Recover an uncertain device save before discarding its server row;
  retain local recovery data when the server outcome remains uncertain.
- Compare demo idempotency bodies canonically, matching live payload semantics.
- Incorporate upstream readiness fix `5004740`, preserving newer main commits.
  The old readiness check rejected the successfully migrated database and
  caused Fly to stop routing traffic. The current check accepts the migration
  head and regression tests exercise both the expected revision and endpoint.

## Verification

- Flutter: 247 tests passed; analyzer reports no issues.
- Backend against SQLite and disposable local PostgreSQL: 433 passed, seven
  optional original-Estimoto interservice tests skipped because that backend
  was not configured. One dependency deprecation warning.
- All three HTTP smoke scripts passed (API with Flutter client, calendar,
  discovery). Identity and upstream services in those scripts are synthetic.
- Capture web: 19 tests passed; production build succeeded.
- The original customer PDF uploaded successfully to an isolated local API,
  downloaded byte-for-byte, and was deleted. The private file was not committed.
- Deploy script exited 0. `/version` matched the source above; `/ready` returned
  ready at `b7f2c9d4e1a0`; Fly machine `784567ef969378` passed its health check.
- Served `main.dart.js` matches the local release artifact, SHA-256:
  `91412efbd2f5d8d19564b72876840cf1d74d91878aef86fa65a5de80fac882ef`.
- Deployed browser: welcome/demo loads, reminder editing saves and returns the
  changed reminder in the garage. Additional automated widget flows cover
  history edits retaining receipts, draft discard/withdraw and locked estimates.

## Distribution limits

This is a web/API release. `/android/current` still reports build 11 from the
previous release; that native artifact does not contain the new CRUD screens.
The active, root and prior deployment checkouts have no Android release
`key.properties`; no replacement native artifact was signed or published.
iOS build 11 and its prior review state were not changed or reverified.
Physical-device behavior, real customer sign-in/mailbox delivery and real
provider transactions are not established by these local or demo checks.
