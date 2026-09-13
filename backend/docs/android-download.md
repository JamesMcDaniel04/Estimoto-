# Stable Android download for Estimoto +

The permanent public tester link is `https://estimoto-plus-api.fly.dev/android/download`. It needs no customer session. The API reads `current.json` from the dedicated public `android-releases` Supabase Storage bucket with a fresh cache nonce and redirects to the immutable GitHub release APK it names. `/android/current` returns the same validated version, byte count, SHA-256, pinned signing certificate, and relative download URL. Both responses use `Cache-Control: no-store`; a missing or malformed pointer returns 503 without redirecting. The API keeps no Supabase service key.

The bucket is intentionally limited to 1 MB JSON objects; this project's Storage object-size limit is below the 58 MB beta.5 APK. GitHub releases host the versioned binaries, so the current pointer is the only mutable object. The publisher updates it last after proving the remote APK matches the local signed package. A new Android build does **not** require an API or web redeploy to advance the emailed link.

For each release:

1. Build the signed `io.estimoto.plus` APK with an increasing Android `versionCode`. Keep the existing release signing certificate.
2. Publish the APK as `estimoto-plus-<versionName>-<versionCode>.apk` under GitHub tag `v<versionName>-beta.<versionCode>` in `JamesMcDaniel04/Estimoto-`. Keep this versioned asset immutable.
3. From `backend/`, run `PYTHONPATH=. .venv/bin/python scripts/publish_android_current.py --apk ../app/build/app/outputs/flutter-apk/app-release.apk`. The script reads the private Plus Supabase URL and service-role key from `~/.config/estimoto-plus/`; never place the key in Fly, source, release notes, or client code.
4. Verify `/android/current`, follow `/android/download` without authentication, and hash the downloaded APK. Do not email a new invitation until the stable URL resolves the new file and hash.

The publisher rejects an unexpected package, signature, bad version, absent/mismatched public asset, and version rollback. Repeating the exact current release is a no-op. If Storage or the GitHub asset fails, it leaves the previous pointer in place. The endpoint is a direct APK download, not a Google Play invitation.

Current pointer: version `0.1.0+5`, APK SHA-256 `fcdccd1ac2ca87a31b63f6716058378b94dbecb9e367eaac0a1eeb56ee643934`, signing certificate SHA-256 `e6d106fccc6c0e77e04a46c64f8edffdafb11b502d4857e51606c725086581dd`.
