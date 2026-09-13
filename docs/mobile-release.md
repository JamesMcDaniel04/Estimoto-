# Mobile beta release

Estimoto + has the separate iOS/Android identity `io.estimoto.plus`, display name `Estimoto +`, and a customer-specific E-plus icon. Build 0.1.0 (1) is an explicitly labeled demo beta; it is not a live customer rollout.

## Build

Use `sh scripts/build_beta.sh` on a clean committed checkout. This creates the App Store Connect IPA, release APK, Android App Bundle and web preview with `PLUS_DEMO=true`. Read the [beta notes](releases/0.1.0-1-beta-notes.md) before distribution.

iOS uses Apple team `J9HNN7TB36`, bundle registration `SFACWALLYZ` and the `Estimoto Plus App Store` provisioning profile. Its App Store Connect app record must be created on Apple's website; the bundle registration and signing profile are separate from that record. The release export preserves the build number. Check the IPA's embedded bundle ID, version, build and signature before upload, then confirm processing and tester attachment separately.

Android uses an owner-controlled release keystore configured locally in ignored `app/android/key.properties`. It can use the existing Estimoto release signing identity while keeping its own package name and update history. Release builds refuse to fall back to debug signing. Keep the keystore and its backup outside this public repository.

The Android APK can be distributed as a prerelease asset in this repository. The AAB is for a separately configured Google Play listing; building an AAB does not create or publish that listing. Neither artifact replaces the staff app's downloads.

## Brand assets

The source image is [estimoto-plus-icon.png](../app/assets/brand/estimoto-plus-icon.png). The built-in image edit tool added a white plus inside Estimoto's teal dot. [Asset notes](../app/assets/brand/README.md) preserve the prompt, and `scripts/sync_app_icons.py` packages the artwork into native/web sizes using macOS `sips`.
