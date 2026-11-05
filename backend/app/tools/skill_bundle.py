"""按清单验证、冻结并加载规则文件，避免批次规则被运行目录更新替换。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import threading
from tempfile import TemporaryDirectory
from pathlib import Path
from types import ModuleType

from ..config import CONFIG
from ..errors import ApiError

_LOCK = threading.Lock()
_HISTORY_ASSETS = frozenset({"assets/delivered_tasks.txt", "assets/existing_tasks_feishu.txt"})


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SkillBundle:
    def __init__(self, root: Path, agents: Path):
        self.root = root
        self.agents = agents
        self.manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
        self.id = self.manifest["rule_snapshot_id"]
        if self.manifest.get("agent_files"):
            identity = json.dumps({key: self.manifest[key] for key in ("files", "agent_files")},
                                  sort_keys=True).encode()
            if self.id != "rs_" + hashlib.sha256(identity).hexdigest()[:16]:
                raise ValueError("规则快照编号与清单不一致")
        self._modules: dict[str, ModuleType] = {}
        for relative, expected in self.manifest["files"].items():
            if relative in _HISTORY_ASSETS:
                continue
            file = (root / relative).resolve()
            if not file.is_relative_to(root.resolve()) or _hash(file) != expected:
                raise ValueError("规则文件与清单不一致")
        for relative, expected in self.manifest.get("agent_files", {}).items():
            file = (agents / relative).resolve()
            if not file.is_relative_to(agents.resolve()) or _hash(file) != expected:
                raise ValueError("角色 Skill 与清单不一致")

    def module(self, name: str) -> ModuleType:
        if f"scripts/{name}.py" not in self.manifest["files"]:
            raise ImportError(name)
        if name not in self._modules:
            spec = importlib.util.spec_from_file_location(
                f"g2_{self.id}_{name}", self.root / "scripts" / f"{name}.py"
            )
            if spec is None or spec.loader is None:
                raise ImportError(name)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._modules[name] = module
        return self._modules[name]

    def agent_files(self, role: str) -> dict[str, str]:
        if not self.manifest.get("agent_files"):
            raise ApiError(500, "RULE_TOOL_FAILED",
                           "该历史批次未保存完整 Agent Skill，请使用新版规则新建批次；历史正文仍保留")
        files = {
            f"/skills/g2-task-{role}/SKILL.md": (self.agents / role / "SKILL.md").read_text(encoding="utf-8"),
        }
        # 上游核心原则作为共享领域规则；交付与自我进化由系统处理。
        source = (self.root / "SKILL.md").read_text(encoding="utf-8")
        start = re.search(r"(?m)^## 核心原则[^\r\n]*\r?\n", source)
        end = re.search(r"(?m)^(?:\d+\.\s*)?\*\*交付格式", source)
        if not start or not end or end.start() <= start.end():
            raise ApiError(500, "RULE_TOOL_FAILED", "规则文件缺少核心原则或交付格式边界")
        files["/rules/SKILL.md"] = source[start.end():end.start()]
        for relative in self.manifest["files"]:
            if relative.startswith("references/") or relative == "assets/atomic_skills_catalog.csv":
                files[f"/rules/{relative}"] = (self.root / relative).read_text(encoding="utf-8")
        return files


def load_bundle(snapshot_id: str | None = None) -> SkillBundle:
    try:
        if snapshot_id is not None:
            if not re.fullmatch(r"rs_[0-9a-f]{16}", snapshot_id):
                raise ValueError("规则快照编号无效")
            frozen = CONFIG.data_dir / "rule-snapshots" / snapshot_id
            if frozen.is_dir():
                bundle = SkillBundle(frozen / "rules", frozen)
                if bundle.id != snapshot_id:
                    raise ValueError("规则快照目录与编号不一致")
                return bundle
        bundle = SkillBundle(CONFIG.skill_snapshot_dir, CONFIG.skill_snapshot_dir.parent)
        if snapshot_id is not None and bundle.id != snapshot_id:
            raise ValueError("指定规则快照文件不可用")
        return bundle
    except (OSError, ValueError, KeyError) as exc:
        raise ApiError(500, "RULE_TOOL_FAILED", "规则快照缺失或内容与清单不一致",
                       {"error_type": type(exc).__name__}) from exc


def freeze_bundle() -> SkillBundle:
    with _LOCK:
        current = load_bundle()
        destination = CONFIG.data_dir / "rule-snapshots" / current.id
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=current.id + "-", dir=destination.parent) as directory:
                temporary = Path(directory)
                rules = temporary / "rules"
                rules.mkdir()
                shutil.copyfile(current.root / "MANIFEST.json", rules / "MANIFEST.json")
                for relative in current.manifest["files"]:
                    if relative in _HISTORY_ASSETS:
                        continue
                    target = rules / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(current.root / relative, target)
                for role in ("generator", "reviewer"):
                    shutil.copytree(current.agents / role, temporary / role)
                SkillBundle(temporary / "rules", temporary)
                temporary.rename(destination)
        return load_bundle(current.id)
