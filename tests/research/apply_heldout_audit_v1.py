import json
import shutil
from collections import Counter
from pathlib import Path

PATH = Path("tests/benchmarks/heldout/heldout_100_v1.jsonl")
BACKUP = Path("tests/new_test_questions_100.before_final_audit.bak")

def load_questions(path):
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("Top-level JSON must be a list")
        return data

    rows = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception as e:
            raise ValueError(f"Invalid JSONL at line {lineno}: {e}") from e
    return rows

questions = load_questions(PATH)

if not BACKUP.exists():
    shutil.copy2(PATH, BACKUP)

by_id = {q["id"]: q for q in questions}

expected_ids = [f"h{i:03d}" for i in range(1, 101)]
actual_ids = [q["id"] for q in questions]

if len(questions) != 100:
    raise ValueError(f"Expected 100 questions, got {len(questions)}")
if len(set(actual_ids)) != 100:
    raise ValueError("Duplicate IDs found")
if set(actual_ids) != set(expected_ids):
    raise ValueError(
        f"ID mismatch: missing={sorted(set(expected_ids)-set(actual_ids))}, "
        f"extra={sorted(set(actual_ids)-set(expected_ids))}"
    )

# --------------------------------------------------
# 1. 恢复 comparison / non-comparison = 50 / 50
# --------------------------------------------------
by_id["h033"]["type"] = "comparison"

by_id["h095"].update({
    "question": "最佳归并树中，权值大的归并段与权值小的归并段在层次安排上有什么区别？为什么？",
    "type": "comparison",
    "reference_answer": (
        "最佳归并树中，权值大的归并段应尽量安排在较浅层次，"
        "权值小的归并段可以位于较深层次。归并段的权值代表其记录数量，"
        "权值越大，每次参与归并产生的磁盘IO代价越高；"
        "缩短大权值归并段的路径可以减少其重复参与归并的次数，"
        "从而降低整棵归并树的带权路径长度WPL和总磁盘IO开销。"
    ),
    "core_facets": [
        "权值大的归并段应安排在较浅层次",
        "权值小的归并段可以安排在较深层次",
        "权值越大的归并段重复参与归并时IO代价越高",
        "这种层次安排可降低WPL和总磁盘IO开销"
    ],
})

# --------------------------------------------------
# 2. difficulty 平衡
# 最终目标：
# comparison     easy 7 / medium 39 / hard 4
# non-comparison easy 8 / medium 38 / hard 4
# --------------------------------------------------
for qid in ["h005", "h015", "h024", "h034", "h074", "h075"]:
    by_id[qid]["difficulty"] = "medium"

for qid in ["h050", "h060"]:
    by_id[qid]["difficulty"] = "hard"

# --------------------------------------------------
# 3. 最后一轮 core facet scope / atomicity 修正
# --------------------------------------------------
by_id["h007"]["core_facets"] = [
    "高效率对应时间复杂度",
    "低存储量需求对应空间复杂度",
    "算法评价需综合权衡时间、空间及其他指标，不能只看时间复杂度"
]

by_id["h023"]["core_facets"] = [
    "中缀转后缀需要一个运算符栈",
    "运算符栈用于暂存运算符并按优先级决定输出顺序",
    "后缀表达式求值需要一个操作数栈",
    "操作数栈用于保存操作数和中间计算结果"
]

by_id["h027"]["core_facets"] = [
    "BFS按层扩展，先发现的顶点先处理，符合先进先出",
    "打印机任务调度按任务到达顺序处理，先提交先执行，符合先进先出"
]

by_id["h036"]["core_facets"] = [
    "模式匹配是在主串中查找与模式串相等的子串",
    "返回该子串在主串中的位置，失败通常返回0",
    "模式匹配是串的查找、替换、删除等操作的基础"
]

by_id["h064"]["core_facets"] = [
    "DFS使用栈或递归实现",
    "DFS沿一条路径深入，无法继续时回溯",
    "BFS使用队列实现",
    "BFS按照距离起点的层次逐层扩展"
]

