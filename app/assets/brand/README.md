# Estimoto + icon artwork

`estimoto-plus-icon.png` is the selected 1024×1024 opaque master artwork for the
build-8 update: a white geometric E on a darker sky-blue background, a
green/teal brand dot, and a smaller navy plus outside the dot. The dot sits
above-left of the plus. The header and welcome screen use the generated
`plusIconAsset` constant from `app/lib/brand_assets.dart`. It points to a copy
whose filename includes the first 16 hexadecimal characters of the master
SHA-256, so a changed image gets a new browser-cache identity.
This asset description does not establish which artwork is installed on a
device or distributed in a released build.

The Android launcher uses a scalable companion encoded in
[`scripts/sync_app_icons.py`](../../../scripts/sync_app_icons.py). Its palette is
sky blue `#58A4E5`, white `#FFFFFF`, navy `#0D3F7A`, and teal `#00B8A9`.
The script writes the companion as adaptive and circular legacy vector resources
with padding for the launcher mask. It separately resizes the master for iOS
app icons, native launch images, the web favicon and web app icons. These are
packaged derivatives of the selected design; the script does not edit the master.
It also writes the content-hashed asset copy and its Dart constant. Native build 8
already contains the correct image. The asset reference for returning browsers
is included with the shop-profile changes in forthcoming build 9; distribution
and final browser-cache verification remain outstanding. Final evidence belongs in
[release status](../../../docs/release-status.md).

From the repository root on macOS:

```sh
python3 scripts/sync_app_icons.py
```

The full command regenerates native/web derivatives using `sips`. Use
`--android-launcher-only` to update only the Android launcher vectors and palette.
Review the master and companion together after an artwork change, including the
dot/plus separation and small-size launcher appearance. Changing the master alone
does not update the companion paths stored in the script.
