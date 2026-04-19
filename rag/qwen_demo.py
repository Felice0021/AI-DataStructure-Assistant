import dashscope
from dashscope import Generation

dashscope.api_key = "sk-e7c4ea0a9d2d4a52a26408bf8d2f0d06"

def ask_qwen_with_knowledge(question, knowledge):
    prompt = f"""
请基于以下数据结构知识回答问题：

{knowledge}

问题：{question}
"""
    
    response = Generation.call(
        model="qwen-turbo",
        prompt=prompt,
        temperature=0.7
    )

    if response.status_code == 200:
        return response.output.text
    else:
        return f"调用失败: {response.code} - {response.message}"


if __name__ == "__main__":
    # 模拟知识库（后面可以换成文件读取）
    knowledge = """
栈（Stack）是一种后进先出（LIFO）的数据结构。
队列（Queue）是一种先进先出（FIFO）的数据结构。
"""

    while True:
        q = input("请输入问题（输入exit退出）：")
        if q.lower() == "exit":
            break

        answer = ask_qwen_with_knowledge(q, knowledge)
        print("回答：", answer)