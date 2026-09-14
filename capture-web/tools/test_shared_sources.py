from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

from shared_sources import SOURCES, sync, verify


class SharedSourceTests(unittest.TestCase):
    def test_sync_pins_commit_and_detects_tampering(self):
        with TemporaryDirectory() as source_dir, TemporaryDirectory() as target_dir:
            source, target = Path(source_dir), Path(target_dir)
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "capture@example.test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Capture Test"], check=True)
            for path in SOURCES:
                file = source / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(".customer-camera { color: red; }\n" if path.endswith("index.css") else f"// {path}\n")
            subprocess.run(["git", "-C", str(source), "add", "dashboard"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-qm", "source"], check=True)
            manifest = sync(source, target)
            self.assertEqual(verify(target), manifest)
            (target / SOURCES["dashboard/src/pages/intake/GuidedCamera.tsx"]).write_text("tampered")
            with self.assertRaisesRegex(ValueError, "differs"):
                verify(target)

    def test_rejects_dirty_authoritative_source(self):
        with TemporaryDirectory() as source_dir, TemporaryDirectory() as target_dir:
            source = Path(source_dir)
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "capture@example.test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Capture Test"], check=True)
            for path in SOURCES:
                file = source / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(".customer-camera { }\n" if path.endswith("index.css") else "// source\n")
            subprocess.run(["git", "-C", str(source), "add", "dashboard"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-qm", "source"], check=True)
            (source / "dashboard/src/pages/intake/template.ts").write_text("// changed\n")
            with self.assertRaisesRegex(ValueError, "Commit original"):
                sync(source, Path(target_dir))


if __name__ == "__main__":
    unittest.main()
