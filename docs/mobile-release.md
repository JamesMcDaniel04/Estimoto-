# Mobile customer preview

Estimoto + uses `io.estimoto.plus`, display name `Estimoto +`, and the E+ icon.
Live builds connect to https://estimoto-plus-api.fly.dev/. Explicit demo mode
is isolated and does not send requests.

## Android 0.1.0 (7)

[Download the latest Plus APK](https://estimoto-plus-api.fly.dev/android/download) · [Current build and hash](https://estimoto-plus-api.fly.dev/android/current) · [Build-7 assets](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.7)

The permanent URL currently serves signed build 7 from source
`ebb7f47275b018f276744322bbb2c191438e4f7a`. This release adds private receipt
photos/PDFs, maintenance/repair/modification cost totals, CarsXE retail and
wholesale estimates, and available shop logos and credited photos. Guided
PDR/Collision capture and VIN confirmation remain available.

- APK: 61,615,687 bytes; SHA-256 `ab4e7af170f261fece55b978bdb3fb8c4c5e2172b167c18069f1177c7050f661`.
- AAB: 59,353,890 bytes; SHA-256 `313ce63ed57d9f12ae51c79dfd3983b6beaa1dbafdb20d0178ce5241aa630063`.
- Signer SHA-256: `e6d106fccc6c0e77e04a46c64f8edffdafb11b502d4857e51606c725086581dd` (unchanged).
- Min SDK 24, target SDK 36. Signed identity/version and exact public artifact bytes verified.
- Installing build 7 over the prior Plus app preserved the synthetic signed-in
  session. The Android emulator showed the recorded-cost rollup and rendered a
  private receipt PDF fetched from the live API; the viewer was then closed.
  After synthetic cleanup, the old session was rejected and explicit Sign out
  returned the emulator to the sign-in screen.
- The previously requested build-6 email was delivered with the permanent link.
  That same link now serves build 7; no new build-7 email was sent.

Installation is customer initiated. This is direct APK distribution; Google Play
publication and physical-device receipt/camera checks remain separate.

## iOS 0.1.0 (7)

[App Store Connect](https://appstoreconnect.apple.com/apps/6811678079/testflight) · [Customer Preview](https://testflight.apple.com/join/RZCXF6vx)

IPA: 24,877,153 bytes; SHA-256
`6b673b4861e2ad7b8602316a8b7784b644c429d163c23d54aea69ec64df47193`.
App Store Connect build `b31d8a1f-99a3-40b7-9841-137e854631c4` processed **VALID**.
Read-only Apple API verification on September 14 at 04:34 UTC confirmed:

- Internal Testers and Customer Preview are attached.
- Internal state: `IN_BETA_TESTING`; external state: `READY_FOR_BETA_SUBMISSION`.
- The 1,103-character en-US What to Test exactly matches the [build-7 notes](releases/0.1.0-7-beta-notes.md).
- Build 7 has no Beta App Review submission. Apple's attempted submission
  returned `ANOTHER_BUILD_IN_REVIEW`; build 2's existing submission remains
  `WAITING_FOR_REVIEW`. Its first review was preserved.

Group attachment and an enabled public link do not make build 7 installable by
external testers before Apple approval.

The new iOS simulator debug build succeeded, but simulator Keychain/signing
blocked authentication (`-34018`; subsequent signing attempts were rejected by
AMFI). The build-7 native iOS receipt view is therefore **unverified**. The signed
App Store IPA and its VALID processing state are unaffected; its signed
application identifier and `get-task-allow=false` were verified. Earlier simulator
Photo Library checks do not substitute for this new receipt check or a physical
iPhone test.

Apple team `J9HNN7TB36`; bundle registration `SFACWALLYZ`; distribution profile
`82QT2M2C8V`. Signing material and private synthetic QA evidence stay outside Git.
See [build-7 evidence](releases/2026-09-13-build7.json) and [build-6 history](releases/2026-09-13-build6.json).

## Reproduce and publish

`sh scripts/build_live.sh all` requires a clean checkout and ignored
`app/config/local.json` containing only supported public live fields. Provider
credentials stay on the backend. The mobile build writes an ignored receipt of
source SHA and signed APK/AAB hashes.

For Android, run `scripts/publish_android.sh --notes docs/releases/<notes>.md`
after building. It verifies identities, signatures and public bytes, then advances
the permanent pointer last. A GitHub upload alone is not current distribution.
Follow the permanent URL and compare its hash before any authorized invite.
See [release workflow](../backend/docs/android-download.md).

`build_beta.sh` produces a labeled demo. Current capability limits and remaining
provider setup are in [release status](release-status.md).
