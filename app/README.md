# Estimoto + mobile app

Separate Flutter customer application, bundle/application ID `io.estimoto.plus`, with iOS, Android and a web preview. It does not reuse the Estimoto staff session or provision a shop account.

## Preview

Use Flutter 3.44.1 / Dart 3.12.1:

```sh
flutter pub get
flutter run --dart-define=PLUS_DEMO=true
```

Choose an iOS simulator, Android device or Chrome from Flutter's device list. `flutter build web --dart-define=PLUS_DEMO=true` creates a static preview in `build/web`. Demo records are fictional and live only in memory; reload resets them. Every main screen identifies demo mode. Requests never contact a real provider.

Without compile-time configuration the app opens its welcome screen with an explicit demo entry. Live failures never fall back to sample records.

## Connect the customer API

Copy `config/live.example.json` to ignored `config/local.json`, fill in the dedicated API origin and Supabase **publishable** key, then run:

```sh
flutter run --dart-define-from-file=config/local.json
```

Allow `io.estimoto.plus://login-callback/` in the Supabase Auth redirect configuration for native email links. Email OTP entry is also provided. Do not put service-role keys or bridge keys into a mobile build. Native sessions use Keychain/encrypted Android storage; web sessions are memory-only. The backend verifies each bearer token and owns authorization. Unresolved service requests retain their approved body and replay key in account-scoped encrypted storage, including across app restarts; web authentication tokens still stay in memory. Confirm an interrupted send from Repairs before changing its details or creating another request.

A development API token can be supplied as `PLUS_DEV_TOKEN` in an ignored local configuration for debug builds only. Never include development tokens in a release configuration. Use `http://127.0.0.1:8000` from an iOS simulator or desktop, and `http://10.0.2.2:8000` from an Android emulator. Production origins require HTTPS. Browser API access additionally requires the backend's explicit CORS allowlist.

## Checks

```sh
flutter analyze
flutter test
flutter build web --dart-define=PLUS_DEMO=true
flutter build ios --simulator --no-codesign --dart-define=PLUS_DEMO=true
flutter build apk --debug --dart-define=PLUS_DEMO=true
```

PDR/Collision drafts reuse garage details. Provider requests have a review and consent step; delivery, provider acceptance and scheduling are separate states. The first assistant uses deterministic common-care guidance and provider matching; care topics link retrieved YouTube videos when the server is configured and search links otherwise. General AI answers, live Estimoto estimating/repair feeds and CARFAX are integration milestones listed in `../docs/release-status.md`.

Reminder alerts are local notifications scheduled on the device from the customer's own reminders (a heads-up 1–14 days ahead and again at 9:00 AM on the due date), turned on from Settings after the system permission prompt. No push token or server is involved; the web preview and the demo never schedule them. Android needs core library desugaring and the boot receiver already declared in the manifest. Settings also shows the live Google Calendar and Gmail connection states; the Gmail screen scans read-only for car-service mail and prefills a service history entry the customer reviews before saving.
