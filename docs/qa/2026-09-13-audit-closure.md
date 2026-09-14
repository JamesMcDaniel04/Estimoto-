# Launch audit follow-up — builds 8 and 9

Current delivery: [build 10](../releases/2026-09-14-build10.json) restores the
network request button and includes Settings. Its 217 app tests/analysis and
published artifact checks are recorded separately. The build-8/9 audit evidence
below remains historical; build 10 changes no backend code.


The September 13 audit examined Plus build 7 (`ebb7f47275b018f276744322bbb2c191438e4f7a`).
Build 8 was published from `e5d0e4ad40ba93866e1905f55c6046d6b4824588`; the full
integration gate ran on its parent `47f8eedfb749509d8540e8468b1cf0eada639308`.
The intervening publisher-only redirect fix passed 16 focused tests. The gate
passed 410 backend tests with zero skips, 208 Flutter tests with clean analysis,
19 capture-web tests/build and all three socket smokes. Source, local validation,
live behavior, device use and external approval remain distinct evidence.
Build 9 (`9dc9e750f63b73cbbd920c27b5f6d14534e4c5e8`) adds profile-opening
shop cards and the hashed brand asset, with 209 Flutter tests, clean analysis and
19 capture tests/build passing. It changes no backend files from build 8; the
410-test backend/socket evidence remains the earlier gate, not a repeated run.
See [build-9 evidence](../releases/2026-09-14-build9.json),
[build-8 evidence](../releases/2026-09-14-build8.json),
[release status](../release-status.md) and [mobile delivery](../mobile-release.md).

