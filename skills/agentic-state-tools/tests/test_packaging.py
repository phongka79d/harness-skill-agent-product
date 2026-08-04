from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from package_skill import build_package, package_members  # noqa: E402
except ModuleNotFoundError:
    build_package = None
    package_members = None


class PackagingTests(unittest.TestCase):
    def require_api(self):
        if not callable(build_package) or not callable(package_members):
            self.fail("package_skill API is not implemented")
        return build_package, package_members

    def test_allowlist_excludes_generated_runtime_and_secret_files(self) -> None:
        build, members = self.require_api()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "skills/demo").mkdir(parents=True)
            (root / "docs").mkdir()
            (root / "skills/demo/SKILL.md").write_text("skill\n", encoding="utf-8")
            (root / "skills/demo/config").mkdir()
            (root / "skills/demo/config/deployment.test.json").write_text('{"model_ids": {"review": "test.review"}}\n', encoding="utf-8")
            (root / "docs/plan.md").write_text("plan\n", encoding="utf-8")
            (root / "skills/demo/__PyCache__").mkdir()
            (root / "skills/demo/__PyCache__/x.pyc").write_bytes(b"cache")
            (root / "skills/demo/__PyCache__/cache.md").write_text("cache\n", encoding="utf-8")
            (root / "skills/demo/.pytest_cache").mkdir()
            (root / "skills/demo/.pytest_cache/state").write_text("cache\n", encoding="utf-8")
            (root / "skills/demo/.AGENT").mkdir()
            (root / "skills/demo/.AGENT/runtime.md").write_text("runtime\n", encoding="utf-8")
            (root / "skills/demo/Tests").mkdir()
            (root / "skills/demo/Tests/test.md").write_text("test\n", encoding="utf-8")
            (root / "skills/demo/Build").mkdir()
            (root / "skills/demo/Build/output.md").write_text("build\n", encoding="utf-8")
            (root / "skills/demo/.env").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / "skills/demo/debug.log").write_text("log\n", encoding="utf-8")
            (root / ".agent/runtime").mkdir(parents=True)
            (root / ".agent/runtime/state.json").write_text("{}\n", encoding="utf-8")
            output = root / "release.zip"
            build(root, output)
            names = members(root)
            self.assertEqual(names, ["docs/plan.md", "skills/demo/SKILL.md"])
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), names)
                self.assertEqual(archive.infolist()[0].date_time, (1980, 1, 1, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
