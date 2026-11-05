import hashlib
import json

import pytest

from scripts import sync_skills


def make_sources(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    snapshot = repo / "skills" / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    (snapshot / "assets").mkdir()
    (snapshot / "SKILL.md").write_text("旧规则", encoding="utf-8")
    (snapshot / "scripts/check.py").write_text("旧检查", encoding="utf-8")
    (snapshot / "assets/delivered_tasks.txt").write_text("保留的旧资产", encoding="utf-8")
    for role in ("generator", "reviewer"):
        directory = repo / "skills" / role
        directory.mkdir()
        (directory / "SKILL.md").write_text(f"旧角色 {role}", encoding="utf-8")

    files = {name: sync_skills.digest(snapshot / name) for name in (
        "SKILL.md", "scripts/check.py", "assets/delivered_tasks.txt",
    )}
    agents = {f"{role}/SKILL.md": sync_skills.digest(repo / "skills" / role / "SKILL.md")
              for role in ("generator", "reviewer")}
    identity = json.dumps({"files": files, "agent_files": agents}, sort_keys=True).encode()
    old_id = "rs_" + hashlib.sha256(identity).hexdigest()[:16]
    manifest = {"source": "old", "files": files, "agent_files": agents, "rule_snapshot_id": old_id}
    (snapshot / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    source = tmp_path / "upstream"
    (source / "scripts").mkdir(parents=True)
    (source / "SKILL.md").write_text("新规则", encoding="utf-8")
    (source / "scripts/check.py").write_text("新检查", encoding="utf-8")
    monkeypatch.setattr(sync_skills, "REPO", repo)
    return repo, snapshot, source, old_id


def test_sync_archives_old_rules_and_preserves_unmanaged_assets(tmp_path, monkeypatch):
    repo, snapshot, source, old_id = make_sources(tmp_path, monkeypatch)
    new_id = sync_skills.sync(source)
    archive = repo / "data/rule-snapshots" / old_id
    assert (archive / "rules/SKILL.md").read_text(encoding="utf-8") == "旧规则"
    assert (archive / "generator/SKILL.md").read_text(encoding="utf-8") == "旧角色 generator"
    assert not (archive / "rules/assets/delivered_tasks.txt").exists()
    assert (snapshot / "assets/delivered_tasks.txt").read_text(encoding="utf-8") == "保留的旧资产"
    manifest = json.loads((snapshot / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["rule_snapshot_id"] == new_id
    assert "assets/delivered_tasks.txt" not in manifest["files"]


def test_sync_refuses_to_archive_a_changed_role(tmp_path, monkeypatch):
    repo, snapshot, source, old_id = make_sources(tmp_path, monkeypatch)
    (repo / "skills/generator/SKILL.md").write_text("已改变", encoding="utf-8")
    with pytest.raises(ValueError, match="旧规则快照不完整或已被修改"):
        sync_skills.sync(source)
    assert not (repo / "data/rule-snapshots" / old_id).exists()
    assert (snapshot / "SKILL.md").read_text(encoding="utf-8") == "旧规则"
