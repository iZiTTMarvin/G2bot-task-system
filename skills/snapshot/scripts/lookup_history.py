#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史任务查询：代替整份读入 assets/delivered_tasks.txt 和 existing_tasks_feishu.txt。

两种用法：
  1. 构思阶段按关键词查（子串匹配，命中词越多越靠前）：
       python lookup_history.py 茶叶 饼干 打包
  2. 校验阶段由 check.py 调用 similar_entries()，按任务名和步骤找近似记录。

输出只是候选线索，同构与否由 Agent 对照核心动作链做语义判断；脚本不给通过或淘汰结论。
"""
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
DELIVERED = ASSETS / "delivered_tasks.txt"
FEISHU = ASSETS / "existing_tasks_feishu.txt"

ENTRY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})｜([^｜]+)｜(.*)$")
# 链条相似度（历史链条的 bigram 被候选任务文本覆盖的比例）和任务名相似度的提示线。
# 用 2026-10-26 那 50 条自检校准：同一条任务自己命中均 ≥0.29，无关任务 ≤0.2，
# 取 0.25 偏召回，宁可多提示几条也不漏同构。
CHAIN_HINT = 0.25
NAME_HINT = 0.3
FEISHU_HINT = 0.67


def main_name(name):
    return name.split("-", 1)[-1]


def bigrams(text):
    text = re.sub(r"[【】\d\s,，。.、→\-｜（）()：:;；]", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def load_delivered():
    entries = []
    for line in DELIVERED.read_text(encoding="utf-8").splitlines():
        m = ENTRY_RE.match(line.strip())
        if m:
            entries.append({"date": m[1], "name": m[2], "chain": m[3]})
    return entries


def load_feishu():
    names = []
    for line in FEISHU.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.extend(n.strip() for n in line.split("、") if n.strip())
    return names


def similar_entries(name, steps_text, delivered, feishu, top=3, ignore_dates=()):
    """返回 (近似的已交付记录, 近似的飞书任务名)，各自按相似度从高到低。"""
    name_bg = bigrams(main_name(name))
    text_bg = bigrams(main_name(name) + steps_text)
    scored = []
    for e in delivered:
        if e["date"] in ignore_dates:
            continue
        entry_bg = bigrams(main_name(e["name"]) + e["chain"])
        entry_name_bg = bigrams(main_name(e["name"]))
        chain_score = len(text_bg & entry_bg) / max(1, len(entry_bg))
        name_score = len(name_bg & entry_name_bg) / max(1, len(name_bg | entry_name_bg))
        if chain_score >= CHAIN_HINT or name_score >= NAME_HINT:
            scored.append((max(chain_score, name_score), e))
    scored.sort(key=lambda t: -t[0])
    feishu_hits = []
    for n in feishu:
        n_bg = bigrams(n)
        if not n_bg:
            continue
        contain = len(n_bg & name_bg) / len(n_bg)
        jaccard = len(n_bg & name_bg) / max(1, len(n_bg | name_bg))
        if contain >= FEISHU_HINT or jaccard >= 0.4:
            feishu_hits.append((max(contain, jaccard), n))
    feishu_hits.sort(key=lambda t: -t[0])
    return scored[:top], feishu_hits[:top]


def keyword_search(terms, limit=25):
    delivered, feishu = load_delivered(), load_feishu()
    hits = []
    for e in delivered:
        text = e["name"] + e["chain"]
        n = sum(t in text for t in terms)
        if n:
            hits.append((n, e))
    hits.sort(key=lambda t: -t[0])
    print(f"已交付记录命中 {len(hits)} 条（显示前 {min(limit, len(hits))} 条，命中词多者优先）：")
    for n, e in hits[:limit]:
        print(f"  [{n}词] {e['date']}｜{e['name']}｜{e['chain']}")
    feishu_hits = [n for n in feishu if any(t in n for t in terms)]
    print(f"飞书已有任务名命中 {len(feishu_hits)} 条：" + "、".join(feishu_hits[:limit]))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    terms = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not terms:
        sys.exit(__doc__)
    keyword_search(terms)


if __name__ == "__main__":
    main()
