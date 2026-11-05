# 批量任务表与脚本（只有需要文件或标签时读）

交付格式（L-033）：5 条及以下在聊天里给，名字、步骤、单套所需物料各一个独立 `txt` 代码块；6 条及以上只交付一个 xlsx，列依次为 `任务名字、任务步骤、单套所需物料`，步骤单元格每行 `1.xxx`，不存 Markdown 围栏，不另外产出 csv/md。

```bash
# 一条命令自动补齐单套所需物料、全量校验并导出交付表 xlsx：
python scripts/check.py 草稿.md [--long] --fill-materials --export 输出.xlsx
```

只有用户明确要求时才加 `场景标签、任务难度、原子能力` 等列；`原子能力` 逐字从 `assets/atomic_skills_catalog.csv` 选择可用英文标签，标注可核对的动作，不必为了填更多标签改写步骤。`check.py` 也认列名 `任务名字`。

库存来自用户实际材料；`assets/material_inventory_template.csv` 是空模板，不代表已经有这些物品。优先核验每条任务能否各准备五套对应物品。

批量文件（一条命令完成校验和批内连续段提示，默认不查历史）：

```bash
python scripts/check.py 任务表.xlsx            # 默认 10～20 步
python scripts/check.py 任务表.xlsx --long     # 长任务建议 30 步以上，无默认上限
```

`--min-steps`/`--max-steps` 仅按用户明确要求自定义；长任务默认不传上限，少于 30 步会提示复核，显式指定边界时按用户要求校验。不能以无效步骤补足。同批近似警告按 `03-diversity.md` 复核。脚本检查基地前缀、部分命名问题、编号、步数、禁用词、手数及重复线索；**动宾主干与必要修饰、每处清洁依据、真实工作必要性、现场时长、双臂干涉、五套库存仍须人工或现场验证**。`validate_tasks.py` 仍可单独运行，逐条列出通过项。

修改技能或脚本后才跑 `python scripts/regression.py` 做回归（出题时不用跑）；教训库维护用 `python scripts/learn.py`，见 `references/07-evolution.md`。

对 `check.py` 提示的同批近似对，结合实际步骤、用途与终态复核；连续重叠或同名不自动等于重复。具体见03-diversity.md。
