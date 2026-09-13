# Mobile beta release

Estimoto + has the separate iOS/Android identity `io.estimoto.plus`, display name `Estimoto +`, and a customer-specific E-plus icon. Build 0.1.0 (1) is an explicitly labeled demo beta; it is not a live customer rollout.

## Current delivery — 2026-09-13

- Source/build commit: `558c35606bc29dac507e454fa264aa47a286eeef`. Flutter analysis and all 19 tests passed. Release IPA, release APK, signed AAB, web and iOS simulator builds passed. The branded simulator app was installed, launched and visually inspected.
- Android: [direct APK prerelease](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.1) published. The APK and AAB signatures match the existing owner-controlled Estimoto release certificate. Both public downloads were downloaded anonymously and their SHA-256 hashes matched the local artifacts. No Android device was connected, so physical installation is not claimed. Google Play listing/internal-track publication is not performed.
- iOS: bundle ID registered and distribution profile `82QT2M2C8V` active. The exported IPA passed signature verification and contains bundle `io.estimoto.plus`, display name `Estimoto +`, version `0.1.0`, build `1`. The profile disallows release debugging.
- TestFlight: app record creation and upload are pending App Store Connect website sign-in. Both available browser sessions were signed out. Apple requires [new app records to be created on the website](https://developer.apple.com/documentation/appstoreconnectapi/apps); the existing API key is available for subsequent uploads and tester setup. No upload, processing or tester availability is claimed yet.

Artifact identities, checksums and delivery status are recorded in [mobile-beta-1.json](releases/2026-09-13-mobile-beta-1.json). The local IPA is `app/build/ios/ipa/Estimoto +.ipa`; do not rebuild or change its build number merely because website sign-in is pending.

## Build

Use `sh scripts/build_beta.sh` on a clean committed checkout. This creates the App Store Connect IPA, release APK, Android App Bundle and web preview with `PLUS_DEMO=true`. Read the [beta notes](releases/0.1.0-1-beta-notes.md) before distribution.

iOS uses Apple team `J9HNN7TB36`, bundle registration `SFACWALLYZ` and the `Estimoto Plus App Store` provisioning profile. Its App Store Connect app record must be created on Apple's website; the bundle registration and signing profile are separate from that record. The release export preserves the build number. Check the IPA's embedded bundle ID, version, build and signature before upload, then confirm processing and tester attachment separately.

Android uses an owner-controlled release keystore configured locally in ignored `app/android/key.properties`. It can use the existing Estimoto release signing identity while keeping its own package name and update history. Release builds refuse to fall back to debug signing. Keep the keystore and its backup outside this public repository.

The Android APK can be distributed as a prerelease asset in this repository. The AAB is for a separately configured Google Play listing; building an AAB does not create or publish that listing. Neither artifact replaces the staff app's downloads.

## Brand assets

The source image is [estimoto-plus-icon.png](../app/assets/brand/estimoto-plus-icon.png). The built-in image edit tool added a white plus inside Estimoto's teal dot. [Asset notes](../app/assets/brand/README.md) preserve the prompt, and `scripts/sync_app_icons.py` packages the artwork into native/web sizes using macOS `sips`.
