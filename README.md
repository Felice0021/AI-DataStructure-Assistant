# AI-DataStructure-Assistant

## 基于大语言模型和 RAG 技术的数据结构课程智能助教系统

本项目为大学生创新训练项目，面向《数据结构》课程学习场景，构建一个基于 RAG（Retrieval-Augmented Generation，检索增强生成）和大语言模型的课程智能助教系统。

系统将课程教材、PPT 等资料整理为结构化知识片段，通过 Embedding 向量化和语义检索获取与问题相关的课程内容，再结合大语言模型生成回答，并向前端返回对应的知识来源。

当前已完成可运行的系统原型，包括：

- 结构化课程知识库；
- RAG 检索与生成流程；
- 相似度阈值与范围外问题拒答机制；
- FastAPI 后端接口；
- 前端问答页面；
- Markdown 与数学公式渲染；
- 知识来源展示；
- 后端健康检查和异常状态提示；
- 自动化测试与评测流程；
- 前端、后端、RAG 三部分联调。

---

## 一、项目目标

项目主要目标包括：

1. 构建数据结构课程知识库；
2. 对课程资料进行结构化整理；
3. 实现文本 Embedding 与语义检索；
4. 基于检索结果调用大语言模型回答课程问题；
5. 返回回答对应的课程知识来源；
6. 对超出当前知识库覆盖范围的问题进行识别和拒答；
7. 提供可交互的前端问答页面；
8. 建立自动化评测流程，对检索质量、范围控制和响应性能进行评估。

---

## 二、系统架构

当前系统主要由四部分组成：

```text
课程资料 / 知识库
        ↓
RAG 检索与生成模块
        ↓
FastAPI 后端服务
        ↓
前端问答页面
        ↓
用户
```

一次完整问答的处理过程为：

```text
用户输入问题
        ↓
前端发送请求
        ↓
POST /api/v1/ask
        ↓
问题 Embedding
        ↓
知识库相似度检索
        ↓
Top-K 排序
        ↓
检查 Top-1 Similarity Score
        ↓
┌─────────────────────────┐
│ score >= threshold      │
└─────────────────────────┘
        ↓ 是
构造课程上下文
        ↓
调用大语言模型
        ↓
生成回答
        ↓
返回 answer + sources

        ↓ 否

直接返回：
“根据当前资料无法确定”
sources = []
```

通过在生成阶段之前增加检索相关性判断，可以避免明显无关的知识片段被送入大语言模型后产生似是而非的回答。

---

## 三、目录结构

```text
AI-DataStructure-Assistant/
├── backend/
│   └── backend/
│       ├── backend/
│       │   ├── main.py
│       │   ├── config.py
│       │   ├── routers/
│       │   ├── schemas/
│       │   └── services/
│       └── requirements.txt
│
├── frontend/
│   ├── index.html
│   ├── css/
│   └── js/
│
├── knowledge_base/
│   ├── ds_chunks.jsonl
│   ├── ds_demo_chunks_v2.jsonl
│   └── ds_demo_chunks_v50.jsonl
│
├── rag/
│   ├── config.py
│   ├── calibrate_threshold.py
│   ├── threshold_calibration.json
│   └── rag_demo/
│       ├── main.py
│       └── requirements.txt
│
├── tests/
│   ├── test_questions.jsonl
│   ├── run_evaluation.py
│   ├── test_results.jsonl
│   └── evaluation_summary.json
│
├── docs/
├── data/
├── assessment_materials/
└── README.md
```

其中当前正式运行所使用的知识库为：

```text
knowledge_base/ds_chunks.jsonl
```

其余 `ds_demo_*` 文件主要保留用于早期 Demo 或阶段性实验。

---

## 四、正式知识库

当前正式知识库：

```text
knowledge_base/ds_chunks.jsonl
```

当前版本共包含：

```text
55 个知识片段
```

每一行是一个独立 JSON 对象。标准 Chunk 包含以下 7 个字段：

```json
{
  "chunk_id": "tree_001",
  "text": "知识片段正文",
  "chapter": "第六章 树和二叉树",
  "section": "相关小节",
  "source_file": "课程资料.pdf",
  "page": 12,
  "content_type": "concept"
}
```

字段含义：

- `chunk_id`：知识片段唯一标识；
- `text`：实际用于 Embedding 和回答生成的文本；
- `chapter`：所属章节；
- `section`：所属小节；
- `source_file`：原始课程资料；
- `page`：原始资料页码；
- `content_type`：知识内容类型。

当前系统的问答范围由正式知识库实际覆盖内容决定，而不是由“大数据结构课程”这一概念范围决定。

因此，例如某个知识点虽然属于数据结构课程，但如果当前正式知识库中尚未包含对应资料，系统仍应将其视为当前知识库范围外问题。

