import os
import json
from pathlib import Path
from typing import List, Dict

import time
import numpy as np
import dashscope
from openai import OpenAI
from dotenv import load_dotenv
from http import HTTPStatus

from rag.config import (
    KNOWLEDGE_BASE_PATH,
    DEFAULT_TOP_K,
    MIN_RETRIEVAL_SCORE,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    GENERATION_MODEL,
    GENERATION_TEMPERATURE,
)


ENV_PATH = Path(__file__).with_name(".env")
load_dotenv(ENV_PATH, override=True)

BASE_DIR = Path(__file__).resolve().parent

REQUIRED_CHUNK_FIELDS = {
    "chunk_id",
    "text",
    "chapter",
    "section",
    "source_file",
    "page",
    "content_type",
}

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not DASHSCOPE_API_KEY:
    raise RuntimeError("没有检测到 DASHSCOPE_API_KEY，请先在 .env 文件中配置。")

dashscope.api_key = DASHSCOPE_API_KEY

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

def load_chunks_from_jsonl(
    file_path: Path = KNOWLEDGE_BASE_PATH,
) -> List[Dict]:
    """
    读取标准 JSONL 知识片段文件，并校验必要字段。

    JSONL 文件每一行都是一个独立的 JSON 对象。
    """
    if not file_path.exists():
        raise RuntimeError(
            f"标准知识片段文件不存在：{file_path}"
        )

    chunks = []
    seen_chunk_ids = set()

    with file_path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"JSONL 第 {line_number} 行格式错误：{exc}"
                ) from exc

            missing_fields = (
                REQUIRED_CHUNK_FIELDS - chunk.keys()
            )

            if missing_fields:
                missing_text = ", ".join(
                    sorted(missing_fields)
                )
                raise RuntimeError(
                    f"JSONL 第 {line_number} 行缺少字段："
                    f"{missing_text}"
                )

            chunk_id = chunk["chunk_id"]

            if chunk_id in seen_chunk_ids:
                raise RuntimeError(
                    f"发现重复 chunk_id：{chunk_id}"
                )

            if not str(chunk["text"]).strip():
                raise RuntimeError(
                    f"chunk {chunk_id} 的 text 不能为空"
                )

            seen_chunk_ids.add(chunk_id)
            chunks.append(chunk)

    if not chunks:
        raise RuntimeError(
            f"知识片段文件为空：{file_path}"
        )

    return chunks
def load_documents(folder: str = "docs") -> List[Dict]:
    """
    读取 docs 目录下所有 txt 文件。
    返回格式：
    [
        {"source": "data_structure.txt", "text": "..."},
        ...
    ]
    """
    documents = []

    folder_path = Path(folder)
    if not folder_path.is_absolute():
        folder_path = BASE_DIR / folder_path

    for file_path in folder_path.glob("*.txt"):
        text = file_path.read_text(encoding="utf-8")
        documents.append({"source": file_path.name, "text": text})

    if not documents:
        raise RuntimeError(f"{folder_path} 目录下没有找到 txt 文件。")

    return documents


def split_text(text: str, chunk_size: int = 250, overlap: int = 50) -> List[str]:
    """
    简单文本切分。
    chunk_size：每个片段大约多少字
    overlap：相邻片段重叠多少字，防止上下文被切断
    """
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start += chunk_size - overlap

    return chunks


def build_chunks(documents: List[Dict]) -> List[Dict]:
    """
    把所有文档切成小块。
    每个 chunk 保存来源文件和内容。
    """
    all_chunks = []

    for doc in documents:
        chunks = split_text(doc["text"])

        for i, chunk in enumerate(chunks):
            all_chunks.append({"source": doc["source"], "chunk_id": i, "text": chunk})

    return all_chunks


