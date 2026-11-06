"""从明确指定的上游完整替换规则文件，生成可核验清单；不触碰上游。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[2]
HISTORY_ASSETS = frozenset({"assets/delivered_tasks.txt", "assets/existing_tasks_feishu.txt"})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_snapshot(rules: Path, roles: Path, manifest: dict) -> None:
    manifest_file = rules / "MANIFEST.json"
    if not manifest_file.is_file() or json.loads(manifest_file.read_text(encoding="utf-8")) != manifest:
        raise ValueError("旧规则快照清单不一致，无法安全归档")
    for directory, entries in ((rules, manifest["files"]), (roles, manifest.get("agent_files", {}))):
        for relative, expected in entries.items():
            if directory == rules and relative in HISTORY_ASSETS:
                continue
            target = (directory / relative).resolve()
            if not target.is_relative_to(directory.resolve()) or not target.is_file() or digest(target) != expected:
                raise ValueError("旧规则快照不完整或已被修改，无法安全归档")


def sync(source: Path, *, source_label: str | None = None) -> str:
    source = source.resolve(strict=True)
    target = (REPO / "skills/snapshot").resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("上游和运行目录不得重叠")
    manifest_file = target / "MANIFEST.json"
    old = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else None
    if old:
        if not re.fullmatch(r"rs_[0-9a-f]{16}", old["rule_snapshot_id"]):
            raise ValueError("旧清单编号无效")
        archive = REPO / "data/rule-snapshots" / old["rule_snapshot_id"]
        if archive.exists():
            verify_snapshot(archive / "rules", archive, old)
        else:
            verify_snapshot(target, REPO / "skills", old)
            archive.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=old["rule_snapshot_id"] + "-", dir=archive.parent) as temporary:
                staging = Path(temporary)
                rules = staging / "rules"
                rules.mkdir()
                shutil.copyfile(manifest_file, rules / "MANIFEST.json")
                for relative in old["files"]:
                    if relative in HISTORY_ASSETS:
                        continue
                    dest = rules / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(target / relative, dest)
                for role in ("generator", "reviewer"):
                    role_dir = REPO / "skills" / role
                    if role_dir.exists():
                        shutil.copytree(role_dir, staging / role)
                staging.rename(archive)
    incoming = {
        p.relative_to(source).as_posix(): p
        for p in source.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        and p.relative_to(source).as_posix() not in HISTORY_ASSETS | {'MANIFEST.json'}
    }
    overrides = REPO / 'skills/overrides'
    if overrides.exists():
        for path in overrides.rglob('*'):
            if path.is_file() and path.suffix != '.pyc' and '__pycache__' not in path.parts:
                incoming[path.relative_to(overrides).as_posix()] = path
    if "SKILL.md" not in incoming or "scripts/check.py" not in incoming:
        raise ValueError("上游 Skill 不完整")
    target.mkdir(parents=True, exist_ok=True)
    for relative, origin in incoming.items():
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, dest)
    # 旧版资产可能包含现场数据，保留原文件但不再纳入新版清单。
    for relative in (old or {}).get("files", {}):
        dest = (target / relative).resolve()
        if not dest.is_relative_to(target):
            raise ValueError("清单文件越界")
        if relative not in incoming and not relative.startswith("assets/") and dest.is_file():
            dest.unlink()
    files = {name: digest(target / name) for name in sorted(incoming)}
    agent_files = {
        p.relative_to(REPO / "skills").as_posix(): digest(p)
        for role in ("generator", "reviewer")
        for p in sorted((REPO / "skills" / role).rglob("*")) if p.is_file()
    }
    identity = json.dumps({"files": files, "agent_files": agent_files}, sort_keys=True).encode()
    snapshot_id = "rs_" + hashlib.sha256(identity).hexdigest()[:16]
    manifest = {"source": source_label or source.as_posix(), "files": files, "agent_files": agent_files,
                "rule_snapshot_id": snapshot_id}
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    return snapshot_id


def refresh_local() -> str:
    target = REPO / 'skills/snapshot'
    manifest = json.loads((target / 'MANIFEST.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='g2-local-rules-') as directory:
        source = Path(directory)
        for relative in manifest['files']:
            if relative in HISTORY_ASSETS:
                continue
            destination = source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target / relative, destination)
        return sync(source, source_label=manifest['source'])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs='?')
    parser.add_argument('--local', action='store_true', help='应用项目 overrides 并生成清单，不读取上游')
    args = parser.parse_args()
    if args.local == bool(args.source):
        parser.error('指定上游 source 或 --local，两者任选其一')
    print(refresh_local() if args.local else sync(args.source))
