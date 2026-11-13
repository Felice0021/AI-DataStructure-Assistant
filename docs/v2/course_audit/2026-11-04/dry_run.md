# 导入 dry-run 验证结果

## 原始 CLI：已通过

在项目独立虚拟环境中补齐导入时依赖后，使用Python 3.12.14 / Windows原生执行**未修改的原始V2导入命令**，退出码0：

```powershell
.\.venv-course-audit\Scripts\python.exe -B -m backend.v2.tools.import_course knowledge_base/ds_chunks.jsonl
```

```json
{"source_records": 1010, "bytes": 383572, "sha256": "e0a548c93bc7d562dd4c0ab4d2e1e6add59c1a3f42d2293817e09026ecd4659a", "filename": "v1-course-e0a548c93bc7d562.txt"}
```

再次使用全新的临时 `--mapping-output` 文件运行，退出码0，stdout完全一致；1010条实际CLI映射与先前离线prepare()映射逐项相同。临时映射文件验证后删除。`pip check` 为 `No broken requirements found.`。

机器可读证据：[cli_dry_run.json](cli_dry_run.json)，记录实际Python版本、平台、安装包版本、两次退出码与映射比较结果。复验包装脚本为 `knowledge_base/course_audit/run_dry_run.py`，仅运行原始只读CLI，不提供apply参数。

**边界：本次验证的是Windows原生下的只读CLI，未启动数据库、解析/Embedding Worker、完整后端或任何云端调用。WSL未安装，不能将此结果写成WSL或完整V2后端兼容性验收。** 工具的dry-run分支未实例化文件存储，因此没有触发完整后端依赖的POSIX文件操作。

## 本次隔离环境

使用本机已有Python3.12运行库创建 `.venv-course-audit`，只安装CLI导入依赖及其传递依赖：

```powershell
python3.12 -m venv .venv-course-audit
.\.venv-course-audit\Scripts\python.exe -m pip install starlette==1.10.0 SQLAlchemy==2.0.55 pydantic-settings==2.16.1 pgvector==0.5.0
.\.venv-course-audit\Scripts\python.exe -B knowledge_base/course_audit/run_dry_run.py
```

四个直接依赖版本取自仓库requirements；实际解析出的传递依赖完整版本见cli_dry_run.json。这是精简CLI环境，没有安装完整后端requirements，也没有修改项目依赖清单、系统Python或安装WSL。虚拟环境不提交。

## 首次尝试的历史阻塞：已解决

2026-11-04，Windows原生 PowerShell / Python 3.14.4，仓库根目录执行：

```powershell
python -m backend.v2.tools.import_course knowledge_base/ds_chunks.jsonl
```

当时退出码1，首个失败为第9行导入 `starlette.datastructures` 时 `ModuleNotFoundError: No module named 'starlette'`，未执行到prepare()。该阻塞现已通过上述独立Python3.12环境解决；不再需要负责人为本轮只读CLI代跑。

## 离线 prepare() 预览：成功，非完整CLI验收

`knowledge_base/course_audit/review.py` 使用 Python AST 从当前原始 `import_course.py` 提取**未改动的唯一 prepare() 函数**，仅注入其使用的标准库 `Path/hashlib/json/re`，执行该纯函数。没有加载后端服务、伪造第三方模块或改写工具。本结果验证原函数可接受当前数据并生成派生TXT/映射，不能代替在项目支持环境中的CLI运行。

| 项目 | 结果 |
| --- | --- |
| source_records | 1010 |
| 派生TXT bytes | 383572 |
| 派生TXT SHA-256 | e0a548c93bc7d562dd4c0ab4d2e1e6add59c1a3f42d2293817e09026ecd4659a |
| filename | v1-course-e0a548c93bc7d562.txt |
| prepare 校验错误 | 无 |
| mapping 条数 | 1010 |

源JSONL摘要统一按UTF-8/LF字节计算，Windows检出换行说明见README；本表 bytes/sha256 仅针对工具生成的 UTF-8 TXT 字节。TXT未落盘，映射写入新的 preview_mapping.json，只保留原ID、原来源、原页码及正文hash，不包含完整正文。当前公开CSV/JSON同样不导出正文，含原文Excel不再跟踪。

## 支持环境中的复现步骤

已有WSL2/Python3.12及V2依赖环境的组员也可从相同数据与工具版本运行，交叉核对平台结果：

```bash
python --version
git rev-parse HEAD
python -m backend.v2.tools.import_course knowledge_base/ds_chunks.jsonl
```

预期stdout：

```json
{"source_records": 1010, "bytes": 383572, "sha256": "e0a548c93bc7d562dd4c0ab4d2e1e6add59c1a3f42d2293817e09026ecd4659a", "filename": "v1-course-e0a548c93bc7d562.txt"}
```

不要附加 `--apply`。若要导出新映射，用全新、不存在的 `--mapping-output` 路径；原工具采用独占创建，不可覆盖旧映射。记录实际退出码/stdout；不一致时先核对源文件版本与工具版本。格式或派生预览通过不证明页码正确、授权已确认、数据库就绪或RAG质量达标。
