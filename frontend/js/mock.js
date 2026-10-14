// frontend/js/mock.js
//
// 离线联调数据。响应结构与后端 /api/v1/ask 保持一致：
//   { request_id, success, error,
//     data: { answer, sources[], mode, out_of_scope, latency_ms } }
//   sources[]  : { chunk_id, chapter, section, source_file, page, content_type }
//   latency_ms : { retrieval, rerank, generation, total }
// 仅在后端不可用或需要离线验证渲染时使用，正式环境请保持 config.js 的 USE_MOCK = false。

const MOCK_DATA = {
    // 概念问答：包含有序列表、公式、表格、行内代码
    qaConcept: {
        request_id: 'mock-qa-0001',
        success: true,
        data: {
            answer: 'AVL 树需要通过旋转来维持平衡，核心原因是**普通二叉排序树在有序插入时会退化成链表**。\n\n### 一、退化的代价\n\n当插入序列已经有序（如 1, 2, 3, 4, 5）时，二叉排序树会不断向右延伸，树高从理想情况的 $O(\\log n)$ 退化为 $O(n)$，查找、插入、删除都随之退化为 $O(n)$。\n\n### 二、平衡因子\n\nAVL 树要求每个结点的平衡因子（左子树高度减右子树高度）取值只能是 $-1$、$0$ 或 $1$：\n\n$$BF(T) = h_L - h_R, \\quad BF \\in \\{-1, 0, 1\\}$$\n\n### 三、失衡的四种情况\n\n1. **LL 型**：在左孩子的左子树上插入，做一次右旋；\n2. **RR 型**：在右孩子的右子树上插入，做一次左旋；\n3. **LR 型**：在左孩子的右子树上插入，先左旋再右旋；\n4. **RL 型**：在右孩子的左子树上插入，先右旋再左旋。\n\n| 失衡类型 | 旋转方式 | 调整后根结点 |\n| --- | --- | --- |\n| LL | 单次右旋 | 原左孩子 |\n| RR | 单次左旋 | 原右孩子 |\n| LR | 先左旋后右旋 | 原左孩子的右孩子 |\n| RL | 先右旋后左旋 | 原右孩子的左孩子 |\n\n因此，旋转不是额外开销，而是把树高重新压回 $O(\\log n)$ 的必要手段，用它换来了各操作的对数级复杂度。',
            sources: [
                {
                    chunk_id: 'ds_ch06_0038',
                    chapter: '第六章 树和二叉树',
                    section: '平衡二叉树',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 138,
                    content_type: 'concept'
                },
                {
                    chunk_id: 'ds_ch06_0041',
                    chapter: '第六章 树和二叉树',
                    section: '二叉排序树的平衡化',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 142,
                    content_type: 'algorithm'
                }
            ],
            mode: 'qa',
            out_of_scope: false,
            latency_ms: { retrieval: 812, rerank: 634, generation: 2360, total: 3806 }
        },
        error: null
    },

    // 习题讲解：有序列表 + 代码块
    exerciseBst: {
        request_id: 'mock-ex-0002',
        success: true,
        data: {
            answer: '### 题目分析\n\n给定数据依次插入二叉排序树（BST），每次比较后决定进入左子树或右子树，最终可以用中序遍历得到递增序列。\n\n### 解题过程\n\n以插入序列 `{45, 24, 53, 12, 37, 93}` 为例：\n\n1. 插入 `45`，作为根结点；\n2. 插入 `24`，小于 `45`，成为 `45` 的左孩子；\n3. 插入 `53`，大于 `45`，成为 `45` 的右孩子；\n4. 插入 `12`，小于 `45` 且小于 `24`，成为 `24` 的左孩子；\n5. 插入 `37`，小于 `45`、大于 `24`，成为 `24` 的右孩子；\n6. 插入 `93`，大于 `45` 且大于 `53`，成为 `53` 的右孩子。\n\n中序遍历按「左 → 根 → 右」递归访问：\n\n```c\nvoid InOrderTraverse(BiTree T)\n{\n    if (T != NULL) {\n        InOrderTraverse(T->lchild);\n        printf("%d ", T->data);\n        InOrderTraverse(T->rchild);\n    }\n}\n```\n\n### 最终答案\n\n中序遍历序列为：`12, 24, 37, 45, 53, 93`，恰好是递增有序的，这也验证了二叉排序树的性质。',
            sources: [
                {
                    chunk_id: 'ds_ch06_0012',
                    chapter: '第六章 树和二叉树',
                    section: '二叉排序树的插入',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 122,
                    content_type: 'exercise'
                },
                {
                    chunk_id: 'ds_ch06_0009',
                    chapter: '第六章 树和二叉树',
                    section: '遍历二叉树',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 118,
                    content_type: 'algorithm'
                }
            ],
            mode: 'exercise',
            out_of_scope: false,
            latency_ms: { retrieval: 956, rerank: 713, generation: 4180, total: 5849 }
        },
        error: null
    },

    // 代码分析：代码块 + 边界条件
    codeAnalysis: {
        request_id: 'mock-code-0003',
        success: true,
        data: {
            answer: '### 代码作用\n\n下面这段遍历在跳出循环后直接访问了 `p->data`，而循环终止条件恰恰是 `p == NULL`：\n\n```c\nvoid PrintList(LinkList L)\n{\n    LinkList p = L->next;\n    while (p != NULL) {\n        printf("%d ", p->data);\n        p = p->next;\n    }\n    printf("%d\\n", p->data);   /* 错误：此时 p 已经是 NULL */\n}\n```\n\n### 问题定位\n\n循环结束时 `p` 一定为 `NULL`，最后一行对空指针解引用，属于典型的**访问空指针**。在多数环境下会触发段错误（Segmentation fault）导致程序崩溃；即使侥幸不崩溃，行为也是未定义的。\n\n### 修改建议\n\n1. 删除循环外那次多余的访问；\n2. 如果确实需要在末尾输出换行，应输出换行符而不是结点数据；\n3. 遍历前先判断链表是否为空，避免对空表误操作。\n\n```c\nvoid PrintList(LinkList L)\n{\n    LinkList p = L->next;\n    while (p != NULL) {\n        printf("%d ", p->data);\n        p = p->next;\n    }\n    printf("\\n");   /* 只输出换行，不解引用 p */\n}\n```\n\n### 复杂度与边界条件\n\n时间复杂度为 $O(n)$，空间复杂度为 $O(1)$。需要额外注意的边界情况包括：空表、只有一个结点、以及循环单链表（`p->next == L` 时应当终止）。',
            sources: [
                {
                    chunk_id: 'ds_ch02_0027',
                    chapter: '第二章 线性表',
                    section: '单链表的遍历',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 31,
                    content_type: 'code'
                }
            ],
            mode: 'code',
            out_of_scope: false,
            latency_ms: { retrieval: 764, rerank: 588, generation: 3120, total: 4472 }
        },
        error: null
    },

    // 正常回答 - 多个来源
    normalWithSources: {
        request_id: 'mock-0004',
        success: true,
        data: {
            answer: '顺序表（Sequential List）支持随机访问是因为其底层采用连续的内存空间存储数据元素。每个元素在内存中占据固定大小的存储单元，通过首地址加上元素序号乘以每个元素所占字节数，即可直接计算出任意元素的存储地址，时间复杂度为 $O(1)$。\n\n具体来说，假设顺序表的首地址为 `LOC(0)`，每个元素占用 `L` 个存储单元，则第 `i` 个元素的地址为：\n\n$$LOC(i) = LOC(0) + i \\times L$$\n\n这种存储方式使得无论访问哪个元素，所需时间都是常数，不随数据规模增大而变化。这也是顺序表与链表的主要区别之一：链表需要通过指针逐个遍历才能访问到目标结点，访问时间复杂度为 $O(n)$。',
            sources: [
                {
                    chunk_id: 'ds_ch02_0012',
                    chapter: '第二章 线性表',
                    section: '顺序表的存储结构',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 21,
                    content_type: 'concept'
                },
                {
                    chunk_id: 'ds_ch02_0015',
                    chapter: '第二章 线性表',
                    section: '顺序表的性能分析',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 24,
                    content_type: 'concept'
                },
                {
                    chunk_id: 'ds_ch01_0004',
                    chapter: '第一章 绪论',
                    section: '1.2 基本概念和术语',
                    source_file: '数据结构（C语言版）严蔚敏.pdf',
                    page: 6,
                    content_type: 'concept'
                }
            ],
            mode: 'qa',
            out_of_scope: false,
            latency_ms: { retrieval: 690, rerank: 512, generation: 1980, total: 3182 }
        },
        error: null
    },

    // 回答成功但无来源
    successNoSources: {
        request_id: 'mock-0005',
        success: true,
        data: {
            answer: '根据当前资料无法确定。建议查阅教材相关章节，或向授课教师进一步确认。',
            sources: [],
            mode: 'qa',
            out_of_scope: false,
            latency_ms: { retrieval: 420, rerank: 0, generation: 860, total: 1280 }
        },
        error: null
    },

    // 范围外问题：正常业务结果，不是系统错误
    outOfScope: {
        request_id: 'mock-0006',
        success: true,
        data: {
            answer: '根据当前资料无法确定',
            sources: [],
            mode: 'qa',
            out_of_scope: true,
            latency_ms: { retrieval: 480, rerank: 0, generation: 0, total: 480 }
        },
        error: null
    },

    // 业务错误
    businessError: {
        request_id: 'mock-0007',
        success: false,
        data: null,
        error: {
            code: 'EMPTY_QUESTION',
            message: '问题内容不能为空，请输入有效的问题。'
        }
    },

    // 模型超时错误
    timeoutError: {
        request_id: 'mock-0008',
        success: false,
        data: null,
        error: {
            code: 'MODEL_TIMEOUT',
            message: '模型调用超时，请稍后重试。如果问题持续出现，请联系管理员。'
        }
    },

    // 检索失败错误
    retrievalError: {
        request_id: 'mock-0009',
        success: false,
        data: null,
        error: {
            code: 'RETRIEVAL_FAILED',
            message: '检索知识库失败，请检查索引是否已构建或稍后重试。'
        }
    }
};

