# Mobile customer preview

Estimoto + uses the separate iOS/Android identity `io.estimoto.plus`, display name
`Estimoto +`, and E+ branding. Live builds connect to https://estimoto-plus-api.fly.dev/.
Explicit demo mode is isolated and does not send requests.

## Android 0.1.0 (5)

[Download APK](https://github.com/JamesMcDaniel04/Estimoto-/releases/download/v0.1.0-beta.5/estimoto-plus-0.1.0-5.apk) · [Release assets](https://github.com/JamesMcDaniel04/Estimoto-/releases/tag/v0.1.0-beta.5)

Source `ec2dafffbd62b424ddd1b6928268b6ecce547365`. Vehicle cards use conservative
CarsXE matching or private camera/gallery uploads. Uploads take priority and can
be removed. Rounded vector/adaptive launcher resources preserve the E+ geometry.
iOS applies its own mask to the master icon.

- APK SHA-256: `fcdccd1ac2ca87a31b63f6716058378b94dbecb9e367eaac0a1eeb56ee643934`
- AAB SHA-256: `ba98f731d15e064f77ff633771e2131419ad0a2d9cd516c3fd5da70aa5a26d1c`
- Signing certificate SHA-256: `e6d106fccc6c0e77e04a46c64f8edffdafb11b502d4857e51606c725086581dd`
- Min SDK 24; target SDK 36; package/version verified from the built APK.
- Public APK/AAB bytes were downloaded and matched the local hashes. APK installed
  over build 4 and retained its live synthetic customer session. CarsXE display,
  real camera capture, system photo-picker replacement and removal were exercised
  in an Android emulator against the live backend. Killing the app process while
  its camera was open preserved the original vehicle destination, showed a saved
  capture on relaunch, and required explicit retry before upload.
- The requested Android invite email containing the preceding build-4 APK was
  delivered through Resend. The latest build-5 link is above. Google Play
  publication and physical-device installation are separate checks.

## iOS 0.1.0 (5)

[App Store Connect](https://appstoreconnect.apple.com/apps/6811678079/testflight) · [Customer Preview link](https://testflight.apple.com/join/RZCXF6vx)

The public link remains gated by Apple's external beta review. Uploading or
attaching a group does not establish external installation.

Source `ec2dafffbd62b424ddd1b6928268b6ecce547365`. IPA SHA-256:
`307d223f9c4d3ab5fc323b8840bdfc247670dd38f9383aa1078ff5de68203c04`.
Embedded bundle/version/build/encryption declaration verified. App Store Connect
build `e25901e4-98c1-4c73-b22f-de3cfd407a11` processed **VALID**, What to Test has
939 characters, and Internal Testers plus Customer Preview are attached. James is
assigned to Internal Testers; internal state is `IN_BETA_TESTING`.

Build 2 (`71673590-792c-4fcd-828b-c30cc92d2255`) remains the first external review
submission. Submitting build 5 returned `ANOTHER_BUILD_IN_REVIEW`; the first review
was retained. Submit build 5 after that review completes. Build 5 has the new
photos; build 3 added cross-device existing-code entry. Actual external availability
and physical-device photo/sign-in behavior must be verified separately.

Apple team `J9HNN7TB36`; bundle registration `SFACWALLYZ`; distribution profile
`82QT2M2C8V`. Signed artifacts and provisioning material are outside version control.

The [build-5 evidence record](releases/2026-09-13-build5.json) captures exact source,
checks, hashes and provider states.

## Reproduce

`sh scripts/build_live.sh all` requires a clean checkout and ignored
`app/config/local.json` containing only the four supported public live fields. The
script refuses demo mode or server credentials. CarsXE credentials stay on the
backend. Record exact source, signatures and served hashes before distribution.

`build_beta.sh` intentionally produces a labeled demo. See [release status](release-status.md)
and [launch checks](launch/2026-09-14-customer-launch.md) for current evidence.
