"""全局配置：数据目录、快照目录与演示开关。

密钥等敏感配置不在这里，保存在 data/config/settings.json（gitignored）。
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).resolve() if value else default


class AppConfig:
    def __init__(self) -> None:
        self.data_dir = _path_from_env("G2_DATA_DIR", REPO_ROOT / "data")
        self.skill_snapshot_dir = _path_from_env(
            "G2_SKILL_SNAPSHOT_DIR", REPO_ROOT / "skills" / "snapshot"
        )
        # 本地演示开关：无真实凭据时用确定性 FakeModel 走通闭环。
        # 测试不走这个开关（测试直接替换 client 工厂），正式联调必须关闭。
        self.demo_fake_model = os.environ.get("G2_DEMO_FAKE_MODEL", "") == "1"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "g2tasks.sqlite3"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "config"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.attachments_dir, self.exports_dir, self.config_dir):
            d.mkdir(parents=True, exist_ok=True)

    def reconfigure(self, **overrides: object) -> None:
        """测试隔离用：原位更新属性（各模块持有同一实例引用）。"""
        for key, value in overrides.items():
            setattr(self, key, value)


CONFIG = AppConfig()