---

## 五、RAG 检索模块

RAG 主程序：

```text
rag/rag_demo/main.py
```

全局配置：

```text
rag/config.py
```

当前关键配置包括：

```text
Knowledge Base:
knowledge_base/ds_chunks.jsonl

Top-K:
3

Embedding Model:
qwen3.7-text-embedding

Embedding Dimension:
1024

Generation Model:
qwen3.7-plus-2026-05-26

Minimum Retrieval Score:
0.62
```

基本检索过程：

```text
用户问题
→ Query Embedding
→ 与所有知识片段 Embedding 计算余弦相似度
→ 按 Score 从高到低排序
→ 返回 Top-K = 3
```

每个内部检索结果除知识片段原有字段外，还保留：

```text
score
```

用于后续范围判断和实验分析。

---

## 六、范围外问题拒答机制

仅依赖 Prompt 让大语言模型自行判断“资料是否足够”容易出现以下问题：

```text
问题实际上超出知识库
→ 检索器仍返回三个最相似但实际无关的片段
→ 大模型根据无关片段或自身知识继续回答
→ 前端同时显示错误来源
```

因此当前系统在大语言模型生成之前增加了显式相似度阈值。

当前阈值：

```text
MIN_RETRIEVAL_SCORE = 0.62
```

判断逻辑：

```text
Top-1 Score >= 0.62

→ 当前资料与问题具有较高相关性
→ 将 Top-K 片段交给生成模型
→ 返回回答和 sources
```

否则：

```text
Top-1 Score < 0.62

→ 不调用大语言模型
→ 直接返回：

根据当前资料无法确定

→ sources = []
```

这样可以保证：

1. 范围外问题不会继续消耗生成模型调用；
2. 不会向用户展示与问题无关的伪来源；
3. 前端回答和来源状态保持一致。

---

## 七、检索阈值标定

阈值标定脚本：

```text
rag/calibrate_threshold.py
```

标定结果：

```text
rag/threshold_calibration.json
```

当前测试数据得到：

```text
范围内问题数量：
18

范围外问题数量：
2

范围内 Top-1 最低值：
0.777295

范围内 Top-1 最高值：
0.941849

范围内 Top-1 平均值：
0.867041

范围外 Top-1 最低值：
0.435564

范围外 Top-1 最高值：
0.455821

范围外 Top-1 平均值：
0.445693
```

当前样本上两类数据完全可分。

两类边界中点为：

```text
(0.777295 + 0.455821) / 2
≈ 0.616558
```

因此当前系统使用：

```text
MIN_RETRIEVAL_SCORE = 0.62
```

作为第一版基线阈值。

运行标定：

```bash
cd AI-DataStructure-Assistant
source .venv/bin/activate
PYTHONPATH=. python3 rag/calibrate_threshold.py
```

需要说明的是，目前范围外样本数量仍较少，因此 `0.62` 不是永久固定阈值。

后续随着知识库扩大，需要增加更多：

- 范围内改写问题；
- 边界问题；
- 其他章节问题；
- 课程信息问题；
- 完全无关问题；

重新统计分布并调整阈值。

---

## 八、大语言模型生成

当前生成模型：

```text
qwen3.7-plus-2026-05-26
```

生成模型只接收已经通过检索相关性判断的课程知识片段。

当前 Prompt 主要约束：

1. 只使用当前课程资料能够直接支持的内容回答；
2. 不得利用资料外常识自行补充核心事实；
3. 回答应自然、准确，并适合本科生理解；
4. 必要时可以使用分点、公式或代码；
5. 不在正文中使用“资料1”“资料2”“片段1”等内部检索编号；
6. 当前资料不足时回答“根据当前资料无法确定”。

---

## 九、后端 API

后端使用 FastAPI 实现。

### 1. 健康检查

接口：

```http
GET /api/v1/health
```

