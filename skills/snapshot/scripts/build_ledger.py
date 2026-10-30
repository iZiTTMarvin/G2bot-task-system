#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从历史任务表（.xlsx/.csv）构建去重台账 CSV。

用法:
    python3 build_ledger.py <历史任务表.xlsx|.csv> [--output 任务台账.csv]

读取列（按表头识别）: 序号 / 任务名称 / 任务步骤 / 任务难度 / 场景标签 / 任务指纹
输出列:
    编号,任务名称,场景标签,任务难度,操作对象集合,核心动作序列,技能族,任务指纹
该台账可直接交给 validate_tasks.py --ledger 做跨批去重，也可粘贴给新会话续产。
"""
import argparse
import re
import sys
from pathlib import Path

# 复用 validate_tasks 中的解析与指纹逻辑（两边必须同口径）
sys.path.insert(0, str(Path(__file__).parent))
from validate_tasks import split_steps, task_fingerprint  # noqa: E402

# 技能族归并（动作词 -> 族），用于统计分布
FAMILY_MAP = {
    "擦拭干清": ["擦", "抹", "刷", "扫", "刮"],
    "折叠卷绕": ["折", "叠", "卷", "铺平", "对折", "撑开", "理顺", "缠绕", "绕"],
    "开合启闭": ["开", "盖", "合", "关", "抽", "拉"],
    "拧转": ["拧", "旋"],
    "推拉拨拢": ["推", "拨", "拢", "对齐", "码齐"],
    "按压卡扣": ["按压", "按", "压", "卡", "扣"],
    "插装连接": ["插", "拔", "穿", "组装"],
    "堆叠码放": ["叠放", "堆叠", "摞", "摞齐"],
    "包裹封贴": ["包", "裹", "贴", "封", "塞", "撕"],
    "挂放张挂": ["挂"],
    "套装配对": ["套", "配对", "配"],
    "舀倒夹取": ["舀", "铲", "倒", "蘸", "夹", "夹取"],
    "系扎收口": ["绑", "系", "扎", "收口", "排气", "捏合"],
    "翻拣整理": ["翻", "整理", "归类"],
    "其他": ["写", "盖章", "盖印", "敲", "戳"],
}


def family_of(skills):
    fams = []
    for s in skills:
        for fam, words in FAMILY_MAP.items():
            if s in words and fam not in fams:
                fams.append(fam)
    return fams or ["拿放/其他"]


def load(path: Path):
    import pandas as pd
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path).fillna("")
    return pd.read_excel(path).fillna("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="历史任务表 .xlsx/.csv")
    ap.add_argument("--output", default="任务台账.csv")
    args = ap.parse_args()

    df = load(Path(args.source))
    if "任务名称" not in df.columns or "任务步骤" not in df.columns:
        print(f"[FATAL] 表中需包含『任务名称』『任务步骤』列，当前列：{list(df.columns)}")
        sys.exit(2)

    import csv
    rows = []
    seen_sig = set()
    for idx, r in df.iterrows():
        name = str(r.get("任务名称", "")).strip()
        steps = split_steps(r.get("任务步骤", ""))
        scene = str(r.get("场景标签", "") or "")
        diff = str(r.get("任务难度", "") or "")
        fp = task_fingerprint(name, steps, scene)
        objs, actions = fp["objects"], fp["actions"]
        fams = family_of(actions)
        given_fp = str(r.get("任务指纹", "") or "")
        atomic = str(r.get("原子能力", "") or "").strip()
        if fp["signature"] in seen_sig:
            continue
        seen_sig.add(fp["signature"])
        rows.append({
            "编号": r.get("序号", idx + 1),
            "任务名称": name,
            "场景标签": scene,
            "任务难度": diff,
            "操作对象集合": "|".join(objs),
            "核心动作序列": ",".join(actions),
            "技能族": "/".join(fams),
            "原子能力": atomic,
            "任务指纹": given_fp or f"{scene}｜{name}｜动作:{','.join(actions[:6])}｜对象:{'/'.join(objs[:6])}",
        })

    out = Path(args.output)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["编号", "任务名称", "场景标签", "任务难度", "操作对象集合",
                            "核心动作序列", "技能族", "原子能力", "任务指纹"])
        w.writeheader()
        w.writerows(rows)

    # 统计
    from collections import Counter
    fam_counter = Counter()
    for r in rows:
        for fam in r["技能族"].split("/"):
            fam_counter[fam] += 1
    print(f"已写出 {len(rows)} 条台账到 {out.resolve()}")
    print("技能族分布：", "，".join(f"{k}×{v}" for k, v in fam_counter.most_common()))
    print("下一批应避开的模式：请人工补充台账末尾或直接在对话中说明。")


if __name__ == "__main__":
    main()
