# Mobile customer preview

Estimoto + uses the separate iOS/Android identity `io.estimoto.plus`, display name `Estimoto +`, and E-plus branding. Live builds connect to https://estimoto-plus-api.fly.dev. Explicit demo mode remains available and does not send requests.

## Android 0.1.0 (4)

[Download APK](https://github.com/JamesMcDaniel04/Estimoto-/releases/download/v0.1.0-beta.4/estimoto-plus-0.1.0-4.apk) · [Release assets](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.4)

Source `24703ecf783029e186a782651698d54eabcf2cb3`. Rounded vector fallback, Android adaptive icon resources and `roundIcon` preserve the E+ geometry. The master PNG and iOS icon assets are unchanged; iOS applies its own icon mask.

- APK SHA-256: `97dc353597893ef495715d2c5288f1606a9ce7f41e007d6e1f086bd9da3fcb52`
- AAB SHA-256: `a9b79a377bf7a12c00db857456e6b5c2d9912de575f4cf08b8d4b42f16860636`
- Signing certificate SHA-256: `e6d106fccc6c0e77e04a46c64f8edffdafb11b502d4857e51606c725086581dd`
- Min SDK 24; target SDK 36; package/version verified from the built APK.
- Public APK/AAB bytes were downloaded and matched the local SHA-256 values. APK installed and launched in Android emulator; launcher rounding was visually verified.
- The user-requested invite email containing this APK link was delivered through Resend. Google Play publication and physical-device installation are separate checks.

## iOS 0.1.0 (3)

[App Store Connect](https://appstoreconnect.apple.com/apps/6811678079/testflight) · [Customer Preview public link](https://testflight.apple.com/join/RZCXF6vx)

The public link remains gated by Apple's external beta review. An upload or a group attachment does not establish that an external tester can install it.

Source `a5403daf8f71f5820671388f049588a84b840196`. IPA SHA-256 `6ed5e737e2862d142a212026b9872171cae6d3d33d17fcd2c409b423015fa450`. Embedded bundle, version, build and encryption declaration verified. App Store Connect build `96257072-1dd2-4b84-a511-442736aacc77` processed **VALID**, What to Test set, and Internal Testers/Customer Preview attached. James's account-holder identity is assigned to Internal Testers.

Build 2 (`71673590-792c-4fcd-828b-c30cc92d2255`) is the first submitted external beta review. Submitting build 3 returned `ANOTHER_BUILD_IN_REVIEW`; keep the first review queued, then submit build 3 once it completes. The newest source change in build 3 adds existing-code entry; normal email sign-in already exists in build 2. Internal build state is `IN_BETA_TESTING`; external availability and physical-device installation must be verified separately.

Apple team `J9HNN7TB36`; bundle registration `SFACWALLYZ`; App Store distribution profile `82QT2M2C8V`. Signed artifacts and provisioning material are kept outside version control. Building an AAB does not publish a Play listing, and building an IPA does not distribute it to testers.

## Reproduce

`sh scripts/build_live.sh all` requires a clean checkout and ignored `app/config/local.json` containing only the four supported public live fields. The script refuses demo mode or server credentials. For an Android-only icon change, build APK/AAB with the same live config and record the exact source SHA; leave already uploaded iOS artifacts intact.

The old `build_beta.sh` command intentionally produces a labeled demo; it is not the live release command. See [current release status](release-status.md) and the original beta-1 JSON under `releases/` for historical artifacts.
