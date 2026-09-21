# AI-DataStructure-Assistant

## 数据结构课程智能助教系统

AI-DataStructure-Assistant 是一个面向《数据结构》课程的 RAG（Retrieval-Augmented Generation，检索增强生成）智能助教项目。

系统以课程教材和整理后的结构化知识库为主要知识来源。当前生产检索链路首先使用 Dense Retriever 召回 Top-10 候选，再通过 Qwen Reranker 重排，并融合 Dense 与 Rerank 分数得到最终 Top-5 Evidence，随后调用大语言模型生成回答并返回知识来源。BM25 与 Hybrid Retrieval 保留为实验和对比基线。

当前项目已经从早期 RAG Demo 进入完整系统开发阶段。

> 当前开发重点：系统稳定性、知识库建设、检索质量、前后端体验和可演示性。
> 论文型 evidence-set research 已阶段性冻结，研究记录见 `docs/RESEARCH_CHECKPOINT_2026-09.md`。

---

## 1. 当前功能

目前已经实现：

- 数据结构课程结构化知识库；
- Dense semantic retrieval（稠密语义检索）；
- Qwen Reranking（文本重排序）；
- Dense + Rerank score fusion（分数融合）；
- BM25 lexical retrieval（词法检索，对比基线）；
- Hybrid Dense + BM25 Retrieval（实验基线）；
- 文档 Embedding 本地缓存；
- Dense Top-10 候选召回 + Fusion Top-5；
- Reranker 故障自动回退 Dense Top-5；
- 基于原始 Dense Top-1 分数的范围控制；
- Qwen 大语言模型回答生成；
- 回答知识来源返回；
- FastAPI 后端服务；
- 前端问答页面；
- Markdown 与数学公式展示；
- 后端健康检查；
- 请求异常处理；
- 检索评测框架；
- Benchmark 与人工相关性标注资产。

---

## 2. 系统架构

当前生产主链路：

```text
用户
 ↓
Web Frontend
 ↓
FastAPI
 ↓
RAG Service
 ↓
rag/main.py
 ↓
Dense Retriever
 ↓
Dense Top-10 Candidates
 ↓
Qwen Reranker
 ↓
Score Fusion
  0.60 × normalized Dense
+ 0.40 × normalized Rerank
 ↓
Top-5 Evidence
 ↓
Scope Check
(raw Dense Top-1 score)
 ↓
Qwen Generator
 ↓
Answer + Sources
```

其中：

- `rag/main.py` 是当前统一 RAG 入口；
- 生产 Retriever 为 `dense_rerank`；
- Dense 文档向量支持持久化缓存；
- Query Embedding 在线计算；
- Reranker 异常时自动 fail-open（故障降级）到 Dense Top-5；
- 范围判断仍使用原始 Dense Top-1 similarity（相似度），不使用 fusion score；
- BM25 和 Hybrid Retriever 保留用于实验与回归比较；
- 当前生成模型由 `rag/config.py` 统一配置。

---

## 3. 仓库结构

```text
AI-DataStructure-Assistant/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── logging_config.py
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
│   ├── retrievers/
│   │   ├── base.py
│   │   ├── dense.py
│   │   ├── dense_rerank.py
│   │   ├── bm25.py
│   │   └── hybrid.py
│   ├── rerankers/
│   │   └── qwen_reranker.py
│   └── generators/
│       └── qwen_generator.py
│
├── tests/
│   ├── system/
│   ├── benchmarks/
│   ├── annotations/
│   ├── research/
│   └── ...
│
├── docs/
│   └── RESEARCH_CHECKPOINT_2026-09.md
│
└── README.md
```

`tests/system/` 保存当前系统单元测试与统一检索评测代码；`tests/research/` 保存已经归档的历史研究实验；Benchmark 与人工标注分别保存在 `tests/benchmarks/` 和 `tests/annotations/`。

---

## 4. 知识库

正式知识库：

```text
knowledge_base/ds_chunks.jsonl
```

当前知识库共有：

```text
463 chunks
```

每个 Chunk 主要包含：

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

当前 `content_type` 包括概念、算法、代码、习题等类型。

知识库质量检查：

```bash
python3 knowledge_base/validate_chunks.py
```

严格检查：

```bash
python3 knowledge_base/validate_chunks.py --fail-on-warning
```

系统可回答范围由当前知识库实际覆盖内容决定，而不是由“数据结构课程”这一大类概念决定。

---

## 5. RAG 配置

主要配置文件：

```text
rag/config.py
```

当前生产配置：

```text
Production Retriever:
dense_rerank

Dense Candidate-K:
10

Final Top-K:
5

Rerank Fusion Alpha:
0.40

Fusion:
0.60 × normalized Dense
+ 0.40 × normalized Rerank

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
```

### Dense Retriever

Dense Retriever 使用 Qwen Embedding，并通过 cosine similarity（余弦相似度）排序。

文档 Embedding 会根据：

- Corpus 内容；
- Embedding model；
- Embedding dimension；

生成 fingerprint，并缓存到：

```text
.cache/rag/
```

