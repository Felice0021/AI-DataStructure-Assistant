from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# =========================
# 知识库
# =========================

KNOWLEDGE_BASE_PATH = (
    PROJECT_ROOT
    / "knowledge_base"
    / "ds_chunks.jsonl"
)

# =========================
# 检索
# =========================

DEFAULT_TOP_K = 3

# 暂时不启用。
# 后续根据课程内 / 范围外问题的真实 similarity score 分布标定。
# 当前测试集：
#   范围内最低 Top-1 = 0.777295
#   范围外最高 Top-1 = 0.455821
#   两类边界中点      = 0.616558
# 因此 v0.2 基线取 0.62。
# 后续扩充测试集后应重新运行 calibrate_threshold.py 标定。
MIN_RETRIEVAL_SCORE = 0.62

# =========================
# Embedding
# =========================

EMBEDDING_MODEL = "qwen3.7-text-embedding"
EMBEDDING_DIMENSION = 1024

# =========================
# Generation
# =========================

GENERATION_MODEL = "qwen3.7-plus-2026-05-26"
GENERATION_TEMPERATURE = 0.2
