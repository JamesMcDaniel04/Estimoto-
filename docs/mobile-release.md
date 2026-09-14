# Mobile customer preview

Estimoto + uses `io.estimoto.plus`, display name `Estimoto +`, and the E+ icon.
Live builds connect to https://estimoto-plus-api.fly.dev/. Explicit demo mode
is isolated and does not send requests.

## Android 0.1.0 (6)

[Download the latest Plus APK](https://estimoto-plus-api.fly.dev/android/download) · [Current build and hash](https://estimoto-plus-api.fly.dev/android/current) · [Build-6 assets](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.6)

The permanent URL follows the current verified release pointer and currently
serves build 6. Installing over an existing Plus installation preserves the
account. Installation is customer initiated; this is a direct APK distribution.

Source `08c156de08b626da9de1ba10975f214a2a89d41b` includes the capped local shop
directory, dedicated shops, shared 3D customer capture, VIN photo confirmation,
continuous guided camera and compact Estibot photo help.

- APK SHA-256: `13bf8d789ea9a099d4708e7c8d3e1b8278885e949caa165d157a10ba380851f6`
- AAB SHA-256: `2d2ddf88ede240df4f16d97314f27e58c2d3191938ad5570e8913c79f37990c5`
- Signer SHA-256: `e6d106fccc6c0e77e04a46c64f8edffdafb11b502d4857e51606c725086581dd`
- Min SDK 24, target SDK 36. Signed package/version and public exact bytes verified.
- The build-5 upgrade preserved the synthetic account, vehicle, draft and photo.
  Interrupted capture recovery required explicit retry. Live Estibot photo help
  and VIN confirmation were exercised in the Android emulator.
- The latest specifically requested Android email was delivered with the permanent
  link. Google Play publication and physical camera-quality checks are separate.

## iOS 0.1.0 (6)

[App Store Connect](https://appstoreconnect.apple.com/apps/6811678079/testflight) · [Customer Preview](https://testflight.apple.com/join/RZCXF6vx)

IPA SHA-256 `ff8d1a9dce044c7e6c0f08e42021b1d28510d2866c593a038c9c8385dfccc0a7`.
App Store Connect build `151a340f-7220-4b08-8c74-cabaa53c8ee2` processed VALID,
What to Test is set, and Internal Testers plus Customer Preview are attached.
Internal state is `IN_BETA_TESTING`; external state is `READY_FOR_BETA_SUBMISSION`.

Apple refused simultaneous external review with `ANOTHER_BUILD_IN_REVIEW`.
Build 2 (`71673590-792c-4fcd-828b-c30cc92d2255`) remains
`WAITING_FOR_BETA_REVIEW`; its first review was preserved. Attaching groups or
uploading does not establish public-link installation. Native and guided Photo
Library pickers opened in the iOS simulator; physical-device checks remain separate.

Apple team `J9HNN7TB36`; bundle registration `SFACWALLYZ`; distribution profile
`82QT2M2C8V`. Signing material and private customer QA evidence stay outside Git.
See [build-6 evidence](releases/2026-09-13-build6.json).

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