知识库和 Embedding 配置不变时，无需重复生成全部文档向量。Query Embedding 仍在每次请求时在线计算。

### Dense + Rerank Retriever

当前生产 Retriever 为 `DenseRerankRetriever`。

执行流程：

```text
Query
 ↓
Dense Top-10
 ↓
Qwen Reranker
 ↓
Query-level Min-Max Normalization
 ↓
0.60 × Dense + 0.40 × Rerank
 ↓
Final Top-5
```

其中：

- `candidate_k = 10`；
- `final_k = 5`；
- `fusion_alpha = 0.40`；
- Dense 权重为 0.60；
- Rerank 权重为 0.40。

如果 Reranker 调用失败，生产系统采用 fail-open（故障降级）策略，自动返回原始 Dense Top-5，不因 Reranker 服务异常中断问答。

### BM25 / Hybrid Retriever

项目同时保留：

- Okapi BM25 lexical retrieval（词法检索）；
- Dense + BM25 RRF（Reciprocal Rank Fusion，倒数排名融合）Hybrid Retriever。

二者主要用于实验、回归测试和检索方案对比。

当前实验中 Hybrid RRF 未超过 Dense baseline，因此没有进入生产链路。

## 6. 范围控制

当前历史 Dense baseline 使用：

```text
MIN_RETRIEVAL_SCORE = 0.62
```

该阈值对应 Dense cosine score（稠密检索余弦相似度）的分数尺度。

虽然当前生产检索已经升级为 Dense + Rerank fusion，但范围判断仍使用：

```text
原始 Dense Top-1 score
```

而不是：

```text
fusion score
rerank score
BM25 score
```

原因是这些分数属于不同尺度，不能直接与 Dense 阈值 `0.62` 比较。

当用于范围判断的 Dense Top-1 score 低于阈值时，系统返回：

```text
根据当前资料无法确定
```

并返回：

```text
sources = []
```

随着知识库持续变化，该阈值仍应通过独立 Benchmark 定期重新标定。

## 7. 大语言模型生成

生成模块：

```text
rag/generators/qwen_generator.py
```

当前模型：

```text
qwen3.7-flash
```

回答生成原则：

- 优先依据检索到的课程资料；
- 避免将模型自身知识伪装成课程资料；
- 回答适合本科《数据结构》学习场景；
- 可以输出 Markdown、公式和代码；
- 当资料不足时应明确拒答。

---

## 8. 后端

后端使用 FastAPI。

主入口：

```text
backend/main.py
```

核心服务：

```text
backend/services/rag_service.py
```

当前生产 Retriever：

```text
dense_rerank
```

默认：

```text
candidate_k = 10
top_k = 5
```

主要接口：

### 健康检查

```http
GET /api/v1/health
```

### 问答

```http
POST /api/v1/ask
```

请求：

```json
{
  "question": "什么是循环单链表？"
}
```

`top_k` 为可选参数；未传入时由后端配置统一使用默认值 5。

响应包含：

- answer；
- sources；
- latency；
- request id；
- error state。

后端问答服务显式选择生产 Retriever，并通过统一的 `rag/main.py` 调用检索与生成链路。

## 9. 前端

前端位于：

```text
frontend/
```

当前采用原生 HTML / CSS / JavaScript。

已经实现：

- 问题输入；
- API 请求；
- 加载状态；
- 回答展示；
- Markdown；
- MathJax；
- 来源展示；
- 延迟展示；
- 历史记录；
- 后端健康检查；
- 异常提示。

默认 API：

```text
http://localhost:8000
```

---

## 10. 环境配置

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

项目当前主要依赖包括：

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

## 11. API 与 Workspace 配置

在项目根目录创建：

```text
.env
```

当前生产链路需要：

```text
DASHSCOPE_API_KEY=YOUR_API_KEY
DASHSCOPE_WORKSPACE_ID=YOUR_WORKSPACE_ID
DASHSCOPE_REGION=cn-beijing
```

其中：

- `DASHSCOPE_API_KEY`：模型服务 API Key；
- `DASHSCOPE_WORKSPACE_ID`：Reranker / Embedding 所使用的 Workspace；
- `DASHSCOPE_REGION`：Workspace 所在区域。

RAG 主入口从项目根目录读取 `.env`。

禁止提交真实 API Key、Workspace ID 或其他私有凭证。`.env` 已通过 Git ignore 排除。

## 12. 启动系统

### 后端

从仓库根目录运行：

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

## 13. 评测

统一检索评测入口：

```text
tests/system/run_retrieval_eval.py
```

当前支持：

```bash
python3 tests/system/run_retrieval_eval.py --retriever dense
python3 tests/system/run_retrieval_eval.py --retriever bm25
python3 tests/system/run_retrieval_eval.py --retriever hybrid
python3 tests/system/run_retrieval_eval.py --retriever dense_rerank
```

主要指标包括：

- Recall@K（前 K 条相关证据召回率）；
- MRR@K（平均倒数排名）；
- nDCG@K（归一化折损累计增益）；
- Hit@K（前 K 条是否命中）；
- Facet Coverage@K（答案要点覆盖率）；
- Full Coverage@K（全部答案要点覆盖率）；
- retrieval latency（检索延迟）。

