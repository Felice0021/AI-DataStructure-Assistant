# frontend-v2

V2 前端（Vue 3 + Vite + TypeScript）。**与 V1 的 `frontend/` 完全独立**，V1 是零构建的原生静态页（指向 `/api/v1`），不要混用。

对应任务：[Issue #3](https://github.com/Felice0021/AI-DataStructure-Assistant/issues/3) · 接口契约：[`docs/v2/openapi.json`](../docs/v2/openapi.json) · 交接说明：[`docs/v2/FRONTEND_HANDOFF.md`](../docs/v2/FRONTEND_HANDOFF.md)

## 1. 快速开始

```bash
cd frontend-v2
npm install
npm run dev
```

打开 **http://127.0.0.1:5173**。

默认启用 MSW 模拟数据，**不需要后端也能看到完整界面与问答流程**（右上角会显示「模拟数据 · answered」徽标）。mock 账号密码任意非空即可。

### 连接真实后端

```bash
cp .env.development.example .env.development.local
```

编辑 `.env.development.local`：

```
VITE_API_BASE=http://127.0.0.1:8001
VITE_USE_MOCK=false
```

然后重启 `npm run dev`。后端启动方式见仓库 README（`python -m backend.v2.tools.dev api --test-providers`）。

> **必须用 `127.0.0.1`，不要用 `localhost`。** 后端按 Origin 白名单校验，用 `localhost:5173` 打开会被判为 `403 origin_rejected`。

### mock 场景切换

两种方式，效果相同：

**方式一：URL 参数（推荐，免重启）** —— 打开 `http://127.0.0.1:5173/?mock=refuse` 即可。顶栏徽标会显示当前生效的场景。

**方式二：环境变量**（写进 `.env.development.local`，需重启 dev server）

```
VITE_MOCK_SCENARIO=answered      # 正常回答（默认）
VITE_MOCK_SCENARIO=refuse        # 200 + 资料不足（正常拒答）
VITE_MOCK_SCENARIO=unavailable   # 503 生成服务不可用
VITE_MOCK_SCENARIO=unauthorized  # 401 会话失效
VITE_MOCK_SCENARIO=logout-fail   # 退出接口 500，验证「退出失败」提示
VITE_MOCK_SCENARIO=many-kbs      # 25 个知识库，验证 20 个选择上限
```

再叠加 `&delay=毫秒` 可以让响应变慢，用来手工复现「请求还在飞时退出登录」：

```
http://127.0.0.1:5173/?mock=answered&delay=4000
```

## 2. 脚本

| 命令 | 说明 |
|---|---|
| `npm run dev` | 开发服务器，固定 `127.0.0.1:5173`（`strictPort`，端口被占会直接报错而不是换端口） |
| `npm run build` | `vue-tsc` 类型检查 + 生产构建到 `dist/` |
| `npm run preview` | 预览构建产物（`127.0.0.1:4173`） |
| `npm run test` | Vitest 单测（56 项） |

## 3. 目录结构

```
src/
├── types/api.ts            手写契约 + 3 处运行时偏差补丁
├── api/
│   ├── config.ts           baseURL / /api/v2 前缀
│   ├── csrf.ts             token 单飞管理（只存内存）
│   ├── http.ts             request()：credentials / CSRF / 错误解析 / 401 兜底 / 超时
│   ├── auth.ts             register / login / me / logout
│   ├── knowledgeBases.ts   list / create / update / remove
│   └── rag.ts              ask
├── stores/
│   ├── auth.ts             用户与会话状态
│   ├── knowledgeBase.ts    列表与多选
│   ├── ask.ts              问答五态
│   └── reset.ts            resetAllPrivateState —— 私人状态唯一清理入口
├── composables/useErrorMessage.ts   error.code → 中文文案
├── components/
│   ├── AuthPanel.vue           注册 / 登录
│   ├── KnowledgeBasePicker.vue 知识库列表与多选
│   ├── AskPanel.vue            提问输入与模式选择
│   ├── AnswerView.vue          五态分发
│   ├── AnswerText.vue          [S1] 安全切分渲染（无 v-html）
│   └── SourceList.vue          来源列表
├── views/HomeView.vue      三段式布局 + 顶栏
├── mocks/                  MSW handlers / fixtures / browser worker
└── styles/main.css         全局变量与基础样式
```

## 4. 本轮实现范围

**已完成（P0）**

- 注册、登录、当前用户显示、退出
- 知识库列表（区分「我的私人资料 / 公共课程资料」）、多选、全选/清空
- 单轮 `POST /api/v2/rag/ask`：问题输入、回答模式（auto/qa/exercise/code）、检索方式（hybrid/bm25/dense）、发送中状态
- `[S1]` 引用渲染与来源列表联动
- 错误与拒答分离：资料不足 / 502 校验失败 / 503 生成不可用 / 401 / 403 / 404 / 422 / 429

**明确未做**（不在本轮验收范围）

- 多轮会话与历史、流式回答、图片/VLM、完整文件管理 UI（上传/解析状态）
- Markdown 渲染（有意不做，见第 6 节）
- 真实云端 Key 配置

## 5. 契约易错点（写新代码前先看这张表）

| 容易写错 | 正确 |
|---|---|
| `question` | **`query`** |
| `mode` | **`retrieval_mode`** + **`answer_mode`** |
| `file_name` | **`source_filename`** |
| `page` | **`page_number`**（PDF 从 1 起，TXT/DOCX 常为 null） |
| `chunk` | **`chunk_index`**（从 0 起） |
| `visibacy` / `scope` | **`visibility`**，枚举仅 `private` / `public` |

**状态语义（不能只看 HTTP 是否 2xx）**

| 情形 | HTTP | `status` | 前端行为 |
|---|---|---|---|
| 正常回答 | 200 | `answered` | 渲染 answer + sources |
| 正常拒答 | **200** | `insufficient_evidence` | 显示「资料不足」，**不是成功也不是故障** |
| 生成校验失败 | 502 | `validation_failed` | 红色错误，不得用旧证据顶替 |
| 生成不可用 | 503 | `generation_unavailable` | 红色错误，与拒答区分 |

502/503 的响应体是「完整 `AskResponse` + `error`」，**openapi.json 只声明了 200/422**，所以 `types/api.ts` 里手写了 `AskErrorResponse`，HTTP 层把 `error.code` 提取成 `ApiError.code`。

**错误体统一是 `{ error: { code, message } }`**，不是 `detail`。422 运行时也是这个形态（openapi 声明的 `HTTPValidationError` 已滞后），解析层两种都兼容。

## 6. 安全设计

| 要求 | 实现 |
|---|---|
| 不读 HttpOnly Cookie、不存 token | CSRF token 只存模块内变量，不进 localStorage、不打日志 |
| 写请求带 CSRF | `http.ts` 对非 GET 自动 `ensureCsrf()` + `X-CSRF-Token`；`csrf_rejected` 自动重取重试一次 |
| Cookie 轮换后必须重取 | 登录成功、登出、`403 csrf_rejected` 三处均作废 token |
| 不渲染不可信 HTML | **全局零 `v-html`**。回答正文按 `[S1]` 正则切片，文本走 `{{ }}` 转义，引用渲染成 `<button>` |
| 引用不能编造 | 只有 `citation_id` 存在于本次 `sources` 才渲染成可点标记，否则降级灰色纯文本 |
| 401 清除旧私人答案 | 唯一入口 `resetAllPrivateState()`，由 `main.ts` 注入到 `http.ts` 的 401 兜底；单测锁定该行为 |
| 不显示后端英文 message | 按 `error.code` 映射中文，未知 code 走兜底文案 |
| mock 不进生产包 | `import.meta.env.DEV` + 动态 `import()` 双重保护；SW 文件放 `src/mocks/` 由开发服务器映射，`dist/` 无 msw 代码也无 `mockServiceWorker.js` |

## 7. 测试

```bash
npm run test
```

覆盖 9 个文件 56 个用例：

- `api/csrf.spec.ts`：并发单飞、缓存、作废后重取、异常响应、**旧响应不覆盖新 token**
- `api/http.spec.ts`：401 触发清理、登录 401 不触发、422 双形态、503 混合体、CSRF 头注入、204、业务 404
- `components/AnswerText.spec.ts`：`[S1]` 切分、未知引用降级、HTML 转义（XSS）
- `components/AnswerView.spec.ts`：拒答不渲染成成功、502/503 徽标不同、401 无重试按钮
- `components/AuthPanel.spec.ts`：会话失效提示、首次访问不误报、注册页不显示、错误优先
- `stores/isolation.spec.ts`：**退出后旧答案/旧列表不写回、旧 401 不影响新会话、超 20 个库本地拦截**
- `stores/knowledgeBase.spec.ts`：**全选按 20 截断、第 21 个被拒、翻页取全**
- `stores/reset.spec.ts`：401/退出后无私人残留、幂等、**退出结果三态（ok / expired / failed）**、退出后作废 CSRF 缓存
- `mocks/handlers.spec.ts`：**未覆盖的 /api/v2 请求被兜底拦下（501），不漏到真实后端**

## 8. 验证状态

**这张表必须如实更新，不要把 fixture 通过写成 HTTP 验证通过。**

| 项目 | 方式 | 状态 |
|---|---|---|
| `npm run dev` 启动 | 本机 Windows | 通过 |
| `npm run build` | 本机 Windows | 通过（gzip 约 38K） |
| 单元测试 56 项 | Vitest | 通过 |
| 生产包不含 msw | 产物清单 | 通过（`dist/` 仅 html + css + js + vite.svg，无 `mockServiceWorker.js`） |
| mock：列库 → 选库 → ask → 引用渲染 | MSW + 真实浏览器 | 通过（`docs/screenshots/01-answered.png`） |
| mock：200 资料不足（不当成成功） | MSW + 真实浏览器 | 通过（`02-refused.png`） |
| mock：503 生成不可用（与拒答区分） | MSW + 真实浏览器 | 通过（`03-generate-unavailable.png`） |
| mock：退出后清空旧答案与选中项 | MSW + 真实浏览器 | 通过（`04-login.png`，退出后回到登录页且无残留） |
| mock：401 会话失效 | 仅单测覆盖 | 未截图（`api/http.spec.ts` + `stores/reset.spec.ts` 断言） |
| 真实后端：注册 / 登录 / 退出 | V2 后端 `127.0.0.1:8001` | 通过（注册 201、登录 200、`/auth/me` 回显真实用户） |
| 真实后端：登录 → 列知识库 | 真实浏览器 + V2 后端 | 通过（`05-real-backend-login.png`） |
| 真实后端：选库 → ask → `[S1]` 引用 | 真实浏览器 + V2 后端 | 通过（`06-real-backend-answer.png`） |
| 真实后端：上传 → 解析 → 向量化 → `ready` | V2 后端 + 隔离解析镜像 | 通过（文档状态 `ready`，2 个 chunk，1 次 embedding 调用） |

**关于真实后端答案的边界**：联调使用 `--test-providers` 的**确定性 Provider**，答案是对检索到的证据原文回显（`generation_model: deterministic-evidence-*`），**不具备真实语义理解能力**，不代表课程问答质量。真实质量仍需 Qwen 云端模型与人工标注评测。

截图位于 `docs/screenshots/`。01–04 为 MSW 合成数据，05–06 为真实后端联调。

## 附录：截图清单

| 文件 | 内容 |
|---|---|
| `01-answered.png` | 正常回答 + `[S1]`/`[S2]` 引用 + 资料来源列表 |
| `02-refused.png` | 200 拒答：黄色「资料不足」卡片 + 具体原因 |
| `03-generate-unavailable.png` | 503：红色「服务不可用」卡片 + 错误码 + 重试按钮 |
| `04-login.png` | 退出登录后的登录页 |
| `05-real-backend-login.png` | 真实后端登录成功：真实用户 + 真实知识库列表 |
| `06-real-backend-answer.png` | 真实后端完整问答：已回答 + `[S1]` + 资料来源 |
| `07-kb-selection-cap.png` | 25 个知识库点「全选」：截断为 20 个并提示上限 |
| `08-logout-failed.png` | 退出请求失败：登录页提示「服务端会话可能仍有效」 |
| `09-stale-response-discarded.png` | 提问中途退出、旧响应迟到：重新登录后答案区无残留 |

## 9. 环境说明

- 实测 Node **22.22.2**（npm 10.9.7）。仓库文档建议 Node 24；Vite 7 要求 ≥20.19，22.x 可正常运行。若要严格对齐文档再升级 Node。
- `msw` 锁在 **2.x**：`msw@3` 要求 TypeScript ≥5.9，而当前脚手架锁定 5.8.3。
- Vitest 5 首次运行需要在 `node_modules/.vitest` 建令牌目录，已用 `pretest` 脚本自动创建；并关闭了文件系统模块缓存（`test.cache: false`）。

## 10. 回滚

本工程是**纯新增目录**，没有修改仓库任何已存在文件。要完全回退：

```bash
rm -rf frontend-v2
```

不需要撤销其他任何改动。

## 11. 并发与边界处理

首版后补充的 5 项健壮性处理，均有单测覆盖：

| 场景 | 处理方式 |
|---|---|
| **请求与用户状态隔离** | `api/session.ts` 维护会话代际（epoch），登录/退出/401 时自增。请求发出时记录 epoch 与自身序号，返回时任一变化即丢弃结果；旧会话迟到的 401 不再清理新会话。 |
| **退出登录结果** | `logoutAndReset()` 返回 `ok / expired / failed`。本地一律清干净并作废 CSRF 缓存；`failed` 时登录页提示"服务端会话可能仍有效"，并提供**「重试退出」按钮**（不承诺关浏览器即可退出）。 |
| **CSRF 并发** | token 缓存加代际计数：Cookie 变化后在飞的旧请求不会覆盖新 token，而是递归取新值。 |
| **知识库数量与分页** | 选择上限 20（后端 `max_length=20`），全选按上限截断并提示，未选项禁用；列表按 100/页翻页取全，超过 5 页才显示"仅显示前 N 个"。 |
| **Mock 隔离** | 末尾加兜底 handler：mock 模式下未被覆盖的 `/api/v2/*` 请求就地返回 `501 mock_unhandled`，**不再发到真实后端**（`onUnhandledRequest` 仅作提示，单靠它挡不住）；`mockServiceWorker.js` 移出 `public/`，由开发服务器中间件映射，生产产物不含该文件。 |


## 12. MSW 生产构建修复复验（2026-11-07）

移除过时的 `package.json` → `msw.workerDirectory: ["public"]`：该配置会让 MSW 安装脚本在 `npm ci` 后重新生成 `public/mockServiceWorker.js`，随后被 Vite 复制到生产包。开发 Worker 继续由 `vite.config.ts` 从 `src/mocks/mockServiceWorker.js` 映射，不需要 public 副本；依赖和 package-lock.json 无需变更。

本次 macOS / Node 24.22.0 实际复验：`npm ci --no-audit --no-fund` 退出 0，未生成 public Worker；Vitest 9 个文件 56 项通过；`npm run build` 退出 0，dist 无 Worker、生产 JS 无 MSW 注册逻辑。生产预览 `/mockServiceWorker.js` 返回 SPA HTML 回退（200 text/html），不是 Worker；开发服务器同路径返回正确 Worker（200 JavaScript）。

Safari 真实验证 MSW answered、refuse、unavailable 三个场景；原有 handler 测试确认未覆盖的 `/api/v2/*` GET/POST 仍返回 501。该兜底仅覆盖 `/api/v2/*`，不保证拦截任意其他网络请求。真实后端模式在独立来源 127.0.0.1:5174 设置 `VITE_USE_MOCK=false`，页面未出现 Mock 用户或知识库，实际尝试后端连接并显示后端未启动提示；配合实际提供的环境开关及启动条件核对，确认未启动 MSW。本轮未启动或操作后端及测试数据库，也未重跑完整后端联调。
