import os
from pathlib import Path
from typing import List, Dict

import numpy as np
import dashscope
from openai import OpenAI
from dotenv import load_dotenv
from http import HTTPStatus
from pathlib import Path

ENV_PATH = Path(__file__).with_name(".env")
load_dotenv(ENV_PATH, override=True)

BASE_DIR = Path(__file__).resolve().parent
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not DASHSCOPE_API_KEY:
    raise RuntimeError("没有检测到 DASHSCOPE_API_KEY，请先在 .env 文件中配置。")

dashscope.api_key = DASHSCOPE_API_KEY

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


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
        documents.append({
            "source": file_path.name,
            "text": text
        })

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
            all_chunks.append({
                "source": doc["source"],
                "chunk_id": i,
                "text": chunk
            })

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
        batch = texts[i:i + batch_size]

        response = dashscope.TextEmbedding.call(
            model="qwen3.7-text-embedding",
            input=batch,
            dimension=1024,
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


def retrieve(query: str, chunks: List[Dict], top_k: int = 3) -> List[Dict]:
    """
    根据用户问题，从知识片段中找最相关的 top_k 个片段。
    """
    query_embedding = embed_texts([query], text_type="query")[0]

    scored_chunks = []

    for chunk in chunks:
        score = cosine_similarity(query_embedding, chunk["embedding"])

        scored_chunks.append({
            "score": score,
            "source": chunk["source"],
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"]
        })

    scored_chunks.sort(key=lambda x: x["score"], reverse=True)

    return scored_chunks[:top_k]


def generate_answer(query: str, retrieved_chunks: List[Dict]) -> str:
    """
    把检索到的文本片段塞给大模型，让模型基于资料回答。
    """
    context = "\n\n".join(
        [
            f"资料{i + 1}，来源：{chunk['source']}，片段编号：{chunk['chunk_id']}\n{chunk['text']}"
            for i, chunk in enumerate(retrieved_chunks)
        ]
    )

    system_prompt = """
你是一个数据结构课程智能助教。
你必须优先依据给定资料回答。
如果资料中没有相关内容，要明确说明“根据当前资料无法确定”，不要编造。
回答要适合本科生理解，必要时可以分点解释。
"""

    user_prompt = f"""
以下是从课程知识库中检索到的资料：

{context}

用户问题：
{query}

请基于以上资料回答。
"""

    completion = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )

    return completion.choices[0].message.content


def main():
    print("正在读取文档...")
    documents = load_documents("docs")

    print("正在切分文档...")
    chunks = build_chunks(documents)

    print(f"共得到 {len(chunks)} 个知识片段。")

    print("正在生成知识片段向量...")
    chunk_texts = [chunk["text"] for chunk in chunks]
    chunk_embeddings = embed_texts(chunk_texts, text_type="document")

    for chunk, embedding in zip(chunks, chunk_embeddings):
        chunk["embedding"] = embedding

    print("RAG demo 已启动。输入 exit 退出。")
    print("-" * 50)

    while True:
        query = input("\n请输入你的问题：").strip()

        if query.lower() in ["exit", "quit", "q"]:
            print("已退出。")
            break

        if not query:
            continue

        print("\n正在检索相关资料...")
        retrieved_chunks = retrieve(query, chunks, top_k=3)

        print("\n检索到的资料片段：")
        for i, chunk in enumerate(retrieved_chunks):
            print(f"\n[{i + 1}] 相似度：{chunk['score']:.4f}，来源：{chunk['source']}，片段：{chunk['chunk_id']}")
            print(chunk["text"])

        print("\n正在调用模型生成回答...")
        answer = generate_answer(query, retrieved_chunks)

        print("\n模型回答：")
        print(answer)


if __name__ == "__main__":
    main()
