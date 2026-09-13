#!/usr/bin/env python3
"""Copy the selected logo into platform asset sizes using macOS sips.

This packages existing artwork; it does not generate or redraw the logo.
"""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
SOURCE = APP / 'assets/brand/estimoto-plus-icon.png'


def resize(destination, pixels):
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['sips', '-z', str(pixels), str(pixels), str(SOURCE), '--out', str(destination)],
                   check=True, stdout=subprocess.DEVNULL)


def main():
    icons = APP / 'ios/Runner/Assets.xcassets/AppIcon.appiconset'
    for item in json.loads((icons / 'Contents.json').read_text())['images']:
        if item.get('filename'):
            pixels = round(float(item['size'].split('x')[0]) * float(item['scale'].rstrip('x')))
            resize(icons / item['filename'], pixels)
    launch = APP / 'ios/Runner/Assets.xcassets/LaunchImage.imageset'
    for scale in (1, 2, 3):
        resize(launch / f'LaunchImage{"" if scale == 1 else f"@{scale}x"}.png', 120 * scale)
    for density, size, scale in [('mdpi', 48, 1), ('hdpi', 72, 1.5), ('xhdpi', 96, 2), ('xxhdpi', 144, 3), ('xxxhdpi', 192, 4)]:
        resources = APP / 'android/app/src/main/res'
        resize(resources / f'mipmap-{density}/ic_launcher.png', size)
        resize(resources / f'drawable-{density}/launch_image.png', round(120 * scale))
    resize(APP / 'web/favicon.png', 32)
    for size in (192, 512):
        resize(APP / f'web/icons/Icon-{size}.png', size)
        # The square logo fits within the maskable safe area after platform padding.
        target = APP / f'web/icons/Icon-maskable-{size}.png'
        resize(target, round(size * 0.66))
        subprocess.run(['sips', '--padToHeightWidth', str(size), str(size), '--padColor', '0D3F7A', str(target)],
                       check=True, stdout=subprocess.DEVNULL)
    print('Updated iOS, Android, launch and web assets from the selected Estimoto + icon.')


if __name__ == '__main__':
    main()