当前正常响应示例：

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "rag_ready": true,
  "chunk_count": 55,
  "knowledge_file": "knowledge_base/ds_chunks.jsonl"
}
```

其中：

- `status`：服务总体状态；
- `rag_ready`：RAG 模块是否初始化成功；
- `chunk_count`：当前加载知识片段数量；
- `knowledge_file`：当前正式知识库。

如果 RAG 初始化失败：

```text
status = degraded
```

---

### 2. 问答接口

接口：

```http
POST /api/v1/ask
```

请求示例：

```json
{
  "question": "什么是循环单链表？"
}
```

正常响应结构：

```json
{
  "request_id": "e0067611",
  "success": true,
  "data": {
    "answer": "回答内容",
    "sources": [
      {
        "chunk_id": "chunk_id",
        "chapter": "章节",
        "section": "小节",
        "source_file": "来源文件",
        "page": 18
      }
    ],
    "latency_ms": 5572
  },
  "error": null
}
```

范围外问题示例：

```json
{
  "request_id": "request_id",
  "success": true,
  "data": {
    "answer": "根据当前资料无法确定",
    "sources": [],
    "latency_ms": 1000
  },
  "error": null
}
```

内部 RAG 会保留检索相似度分数用于评测，但当前公开 API 不额外暴露 `score` 字段，以保持接口结构稳定。

---

## 十、前端

前端位于：

```text
frontend/
```

当前已实现：

- 问题输入；
- 后端接口调用；
- 加载状态；
- 回答展示；
- Markdown 渲染；
- MathJax 数学公式渲染；
- 来源信息展示；
- 请求延迟展示；
- 历史记录；
- 后端健康状态检测；
- 后端断开提示；
- 范围外问题无来源展示。

前端默认请求：

```text
http://localhost:8000
```

当前真实接口：

```text
/api/v1/ask
/api/v1/health
```

默认：

```text
Top-K = 3
USE_MOCK = false
```

---

## 十一、环境配置

### 1. 克隆仓库

```bash
git clone https://github.com/Felice0021/AI-DataStructure-Assistant.git
cd AI-DataStructure-Assistant
```

### 2. 创建 Python 虚拟环境

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows：

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. 安装后端及 RAG 依赖

```bash
pip install -r backend/backend/requirements.txt
```

当前后端 requirements 已包含完整服务运行所需的主要依赖，包括：

```text
fastapi
uvicorn
pydantic
pydantic-settings
openai
dashscope
numpy
python-dotenv
```

---

## 十二、API Key 配置

在：

```text
rag/rag_demo/
```

目录下创建：

```text
.env
```

内容：

```text
DASHSCOPE_API_KEY=YOUR_API_KEY
```

禁止将真实 API Key 提交到 GitHub。

`.env` 应仅保存在本地环境中。

---

## 十三、运行系统

### 1. 启动后端

从项目根目录进入：

```bash
cd backend/backend
```

激活根目录虚拟环境：

```bash
source ../../.venv/bin/activate
```

启动：

```bash
PYTHONPATH="../..:." python3 -m backend.main
```

正常启动时应看到：

```text
正在初始化RAG服务...
正在读取标准知识片段...
共读取 55 个知识片段。
正在生成知识片段向量...
RAG初始化成功
Application startup complete.
```

默认服务地址：

```text
http://127.0.0.1:8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

---

### 2. 启动前端

另开一个终端，在项目根目录运行：

```bash
python3 -m http.server 5500 -d frontend
```

浏览器访问：

```text
http://localhost:5500
```

前端将自动连接：

```text
http://localhost:8000
```

的后端服务。

---

## 十四、自动化评测

测试问题：

```text
tests/test_questions.jsonl
```

评测脚本：

```text
tests/run_evaluation.py
```

详细测试结果：

```text
tests/test_results.jsonl
```

汇总结果：

```text
tests/evaluation_summary.json
```

运行方式：

```bash
cd AI-DataStructure-Assistant
source .venv/bin/activate
PYTHONPATH=. python3 tests/run_evaluation.py
```

运行评测前需要保证后端服务已经启动。

当前评测同时进行：

```text
本地直接检索
+
后端 API 完整问答
```

因此既可以获得真实检索相似度，又不需要改变公开 API 返回结构。

---

## 十五、评测指标

当前主要指标包括：

### Request Success Rate

API 请求成功率。

### Chapter Hit@3

对于范围内问题，Top-3 检索结果中是否存在预期章节。

### Source Hit@3

对于范围内问题，Top-3 中是否存在预期来源文件。

### Chunk Hit@3

对于范围内问题，Top-3 中是否命中预先标注的目标 Chunk。

该指标比章节级和来源级指标更加严格。

由于同一知识点可能由多个语义等价或互补 Chunk 支撑，因此未命中唯一预设 Chunk 并不一定代表实际检索错误。

### Out-of-Scope Refuse Accuracy

范围外问题是否正确拒答。

### Out-of-Scope Sources Empty Rate

范围外问题返回的 `sources` 是否正确为空。

### Average Latency

20 道测试问题的平均 API 响应延迟。

### P95 Latency

95% 请求完成所需的延迟上界，用于观察较慢请求。

---

## 十六、当前最终评测结果

当前正式评测集：

```text
总问题数：20
范围内问题：18
范围外问题：2
正式知识片段：55
Top-K：3
Similarity Threshold：0.62
```

评测结果：

