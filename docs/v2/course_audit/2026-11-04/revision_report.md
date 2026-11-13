# PR #11 最小修订报告

修订前核对：远端main为 `bcd7a6f496b945cb54a4fb2e0afb35f5893d4fb8`，本地/远端PR分支均为 `58b10cfc2481225798631afbc78bd0644999b99b`；PR开放、原有19个改动文件。工作区仅有原有未跟踪嵌套仓库，未处理其内容。源知识库及原AI意见输入保持原样。

## 修复

- `review.csv`、`candidates_100.csv`、`issues.csv` 移除 `text` 字段，不替换成全文摘要或另一份正文；保留原ID、章节、来源、页码、异常、AI意见及复核状态。相应本地中间JSON也不再输出正文。
- 检查原Excel的T列确认包含完整正文；从当前公开Git树取消跟踪，新增该目录忽略规则，本地文件保留为受限研究历史副本。当前公开交付使用无正文CSV/JSON，不生成新Excel。
- 最终候选逐ID检查明确、非空AI初审说明，且不得有已记录问题；缺初审立即报错，在写入任何报告前停止，不自动接受未审替补。
- 自动初审、人工复核、最终批准分别列示；当前人工复核/最终批准均未完成。权限状态明确为组员陈述、未独立核验，公开分发未确认。
- 写入前检查三个CSV和本地中间JSON的人工字段及未知列；发现填写时停止并保留全部文件，不自动覆盖或猜测合并。
- CSV/JSON固定LF，源文件和工具hash采用UTF-8/LF口径；保持源文件不变。重复生成及LF/CRLF输入测试结果一致。

## 本次实际验证

运行 `python -B knowledge_base/course_audit/review.py`：**PASS**，1010条、100条候选、556条待复核疑点，数量保持原交付。

运行 `python -B knowledge_base/course_audit/test_review.py`：**PASS，5项测试**：

1. 候选100条、ID唯一、明确AI初审覆盖。
2. 缺失、空白或带已知问题的AI初审记录拒绝通过。
3. 保留的来源字段与原JSONL一致，三个阶段与权限声明一致。
4. 公开审查CSV/JSON/文档/脚本无完整源正文，含原文Excel不再跟踪。
5. 重复生成、换行一致性及人工填写后停止、产物不被改写。

首次在受限执行环境运行时，第5项因系统临时目录写权限错误而**FAIL（环境错误）**，其余4项通过；在允许测试临时目录写入的执行权限下重跑，最终5项全PASS。测试只在新建临时目录生成产物并核对范围后清理，不写原始知识库。

本轮**未运行**完整后端/WSL、数据库、付费模型、真实RAG评测；原始CLI dry-run沿用之前的已成功证据 `cli_dry_run.json`，不伪造为本轮重跑。未执行apply。

## 修改文件

- 工具：`knowledge_base/course_audit/review.py`、新增 `test_review.py`；`content_notes.json`和原dry-run包装脚本未改。
- 表格：三个CSV更新；含原文 `knowledge_base/course_audit/course_review.xlsx` 从跟踪中移除，本地副本由知识库审查工具目录的 `.gitignore` 忽略。
- JSON：`prepare_offline.json`、`summary.json` 更新摘要口径和状态；元数据映射、近似重复与原校验结果不改变内容。
- 说明：`README.md`、`authorization.md`、`delivery_drafts.md`、`dry_run.md`、`findings.md`及本报告。

最终提交号以本报告所在Git提交及PR提交记录为准，避免在提交自身文件中制造循环hash。只普通push到PR现有分支，不合并main。

## 授权与历史限制

非商用研究试验用途仅来自组员陈述，未附权利人书面许可或独立核验；不推定公开分发权限，人工复核和最终批准仍待完成。

初版提交58b10cf已公开过正文；本次只从最新文件中移除重复正文，**不会清除Git历史、远端缓存、他人克隆或已下载副本，无法保证完全撤回**。未reset、clean、重写历史或强推。原始 `knowledge_base/ds_chunks.jsonl` 及已有历史映射不在本次修改范围内。
