# Mobile customer preview — build 14

Package `io.estimoto.plus`, source `2390c5ed418a6c2d5db6e98b1424354848ce9176`.
[Download latest Android](https://estimoto-plus-api.fly.dev/android/download) · [Build-14 evidence](releases/2026-09-14-build14.json) · [Verification](qa/2026-09-14-build14-verification.md) · [Notes](testflight-build14.txt)

Receipt tasks and parts now appear beneath Recorded costs with links to their private receipts. Main Refresh reloads newly parsed work and cost changes. All 254 app tests passed, analysis is clean, and the signed native build passed live receipt-addition and deletion refresh checks. Public APK and served web hashes match the built artifacts.

iOS 14 is VALID with exact notes and both groups; internal testing is available. External review is blocked by another build in review. Google Cloud verification and Places activation remain pending. Physical-device and Google Play proof remain separate.

## Historical build 12

Package `io.estimoto.plus`, source `c66ecb4c8b2a47da572bd9659825dd14b6c2a79f`.
[Download latest Android](https://estimoto-plus-api.fly.dev/android/download) · [Build-12 evidence](releases/2026-09-14-build12.json) · [Verification](qa/2026-09-14-build12-verification.md) · [Notes](releases/0.1.0-12-beta-notes.md)

Receipt totals now populate empty Recorded costs from private PDF/photo parsing. Build 12 also publishes the dynamic vehicle/ZIP/name discovery controls and completed CRUD improvements. The exact public Android APK was hash-verified and upgraded over 11 on an emulator; native PDF selection, upload, parsed total and refreshed history passed.

iOS 12 is VALID internally with exact notes and both groups. External submission remains blocked by another build in review. Google Places activation still needs Google Cloud account verification; nationwide live coverage remains unverified. Physical-device installation and Google Play publication are separate.

## Historical build 11


Package `io.estimoto.plus`, source `9c53dd85889938dd40a8195b89dc4a43bc98f4f9`.
[Download latest Android](https://estimoto-plus-api.fly.dev/android/download) ·
[Build-11 evidence](releases/2026-09-14-build11.json) ·
[Release notes](releases/0.1.0-11-beta-notes.md)

Add service history now exposes Take photo, Choose photo and Choose PDF above
the optional details, with Save history entry fixed at the bottom. A receipt
action saves the entered details first, then opens the inline receipt editor.
Canceling selection retains the saved entry; pending uploads keep their retry
identity. The browser requires a fresh picker click after the save.

All 227 app tests, analysis, 15 focused backend receipt/PDF checks, one Chrome
picker check and 19 capture-web tests passed. The capture build passed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| APK | 62,534,023 | `b935330a70aae1e4d297399a4116ecfd8372e1d46a231a383f262839d5512e41` |
| AAB | 60,328,339 | `8f1d35a9f735434cefae8e7eef2d68fdf344c709dca8caebb597e60f3703d19a` |
| IPA | 25,900,287 | `2a2ecf658eb91513563098c539ed637d2d8a717d4e945735f3cb33baf2d68288` |

The Android signer remains `e6d106fccc6c0e77e04a46c64f8edffdafb11b502d4857e51606c725086581dd`.
The exact public APK installed over build 10 on an emulator. A scoped synthetic
customer selected a labeled PDF through Android's native file picker, uploaded
it to the live service, rendered it privately, canceled another selection and
reopened the saved entry. The server held one record and one receipt; bytes
matched the fixture, and anonymous access returned 401. The account, vehicle,
record, receipt file and derived data were removed; the old token then returned
401 for reads and writes. No shop request or email was sent.

Apple build `8c5faefa-35cf-4df4-b008-3cce5c6ff57f` is VALID with exact
592-character notes and both tester groups. Internal state is IN_BETA_TESTING;
external state is READY_FOR_BETA_SUBMISSION. Build 2's review remains pending.
The permanent Android URL in the existing delivered invite serves build 11.
Physical-device and real customer mailbox proof remain separate.

## Historical build 10

[Build-10 evidence](releases/2026-09-14-build10.json) records source
`62683757a569c3c82e37bbbf03be6658d780f77f`, the network Request help card button,
Settings, 217 app tests and its own signed artifacts. The build-9 record below
is also historical; earlier evidence has not been relabeled as build 11.

## Android 0.1.0 (9)

[Download the latest Plus APK](https://estimoto-plus-api.fly.dev/android/download) ·
[Current build and hash](https://estimoto-plus-api.fly.dev/android/current) ·
[Build-9 assets](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.9)

At build-9 delivery, the permanent URL served signed build 9 from
`9dc9e750f63b73cbbd920c27b5f6d14534e4c5e8`. Tapping a shop card opens the profile,
which holds Call, Website, Google Maps/reviews and available request/save actions.
See the [build-9 notes](releases/0.1.0-9-beta-notes.md).

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| APK | 62,533,943 | `2b09fb67d7db2120930711fd34056febcebb799498ba2d16c1536e2032ce93c2` |
| AAB | 60,303,839 | `a097f13d2e19bec303f6f4770936dc8c54b66ca36621863c182b897acbfa6fea` |

Signer SHA-256 remains
`e6d106fccc6c0e77e04a46c64f8edffdafb11b502d4857e51606c725086581dd`.
The exact public APK was downloaded, hash-checked and installed over build 8 on
an emulator. Version 9 and the new welcome logo were verified. Native demo QA
opened a shop card and its profile, saved PDR in the dedicated-shop choice dialog,
and verified “Your dedicated shop: PDR” on the returned list. No new Auth account
or shop outreach was used. These checks do not prove a live customer's
saved-shop outcome, real mailbox/code entry or a physical-device install.

The fresh invite was sent once for build 8, accepted at 06:16:05 UTC and confirmed
`delivered` by Resend readback at 06:16:26 UTC, September 14. Its permanent URL
uses the permanent URL shown above. No duplicate email was sent. Recipient details, the provider
message ID and send journal stay private. Delivery does not prove that the
recipient opened the email or installed the APK.

Installation remains customer initiated, with no automatic updater. This is
direct APK distribution; Google Play publication is separate.

## iOS 0.1.0 (9)

[App Store Connect](https://appstoreconnect.apple.com/apps/6811678079/testflight) ·
[Customer Preview](https://testflight.apple.com/join/RZCXF6vx)

IPA: **25,894,533 bytes**, SHA-256
`d6f975da327bcc93a8c88424c551247bc28a63869f60f1eba7b33730b4a11441`.
The signed artifact uses source `9dc9e750f63b73cbbd920c27b5f6d14534e4c5e8`.
Upload completed successfully at 06:41:54 UTC on September 14. Read-only Apple
verification at 06:44:57 UTC confirmed build
`dd9ff8ea-63b9-4f01-a6f3-b723eeca283d` **VALID**, with exact 632-character notes and
Internal Testers/Customer Preview attached. Internal state is `IN_BETA_TESTING`;
external state is `READY_FOR_BETA_SUBMISSION`. Build 9 has no review submission,
and none was attempted; build 2 remains `WAITING_FOR_REVIEW`. The public link does
not establish external build-9 installability. Physical iPhone
sign-in/camera/receipt behavior remains unverified.

## Browser branding and local validation

The hashed brand asset generated by `sync_app_icons.py` and referenced through
`brand_assets.dart` is now deployed. The live JavaScript matches the local build,
and the image SHA-256 is
`fc3222881ab13091274c6571bf2adb2353da05200107b87c7eb288397237a5b3`.
A returning browser displayed the new artwork without clearing its cache. Web demo
QA opened a shop card, its profile and the saved PDR-shop choice. Both demo
sessions were left at welcome and the owned QA browser tab was closed; the
real-owner code tab and user preview were preserved.

Build 9 passed 209 Flutter tests with clean analysis and 19 capture-web tests plus
the build. Backend files are unchanged from build 8. The full backend evidence
remains 410 passed, zero skipped on `47f8eed`, with all three socket smokes; the
publisher-only follow-up in `e5d0e4a` passed 16 focused tests. These are distinct
runs, not a repeated build-9 backend gate.

## Historical build 8

The [build-8 record](releases/2026-09-14-build8.json) preserves its exact
`e5d0e4a` APK/AAB/IPA hashes and earlier live/device checks. Its public APK upgraded
build 7, completed synthetic native sign-in, loaded the live directory, showed
Bronco's Muffler's real logo and opened the mini profile. Synthetic QA cleanup
removed only the exact new account/profile/rate rows after global sign-out and
empty-table checks; the old token was rejected on write and GET. The native
ended-session screen and sign-out back to welcome were verified. The real
customer account was untouched. Build-9 checks do not repeat or relabel that
signed-in evidence.

Apple readback at 06:22:53 UTC confirmed build 8 VALID, exact 1,960-character
notes, both groups and internal testing. Build 8 had no review submission and
remained `READY_FOR_BETA_SUBMISSION` externally; the preserved build-2 submission
was `WAITING_FOR_REVIEW`. Build-9 readback confirmed that review remains. Original Estimoto build
232 has separate external approval, which does not approve Plus.

## Reproduce and publish

`sh scripts/build_live.sh all` requires a clean checkout and ignored
`app/config/local.json` containing only supported public live fields. Provider
credentials stay on the backend. The mobile build writes an ignored receipt of
source SHA and signed APK/AAB hashes.

For Android, run `scripts/publish_android.sh --notes docs/releases/<notes>.md`
after building. It verifies identities, signatures and public bytes, follows only
the bounded trusted repository-rename redirect, and advances the permanent pointer
last. A GitHub upload alone is not current distribution. Follow the permanent URL
and compare its hash before any authorized invite. See the
[release workflow](../backend/docs/android-download.md).

`build_beta.sh` produces a labeled demo. See [release status](release-status.md)
for current provider/device limits and [build-7 evidence](releases/2026-09-13-build7.json)
for historical receipt/emulator checks. Earlier proof is not relabeled as build-9 QA.
