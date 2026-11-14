# 已校验树形图展示

## 结构来源与兼容性

`POST /api/v2/rag/ask` 和 `POST /api/v2/conversations/{id}/ask` 的 `AskResponse` 增加可选的 `tree_visualization`，未触发参考树算法时为 `null`。旧响应及历史记录缺少该字段仍可读取。

该字段只由 `tree_visualization.build()` 从 `verified_trees.Calculation` 生成。模型的 `AnswerDraft` 不接受此字段；模型 JSON、Markdown、ASCII 图均不会被前端推断为结构。课程规则依据、引用有效性、权限、代次和会话校验继续使用原流程。没有足够课程依据的构造仍然拒答。

`answer` 保留文字树、全部说明和来源，供旧客户端及复制功能使用。有合法结构数据的新客户端改用服务端生成的 `explanation`（省略重复 ASCII 图），再显示 SVG；结构缺失或无效时安全回退原 Markdown。失败或拒答响应不带可展示结构。会话历史存储该可选字段；读取、幂等重放继续重新校验来源，来源失效时不会返回旧图。

## 数据与边界

- `version=1`、`origin=server_verified_tree_v1`；`family` 为 AVL / BST / B / B+。
- `source_citations` 必须与同一回答的 `sources[].citation_id` 一致；不增加模型引用权限。
- `final` 是最终完整树；`rotations` 记录每次旋转的局部子树。
- `TreeGraph` 用 `root` 和平坦 `nodes[]` 表示。结点只有 `id`、整数 `keys[]`、`children[]`。二叉结点固定两个槽，`null` 保留缺失左/右孩子的位置；多路树叶子无孩子，内部孩子数为键数加一。
- LL、RR 为旋转前/后两幅；LR、RL 为旋转前/第一次旋转后/旋转后三幅。中间结构在原有真实指针旋转后记录，检查 BST 全局有序及键集合，不要求尚未完成双旋的中间树已经平衡；完成后仍检查 AVL 平衡。
- 每图最多 64 个结点、最大深度 16、每结点最多 8 键、最多 16 次旋转、全部图合计最多 512 结点；键为 ±999999999 范围的严格整数。参考算法原有更小的输入上限不变。
- 后端和前端均拒绝额外字段、非法编号、重复结点、循环、多父、悬空/不可达结点、错误孩子槽、无序键、无效 BST 范围、B/B+ 分隔范围或叶层，以及旋转阶段缺失、键集合变化。
- 前端只使用模板/VNode 创建固定 SVG 元素（circle / rect / line / text）；没有 `v-html`、动态 SVG 源码、事件属性、foreignObject、外部图片或脚本。解释仍走现有安全 Markdown/KaTeX 渲染。

## 布局

子树按占用宽度自底向上测量，按层放置；缺失二叉槽预留宽度，左/右孩子及连线标识明确。二叉树圆形节点，B/B+ 为多关键字分格矩形。连线端点落在节点边界，不穿过节点正文。旋转注明“局部子树”，与最终完整树相同才省略重复的最终图。

每幅图有独立可聚焦横向滚动区域、标题和 SVG 可访问名称。390px 下顺序纵向排列，宽树内部滚动，页面和消息流不横向溢出。B+ 内部键用于导航，叶子保存记录；本次未增加叶子链可视化。

## 验证与复现

```bash
DS_V2_RUN_DB_TESTS=1 python -m pytest backend/v2/tests -q
cd frontend-v2
npm ci
npm test
npm run build
npm run test:production
npm run test:browser
```

后端测试使用已有随机 `ds_v2_test_*` 创建/清理机制，HTTP 集成覆盖真实上传、解析、向量入库、RAG 结构发布、会话持久化、幂等及账号/来源隔离。未调用付费模型、未访问生产数据库。

浏览器使用生产 preview、真实 Chrome、合成认证/API 路由；树数据来自 `backend/v2/tests/tree_display_cases.py` 的实际参考算法，后端测试检查磁盘 JSON 与实时计算完全一致。它证明本地界面和布局，不代表线上部署或真实 Qwen 质量。覆盖四类旋转、稀疏 BST、多层 B/B+、Markdown/公式、每条回答的引用、复制、刷新、注入拒绝及 1440px/390px。截图在 `frontend-v2/docs/screenshots/verified-trees/`。

本 PR 无迁移，不修改知识库、向量、生产数据库、模型或部署配置；旧历史不会从文字图自动升级，需新问答返回已校验结构后显示新图。不扩展参考算法原有有界计算范围。
