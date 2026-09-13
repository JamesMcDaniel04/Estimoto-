# Local customer-to-shop socket proof — September 13, 2026

Passed at **14:57:48 America/Denver**. This is local integration evidence, not production, real-provider, browser, or device evidence.

## Tested source

- Original Estimoto checkout: `/Users/jamesmcdaniel/Estimoto/.worktrees/plus-launch-integration-20260913`, HEAD `5c5cfaaf4dcb5211a4f52e1160139586d4fe63cc`. The bridge implementation is `baefb2f02f97abc469757da883cf76dfa2f66c77` (cherry-picked from `3bf25216e5426fbe2342d4198482a5451253a0b8`). The checkout also contained the parent's uncommitted owner-insights route; that route was not part of this socket scenario.
- Customer checkout: `/Users/jamesmcdaniel/Estimoto-`, HEAD `904af4d8dcd9f9fb518457d5822868641b582083` at server start. This includes bridge contract fix `f1cdf18` and persistent service-request quota `c24efaff99d2f4710ba062892dd94ba462536d49`. Parent GraphRAG/assistant edits were also present; this scenario exercised requests, photos, estimates and status, not the assistant.
- Later mail hardening `1c36e015e5d35b031c190f252ae7276a1c21ba30` and the current GraphRAG working changes were covered by the subsequent full customer backend suite: **131 passed, 1 skipped in 14.10 seconds**. The skipped check requires `PLUS_TEST_POSTGRES_URL`; all actual-source bridge contract tests ran.

These were shared integration checkouts with the explicitly identified working changes, not clean immutable release builds. Release provenance must be verified separately after final commits and deployment.

## Harness and command

Artifacts are preserved in `/tmp/estimoto-plus-socket-proof-20260913/`:

- `original_server.py`, `customer_server.py`: isolated API wrappers.
- `drive.py`: HTTP lifecycle assertions.
- `original.log`, `customer.log`, `drive.log`, `result.json`: run evidence.

```sh
# Run from /tmp/estimoto-plus-socket-proof-20260913
/Users/jamesmcdaniel/Estimoto/backend/.venv/bin/python -m uvicorn original_server:app --host 127.0.0.1 --port 18543 --lifespan off --log-level warning
/Users/jamesmcdaniel/Estimoto-/backend/.venv/bin/python -m uvicorn customer_server:app --host 127.0.0.1 --port 18544 --lifespan off --log-level warning --ssl-certfile cert.pem --ssl-keyfile key.pem
/Users/jamesmcdaniel/Estimoto-/backend/.venv/bin/python drive.py
```

The wrappers seed separate disposable SQLite databases. Re-running from scratch requires new empty fixture databases. Private photo transfer used HTTPS with the local certificate explicitly trusted; certificate verification remained on. Provider fetch URLs and bridge/photo ownership checks were the real application paths. External socket connections were restricted to loopback.

## Verified behavior

- Customer request creation and identical retry produced one durable receipt and one visible normal CRM job.
- Staff acceptance and scheduling returned through the authenticated bridge to the customer; customer cancellation returned to the original job/request.
- A second customer could not read the first customer's request or photos. Bridge photo access without the machine key returned 401.
- Collision's eight required photos and PDR's eight required photos plus one `panel_hood` photo traveled from private Plus storage through the actual original importer with size/hash checks.
- Both estimates progressed from submitted/pending to reviewing/complete, with no customer amount exposed during review.
- An immutable **synthetic reviewed-document fixture** then produced ready/12,345 cents through both real APIs. This proves status/amount gating and transport, not staff review UI or real estimate accuracy.
- Final original database: **3 jobs, 1 explicitly bound customer, 1 vehicle, 2 billing usage rows**, with 8 collision and 9 PDR intake panels. Billing was queued in the normal durable ledger; no Stripe call or charge occurred.
- The normal intake submission flow created exactly **4 existing shop notice queue rows**: two `submission` and two `submission_sms`. All remained pending with **zero attempts**. No customer document, repair authorization, insurer send, real email, or real SMS was sent.

Vision/quality providers and authentication identities were synthetic. The actual HTTP servers, original handlers, relationship binding, photo storage/import, fee eligibility/ledger, receipt persistence and customer status consumer ran normally. Uvicorn lifespan was disabled, so the production scheduler and send workers did not run. Worker delivery endpoints were driven explicitly; local outbox due times were advanced to avoid waiting between each photo.

## Source contract regression command

```sh
cd /Users/jamesmcdaniel/Estimoto-/backend
ESTIMOTO_BRIDGE_BACKEND=/Users/jamesmcdaniel/Estimoto/.worktrees/plus-launch-integration-20260913/backend \
ESTIMOTO_BRIDGE_PYTHON=/Users/jamesmcdaniel/Estimoto/backend/.venv/bin/python \
.venv/bin/python -m pytest -q --tb=short
```

`tests/test_original_bridge_contract.py` passes real Plus-produced payloads into the original backend's actual Pydantic schemas and passes the actual original `estimate_view` output back into Plus validation and ownership/status application. It also checks maximum provider publication bounds, request preflight failures, and the persistent 20/hour request quota with replay exemption.
