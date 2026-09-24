# AI-DataStructure-Assistant

## 数据结构课程智能助教系统

AI-DataStructure-Assistant 是一个面向本科《数据结构》课程的 RAG（Retrieval-Augmented Generation，检索增强生成）智能助教系统。

系统以课程教材、课程资料和结构化知识库为主要知识来源，通过 Query Processing（查询处理）、Hybrid Retrieval（混合检索）、Reranking（重排序）和大语言模型生成，为学生提供概念问答、习题讲解和代码分析能力。

当前项目已从早期 RAG Demo 和论文型实验阶段转入完整系统开发阶段。

> 当前重点：知识库建设、RAG 稳定性、前后端集成、系统测试和最终演示。
> 历史论文型研究记录见 `docs/RESEARCH_CHECKPOINT_2026-09.md`。

---

## 1. 当前系统架构

当前冻结的 RAG V1 主链路：

```text
Raw Query
    ↓
Query Router
    ↓
Query Expansion Gate
    │
    ├── 简单问题
    │     └── Original Query
    │
    └── 复杂问题
          └── Original Query + ≤3 Subqueries
    ↓
Batched Dense Retrieval + BM25 Retrieval
    ↓
Single-query RRF
    ↓
Multi-query RRF
    ↓
Scope Gate
只使用 Original Query 的 Dense Top-1 Score
    ↓
Qwen Reranker
只使用 Original Query
    ↓
Top-K Evidence
    ↓
Mode-specific Generator
    ↓
Answer + Sources
```

核心原则：

- 原始 Query 始终保留；
- 简单问题不做无意义 Query Expansion；
- 比较类、多要求类问题可拆为多个检索子 Query；
- 多 Query 的 Dense Embedding 使用批量 API 请求；
- Dense 与 BM25 使用 RRF（Reciprocal Rank Fusion，倒数排名融合）；
- 多 Query 结果再次进行 RRF 融合；
- Scope Gate 只使用原始 Query，避免查询扩展导致范围漂移；
- Reranker 同样使用原始 Query；
- Query Expansion 或 Reranker 异常时采用 fail-open（故障降级），避免整个问答链路中断。

---

## 2. 当前功能

当前已经实现：

- 数据结构课程结构化知识库；
- Dense semantic retrieval（稠密语义检索）；
- BM25 lexical retrieval（词法检索）；
- Dense + BM25 Hybrid Retrieval（混合检索）；
- RRF 排名融合；
- Query Router（查询模式路由）；
- Query Expansion Gate（查询扩展判断）；
- LLM Query Decomposition（复杂查询拆解）；
- Multi-query Retrieval（多查询检索）；
- Query Embedding 批量调用；
- Qwen Reranking（文本重排序）；
- 范围外问题拒答；
- `qa / exercise / code` 三种回答模式；
- Qwen 大语言模型生成；
- 来源信息返回；
- Dense 文档 Embedding 本地缓存；
- 检索 Benchmark 与评测框架；
- 历史人工相关性和 facet 标注资产；
- FastAPI 后端基础框架；
- Web 前端基础页面。

当前正在进行：

- FastAPI 后端接入新的 `rag.main.run()`；
- 前端适配新的后端响应结构；
- 知识库继续扩充和清洗；
- 系统级回归测试。

---

## 3. Query Processing

### 3.1 Query Router

文件：

```text
rag/query_router.py
```

Query Router 将用户问题路由为：

```text
qa
exercise
code
```

含义：

- `qa`：概念解释、知识问答；
- `exercise`：习题、算法推演、计算过程；
- `code`：代码阅读、错误定位、实现分析。

生产接口默认支持：

```text
mode = auto
```

由系统自动判断回答模式。

---

### 3.2 Query Expansion

文件：

```text
rag/query_processor.py
```

系统不会对所有问题强制扩展。

简单问题：

```text
AVL树为什么需要旋转？
```

保持为：

```text
[
  "AVL树为什么需要旋转？"
]
```

复杂问题：

```text
Prim和Kruskal算法在基本思想和适用场景上有什么区别？
```

可能被拆解为：

```text
[
  "Prim和Kruskal算法在基本思想和适用场景上有什么区别？",
  "Prim算法的基本思想",
  "Kruskal算法的基本思想",
  "Prim和Kruskal算法的适用场景区别"
]
```

