# Receipt work details and refresh — build 14

Estimoto+ **0.1.0+14** is deployed from `2390c5ed418a6c2d5db6e98b1424354848ce9176`, with recent main commits preserved. Web/API and the signed Android download match that source; readiness reports schema `d9e4b82013c7`. [Release evidence](../releases/2026-09-14-build14.json) · [Android download](https://estimoto-plus-api.fly.dev/android/download).

The Repairs page now lists the work and parts read from repair PDFs and receipt photos beneath Recorded costs. Each list stays attached to its history entry, vehicle and private source receipt. Descriptions retain the receipt wording. Item amounts are for reference; only the history entry’s saved total contributes to recorded spending. Existing manual costs remain protected, and unclear extraction is marked for review.

The bounded local parser recognizes numbered service sections and flat item rows, omits totals/payment/terms and deferred or recommended-work sections, and never invents missing repairs. The supplied invoice yielded six service sections in local verification. A bounded production backfill updated one older saved receipt; a repeat found zero remaining receipts needing that parser version. No private invoice text or customer identity was logged by the backfill.

## Verification

- All **254 Flutter tests passed**, including a regression that first reproduced the stale main Refresh behavior and now proves both newly available receipt details and deleted costs reload for the same vehicle. Analysis is clean. The backend receipt/parser suite passed **27 tests**; backend code is unchanged between builds 13 and 14.
- Live synthetic PDF and photo uploads each extracted two work sections and a **$129.90** total. Idempotent replays returned the same attachment; private bytes matched and anonymous reads returned 401. The total was saved once per history entry.
- Signed native build 13 displayed both parsed receipts, their tasks and parts, the correct combined $259.80 total, and the link to the receipt details screen. [Historical build-13 evidence](../releases/2026-09-14-build13.json).
- The final audit found that the main Refresh button did not invalidate history loaded separately from bootstrap. Build 14 fixes this and replaces misleading empty-details text. The regression failed before the fix and passed afterwards.
- Signed native build 14 updated the existing emulator installation and retained the QA session. Starting from an empty vehicle, a receipt was added through the live API while Repairs stayed open. Main Refresh then showed its tasks, parts and **$129.90** total. Deleting that record through the API and refreshing cleared the tasks and returned costs to zero while retaining the same vehicle. This was verified without changing tabs or restarting.
- The permanent Android URL and served JavaScript match the built artifact hashes. Native version code is 14. The temporary account was signed out, all three QA receipt files/tombstones, history records, vehicles and residual rows were removed, and the auth account was deleted. Removed credentials returned 401 for reads and writes. No shop call, SMS or email was sent for this receipt QA.

Native evidence: [recorded costs](build14/recorded-costs.png), [parsed tasks and parts](build14/receipt-work.png), [deletion refresh](build14/deleted-refresh.png).

## Distribution and remaining external gates

Android build 14 is published through the permanent direct APK link. iOS build `6e1f66f3-8049-4b37-bf2d-f7613331430f` is **VALID**, with exact 798-character notes and both tester groups attached; internal state is **IN_BETA_TESTING**. External state remains **READY_FOR_BETA_SUBMISSION** because Apple rejected submission with `ANOTHER_BUILD_IN_REVIEW`. The existing review was not withdrawn.

Dynamic vehicle/ZIP/name discovery controls remain included. Google Places activation still requires the account owner’s Google Cloud verification; New York public-provider coverage remains unreliable. This release does not claim nationwide provider coverage, physical-device proof or Google Play publication. The separately requested original Estimoto build-233 email and its delivery are documented in the original Estimoto repository.
