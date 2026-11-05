#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G2 机器人采集任务表自动质检脚本。

用法:
    python3 validate_tasks.py <任务表.xlsx|.csv> [--ledger <历史台账.csv>] [--long] [--min-steps N] [--max-steps N]

任务表支持的列（按表头识别，缺列自动跳过对应检查）:
    序号 / 任务名称 / 任务步骤 / 任务难度 / 场景标签 / 原子能力 / 任务指纹
任务步骤单元格内用换行分隔的编号步骤，如 "1.从…\n2.把…\n3.将…"
原子能力列为可选，仅在批量任务平台要求时填写；标签见 assets/atomic_skills_catalog.csv。

输出:
    逐条任务的问题清单 + 汇总统计；退出码 0 表示全部通过，1 表示存在不通过项。
脚本只做规则可判的部分，机器人可执行性、逻辑闭环、真实感仍需人工判定。
"""
import argparse
import csv
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOG_PATH = SCRIPT_DIR.parent / "assets" / "atomic_skills_catalog.csv"


def load_catalog():
    """返回 全部标签集合、可用标签集合、非拿放可用标签集合、禁用标签集合。"""
    all_tags, usable, non_pick, forbidden = set(), set(), set(), set()
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                tag = row["英文标签"].strip()
                status = row["状态"].strip()
                family = row["所属技能族"].strip()
                all_tags.add(tag)
                if status.startswith("可用"):
                    usable.add(tag)
                    if family != "基础":
                        non_pick.add(tag)
                else:
                    forbidden.add(tag)
    return all_tags, usable, non_pick, forbidden


ALL_TAGS, USABLE_TAGS, NON_PICK_TAGS, FORBIDDEN_TAGS = load_catalog()

# 步骤动作关键词 → 必须出现的原子能力标签（任一即可）；出现即触发"漏标"检查
# 注意：匹配前剔除【】中的物品名，避免"包装纸/收纳盒/清洁刷/印章"等物品名误伤
ACTION_REQUIRED_TAG = [
    (r"拉链", None),                                   # 拉链方向特殊处理见下
    (r"拧开|拧松", None),                              # Unscrew / OpenJar
    (r"拧紧|拧回|拧好|拧上", None),                    # Screw / CloseJar
    (r"折叠|对折|折起|折好|折成", {"Fold"}),
    (r"卷成|卷起|卷绕|绕成圈|卷成圈", {"Roll"}),
    (r"撑开|张开", {"Spread open", "Unfold"}),
    (r"抖开|铺平|展开|铺开", {"Unfold", "Spread open"}),
    (r"叠放(?!的)|堆叠|摞[到齐在好上]|码垛", {"Stack"}),
    (r"挂到|挂回|挂在|挂上", {"Hang"}),
    (r"插入|插进|插好|插到|套到|套入|套进|套上", {"Insert"}),
    (r"拔插头|拔出|拔起", {"Unplug", "PullOut"}),
    (r"(?<!魔术)贴", {"Stick"}),
    (r"撕", {"Tear"}),
    (r"系紧|系好|系上|系成|扎好|捆好", {"Tie"}),
    (r"包装|包裹|包好|包住|裹住|盖住", {"Package", "Cover"}),
    (r"盖章|盖印|印章", {"stamp"}),
    (r"写字|书写|写明|画一横|画一条横线", {"Write"}),
    (r"倒进|倒入|倒到|倒满|倒出", {"Pour"}),
    (r"舀|铲起", {"Scoop", "Scoop up"}),
    (r"擦拭|干擦|擦去|擦[拭抹]", {"Wipe"}),
    (r"刷子刷|干刷|刷[洗洗拭]", {"Brush"}),
    (r"扫[进拢到]|扫地|清扫", {"Sweep"}),
    (r"夹取|夹起|夹到|夹住|夹进|夹入|夹着|用[^，。；]{0,8}夹", {"Pinch", "Clip"}),
    (r"翻[面到转]|翻转|翻开", {"Flip", "Open"}),
    (r"按|压", {"Press", "PressButton", "Toggle"}),
    (r"推合|推到|推进|推回|推动", {"Push", "PushTogether"}),
    (r"拉开|拉回|拉动|拉出", {"Pull", "PullApart", "Unzip"}),
    (r"摇[匀动晃]", {"Shake"}),
    (r"搅拌", {"Stir"}),
]

ZIP_OPEN_RE = re.compile(r"拉开?拉链|拉链.*拉开")
ZIP_CLOSE_RE = re.compile(r"拉合|拉上.*拉链|拉链.*拉[合上]")

# 标签 → 步骤中应出现的关键词（标了却没出现，给 WARN；用完整文本，含【】）
TAG_KEYWORD_HINT = {
    "Fold": r"折|叠", "Unfold": r"展开|铺平|抖开|铺", "Roll": r"卷|绕",
    "Stack": r"叠放|摞|堆叠|码", "Hang": r"挂", "Insert": r"插|套",
    "Unplug": r"拔插头|拔", "PullOut": r"拔出|拔",
    "Stick": r"贴", "Tear": r"撕", "Tie": r"系|扎|捆",
    "Package": r"包|裹", "Cover": r"盖|遮|裹",
    "stamp": r"章|盖印", "Write": r"写|画.*横",
    "Pour": r"倒", "Scoop": r"舀", "Scoop up": r"铲",
    "Wipe": r"擦", "Brush": r"刷", "Sweep": r"扫",
    "Pinch": r"夹|捏", "Clip": r"夹",
    "Flip": r"翻", "Unzip": r"拉链",
    "Screw": r"拧", "Unscrew": r"拧", "OpenJar": r"拧|罐", "CloseJar": r"拧|罐",
    "Push": r"推", "Pull": r"拉", "Toggle": r"拨|按",
    "Press": r"按|压", "PressButton": r"按",
    "Shake": r"摇", "Stir": r"搅",
    "Spread open": r"撑开|张开",
    "Open": r"打开|翻开|开", "OpenBox": r"打开|掀开|盒盖", "Close": r"合|盖|关",
    "CloseBox": r"合|盖|盒盖", "Uncap": r"掀开|打开.*盖|壶盖|瓶盖",
}


def parse_tags(raw):
    return [t.strip() for t in re.split(r"[,，、;；]", str(raw or "")) if t.strip()]


# ---------- 规则词表（与 SKILL.md 及 references/02-writing-and-review.md 保持一致）----------

# 心智动作禁用词：出现即判不通过
MENTAL_BANS = [
    "观察", "查看", "核对", "记录", "对比", "等待", "确认", "检查", "判断", "分辨",
    "辨认", "识别", "看一眼", "思考", "确保", "清点", "点数", "留意", "注意",
    "静置", "等候", "待机", "注视", "打量", "辨识", "盘点",
]
# 注意：含禁用字但合法的动作（如"捡起"），MENTAL_BANS 用精确词匹配，不做子串误伤；
# "检查"等词若以"检查"子串出现即命中，这里没有合法动作含这些词，直接子串匹配。

# 量化/方式类禁用
QUANT_BANS = [
    "适量", "少许", "八分满", "七分满", "若干", "顺时针", "逆时针", "多次", "反复",
]
DEGREE_BANS = [r"\d+\s*度", r"\d+\s*分钟", r"\d+\s*秒"]

# 能力越界禁用
ABILITY_BANS = [
    "走过去", "走到", "走至", "转身", "弯腰", "蹲下", "起身", "转头", "扭头", "升降", "移动底盘",
    "开水龙头", "水龙头", "冲洗", "水洗", "浸泡", "淘米", "烧水", "接水", "煮",
    "炒", "煎", "炸", "蒸", "烤", "开火", "打开冰箱", "开冰箱", "扣扣子", "系鞋带",
    "穿针", "一键复位", "湿抹布", "湿巾", "洗碗", "洗菜", "洗杯",
    "橡皮屑", "碎屑", "纸屑", "撒碎",
    # 90D 平行两指夹爪做不了：扣扳机、大力按压、剪切类工具
    "订书机", "打孔器", "扫码枪", "价签枪", "胶枪", "扳机", "剪刀", "压蒜器", "核桃夹",
    # 采集结束的手臂复位由采集员录制，不属于任务步骤
    "手臂复位", "复位手臂",
]

# 指定手数的措辞：写了就强制采集员必须用双手/某只手，现场要求一律不写，由采集员自选
HAND_SPEC_PATTERN = re.compile(r"双臂|双手|一手|一只手|另一手|另一只手|左手|右手|左臂|右臂")

LEARNED_RULES_PATH = SCRIPT_DIR.parent / "references" / "06-learned-rules.md"


def load_learned_bans():
    """读取教训库中“生效”规则的禁用词。用户新提出的禁令记进教训库后，无需改脚本即可拦截。"""
    bans = []
    if not LEARNED_RULES_PATH.exists():
        return bans
    status = rule_id = None
    for line in LEARNED_RULES_PATH.read_text(encoding="utf-8").splitlines():
        head = re.match(r"^### (L-\d{3})｜.+?｜(.+?)｜", line)
        if head:
            rule_id, status = head.group(1), head.group(2)
            continue
        ban = re.match(r"^- 禁用词：(.*)$", line)
        if ban and status == "生效":
            for w in re.split(r"[、,，]", ban.group(1)):
                w = w.strip()
                # 已在内置词表里的不重复报
                if w and w not in ABILITY_BANS:
                    bans.append((w, rule_id))
    return bans


LEARNED_BANS = load_learned_bans()

# 精确放置位置（放/摆 + 左右/角/第N个）
PRECISE_PLACE_PATTERNS = [
    r"[放摆搁].{0,4}(左侧|右侧|左上角|右下角|左下角|右上角|正中央|最左边|最右边)",
    r"第[一二三四五1-5]个格", r"距.{0,4}\d+\s*厘米", r"台面左|台面右",
]

# 非拿放类技能关键词（命中即视为包含非拿放技能）
NON_PICK_PLACE_SKILLS = [
    "擦", "抹", "刷", "扫", "折", "叠", "卷", "铺平", "对折", "撑开", "拧", "旋",
    "盖", "合", "关", "开", "拉", "推", "拨", "按压", "按", "插", "拔", "套", "挂",
    "贴", "封", "缠", "绕", "绑", "系", "扎", "夹", "夹取", "舀", "铲", "倒", "蘸",
    "包", "裹", "塞", "卡", "扣", "撕", "剥", "翻", "码齐", "对齐", "拢", "整理",
    "堆叠", "叠放", "摞", "配对", "组装", "装", "压", "戳", "敲", "盖印", "盖章",
    "书写", "写", "画一横", "画一条横线", "抽", "捏合", "收口", "排气", "卷绕", "理顺", "穿",
]

# 拿起来源词（步骤里出现"拿起/取出/取下/夹起"等时，必须同时出现来源位置）
PICK_VERBS = ["拿起", "拿出", "取出", "取下", "夹起", "抓起", "捧起", "端起", "抽出", "拎起", "拔起"]

# 位置/容器名词（用于识别"XX上/里/中"）
LOCATION_NOUNS = "桌台架筐篮盒箱袋包钩杆盘筒瓶罐柜手书堆叠座格兜盆碗锅杯层床凳铺垫巾布"

# 来源位置识别：
#   A：从XX上/里/中/旁/边/内拿起
#   B：位置名词 + 方位词（桌子上 / 胶带座上 / 晾衣杆上 / 抽屉里）
#   C：方位词 + 拿起/取出/取下（上拿起 / 里取出 / 杆上取下）
SOURCE_PATTERNS = [
    r"从[^，。；,;]{0,14}[上里中旁边内]",
    rf"[{LOCATION_NOUNS}][^，。；,;]{{0,3}}[上里中旁边内]",
    r"[上里中旁边内][\s]*[拿取抽夹拎端拔捧]?[起出下]",
]
SOURCE_CONTAINERS = ["桌", "台", "抽屉", "架", "筐", "篮", "盒", "箱", "袋", "包", "钩",
                     "杆", "托盘", "筒", "瓶", "罐", "槽", "格", "盘", "柜", "手", "掌",
                     "兜", "窝", "夹", "盆", "碗", "锅", "杯", "书", "堆", "叠", "垫", "巾", "布"]

# 一步到位模式
ONE_SHOT_PATTERNS = [
    r"[一二三四五六七八九十两\d]+个?【[^】]+】.{0,6}(放进|放入|放进|插到|插进|拿到)",
    r"一次性", r"一起(放|装|拿|插)",
]

# 常见“并”连接动作的写法应改写；其他含“并”情形可能是固有名，仅提醒。
NAME_AND_ACTION = re.compile(
    r"(?<![合兼归吞])并(?:且|将|把|摆|铺|叠|折|拿|取|放|装|收|分|清|擦|刷|夹|拧|关|合|盖|开|拉|推|"
    r"插|拔|挂|贴|码|堆|整|打|归|理|卷|搅|舀|拆|印|写|画|倒|压|按|拨)"
)
# “XX后XX”禁用；和/与/及只提醒人工复核。
NAME_SOFT_WORDS = ["和", "与", "及"]
# “后”作为方位词的合法用法，不当作“XX后XX”
HOU_WHITELIST = ["前后", "后备", "后背", "后排", "后方", "后侧", "后面", "后座", "后部", "后端", "后盖", "后厨"]
# 场景描述由场景标签承担，不进任务名；确需使用时只能写成“在 xx”
SCENE_WORDS = ["客房", "厨房", "卧室", "客厅", "书房", "办公室", "超市", "酒店", "柜台",
               "浴室", "阳台", "教室", "餐厅", "前台", "收银台", "仓库", "玄关", "卫生间"]
# 一步一个动作的启发式。纯搬运“拿起X放进Y”算一个动作，不在此列；
# “拿起X后面再贴/擦/倒/盖/拧/夹…”是两个动作，要拆开。
# 匹配前先把【】里的物品名替换掉，避免【折叠椅】【夹子】这类名字误报。
MULTI_PICK_PATTERN = re.compile(
    r"(拿起|取出|拿出|取下|捏起|提起|端起)[^，。；\n]*?"
    r"(贴|擦拭|擦|倒入|倒进|倒出|盖上|盖回|盖在|拧开|拧紧|拧上|套上|套在|夹住|夹取|撕开|撕下|"
    r"对折|折叠|卷成|卷起|涂抹|搅拌|扣上|按住|打开|合上)"
)
# “后”表示先后连接（排除 后方/后侧/后面/后部 等方位词，以及“从前向后对折”里的“向后”）
AFTER_CONNECTOR_PATTERN = re.compile(r"(?<![前向往朝])后(?![方侧面部端排座背备])")
STEP_MAX_CHARS = 30

# P0 自动可判部分：其他复杂物理/5 套库存/动作顺序仍须人工核验
BANNED_DETAIL_ITEMS = [
    "硬壳笔记本", "彩色圆珠笔", "茶杯", "咖啡杯", "旅行洗护瓶",
    "证件卡套", "防漏袋", "瓶盘",
]
# 拟人化/精细修整动作正则（L-027）：平行夹爪无法完成或无实际作业意义的精细修整
FUSSY_HUMAN_PATTERN = re.compile(
    r"让.{0,8}(?:标签|商标|盒面|正面|牌面|图案|字样)朝"
    r"|提手(?:竖起|分开|理顺|拨正)"
    r"|(?:袋身|袋面|桌布)抚平|抚平【[^】]+】的(?:袋面|袋身)"
    r"|四角(?:向上)?(?:包起|压平)"
    r"|(?:扣好|按好).{0,6}卡扣"
    r"|搭在.{0,6}(?:边沿|桌角|台角)"
    r"|擦拭【[^】]+】(?:内壁|内底|瓶身|罐身|盒面|壳身|提手|边沿|牌面|盘面)"
)
FIXED_ENVIRONMENTS = {
    "桌面", "台面", "桌子", "书桌", "货架", "置物架", "书架",
    "床面", "桌面抽屉", "晾衣杆", "挂钩",
}
# 只查“明确倒出液体”的措辞：倒扣、倒置不属于液体倾倒。
LIQUID_POUR_PATTERN = re.compile(
    r"(?:倒(?:入|进|出|到|向|往|给)?[^，。；\n]{0,24}"
    r"(?:水|油|饮料|牛奶|果汁|洗护液|液体|酱油))"
    r"|(?:(?:水|油|饮料|牛奶|果汁|洗护液|液体|酱油)"
    r"[^，。；\n]{0,24}倒(?:入|进|出|到))"
)


def is_l017_watering(step: str, joined: str = "") -> bool:
    """L-017（生效）：用户明确允许从【水瓶】往【花瓶】倒水。

    放行条件（三条都要满足）：目标任务里有【水瓶】作水源；本步目标是【花瓶】；
    倒的是水而不是饮料、油、洗护液等其它液体。其余倒液体场景仍然禁止。
    """
    if not re.search(r"【花瓶\d*】", step):
        return False
    if not re.search(r"倒(?:入|进|到|向|往)[^，。；\n]{0,24}水(?!油)", step):
        return False
    return bool(re.search(r"【水瓶】", step) or re.search(r"【水瓶】", joined))
STRICT_STEP_FORMAT = re.compile(r"^\d+\.[^\s]")


# 宾语前置启发式：名称主体（去掉前缀后）以这些动词结尾且长度短，疑似"宾语+动词"
OBJECT_FIRST_VERBS = ["分拣", "收纳", "整理", "打包", "折叠", "摆放", "归类", "码放", "清洁",
                      "归位", "归置", "归拢", "叠放", "摆好", "擦拭", "分装", "陈列", "收好", "叠好"]


def has_source(step: str) -> bool:
    """判断一个含『拿起/取出/取下…』的步骤是否写明了来源位置。"""
    if any(re.search(p, step) for p in SOURCE_PATTERNS):
        return True
    # 从 + 容器名词（如 从筐里、从书包中、从另一只手上）
    if "从" in step and any(c in step for c in SOURCE_CONTAINERS):
        return True
    return False


def split_steps(raw: str):
    """从步骤单元格解析步骤列表，支持 1. / 1、/ (1) 以及换行。"""
    if raw is None:
        return []
    text = str(raw).replace("\r", "\n")
    # 先按换行拆
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    steps = []
    for line in lines:
        # 同一行里可能有多个编号
        parts = re.split(r"(?:^|[\s；;])\s*(\d+)\s*[\.、\)）:：]\s*", line)
        if len(parts) > 1:
            # parts: 前缀, 编号, 内容, 编号, 内容...
            for i in range(1, len(parts), 2):
                content = parts[i + 1].strip() if i + 1 < len(parts) else ""
                if content:
                    steps.append(content)
        else:
            # 无编号，若整行非空也算一步
            cleaned = re.sub(r"^\d+\s*[\.、\)）:：]\s*", "", line).strip()
            if cleaned:
                steps.append(cleaned)
    return steps


def extract_brackets(text: str):
    return re.findall(r"【([^】]*)】", text or "")


def check_brackets_balance(text: str):
    return text.count("【") == text.count("】")


def has_non_pick_skill(steps):
    joined = "".join(steps)
    return [w for w in NON_PICK_PLACE_SKILLS if w in joined]


from collections import Counter

# 平台非拿放原子技能映射，仅用于步骤近似提示，不单独决定判重。
STEP_ATOMIC_SKILL_MAP = [
    (r"拉开?拉链|拉链.*拉开", "Unzip"),
    (r"拉合|拉上.*拉链|拉链.*拉[合上]", "CloseZip"),
    (r"拧开|拧松", "OpenJar"),
    (r"拧紧|拧回|拧好|拧上", "CloseJar"),
    (r"打开.*(?:盒|箱|篮|筐)|掀开.*(?:盒|箱|篮)", "OpenBox"),
    (r"合上.*(?:盒|箱|篮|筐)|盖好.*(?:盒|箱)|关闭.*(?:盒|箱)", "CloseBox"),
    (r"拿下.*盖|取下.*盖|掀开.*盖|揭开.*盖|打开.*盖", "Uncap"),
    (r"盖回|盖在|盖上.*盖", "Cover"),
    (r"折叠|对折|折起|折好", "Fold"),
    (r"展开|铺平|抖开|铺开|铺在", "Unfold"),
    (r"撑开|张开", "Spread open"),
    (r"卷成|卷起|卷绕|绕成", "Roll"),
    (r"叠放(?!的)|堆叠|摞[到齐在好上]|码垛|套在□", "Stack"),
    (r"拆下|拆卸|取下.*套", "Unstack"),
    (r"擦拭|干擦|擦去|擦[拭抹]", "Wipe"),
    (r"刷|干刷", "Brush"),
    (r"夹取|夹起|捏住|捏起", "Pinch"),
    (r"夹住|夹封|别在", "Clip"),
    (r"倒进|倒入|倒到|倒满|倒出|倒掉", "Pour"),
    (r"舀", "Scoop"),
    (r"铲起|铲入", "Scoop up"),
    (r"搅拌", "Stir"),
    (r"挂到|挂回|挂在|挂上", "Hang"),
    (r"从.*(?:架|杆|钩).*取下", "Takedown"),
    (r"插入|插进|插好|插到|套入|套进|套上", "Insert"),
    (r"拔出|拔下|拔起|拔掉", "PullOut"),
    (r"拔插头", "Unplug"),
    (r"按压|按下|按住|拍松|扣上", "Press"),
    (r"拨动|拨开|拨回", "Toggle"),
    (r"推合|推到|推进|推回", "Push"),
    (r"拉动|拉开(?!.*拉链)|拉直", "Pull"),
    (r"摇动|摇匀|晃动", "Shake"),
    (r"贴在|贴到|粘贴", "Stick"),
    (r"盖章|盖印", "stamp"),
    (r"画一横|画一条横线", "Write"),
    (r"解开|松开", "Untie"),
    (r"系紧|系好|扎好", "Tie"),
    (r"翻开|翻页", "Flip"),
]

_LOC_RE = re.compile(
    r"桌面|台面|书桌|货架|展示架|陈列架|样品架|展示台|促销台|置物架"
    r"|上层|下层|左前侧|右前侧|左后方|左上角|右上角|左下角|右下角"
    r"|前侧|后侧|左侧|右侧|中央|左边|右边|内部|一侧|靠里位置|原位"
)


def _step_skills(step: str):
    plain = re.sub(r"【[^】]*】", "□", step)
    found = []
    if re.search(r"用【[^】]*夹】", step):
        found.append("Pinch")
    for pat, tag in STEP_ATOMIC_SKILL_MAP:
        if re.search(pat, plain) and tag not in found:
            found.append(tag)
    return found


def extract_non_pick_atomic_skills(steps):
    skills = []
    for s in steps:
        for tag in _step_skills(s):
            if tag not in skills:
                skills.append(tag)
    return skills


def step_skeletons(steps):
    """提取无序动作步骨架；屏蔽物品和方位可能误合并，仅作复核线索。"""
    out = []
    for s in steps:
        sk = _step_skills(s)
        if sk:
            out.append("SKILL:" + "+".join(sk))
            continue
        plain = re.sub(r"【[^】]*】", "□", s)
        plain = _LOC_RE.sub("○", plain)
        out.append(plain)
    return out


def task_fingerprint(name, steps, scene=""):
    """从任务名和步骤提取对象、动作及骨架，用于同批近似提示。"""
    joined = "".join(steps)
    objects = sorted(set(re.findall(r"【([^】\d]*?)(?:\d+)?】", joined)))
    actions = []
    for s in steps:
        for w in NON_PICK_PLACE_SKILLS:
            if w in s and w not in actions:
                actions.append(w)
    atomic_skills = extract_non_pick_atomic_skills(steps)
    skeletons = step_skeletons(steps)
    return {
        "name": name,
        "scene": scene,
        "objects": objects,
        "actions": actions,
        "atomic_skills": atomic_skills,
        "step_skeletons": skeletons,
        "literal_steps": [re.sub(r"\s+", "", s) for s in steps],
        "signature": "|".join(objects) + "::" + ",".join(actions),
    }


def step_difference(a, b):
    """无序一对一匹配动作骨架，以较长任务为分母；缺步骤时返回 None。"""
    ska = a.get("step_skeletons") or []
    skb = b.get("step_skeletons") or []
    if not ska or not skb:
        return None
    inter = sum((Counter(ska) & Counter(skb)).values())
    return 1.0 - inter / max(len(ska), len(skb))


def validate_atomic_tags(raw_tags, joined):
    """校验"原子能力"列：必填、标签合法、禁用标签、非拿放≥1、与步骤一致。"""
    issues = []
    tags = parse_tags(raw_tags)
    if not tags:
        issues.append(("BLOCK", "缺少『原子能力』列或未填写（必须附带平台标准原子能力标签）"))
        return issues, tags
    # 漏标匹配时剔除【】中的物品名（包装纸/收纳盒/清洁刷/印章等物品名会误伤）
    action_text = re.sub(r"【[^】]*】", "", joined)
    tag_set = set(tags)
    # 非法/禁用标签
    for t in tags:
        if ALL_TAGS and t not in ALL_TAGS:
            issues.append(("BLOCK", f"原子能力标签『{t}』不在平台原子能力表中（查 assets/atomic_skills_catalog.csv）"))
        elif t in FORBIDDEN_TAGS:
            issues.append(("BLOCK", f"原子能力标签『{t}』属于禁用/不可用动作"))
    # 非拿放标签 ≥1
    if tag_set and not (tag_set & NON_PICK_TAGS):
        issues.append(("BLOCK", "原子能力只有拿放类标签（Pick/Place 等），至少补 1 个非拿放类标签"))
    # 漏标：步骤里有明确动作但没给对应标签
    for pat, needed in ACTION_REQUIRED_TAG:
        if re.search(pat, action_text):
            if needed and not (tag_set & needed):
                issues.append(("BLOCK", f"步骤中出现『{pat}』动作，但原子能力未标注 {sorted(needed)}"))
    # 拉链方向性
    if ZIP_OPEN_RE.search(action_text) and not (tag_set & {"Unzip"}):
        issues.append(("BLOCK", "步骤中有拉开拉链动作，但未标注 Unzip"))
    if ZIP_CLOSE_RE.search(action_text) and not (tag_set & {"Close", "CloseBox"}):
        issues.append(("WARN", "步骤中有拉合拉链动作，建议用 Close 标注（平台无拉上拉链标签）"))
    if re.search(r"拧开|拧松", action_text) and not (tag_set & {"Unscrew", "OpenJar"}):
        issues.append(("BLOCK", "步骤中有拧开/拧松动作，但未标注 Unscrew 或 OpenJar"))
    if re.search(r"拧紧|拧回|拧好|拧上", action_text) and not (tag_set & {"Screw", "CloseJar", "Close"}):
        issues.append(("BLOCK", "步骤中有拧紧/拧回动作，但未标注 Screw 或 CloseJar/Close"))
    # 错标（WARN，宽松）：标了标签但完整步骤里完全没有对应动作/物品名；
    # 用完整文本（含【】），因为"盖、章、夹"等动作字可能落在【水壶盖】【印章】这类物品名里
    for t in tags:
        hint = TAG_KEYWORD_HINT.get(t)
        if hint and not re.search(hint, joined):
            issues.append(("WARN", f"标注了『{t}』但步骤中未出现对应动作（{hint}），请确认是否误标"))
    return issues, tags


def resolve_step_limits(long_task, min_steps, max_steps):
    """默认长任务按 30 步提示，自定义边界由用户要求决定。"""
    recommended = 30 if (long_task and min_steps is None
                         and (max_steps is None or max_steps >= 30)) else None
    minimum = min_steps if min_steps is not None else (1 if long_task else 10)
    maximum = max_steps if max_steps is not None else (None if long_task else 20)
    return minimum, maximum, recommended


def validate_row(row, min_steps, max_steps, ledger_sigs, recommended_min_steps=None):
    issues = []
    name = str(row.get("任务名称", "") or "").strip()
    steps_raw = row.get("任务步骤", "")
    scene = str(row.get("场景标签", "") or "").strip()
    steps = split_steps(steps_raw)
    joined = "\n".join(steps)

    # ---- 命名 ----
    if not name:
        issues.append(("BLOCK", "任务名称为空"))
    else:
        for w, rid in LEARNED_BANS:
            if w in name:
                issues.append(("BLOCK", f"任务名称违反教训库 {rid}：含『{w}』：{name}"))
        base, separator, subject = name.partition("-")
        main = (subject if separator else name).strip()
        if not separator or not base.strip():
            issues.append(("BLOCK", f"任务名称缺少实际基地前缀，应为『基地-任务主体』：{name}"))
        if not main:
            issues.append(("BLOCK", "任务名称缺少核心动作"))
        if NAME_AND_ACTION.search(main):
            issues.append(("BLOCK", f"任务名称不得含『并』连接复合动作，请直接连写或概括共同目标：{name}"))
        elif "并" in main:
            issues.append(("WARN", f"任务主体含『并』，请避免用作动作连接词；固有物品名称可保留：{name}"))
        masked = main
        for ok_word in HOU_WHITELIST:
            masked = masked.replace(ok_word, "")
        if "后" in masked:
            issues.append(("BLOCK", f"任务名称禁用“XX后XX”，应概括共同目标（如折叠短裤）：{name}"))
        for w in NAME_SOFT_WORDS:
            if w in main:
                issues.append(("WARN", f"任务名称含『{w}』：请确认名称概括同一工作而非罗列步骤：{name}"))
        for sw in SCENE_WORDS:
            if sw in main and f"在{sw}" not in main and f"从{sw}" not in main:
                issues.append(("WARN", f"任务名称含场景词『{sw}』：场景一般省略，确需说明时可用『在{sw}』；物品名称请按语义核对：{name}"))
        for v in OBJECT_FIRST_VERBS:
            if main.endswith(v) and len(main) <= len(v) + 6:
                issues.append(("BLOCK", f"任务名称宾语前置（以『{v}』结尾），应动词在前宾语在后：{name}"))
        if main.startswith("把") or main.startswith("将"):
            issues.append(("BLOCK", f"任务名称用了“把/将”句式，属于宾语前置，应动词在前：{name}"))
        if re.search(r"从.+?(?:放到|移到|拿到|摆到)|拿起.+?(?:对折|放到|放进)", main) or "、" in main:
            issues.append(("BLOCK", f"任务名称写核心动作，不写步骤过程或起止位置（反例：把衣服叠好从床上放到旁边的椅子上）：{name}"))
        if re.search(r"(?:工作|任务|流程|事宜|作业)$", main) or main.startswith("结束"):
            issues.append(("BLOCK", f"任务名称须直接体现机器人核心物理动作，不写抽象工作名（反例：结束槟榔试吃工作）：{name}"))

    # ---- P0：物料名称、括号边界与步骤编号 ----
    for obj in extract_brackets(joined):
        if obj in FIXED_ENVIRONMENTS:
            issues.append(("BLOCK", f"固定环境/家具不可加【】标注：{obj}"))
        if any(bad in obj for bad in BANNED_DETAIL_ITEMS):
            issues.append(("BLOCK", f"物料名称过细或违规：{obj}（应退回通用基础词，如 茶杯/咖啡杯→杯子、硬壳笔记本→笔记本、彩色圆珠笔→圆珠笔）"))
    ordinal = 0
    for line_no, raw_line in enumerate(str(steps_raw or "").replace("\r", "\n").split("\n"), 1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        ordinal += 1
        match = re.match(r"^(\d+)\.([^\s].*)$", raw_line)
        if not match:
            issues.append(("BLOCK", f"第{line_no}行编号格式不符，应为 1.xxx 且英文点后无空格：{raw_line[:45]}"))
        elif int(match.group(1)) != ordinal:
            issues.append(("BLOCK", f"第{line_no}行编号不连续，应是 {ordinal}.：{raw_line[:45]}"))

    # ---- 步骤数 ----
    n = len(steps)
    if n == 0:
        issues.append(("BLOCK", "未解析出任何步骤（检查步骤是否按换行+编号填写）"))
    elif n < min_steps:
        issues.append(("BLOCK", f"步骤数 {n}，少于下限 {min_steps}"))
    elif max_steps is not None and n > max_steps:
        issues.append(("BLOCK", f"步骤数 {n}，超过上限 {max_steps}；请检查是否拆步注水或确需扩展"))
    elif recommended_min_steps is not None and n < recommended_min_steps:
        issues.append(("WARN", f"长任务 {n} 步，建议 {recommended_min_steps} 步以上；优先补充同目标的关联工作和必要物料，时长须实测"))

    # 是否需要清洁依赖上下文；没有明显脏污线索时提示，不把关键词当成语义证明。
    clean_actions = [s for s in steps if re.search(
        r"擦|刷拭|刷洗|干刷|刷去|刷掉|用.{0,10}刷", re.sub(r"【[^】]*】", "", s))]
    if clean_actions and not re.search(
        r"灰尘|积灰|浮灰|灰渍|尘土|粉尘|污渍|污垢|污迹|油渍|油污|水渍|脏污|沾灰|有灰|有污|脏了|脏的|洒落|残留|擦去.{0,8}灰",
        name + joined,
    ):
        issues.append(("WARN", "擦拭或刷拭缺少明确脏污线索：逐处核对交付内容中的清洁对象、污渍或积灰及清洁原因；无依据应删除"))

    # ---- 逐步检查 ----
    for i, s in enumerate(steps, 1):
        if "，" in s or "," in s:
            issues.append(("BLOCK", f"第{i}步出现逗号，请拆分冗余描述或删去逗号：{s}"))
        for w in MENTAL_BANS:
            if w in s:
                issues.append(("BLOCK", f"第{i}步含心智动作『{w}』：{s}"))
        for w in QUANT_BANS:
            if w in s:
                issues.append(("BLOCK", f"第{i}步含模糊量词/方式词『{w}』：{s}"))
        if LIQUID_POUR_PATTERN.search(s) and not is_l017_watering(s, joined):
            issues.append(("BLOCK", f"第{i}步疑似真实液体倾倒（全部禁止）：{s}"))
        for pat in DEGREE_BANS:
            if re.search(pat, s):
                issues.append(("BLOCK", f"第{i}步含精确度数/时间：{s}"))
        for w in sorted(ABILITY_BANS, key=len, reverse=True):
            if w in s:
                issues.append(("BLOCK", f"第{i}步含能力越界内容『{w}』：{s}"))
                break
        hit_learned = False
        for w, rid in LEARNED_BANS:
            if w in s:
                issues.append(("BLOCK", f"第{i}步违反教训库 {rid}：含『{w}』：{s}"))
                hit_learned = True
        if not hit_learned:
            m_fussy = FUSSY_HUMAN_PATTERN.search(s)
            if m_fussy:
                issues.append(("BLOCK", f"第{i}步含拟人化或精细修整动作『{m_fussy.group(0)}』（违反 L-027，请改为正规朴素机器动作，擦拭统一写『擦拭【XX】表面』）：{s}"))
        if (("【键盘】" in s and "支脚" in s)
                or ("【电脑支架】" in s and "高度旋钮" in s)):
            issues.append(("WARN", f"第{i}步依赖型号结构；未核验现有物料时应换为同场景相邻作业：{s}"))
        if re.search(r"传递|递给|交到另一", s):
            issues.append(("WARN", f"第{i}步含传递动作：单手能完成的步骤不要为凑步数写成传递：{s}"))
        hand = HAND_SPEC_PATTERN.search(s)
        if hand:
            issues.append(("BLOCK", f"第{i}步指定了手数『{hand.group(0)}』（直接写动作，由采集员自选单手或双手）：{s}"))
        for pat in ONE_SHOT_PATTERNS:
            if re.search(pat, s):
                issues.append(("BLOCK", f"第{i}步疑似一步到位（同类多件须拆步）：{s}"))
        plain = re.sub(r"【[^】]*】", "□", s)
        if re.search(r"(?:打开|取下|拿下|掀开).*(?:盖子|盒盖|箱盖).*(?:放到|放在|放回|放置)", plain):
            issues.append(("BLOCK", f"第{i}步开盖或取盖与放下盖子须拆成两步：{s}"))
        if MULTI_PICK_PATTERN.search(plain):
            issues.append(("WARN", f"第{i}步『拿起』后面还带了别的动作，建议拆成两步（先拿起，再做动作）：{s}"))
        if "并" in plain:
            issues.append(("WARN", f"第{i}步用“并”连接了多个动作，建议拆成两步：{s}"))
        if AFTER_CONNECTOR_PATTERN.search(plain):
            issues.append(("WARN", f"第{i}步用“后”连接了多个动作，建议拆成两步：{s}"))
        if len(plain) > STEP_MAX_CHARS:
            issues.append(("WARN", f"第{i}步偏长（{len(plain)}字，建议不超过{STEP_MAX_CHARS}字），检查是否含多个动作：{s}"))
        # 【】配对
        if not check_brackets_balance(s):
            issues.append(("BLOCK", f"第{i}步【】不配对：{s}"))
        # 拿起来源
        if any(v in s for v in PICK_VERBS):
            if "【" in s and not has_source(s):
                issues.append(("BLOCK", f"第{i}步拿起物品未写明来源位置：{s}"))

    if (re.search(r"(?:备好|备齐|布置).*(?:学习|素描|绘画)", name)
            and not re.search(r"装包|携带|随行|收存", name)):
        tool_locations = {}
        pencil_case_closed = False
        for s in steps:
            for tool in re.findall(r"【((?:铅笔|笔|直尺|橡皮)\d*)】", s):
                if re.search(r"(?:放进|放入)【文具盒】", s):
                    tool_locations[tool] = "inside"
                elif "从【文具盒】" in s and re.search(r"拿出|取出|放到|放在", s):
                    tool_locations[tool] = "outside"
            if "【文具盒】" in s:
                if "打开" in s:
                    pencil_case_closed = False
                elif "合上" in s or "盖好" in s:
                    pencil_case_closed = True
        hidden_tools = [tool for tool, location in tool_locations.items() if location == "inside"]
        if pencil_case_closed and hidden_tools:
            issues.append(("WARN", "终态冲突：学习或绘画准备把待用文具留在合上的文具盒内；核对是否应取出摆好："
                           + "、".join(hidden_tools)))

    # 全文【】配对
    if not check_brackets_balance(joined):
        issues.append(("BLOCK", "整条任务【】括号不配对"))

    # ---- 非拿放技能 ----
    skills = has_non_pick_skill(steps)
    if not skills:
        issues.append(("BLOCK", "整条任务缺少非拿放类技能（纯拿放任务）"))
    elif len(set(skills)) < 2:
        issues.append(("WARN", f"非拿放技能仅命中『{skills[0]}』，动作类型偏单一"))

    # ---- 原子能力标签 ----
    # 原子能力为批量可选字段；只有填写了才严格检查标签一致性。
    if str(row.get("原子能力", "") or "").strip():
        tag_issues, _ = validate_atomic_tags(row.get("原子能力", ""), joined)
        issues.extend(tag_issues)

    # ---- 物品闭环粗检：开盖/盖子 ----
    # 出现"打开/拧开...盖"但全文未出现该盖的"放"与"盖回"，给 WARN（人工确认）
    opens = re.findall(r"(?:打开|拧开|掀开|揭开)【[^】]*盖[^】]*】", joined)
    if opens and ("盖回" not in joined and "盖到" not in joined and "盖上" not in joined and "合上" not in joined):
        issues.append(("WARN", "出现开盖动作但未见盖回/合上，请人工确认盖子去向闭环"))

    # ---- 同批步骤近似提示；外部台账只比较名称 ----
    fp = task_fingerprint(name, steps, scene)
    for old in ledger_sigs:
        if old.get("history"):
            current_name = name.split("-", 1)[-1].strip()
            old_name = old["name"].split("-", 1)[-1].strip()
            if current_name and current_name == old_name:
                issues.append(("WARN", f"历史任务同名：『{old['name']}』；名称相同不代表步骤重复，按需人工筛选"))
            continue
        literal, old_literal = fp["literal_steps"], old.get("literal_steps") or []
        if literal and old_literal and Counter(literal) == Counter(old_literal):
            issues.append(("BLOCK", f"与同批任务『{old['name']}』的步骤完全相同（忽略顺序）"))
            continue
        diff = step_difference(fp, old)
        if diff is not None and diff < 0.5:
            issues.append(("WARN", f"与同批任务『{old['name']}』动作骨架估计差异 {diff*100:.0f}%（允许50%重复）；骨架会忽略物品和细节，请按实际步骤及用途复核"))
    ledger_sigs.append(fp)

    return issues, fp, skills


def load_table(path: Path):
    if path.suffix.lower() == ".csv":
        import pandas as pd
        return pd.read_csv(path).fillna("")
    import pandas as pd
    return pd.read_excel(path).fillna("")


def load_ledger(path: Path):
    import pandas as pd
    reader = pd.read_csv if path.suffix.lower() == ".csv" else pd.read_excel
    df = reader(path, usecols=lambda column: column in {"任务名称", "任务名字"}, dtype=str).fillna("")
    if "任务名称" not in df.columns and "任务名字" not in df.columns:
        raise ValueError("历史表缺少『任务名称』或『任务名字』列，无法比较名称")
    return [{"name": str(r.get("任务名称", r.get("任务名字", ""))).strip(), "history": True}
            for _, r in df.iterrows()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", help="任务表 .xlsx/.csv")
    ap.add_argument("--ledger", help="可选历史表 .csv/.xlsx；仅提示同名，不比较历史步骤")
    ap.add_argument("--long", action="store_true", help="长任务建议30步以上，未达时提醒复核，无默认上限")
    ap.add_argument("--min-steps", type=int)
    ap.add_argument("--max-steps", type=int)
    args = ap.parse_args()
    min_steps, max_steps, recommended = resolve_step_limits(args.long, args.min_steps, args.max_steps)
    if min_steps < 1 or (max_steps is not None and max_steps < min_steps):
        ap.error("步数下限须为正数，上限不得小于下限")

    df = load_table(Path(args.tasks))
    required = {"任务名称", "任务步骤"}
    missing = required - set(df.columns)
    if missing:
        print(f"[FATAL] 任务表缺少必需列：{missing}，当前列为：{list(df.columns)}")
        sys.exit(2)

    ledger = load_ledger(Path(args.ledger)) if args.ledger else []
    print(f"本批任务 {len(df)} 条")
    if args.ledger:
        print(f"已读取指定表格的任务名称 {len(ledger)} 条")
    print()

    block_cnt = warn_cnt = pass_cnt = 0
    skill_family = {}
    for idx, row in df.iterrows():
        seq = row.get("序号", idx + 1)
        issues, fp, skills = validate_row(row, min_steps, max_steps, ledger, recommended)
        blocks = [i for i in issues if i[0] == "BLOCK"]
        warns = [i for i in issues if i[0] == "WARN"]
        for s in skills:
            skill_family[s] = skill_family.get(s, 0) + 1
        if blocks:
            block_cnt += 1
            print(f"[不通过] 序号{seq}  {fp['name']}")
            for _, msg in blocks:
                print(f"    ✗ {msg}")
            for _, msg in warns:
                print(f"    ⚠ {msg}")
        elif warns:
            warn_cnt += 1
            print(f"[有警告] 序号{seq}  {fp['name']}")
            for _, msg in warns:
                print(f"    ⚠ {msg}")
        else:
            pass_cnt += 1
            print(f"[通过]   序号{seq}  {fp['name']}")

    print("\n" + "=" * 60)
    print(f"汇总：通过 {pass_cnt}，有警告 {warn_cnt}，不通过 {block_cnt}，共 {len(df)} 条")
    if skill_family:
        top = sorted(skill_family.items(), key=lambda x: -x[1])[:10]
        print("命中技能词频 Top10：", "，".join(f"{k}×{v}" for k, v in top))
    print("\n提醒：真实作业必要性、现场时长、物料五套库存、物品闭环及双臂可行性须现场或人工验证（见 references/02-writing-and-review.md）。")
    sys.exit(1 if block_cnt else 0)


if __name__ == "__main__":
    main()
