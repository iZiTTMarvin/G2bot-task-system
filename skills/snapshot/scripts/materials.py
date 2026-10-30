#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从任务步骤里的【物料】推出“单套所需物料”（例：书本2个、杯子1个）。

规则：步骤里每个不同的 【名称】 算一件；名称末尾的编号去掉后归为同一类，
同类件数 = 不同编号的个数（【碗1】【碗2】→ 碗2个）。固定环境（桌面、架子）不加【】，所以不会进来。
量词默认“个”，少数物品用习惯量词（QUANTIFIERS）。盖子、笼盖等附属部件不写【】，同样不会进来。
"""
import re

BRACKET_RE = re.compile(r"【([^】]+)】")
SUFFIX_RE = re.compile(r"\d+$")

# 习惯量词；没列出的一律用“个”
QUANTIFIERS = {"筷子": "双", "手套": "双", "鞋": "双", "袜子": "双"}


def derive_materials(steps_text):
    """返回 [(基础名, 件数)]，按首次出现顺序。"""
    groups = {}
    for name in BRACKET_RE.findall(str(steps_text)):
        base = SUFFIX_RE.sub("", name.strip())
        groups.setdefault(base, set()).add(name.strip())
    return [(base, len(names)) for base, names in groups.items()]


def format_materials(pairs):
    return "、".join(f"{base}{count}{QUANTIFIERS.get(base, '个')}" for base, count in pairs)


def materials_text(steps_text):
    return format_materials(derive_materials(steps_text))


def parse_materials(text):
    """把“书本2个、杯子1个”解析回 {基础名: 件数}；解析不了的片段原样放进 bad 列表。"""
    result, bad = {}, []
    for part in re.split(r"[、，,；;\n]+", str(text or "")):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.+?)(\d+)([^\d]*)$", part)
        if not m:
            bad.append(part)
            continue
        result[m.group(1)] = int(m.group(2))
    return result, bad


def compare_materials(steps_text, listed_text):
    """返回问题列表（空表示一致）。"""
    expected = dict(derive_materials(steps_text))
    listed, bad = parse_materials(listed_text)
    issues = [f"物料『{b}』格式应为 名称+数量+量词，如 书本2个" for b in bad]
    for name, count in expected.items():
        if name not in listed:
            issues.append(f"单套所需物料缺少『{name}{count}』")
        elif listed[name] != count:
            issues.append(f"单套所需物料『{name}』应为{count}件，表中写了{listed[name]}")
    for name in listed:
        if name not in expected:
            issues.append(f"单套所需物料多出『{name}』，步骤里没有用到")
    return issues


def fill_text(text):
    """给文本任务里每条没写“物料：”的任务补上一行（插在该条最后一个步骤之后）。"""
    out, name, steps, has_material = [], None, [], False

    def finish():
        if name is not None and not has_material:
            out.append("物料：" + materials_text("\n".join(steps)))

    for line in str(text).splitlines():
        s = line.strip()
        if re.match(r"^#+\s*\S", s):
            finish()
            name, steps, has_material = s, [], False
        elif re.match(r"^\d{1,2}\.", s):
            steps.append(s)
        elif re.match(r"^(单套所需)?物料[：:]", s):
            has_material = True
        elif not s and name is not None and not has_material:
            finish()
            has_material = True
        out.append(line)
    finish()
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        sys.exit("用法: python materials.py 任务.md|-   # 给每条任务补『物料：…』行后输出到标准输出")
    src = sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1], encoding="utf-8").read()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(fill_text(src))
