from __future__ import annotations

import unittest
from pathlib import Path


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
        self.assertIn("Codex App Fast proxy", fields["description"])
        self.assertIn("install --start", body)


if __name__ == "__main__":
    unittest.main()
