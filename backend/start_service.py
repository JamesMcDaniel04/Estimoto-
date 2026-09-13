"""Create the private mounted photo directory, then drop service privileges."""
import os
from pathlib import Path
import sys

if os.geteuid() == 0:
    photos = Path(os.environ.get("PHOTO_DIR", "/data/photos"))
    photos.mkdir(parents=True, exist_ok=True)
    os.chown(photos, 10001, 10001)
    os.chmod(photos, 0o700)
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
os.execvp(sys.argv[1], sys.argv[1:])