| 指标 | 结果 |
|---|---:|
| Request Success Rate | 100% |
| Chapter Hit@3 | 100% |
| Source Hit@3 | 100% |
| Chunk Hit@3 | 88.89% |
| Out-of-Scope Refuse Accuracy | 100% |
| Out-of-Scope Sources Empty Rate | 100% |
| Average Latency | 4932.30 ms |
| P95 Latency | 7912.23 ms |
| Failed Questions | 0 |

其中：

```text
18 / 18
```

范围内问题均在 Top-3 中命中正确章节和正确来源。

范围外测试：

```text
哈希表的基本原理是什么？如何解决哈希冲突？

Top-1 Score ≈ 0.4558
→ 低于 0.62
→ 正确拒答
→ sources = []
```

以及：

```text
这门数据结构课程的授课教师是谁？

Top-1 Score ≈ 0.4354
→ 低于 0.62
→ 正确拒答
→ sources = []
```

当前测试集中没有出现范围内问题被阈值误拒答。

---

## 十七、当前阶段结论

当前版本已经完成从早期 RAG Demo 到可运行系统原型的基本闭环：

```text
正式课程知识库
        ↓
Embedding
        ↓
Top-K 检索
        ↓
范围判断
        ↓
LLM 回答生成
        ↓
FastAPI
        ↓
前端页面
        ↓
来源展示
        ↓
自动化评测
```

已经解决的主要问题包括：

- 正式知识库接入；
- RAG 参数集中配置；
- 检索 Score 保留；
- Top-K 参数统一；
- 范围外问题仍生成答案的问题；
- 范围外问题仍返回错误来源的问题；
- Prompt 中机械引用“资料1/资料2”的问题；
- 前端与后端真实接口联调；
- 后端健康状态检测；
- 检索指标统计口径不统一；
- 范围内和范围外评测分母混用的问题。

因此，当前版本已经具备：

```text
可运行
可联调
可演示
可评测
可追溯
```

的系统原型能力。

---

## 十八、当前局限

目前系统仍存在以下限制：

1. 正式知识库规模仍较小，目前为 55 个 Chunk；
2. 当前知识库尚未覆盖整门数据结构课程；
3. 范围外标定样本数量仍不足；
4. 当前 Embedding 在服务启动时重新计算，尚未实现持久化向量索引；
5. 当前采用线性余弦相似度搜索，知识库扩大后效率会下降；
6. 尚未接入专门的向量数据库；
7. `Chunk Hit@3` 仍有提升空间；
8. 当前自动化评测重点覆盖检索和范围控制，对生成答案语义质量的自动评价仍较有限；
9. 当前实验集规模仍不足以证明系统在完整课程范围内的泛化性能。

因此当前评测结果应理解为：

```text
当前知识库 + 当前测试集 + 当前模型配置
```

下的阶段性实验结果，而不是对完整数据结构课程所有问题的最终性能结论。

---

## 十九、后续计划

下一阶段可重点推进：

1. 扩充线性表之外的课程章节；
2. 建立覆盖栈、队列、树、图、查找、排序等内容的正式知识库；
3. 增加范围内和范围外测试问题；
4. 使用独立开发集重新标定相似度阈值；
5. 增加更困难的改写问题和边界问题；
6. 优化 Chunk 划分粒度；
7. 分析未命中预期 Chunk 的测试问题；
8. 引入向量索引或向量数据库；
9. 对 Embedding 结果进行缓存或持久化；
10. 增加生成答案正确性、完整性、引用一致性等评测指标；
11. 完善系统部署和演示流程；
12. 为后续项目总结和论文实验积累更完整的数据。

---

## 二十、团队分工

当前项目由 5 名成员协作完成：

- 李均乐：项目协调、RAG 核心流程、系统联调与最终验收；
- 郭星辰：课程知识库和数据整理；
- 祝晟译：FastAPI 后端接口；
- 张圣江：前端问答页面；
- 常慧思：测试、评测、文档相关工作。

各模块最终通过统一仓库和接口进行集成。

---

## 二十一、安全说明

开发和使用过程中需要注意：

- 不提交 `.env`；
- 不提交真实 API Key；
- 不在 README、实验日志、截图或提交记录中暴露 Token；
- 不提交 `.venv`；
- 不提交 `__pycache__`；
- 不提交 `.pyc`；
- API Key 应通过环境变量加载；
- 对外展示实验结果时应明确当前知识库和测试集范围。

---

## 二十二、当前项目状态

当前状态：

```text
RAG 核心流程：已完成
正式知识库接入：已完成
相似度阈值机制：已完成
FastAPI 后端：已完成
前端页面：已完成
前后端联调：已完成
范围外问题处理：已完成
自动化评测：已完成
20 题阶段性验收：通过
```

当前代码已形成一个可以继续扩充知识库、优化检索算法和开展后续实验的数据结构课程 RAG 智能助教系统原型。
