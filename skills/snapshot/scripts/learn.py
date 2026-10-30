#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G2 任务设计技能的教训库维护脚本。

教训库位于 references/06-learned-rules.md，内容来自用户的修改意见，每次出题前必读。
本脚本只做确定性的工作：编号、查重计数、状态流转和体量检查。
规则该不该记、怎么措辞，由 Agent 按 references/07-evolution.md 判断。

用法:
  python learn.py add --kind 能力 --rule "..." --why "..." --source "2026-10-20 用户：..." \
      [--status 生效|待确认|候选] [--landed "SKILL.md"] [--ban 订书机,扫码枪] [--merge-into L-001] [--force-new]

查重分两层：字面高度相似时脚本自动合并；只是意思相近时脚本列出候选，
由 Agent 判断是否同义，同义就用 --merge-into 指定编号合并（换种说法的重复靠这一层兜住）。
  python learn.py list [--status 生效]
  python learn.py set L-003 --status 作废 --reason "被 L-009 取代"
  python learn.py check
  python learn.py brief      # 重新生成出题前读的速查 references/06-brief.md（add/set 会自动生成）
"""
import argparse
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = SKILL_DIR / "references" / "06-learned-rules.md"
BRIEF_PATH = SKILL_DIR / "references" / "06-brief.md"
SKILL_MD = SKILL_DIR / "SKILL.md"

STATUSES = ["生效", "待确认", "候选", "作废"]
FIELDS = ["规则", "原因", "来源", "落地", "禁用词", "备注"]
HEADER_RE = re.compile(r"^### (L-\d{3})｜(.+?)｜(.+?)｜命中 (\d+)\s*$")
FIELD_RE = re.compile(r"^- (" + "|".join(FIELDS) + r")：(.*)$")
SECTION_RE = re.compile(r"^## (" + "|".join(STATUSES) + r")\s*$")

# 体量上限：超过就提醒合并，保证每次出题读取教训库的成本可控
MAX_ACTIVE = 30
MAX_SKILL_LINES = 90
MAX_BRIEF_CHARS = 5500
# 相似度达到该值视为同一条规则，只加命中次数
DUP_THRESHOLD = 0.6
# 低于自动合并线但达到该值的，列出来请 Agent 做语义判断
HINT_THRESHOLD = 0.3


def load():
    """解析教训库，返回 (开头说明文字, 规则列表)。来源允许多行，按出现顺序保存。"""
    text = RULES_PATH.read_text(encoding="utf-8")
    intro, entries, cur = [], [], None
    seen_body = False
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            seen_body = True
            cur = {"id": m.group(1), "kind": m.group(2), "status": m.group(3),
                   "hits": int(m.group(4)), "fields": {k: [] for k in FIELDS}}
            entries.append(cur)
            continue
        if SECTION_RE.match(line):
            seen_body = True
            cur = None
            continue
        if not seen_body:
            intro.append(line)
            continue
        f = FIELD_RE.match(line)
        if f and cur is not None:
            cur["fields"][f.group(1)].append(f.group(2).strip())
    return "\n".join(intro).rstrip() + "\n", entries


def save(intro, entries):
    """按状态分组重写整个文件，保证格式稳定，便于脚本和人阅读。"""
    out = [intro.rstrip(), ""]
    for status in STATUSES:
        group = [e for e in entries if e["status"] == status]
        if not group:
            continue
        out += [f"## {status}", ""]
        for e in sorted(group, key=lambda x: x["id"]):
            out.append(f"### {e['id']}｜{e['kind']}｜{e['status']}｜命中 {e['hits']}")
            for k in FIELDS:
                for v in e["fields"][k]:
                    out.append(f"- {k}：{v}")
            out.append("")
    RULES_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    BRIEF_PATH.write_text(render_brief(entries), encoding="utf-8")


def render_brief(entries):
    """出题前只读这份：每条规则一行，省掉原因、来源、落地，读取量约为完整库的一半。

    由 save() 自动生成，保证和完整库同步；手改会在 check 时被判为过期。
    """
    out = [
        "# 教训库速查（出题前读这份）",
        "",
        "自动生成，勿手改；原因、来源、落地见 `06-learned-rules.md`。优先级：现场安全 ＞ 生效规则 ＞ SKILL.md 正文 ＞ 范例。",
    ]
    titles = {"生效": "## 生效（必须遵守）", "待确认": "## 待确认（出题前先问用户，确认前避开）",
              "候选": "## 候选（只作提醒）"}
    for status in ("生效", "待确认", "候选"):
        group = sorted((e for e in entries if e["status"] == status), key=lambda x: x["id"])
        if not group:
            continue
        out += ["", titles[status]]
        for e in group:
            rule = e["fields"]["规则"][0] if e["fields"]["规则"] else ""
            ban = f"（禁用词：{e['fields']['禁用词'][0]}）" if e["fields"]["禁用词"] else ""
            out.append(f"- {e['id']}｜{e['kind']}｜{rule}{ban}")
    return "\n".join(out) + "\n"


def bigrams(s):
    s = re.sub(r"[\s，。、：；“”（）()【】,.:;\"'！!？?…/｜|-]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def similarity(a, b):
    """取 Jaccard 与打折后的包含度中的较大值：短句被长规则包含时也能识别为相近。"""
    x, y = bigrams(a), bigrams(b)
    inter = len(x & y)
    jaccard = inter / max(1, len(x | y))
    overlap = inter / max(1, min(len(x), len(y)))
    return max(jaccard, 0.8 * overlap)


def next_id(entries):
    nums = [int(e["id"][2:]) for e in entries]
    return f"L-{(max(nums) + 1 if nums else 1):03d}"


def merge(intro, entries, target, source):
    target["hits"] += 1
    target["fields"]["来源"].append(source)
    save(intro, entries)
    print(f"[合并] 并入 {target['id']}，命中次数 +1 → {target['hits']}")
    if target["status"] == "候选" and target["hits"] >= 2:
        print(f"[提示] {target['id']} 候选已命中 {target['hits']} 次，可升级为生效：python learn.py set {target['id']} --status 生效")


def cmd_add(args):
    intro, entries = load()
    if args.merge_into:
        target = next((x for x in entries if x["id"] == args.merge_into), None)
        if not target:
            sys.exit(f"找不到 {args.merge_into}")
        merge(intro, entries, target, args.source)
        return
    if not args.force_new:
        best, score = None, 0.0
        for e in entries:
            if e["status"] == "作废" or not e["fields"]["规则"]:
                continue
            s = similarity(args.rule, e["fields"]["规则"][0])
            if s > score:
                best, score = e, s
        if best and score >= DUP_THRESHOLD:
            print(f"[相似] 与 {best['id']} 字面相似度 {score:.2f}")
            merge(intro, entries, best, args.source)
            return
        near = sorted(
            ((similarity(args.rule, e["fields"]["规则"][0]), e) for e in entries
             if e["status"] != "作废" and e["fields"]["规则"]),
            key=lambda t: -t[0])
        near = [(s, e) for s, e in near if s >= HINT_THRESHOLD][:3]
        if near:
            print("[未写入] 发现意思可能相近的规则，请判断是否同义：")
            for s, e in near:
                print(f"    {e['id']}（{s:.2f}）{e['fields']['规则'][0]}")
            print("    同义：加 --merge-into <编号> 重跑；确实是新规则：加 --force-new 重跑")
            sys.exit(2)
    e = {"id": next_id(entries), "kind": args.kind, "status": args.status, "hits": 1,
         "fields": {k: [] for k in FIELDS}}
    e["fields"]["规则"] = [args.rule]
    e["fields"]["原因"] = [args.why] if args.why else []
    e["fields"]["来源"] = [args.source]
    e["fields"]["落地"] = [args.landed] if args.landed else []
    if args.ban:
        words = [w.strip() for w in re.split(r"[,，、]", args.ban) if w.strip()]
        e["fields"]["禁用词"] = ["、".join(words)]
    entries.append(e)
    save(intro, entries)
    print(f"[新增] {e['id']}｜{e['kind']}｜{e['status']}：{args.rule}")
    if args.status == "生效" and not args.landed:
        print("[提示] 生效规则还没写落地位置；改完技能文件后用 set --landed 补上")


def cmd_set(args):
    intro, entries = load()
    e = next((x for x in entries if x["id"] == args.id), None)
    if not e:
        sys.exit(f"找不到 {args.id}")
    if args.status:
        e["status"] = args.status
    if args.landed:
        e["fields"]["落地"] = [args.landed]
    if args.reason:
        e["fields"]["备注"].append(args.reason)
    save(intro, entries)
    print(f"[更新] {e['id']} → {e['status']}")


def cmd_list(args):
    _, entries = load()
    for e in entries:
        if args.status and e["status"] != args.status:
            continue
        rule = e["fields"]["规则"][0] if e["fields"]["规则"] else ""
        print(f"{e['id']}｜{e['kind']}｜{e['status']}｜命中 {e['hits']}｜{rule}")


def cmd_brief(_args):
    _, entries = load()
    BRIEF_PATH.write_text(render_brief(entries), encoding="utf-8")
    print(f"[已生成] {BRIEF_PATH.name}，{len(BRIEF_PATH.read_text(encoding='utf-8'))} 字符")


def cmd_check(_args):
    """体量与健康检查：返回非零退出码表示需要处理（合并、升级、补落地）。"""
    _, entries = load()
    problems = 0
    counts = {s: sum(e["status"] == s for e in entries) for s in STATUSES}
    print("规则数：" + "，".join(f"{k} {v}" for k, v in counts.items()))
    if counts["生效"] > MAX_ACTIVE:
        problems += 1
        print(f"[需合并] 生效规则 {counts['生效']} 条，超过 {MAX_ACTIVE}；按 07-evolution.md 第六节合并")
    # 出题时读的是速查版，所以体量上限卡速查；完整库只在查来源或维护时读
    brief = render_brief(entries)
    if not BRIEF_PATH.exists() or BRIEF_PATH.read_text(encoding="utf-8") != brief:
        problems += 1
        print("[过期] 06-brief.md 与教训库不一致；运行 python learn.py brief 重新生成（不要手改速查）")
    if len(brief) > MAX_BRIEF_CHARS:
        problems += 1
        print(f"[需合并] 速查 {len(brief)} 字符，超过 {MAX_BRIEF_CHARS}，每次读取成本偏高")
    lines = len(SKILL_MD.read_text(encoding="utf-8").splitlines())
    if lines > MAX_SKILL_LINES:
        problems += 1
        print(f"[需精简] SKILL.md {lines} 行，超过 {MAX_SKILL_LINES}；细节下沉到 references/")
    for e in entries:
        if e["status"] == "生效" and not e["fields"]["落地"]:
            problems += 1
            print(f"[未落地] {e['id']} 已生效但没写进技能文件或脚本")
        if e["status"] == "候选" and e["hits"] >= 2:
            print(f"[可升级] {e['id']} 候选已命中 {e['hits']} 次")
        if e["status"] == "待确认":
            print(f"[待确认] {e['id']} 出题前先问用户：{e['fields']['规则'][0] if e['fields']['规则'] else ''}")
    print("检查完成" + ("，有需要处理的项" if problems else "，无阻塞问题"))
    sys.exit(1 if problems else 0)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--kind", required=True)
    a.add_argument("--rule", required=True)
    a.add_argument("--why", default="")
    a.add_argument("--source", required=True)
    a.add_argument("--status", default="候选", choices=STATUSES[:3])
    a.add_argument("--landed", default="")
    a.add_argument("--ban", default="")
    a.add_argument("--merge-into", default="")
    a.add_argument("--force-new", action="store_true")
    s = sub.add_parser("set")
    s.add_argument("id")
    s.add_argument("--status", choices=STATUSES)
    s.add_argument("--landed", default="")
    s.add_argument("--reason", default="")
    l = sub.add_parser("list")
    l.add_argument("--status", choices=STATUSES)
    sub.add_parser("check")
    sub.add_parser("brief")
    args = ap.parse_args()
    {"add": cmd_add, "set": cmd_set, "list": cmd_list, "check": cmd_check, "brief": cmd_brief}[args.cmd](args)


if __name__ == "__main__":
    main()
