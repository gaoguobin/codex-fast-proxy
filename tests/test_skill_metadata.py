from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

from codex_fast_proxy import __version__


ROOT = Path(__file__).resolve().parents[1]


class SkillMetadataTests(unittest.TestCase):
    def test_skill_frontmatter_has_required_fields_only(self) -> None:
        skill_path = ROOT / "skills" / "codex-fast-proxy" / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")

        self.assertTrue(content.startswith("---\n"))
        _leading, frontmatter, body = content.split("---", 2)
        fields = {}
        for line in frontmatter.strip().splitlines():
            key, separator, value = line.partition(":")
            self.assertEqual(separator, ":")
            fields[key.strip()] = value.strip()

        self.assertEqual(set(fields), {"name", "description"})
        self.assertEqual(fields["name"], "codex-fast-proxy")
        self.assertIn("Codex Model Gateway", fields["description"])
        self.assertIn("provider management", fields["description"])
        self.assertIn("install --start", body)

    def test_codex_docs_delegate_skill_links_to_manager(self) -> None:
        for path in (ROOT / ".codex").glob("*.md"):
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("cmd /d /c", content, path.name)
            self.assertNotIn("mklink", content, path.name)
            self.assertNotIn('rmdir `"', content, path.name)
        install_update = "\n".join(
            (ROOT / ".codex" / name).read_text(encoding="utf-8")
            for name in ("INSTALL.md", "UPDATE.md", "UNINSTALL.md")
        )
        self.assertIn("link-skill", install_update)
        self.assertIn("unlink-skill", install_update)

    def test_package_and_plugin_versions_match(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        plugin = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["version"], __version__)
        self.assertEqual(plugin["version"], __version__)


if __name__ == "__main__":
    unittest.main()
