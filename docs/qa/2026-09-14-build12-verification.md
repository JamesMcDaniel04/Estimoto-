# Build 12 verification — September 14, 2026

Source `c66ecb4c8b2a47da572bd9659825dd14b6c2a79f` is merged into main and deployed to Estimoto +. Recent commits were preserved. `/version` matches that source, `/ready` reports schema `d9e4b82013c7`, and served JavaScript matches the built bytes. [Machine-readable release evidence](../releases/2026-09-14-build12.json).

## Receipt totals

Digital PDFs and receipt photos are parsed privately on the service. A confident USD total fills an empty Recorded costs amount. Existing costs are preserved, uncertain totals require review, and retrying an upload cannot add a second charge. Users can read older receipts, review a replacement total or edit the recorded amount manually.

The supplied 11-page invoice parsed locally as **$1,703.48**; its private bytes were not uploaded to production. Synthetic live PDF and photo fixtures produced **$1,703.48** and **$108.25**. Replays returned the same attachment, byte hashes matched, and anonymous reads were rejected. Browser QA changed an existing $50 cost and verified the explicit replacement review.

The exact public Android APK installed over build 11. Its native PDF picker uploaded the synthetic PDF and displayed **Recorded total (USD): $1,703.48**. Returning to history refreshed to one receipt and that amount. The server confirmed two QA records totaling $3,406.96, with one attachment each. Browser and native QA sessions were signed out; the synthetic account, vehicles, records, files, receipt tombstones and residual rows were removed. Old credentials were rejected with 401 on reads and writes. No shop message, call or email was sent.

## Validation and delivery

- Backend: **471 passed, 7 skipped**. The skips are preexisting optional original-backend contract checks whose referenced files are absent.
- Flutter: **252 passed**; analysis clean. Capture web: **19 passed**. All-surface build exited 0.
- Android: signed build **12**, permanent download and GitHub assets verified by hash; native search controls and receipt flow checked on an emulator. Direct APK distribution, not Google Play.
- iOS: build **12 VALID**, exact 1,080-character notes and both groups verified. Internal testers can use it. External beta submission was rejected because another build remains in review; attaching the external group does not establish external installation availability.

## Discovery coverage still requires provider activation

The native ZIP, shop-name and vehicle-match controls are published in build 12. Live browser QA found The ToyShop for Toyota, and Bluewater Performance / EuroWerkz for Audi in 80229. Switching vehicles changed matching and results; searching another ZIP did not change the saved profile ZIP.

The New York 10001 public-provider check still failed and displayed the explicit partial-results state. Google Places support, attribution, privacy boundaries and a shared capped request budget are implemented and tested, but the production key/flag have not been activated. Google Cloud requires the account owner to complete verification before setup can continue. Nationwide live coverage is **not closed**. Physical-device checks and external Apple distribution remain separate from source/build/emulator proof.