// 按关键词匹配 mock 数据，便于离线覆盖 qa / exercise / code / out_of_scope 四种情况
function getMockResponse(question) {
    const q = (question || '').trim().toLowerCase();

    // 范围外：与后端 Scope Gate 的效果对齐
    if (q.includes('tcp') || q.includes('三次握手') || q.includes('天气') ||
        q.includes('股票') || q.includes('新闻')) {
        return MOCK_DATA.outOfScope;
    }

    // 代码题：与 rag/query_router.py 的 _CODE_KEYWORDS 对齐
    if (q.includes('指针') || q.includes('代码') || q.includes('报错') ||
        q.includes('段错误') || q.includes('越界') || q.includes('bug')) {
        return MOCK_DATA.codeAnalysis;
    }

    // 习题：与 rag/query_router.py 的 _EXERCISE_KEYWORDS 对齐
    if (q.includes('给定') || q.includes('构造') || q.includes('画出') ||
        q.includes('计算') || q.includes('排序过程') || q.includes('遍历序列')) {
        return MOCK_DATA.exerciseBst;
    }

    // 概念题
    if (q.includes('avl') || q.includes('旋转') || q.includes('平衡')) {
        return MOCK_DATA.qaConcept;
    }

    if (q.includes('顺序表') || q.includes('随机访问')) {
        return MOCK_DATA.normalWithSources;
    }

    if (q.includes('空来源') || q.includes('无法确定')) {
        return MOCK_DATA.successNoSources;
    }

    // 默认返回概念题样例
    return MOCK_DATA.qaConcept;
}

// 模拟 API 调用
function mockAsk(question, topK = 5) {
    return new Promise((resolve) => {
        const response = getMockResponse(question);
        const latency = response.data && response.data.latency_ms;
        const delay = latency ? latency.total : 800;

        setTimeout(() => {
            resolve(response);
        }, Math.min(delay, 1500));
    });
}
