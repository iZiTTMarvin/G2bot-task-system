import shutil

import pytest

from app.config import CONFIG
from app.errors import ApiError
from app.tools.skill_bundle import freeze_bundle, load_bundle
from app.tools.validation import validate_content
from app.agents.fake import _content


def test_freeze_keeps_rules_and_role_skills_after_source_changes(tmp_path, monkeypatch):
    source = tmp_path / "skills"
    for folder in ("snapshot", "generator", "reviewer"):
        shutil.copytree(CONFIG.skill_snapshot_dir.parent / folder, source / folder)
    monkeypatch.setattr(CONFIG, "skill_snapshot_dir", source / "snapshot")
    monkeypatch.setattr(CONFIG, "data_dir", tmp_path / "data")
    frozen = freeze_bundle()
    role_before = frozen.agent_files("generator")
    (source / "generator/SKILL.md").write_text("被修改", encoding="utf-8")
    assert load_bundle(frozen.id).agent_files("generator") == role_before
    with pytest.raises(ApiError, match="清单不一致"):
        load_bundle()


def test_corrupt_frozen_script_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "data_dir", tmp_path)
    bundle = freeze_bundle()
    (bundle.root / "scripts/materials.py").write_text("损坏", encoding="utf-8")
    with pytest.raises(ApiError) as error:
        validate_content(_content(1, "", "standard"), "standard", bundle.id)
    assert error.value.code == "RULE_TOOL_FAILED"


def test_upstream_manifest_is_complete_and_runtime_only_exposes_role(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "data_dir", tmp_path)
    bundle = freeze_bundle()
    manifest = bundle.manifest
    assert "/.kiro/skills/g2-robot-task-designer-v2" in manifest["source"]
    for name in ["scripts/check.py", "scripts/regression.py", "assets/delivered_tasks.txt",
                 "references/01-capability.md", "references/06-brief.md"]:
        assert name in manifest["files"]
    files = bundle.agent_files("reviewer")
    assert "/skills/g2-task-reviewer/SKILL.md" in files
    assert "/skills/g2-task-generator/SKILL.md" not in files
    assert "交付格式" not in files["/rules/SKILL.md"]
    assert "## 执行流程" not in files["/rules/SKILL.md"]
    assert "/rules/assets/delivered_tasks.txt" in files
    assert "/rules/scripts/check.py" in files


def test_unknown_snapshot_does_not_fall_back_to_current_rules():
    with pytest.raises(ApiError, match="快照缺失"):
        load_bundle("rs_0000000000000000")
