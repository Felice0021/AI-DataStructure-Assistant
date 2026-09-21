# AI-DataStructure-Assistant

## 数据结构课程智能助教系统

AI-DataStructure-Assistant 是一个面向《数据结构》课程的 RAG（Retrieval-Augmented Generation，检索增强生成）智能助教项目。

系统以课程教材和整理后的结构化知识库为主要知识来源，通过 Dense / BM25 检索获取相关课程内容，再调用大语言模型生成回答，并向用户展示回答对应的知识来源。

当前项目已经从早期 RAG Demo 进入完整系统开发阶段。

> 当前开发重点：系统稳定性、知识库建设、检索质量、前后端体验和可演示性。
> 论文型 evidence-set research 已阶段性冻结，研究记录见 `docs/RESEARCH_CHECKPOINT_2026-09.md`。

---

## 1. 当前功能

目前已经实现：

- 数据结构课程结构化知识库；
- Dense semantic retrieval（稠密语义检索）；
- BM25 lexical retrieval（词法检索）；
- 文档 Embedding 本地缓存；
- Top-K 检索；
- Dense 相似度阈值范围控制；
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

当前主链路：

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
Retriever
 ├── Dense
 └── BM25
 ↓
Top-K Evidence
 ↓
Scope Check
 ↓
Qwen Generator
 ↓
Answer + Sources
```

其中：

- `rag/main.py` 是当前统一 RAG 入口；
- 后端和实验代码共享同一套 Retriever；
- Dense 文档向量支持持久化缓存；
- Query Embedding 在线计算；
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
│   │   └── bm25.py
│   └── generators/
│       └── qwen_generator.py
│
├── tests/
│   ├── benchmarks/
│   ├── annotations/
│   ├── metrics.py
│   ├── run_retrieval_eval.py
│   └── ...
│
├── docs/
│   └── RESEARCH_CHECKPOINT_2026-09.md
│
└── README.md
```

`tests/` 中目前同时保留系统评测代码和历史研究实验脚本。

为避免破坏已有实验路径，现阶段不批量移动历史文件。后续新增的系统测试应优先保持简洁、模块化。

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

当前主要参数：

```text
Default Top-K:
3

Embedding Model:
qwen3.7-text-embedding

Embedding Dimension:
1024

Embedding Batch Size:
10

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

知识库和 Embedding 配置不变时，无需重复生成全部文档向量。

### BM25 Retriever

项目同时提供 Okapi BM25 作为 lexical retrieval baseline（词法检索基线）。

Dense 和 BM25 当前使用统一 Retriever 接口，方便后续扩展：

- Hybrid Retrieval；
- Reranker；
- Evidence Selector。

---

## 6. 范围控制

当前历史 Dense baseline 使用：

```text
MIN_RETRIEVAL_SCORE = 0.62
```

注意：

该阈值只适用于当前 Dense cosine score。

BM25 分数尺度不同，不应直接使用 0.62。

随着知识库已经从早期版本扩展到 463 chunks，旧阈值只能作为历史 baseline，后续系统上线前应重新使用独立 Dev Set 进行标定。

当 Dense Top-1 score 低于阈值时，系统返回：

```text
根据当前资料无法确定
```

同时：

```text
sources = []
```

---

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
  "question": "什么是循环单链表？",
  "top_k": 3
}
```

响应包含：

- answer；
- sources；
- latency；
- request id；
- error state。

---

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

## 11. API Key

在项目根目录创建：

```text
.env
```

内容：

```text
DASHSCOPE_API_KEY=YOUR_API_KEY
```

不要提交真实 API Key。

RAG 主入口会从项目根目录读取 `.env`。

---

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

统一检索评测：

```text
tests/system/run_retrieval_eval.py
```

支持：

```bash
python3 tests/system/run_retrieval_eval.py --retriever dense
python3 tests/system/run_retrieval_eval.py --retriever bm25
```

当前主要检索指标包括：

- Recall@K；
- MRR@K；
- nDCG@K；
- Hit@K；
- retrieval latency；
- index build latency。

项目还保留了 facet-level benchmark，用于分析：

- Facet Recall；
- Full-Facet Coverage；
- multi-evidence retrieval；
- comparison query。

这些研究资产目前主要作为系统回归测试与算法优化参考，不作为已完成论文成果。

---

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

后续主线转为系统开发。

优先级：

1. 稳定 RAG 主链路；
2. 完善知识库覆盖；
3. 改进 Chunking；
4. 实现 Hybrid Retrieval；
5. 增加 Reranking；
6. 将 evidence-set 思路做成轻量可选优化模块；
7. 完善前端交互；
8. 增加知识来源和解释能力；
9. 建立稳定 regression benchmark；
10. 完善部署、日志和异常处理。

后续 Evidence Selector 可以考虑统一接口：

```text
topk
setwise
scope_aware
```

但不要求作为论文创新点。

---

## 16. 当前项目状态

```text
Knowledge Base          463 chunks
Dense Retrieval         Available
BM25 Retrieval          Available
Embedding Cache         Available
Qwen Generation         Available
FastAPI Backend         Available
Frontend                Available
Source Attribution      Available
Evaluation Framework    Available
Held-out Benchmark      Available
Paper-oriented Research Paused
System Development      Active
```

当前项目定位：

> 一个持续开发中的数据结构课程 RAG 智能助教系统，而不是单一论文实验仓库。

---

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