def embed_texts(texts: List[str], text_type: str = "document") -> List[List[float]]:
    """
    调用 qwen3.7-text-embedding，把文本转成向量。
    text_type:
    - document：用于知识库文本
    - query：用于用户问题
    """
    all_embeddings = []
    batch_size = 10

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        response = dashscope.TextEmbedding.call(
            model=EMBEDDING_MODEL,
            input=batch,
            dimension=EMBEDDING_DIMENSION,
            text_type=text_type,
        )

        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"Embedding 调用失败：{response.code} - {response.message}"
            )

        embeddings = response.output["embeddings"]

        # 按 index 排序，保证向量顺序和输入文本顺序一致
        embeddings = sorted(embeddings, key=lambda x: x["text_index"])

        for item in embeddings:
            all_embeddings.append(item["embedding"])

    return all_embeddings


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    计算两个向量的余弦相似度。
    值越大，说明语义越相似。
    """
    vec_a = np.array(a)
    vec_b = np.array(b)

    return float(np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b)))


def retrieve(
    query: str,
    chunks: List[Dict],
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict]:
    """
    根据用户问题检索最相关的 top_k 个标准知识片段。
    """
    query_embedding = embed_texts(
        [query],
        text_type="query",
    )[0]

    scored_chunks = []

    for chunk in chunks:
        score = cosine_similarity(
            query_embedding,
            chunk["embedding"],
        )

        scored_chunks.append({
            "score": score,
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
            "chapter": chunk["chapter"],
            "section": chunk["section"],
            "source_file": chunk["source_file"],
            "page": chunk["page"],
            "content_type": chunk["content_type"],
        })

    scored_chunks.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return scored_chunks[:top_k]

def generate_answer(
    query: str,
    retrieved_chunks: List[Dict],
) -> str:
    """
    把检索到的文本片段传给大模型，
    让模型依据课程资料回答。
    """
    context_blocks = []

    for i, chunk in enumerate(retrieved_chunks):
        page_text = (
            str(chunk["page"])
            if chunk["page"] is not None
            else "未标注"
        )

        context_blocks.append(
            f"资料{i + 1}\n"
            f"章节：{chunk['chapter']}\n"
            f"小节：{chunk['section']}\n"
            f"来源文件：{chunk['source_file']}\n"
            f"页码：{page_text}\n"
            f"片段编号：{chunk['chunk_id']}\n"
            f"内容：{chunk['text']}"
        )

    context = "\n\n".join(context_blocks)

    system_prompt = """
你是一个数据结构课程智能助教。

回答规则：
1. 只使用给定课程资料中能够直接支持的内容回答，不得凭常识补充资料中没有的信息。
2. 回答应自然、准确、适合本科生理解，必要时可以分点、给出公式或代码。
3. 不要在正文中使用“资料1”“资料2”“片段1”等内部检索编号，也不要机械重复来源文件名。
4. 如果现有资料不足以回答问题的核心内容，只回答“根据当前资料无法确定”，不要猜测或编造。
"""

    user_prompt = f"""
以下是从课程知识库中检索到的资料：

{context}

用户问题：
{query}