其中第一个 Query 永远是用户原始问题。

当前最多生成：

```text
3 subqueries
```

代码模式默认不进行 Query Expansion，避免代码内容被错误改写。

Query Expansion 当前复用系统生成模型，不需要单独部署查询模型。

---

## 4. Hybrid Retrieval

当前生产 Retriever 使用：

```text
Dense + BM25
```

### Dense Retrieval

Dense Retriever 使用 Qwen Embedding 和 cosine similarity（余弦相似度）。

当前配置：

```text
Embedding Model:
qwen3.7-text-embedding

Embedding Dimension:
1024

Embedding Batch Size:
10
```

文档 Embedding 会持久化缓存到：

```text
.cache/rag/
```

当知识库内容和 Embedding 配置不变时，无需重复生成全部文档向量。

对于 Multi-query Retrieval，多条 Query 的 Embedding 会尽量通过一次批量 API 请求生成，减少网络调用延迟。

---

### BM25 Retrieval

BM25 用于 lexical retrieval（词法检索），用于补充 Dense Retrieval 对：

- 专有名词；
- 算法名称；
- 代码符号；
- 精确关键词；

等内容的召回能力。

---

### RRF Fusion

Dense 与 BM25 不直接比较原始分数，而通过：

```text
RRF
Reciprocal Rank Fusion
倒数排名融合
```

按照排名进行融合。

对于复杂问题：

```text
Original Query
+ Subqueries
```

每个 Query 都独立进行 Hybrid Retrieval，然后再进行第二层 Multi-query RRF 融合。

---

## 5. Scope Control

当前范围控制使用：

```text
MIN_RETRIEVAL_SCORE = 0.58
```

该阈值对应：

```text
Original Query
→ Dense Retrieval
→ Dense Top-1 cosine similarity
```

不会使用：

```text
BM25 score
RRF score
Multi-query score
Rerank score
```

作为范围判断依据。

原因是这些分数属于不同尺度，不能直接与 Dense cosine score 比较。

当原始 Query 的 Dense Top-1 分数低于阈值时，系统直接返回：

```text
根据当前资料无法确定
```

同时：

```text
sources = []
```

并跳过 Rerank 与 Generation。

例如当前测试：

```text
TCP为什么需要三次握手？
```

可被正确判断为当前数据结构知识库范围外问题。

当前阈值 `0.58` 属于系统开发阶段配置，后续知识库扩大后应通过独立测试集重新标定。

---

## 6. Reranking

Reranker：

```text
qwen3.7-text-rerank
```

Hybrid / Multi-query Retrieval 生成候选池后，使用用户的：

```text
Original Query
```

进行重排序。

这样可以避免子 Query 对最终问题语义产生过强影响。

如果 Reranker 调用异常，系统采用 fail-open 策略，使用已有检索结果继续工作。

---

## 7. Answer Generation

生成模块：

```text
rag/generators/qwen_generator.py
```

当前生成模型：

```text
qwen3.7-flash
```

Temperature：

```text
0.2
```

系统根据 Query Router 的结果使用不同回答模式。

### QA

主要结构：

```text
直接回答
→ 必要原理
→ 相关说明
```

### Exercise

主要结构：

```text
题目分析
→ 解题过程
→ 最终答案
```

### Code

主要结构：

```text
代码作用
→ 问题定位
→ 修改建议
→ 复杂度 / 边界条件
```

生成模型应优先依据检索得到的课程 Evidence，不应把模型自身知识伪装成课程材料。

---

## 8. RAG 统一入口

当前生产 RAG 入口：

```text
rag/main.py
```

主要接口：

```python
run(
    query,
    chunks,
    top_k=5,
    mode="auto"
)
```

核心流程：

```text
Query
→ Router
→ Query Processing
→ Hybrid Retrieval
→ Scope Gate
→ Reranker
→ Generator
```

主要返回字段包括：

```text
answer
sources
retrieved_chunks
retrieval_queries
mode
out_of_scope
threshold_score
rerank_fallback
latency_ms
error
```

其中：

```text
retrieved_chunks
retrieval_queries
threshold_score
rerank_fallback
```

主要用于内部调试和系统评测。

后端面向前端主要暴露：

```text
answer
sources
mode
out_of_scope
latency_ms
error
```

---

## 9. 当前 RAG 配置

主要配置文件：

```text
rag/config.py
```