### Dev Set

Dev Set 中共有 50 道问题，其中 49 道有效问题用于检索方案选择与参数冻结。

最终比较：

```text
                           Dense       Fusion       Delta
Recall@3                  0.7448       0.7618     +0.0170
Recall@5                  0.9132       0.9391     +0.0259
nDCG@3                    0.9717       0.9873     +0.0156
nDCG@5                    0.9513       0.9728     +0.0215
```

Recall@5 query-level：

```text
better = 6
worse  = 0
```

据此冻结：

```text
candidate_k = 10
final_k = 5
fusion_alpha = 0.40
```

Dev Set 在参数冻结后不再继续用于调节 `fusion_alpha`。

### Held-out Set

Held-out Benchmark 共有：

```text
100 questions
```

人工 facet coverage（答案要点覆盖）检查结果：

```text
single_complete   = 39
combined_complete = 33
corpus_gap        = 28
```

因此：

```text
72 questions
```

具有完整知识库证据覆盖，用于冻结参数后的泛化验证；另外 28 道保留为知识库缺口诊断集，不用于评价 Retriever 本身。

72 道 Held-out 最终结果：

```text
                           Dense       Fusion       Delta
Recall@3                  0.7856       0.8027     +0.0171
Recall@5                  0.8732       0.8780     +0.0048
nDCG@3                    0.8537       0.8709     +0.0171
nDCG@5                    0.8662       0.8732     +0.0070
Facet Coverage@3          0.9132       0.9329     +0.0197
Facet Coverage@5          0.9676       0.9688     +0.0012
Full Coverage@3           0.8056       0.8472     +0.0417
Full Coverage@5           0.9028       0.9167     +0.0139
```

Recall@5 query-level：

```text
better = 3
worse  = 1
same   = 68
```

Full Coverage@5 query-level：

```text
better = 1
worse  = 0
same   = 71
```

Held-out Reranker-only latency：

```text
average = 975.7 ms
p95     = 1232.5 ms
```

最终生产配置没有根据 Held-out 结果再次调参。

实验输出保存在：

```text
tests/results/
```

该目录被 Git 忽略，不作为源码提交。

## 14. 研究资产

2026 年 9 月曾针对 evidence-set construction 开展论文型探索。

目前该路线已经冻结，详细记录：

```text
docs/RESEARCH_CHECKPOINT_2026-09.md
```

已经保留：

- 100-question held-out benchmark；
- comparison / non-comparison 划分；
- core facets；
- 1546 条人工 question-chunk 标注；
- Dense / BM25 pooling；
- SetR-inspired 实验代码；
- evidence coverage 分析。

这些资产不会删除，但当前不继续投入论文级 qrels 扩充和人工 annotation。

---

## 15. 当前开发重点

检索主链路已经完成一轮系统化优化：

```text
Dense Top-10
→ Qwen Rerank
→ Dense/Rerank Score Fusion
→ Top-5
```

并已通过 Dev、Held-out、单元测试和真实 Backend 端到端验证。

后续优先级：

1. 完善知识库覆盖，重点处理 Held-out 中识别出的 28 道 corpus-gap 问题；
2. 改进 Chunking 与知识组织质量；
3. 优化端到端问答延迟，重点分析生成阶段耗时；
4. 完善前端交互和来源展示；
5. 建立稳定 regression benchmark（回归基准）；
6. 完善部署、日志、健康检查和异常处理；
7. 持续保留 Dense / BM25 / Hybrid baseline 做回归比较；
8. evidence-set 相关方法作为可选研究资产保留。

当前不继续投入论文级 qrels 扩充和大规模人工 annotation。

## 16. 当前项目状态

```text
Knowledge Base          463 chunks

Dense Retrieval         Available
Qwen Reranking          Production
Dense + Rerank Fusion   Production
BM25 Retrieval          Baseline
Hybrid RRF Retrieval    Experimental

Dense Candidate-K       10
Final Evidence Top-K    5
Fusion Alpha            0.40

Embedding Cache         Available
Qwen Generation         Available

FastAPI Backend         Available
Frontend                Available
Source Attribution      Available

Evaluation Framework    Available
Dev Benchmark           Available
Held-out Benchmark      Available

Paper-oriented Research Paused
System Development      Active
```

当前项目定位：

> 一个持续开发中的数据结构课程 RAG 智能助教系统，而不是单一论文实验仓库。

## 17. 团队分工

项目由 5 名成员协作：

- 李均乐：项目负责人、RAG 核心流程、系统集成；
- 郭星辰：知识库与数据整理；
- 祝晟译：FastAPI 后端；
- 张圣江：前端；
- 常慧思：材料、测试和评测支持。

后续开发以统一主分支和稳定接口为基础推进。

---

## 18. 安全说明

禁止提交：

- `.env`
- API Key / Token
- `.venv`
- `__pycache__`
- `.pyc`
- 本地日志
- 临时实验结果
- 私有凭证

API Key 只能通过环境变量或本地 `.env` 加载。

如果历史提交中曾出现真实 Key，应立即在服务提供方撤销并重新生成。
