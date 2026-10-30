# 批量任务表与脚本（只有需要文件/台账/标签时读）

交付格式（L-033）：5 条及以下在聊天里给，名字、步骤、单套所需物料各一个独立 `txt` 代码块；6 条及以上只交付一个 xlsx，列依次为 `任务名字、任务步骤、单套所需物料`，步骤单元格每行 `1.xxx`，不存 Markdown 围栏，不另外产出 csv/md。

```bash
python scripts/materials.py 草稿.md > 补物料.md        # 按步骤里的【】补 物料：书本2个、杯子1个
python scripts/check.py 补物料.md                      # 校验（含物料与步骤一致）
python scripts/export_xlsx.py 补物料.md 输出.xlsx      # 导出交付表
```

只有用户明确要求时才加 `场景标签、任务难度、原子能力` 等列；`原子能力` 逐字从 `assets/atomic_skills_catalog.csv` 选择可用英文标签，标注可核对的动作，不必为了填更多标签改写步骤。`check.py` 也认列名 `任务名字`。

库存来自用户实际材料；`assets/material_inventory_template.csv` 是空模板，不代表已经有这些物品。优先核验每条任务能否各准备五套对应物品。

批量文件（一条命令完成校验、批内连续段重叠、历史近似检查，只列有问题的条目）：

```bash
python scripts/check.py 任务表.xlsx            # 默认 10～20 步
python scripts/check.py 任务表.xlsx --long     # 长任务 20～30 步
python scripts/build_ledger.py 历史任务表.xlsx --output 历史台账.csv
python scripts/check.py 任务表.xlsx --ledger 历史台账.csv --history 历史任务表.csv
```

`--min-steps`/`--max-steps` 可自定义，不能以无效步骤补足。脚本查命名、编号、步数、逗号、禁用词、“双臂协同/双手/一手另一手”等指定手数措辞、部分括号/场景冲突、指纹相似度、连续段重叠和历史近似记录；**真实工作必要性、双臂干涉、五套库存仍人工终检**。`validate_tasks.py` 仍可单独运行，逐条列出通过项。

修改技能或脚本后才跑 `python scripts/regression.py` 做回归（出题时不用跑）；教训库维护用 `python scripts/learn.py`，见 `references/07-evolution.md`。

核心段去重时同时提供连续核心段、衍生差异和终态字段。长批次对 `check.py` 列出的重叠对写复核记录，不以文本相似度低代替语义判断；具体见03-diversity.md。