当前关键配置：

```text
Final Top-K:
5

Hybrid Candidate-K:
10

Scope Threshold:
0.58

Embedding Model:
qwen3.7-text-embedding

Embedding Dimension:
1024

Embedding Batch Size:
10

Rerank Model:
qwen3.7-text-rerank

Generation Model:
qwen3.7-flash

Generation Temperature:
0.2

Query Expansion:
Enabled

Max Subqueries:
3

Multi-query Candidate Pool:
20
```

---

## 10. 知识库

正式知识库：

```text
knowledge_base/ds_chunks.jsonl
```

当前约有：

```text
463 chunks
```

Chunk Schema：

```json
{
  "chunk_id": "ds_ch06_0001",
  "text": "知识正文",
  "chapter": "第六章 树和二叉树",
  "section": "6.x",
  "source_file": "数据结构（C语言版）严蔚敏.pdf",
  "page": 1,
  "content_type": "concept"
}
```

当前固定字段：

```text
chunk_id
text
chapter
section
source_file
page
content_type
```

`content_type` 主要包括：

```text
concept
algorithm
code
exercise
```

知识库后续可以继续扩充，但不应随意修改字段结构。

质量检查：

```bash
python3 knowledge_base/validate_chunks.py
```

严格模式：

```bash
python3 knowledge_base/validate_chunks.py --fail-on-warning
```

---

## 11. 仓库结构

```text
AI-DataStructure-Assistant/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── routers/
│   ├── services/
│   └── requirements.txt
│
├── frontend/
│   ├── index.html
│   ├── css/
│   └── js/
│
├── knowledge_base/
│   ├── ds_chunks.jsonl
│   └── validate_chunks.py
│
├── rag/
│   ├── main.py
│   ├── config.py
│   ├── query_router.py
│   ├── query_processor.py
│   │
│   ├── retrievers/
│   │   ├── base.py
│   │   ├── dense.py
│   │   ├── bm25.py
│   │   ├── hybrid.py
│   │   └── dense_rerank.py
│   │
│   ├── rerankers/
│   │   └── qwen_reranker.py
│   │
│   └── generators/
│       └── qwen_generator.py
│
├── tests/
│   ├── system/
│   ├── benchmarks/
│   ├── annotations/
│   └── research/
│
├── docs/
│   └── RESEARCH_CHECKPOINT_2026-09.md
│
└── README.md
```

---

## 12. 后端

后端基于：

```text
FastAPI
```

主要目录：

```text
backend/
```

当前已有接口：

```http
GET /api/v1/health
POST /api/v1/ask
```

当前开发阶段正在将原有后端 RAG 调用迁移至：

```text
rag.main.run()
```

后端不应重复实现：

- Query Router；
- Query Expansion；
- Retrieval；
- Scope Gate；
- Reranking。

这些逻辑统一由 RAG 层负责。

---

## 13. 前端

前端位于：

```text
frontend/
```

当前采用：

```text
HTML
CSS
JavaScript
```

已有基础能力：

- 问题输入；
- API 请求；
- Loading 状态；
- Markdown 展示；
- MathJax；
- 来源展示；
- 历史记录；
- 异常提示。

后续将根据新的后端 API 增加：

- QA / Exercise / Code 模式状态；
- Out-of-scope 状态；
- 新 Sources 格式；
- 新 Latency 信息。

---

## 14. 环境配置

克隆仓库：

```bash
git clone https://github.com/Felice0021/AI-DataStructure-Assistant.git
cd AI-DataStructure-Assistant
```

创建虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r backend/requirements.txt
```

主要依赖包括：

```text
fastapi
uvicorn
pydantic
pydantic-settings
openai
dashscope
numpy
python-dotenv
jieba
```

---

## 15. 模型服务配置

项目根目录创建：

```text
.env
```

配置：

```text
DASHSCOPE_API_KEY=YOUR_API_KEY
DASHSCOPE_WORKSPACE_ID=YOUR_WORKSPACE_ID
DASHSCOPE_REGION=cn-beijing
```

禁止提交：

```text
API Key
Token
Workspace 私有信息
其他凭证
```

`.env` 应保持在 Git ignore 中。

---

## 16. 启动系统

### 后端

从项目根目录：

```bash
source .venv/bin/activate
python3 -m backend.main
```

默认地址：

```text
http://127.0.0.1:8000
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

