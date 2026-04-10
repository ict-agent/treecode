"""Tests for project-local gather spec loading."""

from __future__ import annotations

from pathlib import Path

from treecode.swarm.gather_spec import GatherSpec, get_project_gather_dir, load_gather_spec


def test_get_project_gather_dir_creates_project_scoped_directory(tmp_path: Path):
    gather_dir = get_project_gather_dir(tmp_path)

    assert gather_dir == tmp_path / ".treecode" / "gather"
    assert gather_dir.is_dir()


def test_load_gather_spec_parses_yaml_frontmatter_and_body(tmp_path: Path):
    gather_dir = get_project_gather_dir(tmp_path)
    spec_path = gather_dir / "gather_handshake.md"
    spec_path.write_text(
        """---
name: gather_handshake
description: Recursive handshake-style subtree gather.
version: 1
allow_none: true
timeout_seconds: 18
ordering: topology
return_mode: tree
---

# Gather Handshake

Return a compact handshake payload for this node.

- Leaf nodes may return `null` when they have nothing to contribute.
- Non-leaf nodes should recurse first, then assemble `self + children`.
""",
        encoding="utf-8",
    )

    spec = load_gather_spec("gather_handshake", tmp_path)

    assert isinstance(spec, GatherSpec)
    assert spec.name == "gather_handshake"
    assert spec.description == "Recursive handshake-style subtree gather."
    assert spec.version == 1
    assert spec.allow_none is True
    assert spec.timeout_seconds == 18
    assert spec.ordering == "topology"
    assert spec.return_mode == "tree"
    assert spec.path == spec_path
    assert "Return a compact handshake payload" in spec.instructions


def test_load_gather_spec_defaults_name_from_file_stem_when_missing(tmp_path: Path):
    gather_dir = get_project_gather_dir(tmp_path)
    spec_path = gather_dir / "subtree_status.md"
    spec_path.write_text(
        """---
description: Gather local status for descendants.
---

Return local status for this node.
""",
        encoding="utf-8",
    )

    spec = load_gather_spec("subtree_status", tmp_path)

    assert spec is not None
    assert spec.name == "subtree_status"
    assert spec.path == spec_path


def test_load_gather_spec_returns_none_for_missing_spec(tmp_path: Path):
    assert load_gather_spec("missing", tmp_path) is None


def test_checked_in_gather_handshake_fixture_loads(tmp_path: Path):
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "gather" / "gather_handshake.md"
    fixture_content = fixture_path.read_text(encoding="utf-8")
    gather_dir = get_project_gather_dir(tmp_path)
    (gather_dir / "gather_handshake.md").write_text(fixture_content, encoding="utf-8")

    spec = load_gather_spec("gather_handshake", tmp_path)

    assert spec is not None
    assert spec.name == "gather_handshake"
    assert spec.return_mode == "tree"
    assert "topology-like handshake" in spec.instructions
