from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Knowledge base
KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base" / "ds_chunks.jsonl"

# Retrieval
DEFAULT_TOP_K = 3
# Historical dense baseline threshold. Do not reuse it for BM25 and do not use
# it in Experiment 0; recalibrate on a held-out dev set after the new corpus
# and benchmark are frozen.
MIN_RETRIEVAL_SCORE = 0.62

# Embedding
EMBEDDING_MODEL = "qwen3.7-text-embedding"
EMBEDDING_DIMENSION = 1024
EMBEDDING_BATCH_SIZE = 10
RAG_CACHE_DIR = PROJECT_ROOT / ".cache" / "rag"

# Generation
GENERATION_MODEL = "qwen3.7-flash"
GENERATION_TEMPERATURE = 0.2