### 前端

新终端运行：

```bash
python3 -m http.server 5500 -d frontend
```

浏览器访问：

```text
http://localhost:5500
```

---

## 17. 评测

统一检索评测入口：

```text
tests/system/run_retrieval_eval.py
```

支持：

```bash
python3 tests/system/run_retrieval_eval.py --retriever dense
python3 tests/system/run_retrieval_eval.py --retriever bm25
python3 tests/system/run_retrieval_eval.py --retriever hybrid
python3 tests/system/run_retrieval_eval.py --retriever dense_rerank
```

常用指标：

- Recall@K（前 K 条相关证据召回率）；
- MRR@K（平均倒数排名）；
- nDCG@K（归一化折损累计增益）；
- Hit@K（前 K 条是否命中）；
- Facet Coverage@K（答案要点覆盖率）；
- Full Coverage@K（完整答案要点覆盖率）；
- retrieval latency（检索延迟）。

当前已经保留：

```text
Dev Benchmark
Held-out Benchmark
人工 question-chunk 标注
facet 标注
历史检索实验结果
```

这些资产主要用于后续系统回归测试，而不是当前生产逻辑的一部分。

---

## 18. 历史研究资产

项目曾围绕：

```text
evidence-set construction
comparison query
facet coverage
adaptive evidence selection
```

开展论文型实验。

当前该研究路线已经暂停。

研究总结：

```text
docs/RESEARCH_CHECKPOINT_2026-09.md
```

历史代码保存在：

```text
tests/research/
```

这些代码不作为当前生产 RAG 入口。

---

## 19. 当前开发状态

```text
Knowledge Base              ~463 chunks

Query Router                Production
Query Expansion             Production
Multi-query Retrieval       Production

Dense Retrieval             Production
BM25 Retrieval              Production
Hybrid RRF                  Production
Multi-query RRF             Production

Scope Gate                  Production
Qwen Reranker               Production
Mode-specific Generation    Production

Embedding Cache             Available
Batch Query Embedding       Available

RAG V1 Core                 Frozen

FastAPI Backend             Adapting to new RAG
Frontend                    Waiting for new API
Knowledge Base              Expanding
System Regression           Preparing

Paper-oriented Research     Paused
System Development          Active
```

---

## 20. 当前验证结果

当前已完成基础真实链路验证。

### 简单知识问题

```text
AVL树为什么需要旋转？
```

结果：

```text
Query Expansion: No
Mode: qa
Out of Scope: False
Rerank Fallback: False
```

### 复杂比较问题

```text
Prim和Kruskal算法在基本思想和适用场景上有什么区别？
```

系统能够拆解为多个检索 Query，并同时召回 Prim、Kruskal 和比较类 Evidence。

批量 Query Embedding 优化后，复杂 Query Retrieval 延迟相比串行多次 Embedding 明显下降。

### 代码问题

单链表空指针问题可以正确进入：

```text
mode = code
```

并完成：

```text
代码作用
→ 问题定位
→ 修改建议
→ 边界分析
```

### 范围外问题

```text
TCP为什么需要三次握手？
```

能够在 Scope Gate 阶段拒答：

```text
根据当前资料无法确定
```

不会继续调用 Reranker 和 Generator。

---

## 21. 团队分工

项目由 5 名成员协作：

- 李均乐：项目负责人、RAG 核心流程、系统集成；
- 郭星辰：知识库与数据整理；
- 祝晟译：FastAPI 后端；
- 张圣江：前端；
- 常慧思：材料、测试和评测支持。

当前开发依赖关系：

```text
RAG Core
   ├── Knowledge Base
   │
   └── Backend
          ↓
       Frontend
          ↓
   End-to-End Testing
```

---

## 22. 安全说明

禁止提交：

```text
.env
API Key
Token
.venv
__pycache__
*.pyc
本地日志
临时实验结果
私有凭证
```

如果历史提交中曾暴露真实凭证，应立即在对应服务平台撤销并重新生成。

---

## 23. 项目定位

当前项目定位：

> 一个持续开发中的数据结构课程 RAG 智能助教系统。

现阶段目标不是继续扩大论文实验，而是完成：

```text
稳定知识库
→ 稳定 RAG
→ 后端集成
→ 前端集成
→ 系统回归测试
→ 可部署 / 可演示版本
```