by_id["h093"]["core_facets"] = [
    "归并趟数公式S=⌈logₖr⌉",
    "k增大时归并趟数减少",
    "r减少时归并趟数减少",
    "k增大和r减少对归并趟数的影响方向相同"
]

by_id["h094"]["core_facets"] = [
    "真实归并段参与实际的磁盘读写IO",
    "虚归并段不产生实际磁盘IO操作"
]

# --------------------------------------------------
# 4. 按 h001~h100 顺序写成真正 JSONL
# --------------------------------------------------
questions = [by_id[qid] for qid in expected_ids]

with PATH.open("w", encoding="utf-8", newline="\n") as f:
    for q in questions:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")

# --------------------------------------------------
# 5. 最终审计
# --------------------------------------------------
required_fields = {
    "id", "question", "type", "reference_answer",
    "expected_chapter", "expected_source",
    "expected_chunk_id", "is_out_of_scope",
    "difficulty", "core_facets"
}

errors = []

for q in questions:
    missing = required_fields - set(q)
    if missing:
        errors.append(f"{q['id']}: missing fields {sorted(missing)}")

    if q["difficulty"] not in {"easy", "medium", "hard"}:
        errors.append(f"{q['id']}: invalid difficulty={q['difficulty']}")

    if q["expected_chunk_id"] != []:
        errors.append(f"{q['id']}: expected_chunk_id should be []")

    if q["is_out_of_scope"] is not False:
        errors.append(f"{q['id']}: is_out_of_scope should be false")

    if not isinstance(q["core_facets"], list) or not q["core_facets"]:
        errors.append(f"{q['id']}: empty core_facets")

    if any(not isinstance(x, str) or not x.strip() for x in q["core_facets"]):
        errors.append(f"{q['id']}: invalid core facet")

# 真 JSONL 校验
parsed_lines = []
for lineno, line in enumerate(PATH.read_text(encoding="utf-8").splitlines(), 1):
    if not line.strip():
        continue
    try:
        obj = json.loads(line)
    except Exception as e:
        errors.append(f"JSONL line {lineno} invalid: {e}")
        continue
    if not isinstance(obj, dict):
        errors.append(f"JSONL line {lineno} is not a JSON object")
    parsed_lines.append(obj)

comparison = [q for q in questions if q["type"] == "comparison"]
noncomparison = [q for q in questions if q["type"] != "comparison"]

comp_diff = Counter(q["difficulty"] for q in comparison)
non_diff = Counter(q["difficulty"] for q in noncomparison)
chapters = Counter(q["expected_chapter"] for q in questions)

print("===== HELD-OUT FINAL AUDIT =====")
print("questions =", len(questions))
print("jsonl_lines =", len(parsed_lines))
print("unique_ids =", len(set(q["id"] for q in questions)))
print("comparison =", len(comparison))
print("non_comparison =", len(noncomparison))
print("comparison_difficulty =", dict(comp_diff))
print("noncomparison_difficulty =", dict(non_diff))
print("chapters =", dict(chapters))
print("backup =", BACKUP)
print("output =", PATH)

if len(comparison) != 50:
    errors.append(f"comparison count != 50: {len(comparison)}")
if len(noncomparison) != 50:
    errors.append(f"non-comparison count != 50: {len(noncomparison)}")
if len(parsed_lines) != 100:
    errors.append(f"JSONL line count != 100: {len(parsed_lines)}")
if any(v != 10 for v in chapters.values()) or len(chapters) != 10:
    errors.append(f"chapter distribution is not 10x10: {dict(chapters)}")

expected_comp_diff = {"easy": 7, "medium": 39, "hard": 4}
expected_non_diff = {"easy": 8, "medium": 38, "hard": 4}

if dict(comp_diff) != expected_comp_diff:
    errors.append(
        f"comparison difficulty mismatch: {dict(comp_diff)} "
        f"!= {expected_comp_diff}"
    )
if dict(non_diff) != expected_non_diff:
    errors.append(
        f"non-comparison difficulty mismatch: {dict(non_diff)} "
        f"!= {expected_non_diff}"
    )

if errors:
    print("\n===== ERRORS =====")
    for e in errors:
        print("-", e)
    raise SystemExit(1)

print("\nFINAL_AUDIT=PASS")
