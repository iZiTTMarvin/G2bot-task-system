"""连续段检测的规则回归；不验证机器人可执行性或场景意义。"""
from check_segment_overlap import find_overlaps


def task(number, steps):
    return {"id": str(number), "name": f"示例{number}", "steps": steps}


def main():
    original = [
        "从桌面拿起【餐巾1】", "把【餐巾1】铺在桌面上",
        "把【勺子1】放到【餐巾1】上", "把【叉子1】放到【餐巾1】上",
        "把【餐巾1】下侧折到餐具上", "把【餐巾1】一侧向内折",
        "把【餐巾1】另一侧向内折", "把包着餐具的【餐巾1】卷起",
    ]
    numbered = [step.replace("1】", "2】") for step in original]
    renamed = [step.replace("餐巾1", "包布2").replace("勺子1", "工具2").replace("叉子1", "配件2")
               for step in original]
    assert max(row["length"] for row in find_overlaps([task(1, original), task(2, numbered)])) == 8
    assert max(row["length"] for row in find_overlaps([task(1, original), task(2, renamed)], mask_objects=True)) == 8
    assert not find_overlaps([task(1, original), task(2, list(reversed(original)))])
    assert not find_overlaps([task(1, original[:2] + ["取用物品甲"]), task(2, original[:2] + ["取用物品乙"])])
    assert not find_overlaps([task(1, original)])
    print("5项连续段检测回归通过：编号、改名、顺序、短辅助段、自比较。")


if __name__ == "__main__":
    main()
