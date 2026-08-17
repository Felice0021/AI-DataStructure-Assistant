"""
Qwen大模型生成器
"""
from openai import OpenAI
from typing import List, Dict

from rag.config import GENERATION_MODEL, GENERATION_TEMPERATURE


class QwenGenerator:
    def __init__(self, api_key: str = None):
        if api_key is None:
            import os
            api_key = os.getenv("DASHSCOPE_API_KEY")
            if not api_key:
                raise RuntimeError("未设置 DASHSCOPE_API_KEY")

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = GENERATION_MODEL
        self.temperature = GENERATION_TEMPERATURE

    def generate(self, query: str, retrieved_chunks: List[Dict]) -> str:
        if not retrieved_chunks:
            return "抱歉，在课程资料中没有找到相关内容。"

        context_blocks = []
        for i, chunk in enumerate(retrieved_chunks):
            page_text = str(chunk["page"]) if chunk.get("page") else "未标注"
            context_blocks.append(
                f"资料{i + 1}\n"
                f"章节：{chunk.get('chapter', '')}\n"
                f"小节：{chunk.get('section', '')}\n"
                f"来源文件：{chunk.get('source_file', '')}\n"
                f"页码：{page_text}\n"
                f"内容：{chunk.get('text', '')}"
            )

        context = "\n\n".join(context_blocks)

        system_prompt = """
你是一个数据结构课程智能助教。

回答规则：
1. 只使用给定课程资料中能够直接支持的内容回答。
2. 回答应自然、准确、适合本科生理解。
3. 如果现有资料不足以回答，只回答"根据当前资料无法确定"。
"""

        user_prompt = f"""
以下是从课程知识库中检索到的资料：

{context}

用户问题：
{query}

请基于以上资料回答。
"""

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_prompt.strip()},
            ],
            temperature=self.temperature,
            extra_body={"enable_thinking": False},
        )

        return completion.choices[0].message.content