请基于以上资料回答。
"""

    completion = client.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt.strip(),
            },
            {
                "role": "user",
                "content": user_prompt.strip(),
            },
        ],
        temperature=GENERATION_TEMPERATURE,
        extra_body={"enable_thinking": False},
    )

    return completion.choices[0].message.content


def answer_question(
    query: str,
    chunks: List[Dict],
    top_k: int = DEFAULT_TOP_K,
) -> Dict:
    """
    根据用户问题完成检索和回答生成。

    Args:
        query: 用户问题。
        chunks: 已包含 embedding 的知识片段。
        top_k: 检索结果数量上限。

    Returns:
        包含答案、来源、检索结果、耗时和错误信息的字典。
    """
    start_time = time.perf_counter()
    query = query.strip()

    if not query:
        return {
            "answer": "",
            "sources": [],
            "retrieved_chunks": [],
            "latency_ms": 0,
            "error": {
                "code": "INVALID_QUERY",
                "message": "问题不能为空。",
            },
        }

    try:
        retrieved_chunks = retrieve(
            query=query,
            chunks=chunks,
            top_k=top_k,
        )

        if not retrieved_chunks:
            latency_ms = int(
                (time.perf_counter() - start_time) * 1000
            )

            return {
                "answer": "",
                "sources": [],
                "retrieved_chunks": [],
                "latency_ms": latency_ms,
                "error": {
                    "code": "EMPTY_RETRIEVAL",
                    "message": "没有检索到相关课程资料。",
                },
            }

        # 保存本次 Top-K 的相似度，供调试和评测使用
        retrieval_scores = [
            chunk["score"]
            for chunk in retrieved_chunks
        ]

        top1_score = retrieval_scores[0]

        # 先判断检索结果是否足够相关，再决定是否调用生成模型。
        # 这样可以避免“模型使用了低相关资料回答，
        # 但最终 sources 又被清空”的逻辑不一致。
        if (
            MIN_RETRIEVAL_SCORE is not None
            and top1_score < MIN_RETRIEVAL_SCORE
        ):
            latency_ms = int(
                (time.perf_counter() - start_time) * 1000
            )

            return {
                "answer": "根据当前资料无法确定",
                "sources": [],
                "retrieved_chunks": retrieved_chunks,
                "retrieval_scores": retrieval_scores,
                "top1_score": top1_score,
                "out_of_scope": True,
                "latency_ms": latency_ms,
                "error": None,
            }

        answer = generate_answer(
            query=query,
            retrieved_chunks=retrieved_chunks,
        )

        latency_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        sources = []

        for chunk in retrieved_chunks:
            sources.append({
                "chunk_id": chunk["chunk_id"],
                "chapter": chunk["chapter"],
                "section": chunk["section"],
                "source_file": chunk["source_file"],
                "page": chunk["page"],
            })

        return {
            "answer": answer,
            "sources": sources,
            "retrieved_chunks": retrieved_chunks,
            "retrieval_scores": retrieval_scores,
            "top1_score": top1_score,
            "out_of_scope": False,
            "latency_ms": latency_ms,
            "error": None,
        }

    except Exception as exc:
        latency_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        return {
            "answer": "",
            "sources": [],
            "retrieved_chunks": [],
            "latency_ms": latency_ms,
            "error": {
                "code": type(exc).__name__,
                "message": str(exc),
            },
        }


def prepare_knowledge_base(
    file_path: Path = KNOWLEDGE_BASE_PATH,
) -> List[Dict]:
    """
    读取标准 JSONL 知识片段，并生成文档向量。

    服务启动时执行一次，返回包含 embedding 的 chunks。
    """
    print("正在读取标准知识片段...")
    chunks = load_chunks_from_jsonl(file_path)

    print(f"共读取 {len(chunks)} 个知识片段。")

    print("正在生成知识片段向量...")
    chunk_texts = [chunk["text"] for chunk in chunks]
    chunk_embeddings = embed_texts(
        chunk_texts,
        text_type="document",
    )

    for chunk, embedding in zip(
        chunks,
        chunk_embeddings,
    ):
        chunk["embedding"] = embedding

    return chunks


def main():
    chunks = prepare_knowledge_base()

    print("RAG demo 已启动。输入 exit 退出。")
    print("-" * 50)

    while True:
        query = input("\n请输入你的问题：").strip()

        if query.lower() in ["exit", "quit", "q"]:
            print("已退出。")
            break

        if not query:
            continue

        print("\n正在处理问题...")

        result = answer_question(
            query=query,
            chunks=chunks,
            top_k=DEFAULT_TOP_K,
        )
        
        if result["error"] is not None:
            print(
                "\n处理失败："
                f"{result['error']['message']}"
            )
            continue

        print("\n检索到的资料片段：")

        for i, chunk in enumerate(result["retrieved_chunks"]):
            print(
                f"\n[{i + 1}] "
                f"相似度：{chunk['score']:.4f}，"
                f"章节：{chunk['chapter']}，"
                f"来源：{chunk['source_file']}，"
                f"片段：{chunk['chunk_id']}"
            )
            print(chunk["text"])

        print("\n模型回答：")
        print(result["answer"])

        print(f"\n本次问答耗时：{result['latency_ms']} ms")

if __name__ == "__main__":
    main()