| Finding | Resolution | Evidence / remaining check |
| --- | --- | --- |
| H1: main behind production | `main` and `origin/main` were fast-forwarded from the old `1a69205` history to include artifact source `e5d0e4a`; README uses the permanent Android URL. | Local and remote-tracking refs matched the delivered source. No force-push; the build-9 record separately identifies delivered source `9dc9e75`. |
| H2: hosted CI billing lock | Four configured jobs now cover Flutter, backend/PostgreSQL and capture; a complete local release gate passed. | **External block remains:** build-9 [run 34814184249](https://github.com/JamesMcDaniel04/Estimoto-plus/actions/runs/34814184249), annotation check `103881307863`, all four jobs had zero steps because account billing prevented startup. No hosted CI pass is claimed. |
| H3: pure-Dart socket no longer compiles | Repository imports platform-free pending-operation types; native adapters remain in the UI. | Integrated API/pure-Dart real HTTP smoke and restart checks passed. |
| H4: capture tests omitted | Capture build runs tests before bundling; CI has a capture-web job. | 19 Vitest tests, TypeScript/Vite build and integrated capture gate passed locally; hosted execution is blocked under H2. |
| H5: contradictory docs | Backend/API/launch, discovery, Calendar and artwork docs describe current implemented behavior; release docs identify build 9 and preserve build-8 evidence. | Build-4/5 evidence remains historical. Submission, capture v2, images/valuation, 30-result reviewed directory and saved-zone behavior were reconciled with source. |
| M1: public production docs | Production disables `/docs`, `/redoc`, `/openapi.json`; development retains them. | All three returned 404 in the live build-8 surface checks. |
| M2: missing-record dead ends | Unavailable screens keep back navigation, deleted-vehicle copy is accurate and missing guided estimates do not crash. | Navigation/deletion/account-change regressions passed within the 208-test Flutter gate. |
| M3: demo phone scheduling has no call | Authorized phone-only drafts become `call_required` with a validated call URI. | Regression verified explicit consent and the exact mocked dialer launch. It did not call a real shop. |
| M4: default Calendar UTC | New setup suggests a validated device IANA zone only for an unconfigured preference; explicit saved UTC survives reconnect; demo uses Denver. | Flutter/backend first-save, reconnect and late-night regressions passed. Signed Android/iOS artifacts built; physical-device timezone behavior remains unverified. |
| M5: every read rechecks Auth | Per-app pooled client and bounded successful GET/HEAD cache coalesce duplicate verification. Writes verify fresh and invalidate reads. | Expiry, revocation, error, capacity, concurrency and app-isolation tests passed; see the explicit read-revocation tradeoff below. |
| M6: missing web frame/security headers | Main pages set HSTS and frame protection; guided capture retains same-origin embedding. | Live headers, restrictive capture policy and exact served bytes passed the surface gate. |
| M7: overly broad Estibot promise | Prompt names supported estimate/routine-care/matching/scheduling topics and explains diagnostic limits. | Source review and full Flutter gate passed; no general diagnostic-AI claim. |
| L1: malformed email called empty | Empty and malformed addresses have separate messages. | Welcome validation regressions passed without sending email. |
| L2: demo valuation disabled | A synthetic VIN and fixed fictional result demonstrate the layout. | Widget regression verifies sample attribution and no CarsXE result claim; demo performs no provider call. |
| L3: inaccurate WebView resume doc | Integration docs describe pause, reload and a fresh handshake on resume. | Checked against the native host; reserved resume RPC is distinguished. |
| L4: stale web shell | Entry HTML, bootstrap, service worker, main bundle and version/manifest require revalidation. | Live header and conditional-304 checks passed. Build 9 deployed the content-hashed brand asset; its bytes match exactly and a returning browser displayed the new logo without clearing its cache. |
| L5: 34 skipped integration cases | Isolated PostgreSQL and actual original bridge source exercised all 34 cases. | Clean integrated gate: **410 passed, zero skipped**; source unchanged, cluster stopped/removed and port closed afterward. |

Twenty live surface checks passed; the directory/media check returned 27 listings
with complete website/phone fields and 27 decoded images (26 logos and one shop
photo). All 26 independent content-addressed image hashes matched. Browser QA
rendered all 27 images and a mini profile after synthetic sign-in. The exact
public Android-8 APK upgraded build 7 on an emulator, showed the new artwork and
completed synthetic native sign-in. The native directory loaded, displayed
Bronco's Muffler's real logo and opened its mini profile. No repair shop was
contacted and no request was created;
synthetic checks do not prove real mailbox use.

Build-8 synthetic QA data cleanup is complete: global sign-out preceded removal
of the exact new Auth account, profile and rate rows, and other customer-owned
tables were confirmed empty before cleanup. The old token was rejected with 401
on a write and a subsequent GET. The real customer account was untouched and no
private files were uploaded. The native app displayed the ended-session screen;
signing out returned to welcome, completing that UI check.

Build-9 live verification confirmed `/version` at `9dc9e75`, readiness at schema
`a63e90b72d14`, matching JavaScript bytes and the exact hashed brand image. A
returning browser displayed the new logo without clearing its cache. The exact
public build-9 APK upgraded build 8 on an emulator; version 9 and welcome artwork
were verified. Both web and native demo checks opened a card/profile and saved
PDR, with the native returned list displaying “Your dedicated shop: PDR”. These
checks created no new live Auth account or shop outreach and do not prove a live
owner's saved-shop outcome. Both demo sessions were left at welcome and the owned
QA browser tab was closed; the real-owner code tab and user preview were preserved.

## Authentication capacity tradeoff

Only upstream-confirmed, non-anonymous identities are cached. Keys are SHA-256 token hashes; raw tokens, user metadata, errors and negative responses are not retained. GET/HEAD cache entries last at most 15 seconds from verification start and never beyond JWT expiry; monotonic and absolute clocks both bound reuse. Capacity is 1,024 identities and 64 in-flight checks per app. Mutations always reverify and invalidate the token's read cache before and after verification. An upstream-revoked token can therefore remain readable for the remainder of that brief read window; it cannot use the cache to authorize an edit.

This reduces duplicate authentication calls; it is not a load-test result or proof of multi-machine readiness. Private uploads still use the current mounted volume. Wider scaling needs a shared storage/worker plan before adding replicas.

## Reproduce a complete local release gate

Use a **new disposable local PostgreSQL database**, with test-only `anon` and `authenticated` roles, and a local checkout of the original Estimoto backend. The tests create/reset their test schema. Never supply a production database URL.

Set `PLUS_TEST_POSTGRES_URL`, `CALENDAR_TEST_POSTGRES_URL` and `DISCOVERY_TEST_POSTGRES_URL` to that disposable database's `postgresql+psycopg://` URL. Set `ESTIMOTO_BRIDGE_BACKEND` to the original backend directory and `ESTIMOTO_BRIDGE_PYTHON` to its prepared Python environment. No bridge production key is needed.

From the clean Plus candidate, run:

```sh
python3 scripts/check_release.py --integration --output /tmp/plus-release-checks-unique
```

The gate records its source SHA, log hashes, return codes and backend skip count, then rejects source changes during the run. It runs backend pytest, Flutter analysis/tests, capture-web tests/build, API plus pure-Dart socket checks, discovery socket checks and calendar socket checks. `--integration` rejects any skipped backend test. Keep raw logs private until reviewed; copy sanitized results into release evidence. Stop and remove only the temporary PostgreSQL cluster created for that run.

## Checks that remain separate

- A normal real-customer sign-in code was requested through the UI; inbox/code
  entry is still pending. Synthetic browser/emulator sign-in cannot prove mail
  delivery or code entry by the customer.
- The freshly requested Android invite was sent once, accepted at 06:16:05 UTC
  and confirmed delivered by Resend readback at 06:16:26 UTC on September 14.
  Its unchanged permanent URL now serves build 9; no duplicate email was sent.
  This proves invite delivery only, not opening, installation or authentication.
- Hosted GitHub Actions remains blocked by account billing. Resolve the account
  issue and rerun the four jobs; local success is not a substitute for a hosted run.
- Read-only Apple verification at 06:44:57 UTC confirmed build 9 VALID, exact
  632-character notes and both groups, internal `IN_BETA_TESTING` and external
  `READY_FOR_BETA_SUBMISSION`. No build-9 review submission was attempted;
  build 2 remains `WAITING_FOR_REVIEW`. Original Estimoto build 232's separate
  approval does not approve Plus.
- Physical iOS/Android camera, receipts, interrupted-picker recovery and a first
  real shop handoff/acceptance remain unverified. Google Calendar provider setup
  remains disabled; no real customer Calendar connection/event is proved.
- Build-9 web/Android publication, returning-browser refresh and demo profile/save
  checks are verified; see the [release record](../releases/2026-09-14-build9.json).
  Build-8 synthetic cleanup and native ended-session/sign-out UI checks remain
  preserved historical evidence. Credentials, cohort identifiers, private files
  and raw cleanup journals stay outside Git.
