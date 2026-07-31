// frontend/js/mock.js

const MOCK_DATA = {
    // 正常回答 - 带多个来源
    normalWithSources: {
        success: true,
        data: {
            answer: '顺序表（Sequential List）支持随机访问是因为其底层采用连续的内存空间存储数据元素。每个元素在内存中占据固定大小的存储单元，通过首地址加上元素序号乘以每个元素所占字节数，即可直接计算出任意元素的存储地址，时间复杂度为 O(1)。\n\n具体来说，假设顺序表的首地址为 LOC(0)，每个元素占用 L 个存储单元，则第 i 个元素的地址为 LOC(i) = LOC(0) + i * L。这种存储方式使得无论访问哪个元素，所需时间都是常数，不随数据规模增大而变化。\n\n这也是顺序表与链表的主要区别之一，链表需要通过指针逐个遍历才能访问到目标节点，访问时间复杂度为 O(n)。',
            sources: [
                {
                    chunk_id: 'linear_ch02_0012',
                    chapter: '第二章 线性表',
                    section: '顺序表的存储结构',
                    source_file: '第二章线性表.pdf',
                    page: 8
                },
                {
                    chunk_id: 'linear_ch02_0015',
                    chapter: '第二章 线性表',
                    section: '顺序表的性能分析',
                    source_file: '第二章线性表.pdf',
                    page: 10
                },
                {
                    chunk_id: 'ds_overview_0003',
                    chapter: '第一章 数据结构概述',
                    section: '数据的存储结构',
                    source_file: '第一章绪论.pdf',
                    page: 5
                }
            ],
            latency_ms: 1820
        },
        error: null
    },
    
    // 正常回答 - 单个来源
    normalSingleSource: {
        success: true,
        data: {
            answer: '完全二叉树（Complete Binary Tree）是指除最后一层外，每一层都被完全填满，且最后一层的所有结点都尽可能靠左排列的二叉树。\n\n完全二叉树的一个重要性质是：如果对完全二叉树按从上到下、从左到右的顺序编号，则编号为 i 的结点，其左孩子编号为 2i，右孩子编号为 2i+1，父结点编号为 i//2。\n\n这种结构在堆排序和优先队列中有着广泛应用。',
            sources: [
                {
                    chunk_id: 'tree_ch06_0023',
                    chapter: '第六章 树和二叉树',
                    section: '完全二叉树',
                    source_file: '第六章树和二叉树.pdf',
                    page: 18
                }
            ],
            latency_ms: 1560
        },
        error: null
    },
    
    // 回答成功但无来源
    successNoSources: {
        success: true,
        data: {
            answer: '根据课程资料，我无法找到关于这个问题的直接答案。建议您查阅教材相关章节或向授课教师请教。',
            sources: [],
            latency_ms: 850
        },
        error: null
    },
    
    // 知识库外问题 - 应该拒答
    outOfScope: {
        success: true,
        data: {
            answer: '抱歉，您的问题超出了我的知识范围。我目前只支持回答与数据结构课程相关的问题，包括线性表、栈与队列、树与二叉树、图、查找、排序等课程内容。如果您有相关课程问题，欢迎提问！',
            sources: [],
            latency_ms: 620
        },
        error: null
    },
    
    // 业务错误
    businessError: {
        success: false,
        data: null,
        error: {
            code: 'EMPTY_QUESTION',
            message: '问题内容不能为空，请输入有效的问题。'
        }
    },
    
    // 模型超时错误
    timeoutError: {
        success: false,
        data: null,
        error: {
            code: 'MODEL_TIMEOUT',
            message: '模型调用超时，请稍后重试。如果问题持续出现，请联系管理员。'
        }
    },
    
    // 检索失败错误
    retrievalError: {
        success: false,
        data: null,
        error: {
            code: 'RETRIEVAL_FAILED',
            message: '检索知识库失败，请检查索引是否已构建或稍后重试。'
        }
    }
};

// 根据问题关键词返回不同的 mock 响应
function getMockResponse(question) {
    const q = question.trim().toLowerCase();
    
    // 模拟延迟 500-2000ms
    const delay = 500 + Math.random() * 1500;
    
    // 根据问题内容匹配不同的 mock 数据
    if (q.includes('顺序表') || q.includes('随机访问')) {
        return { ...MOCK_DATA.normalWithSources, data: { ...MOCK_DATA.normalWithSources.data, latency_ms: delay } };
    }
    
    if (q.includes('完全二叉树') || q.includes('二叉树') && q.includes('完全')) {
        return { ...MOCK_DATA.normalSingleSource, data: { ...MOCK_DATA.normalSingleSource.data, latency_ms: delay } };
    }
    
    if (q.includes('天气') || q.includes('今天') || q.includes('股票') || q.includes('新闻')) {
        return { ...MOCK_DATA.outOfScope, data: { ...MOCK_DATA.outOfScope.data, latency_ms: delay } };
    }
    
    if (q.includes('空') || q.includes('测试空来源')) {
        return { ...MOCK_DATA.successNoSources, data: { ...MOCK_DATA.successNoSources.data, latency_ms: delay } };
    }
    
    // 默认返回带多个来源的回答
    return { 
        ...MOCK_DATA.normalWithSources, 
        data: { 
            ...MOCK_DATA.normalWithSources.data, 
            answer: `关于"${question}"，根据课程资料分析如下：\n\n数据结构课程中，这个问题涉及到数据组织与存储的核心概念。在实际应用中，选择合适的数据结构能够显著提升算法效率。\n\n建议您结合教材中的实例进行理解，通过具体的代码实现加深印象。`, 
            latency_ms: delay 
        } 
    };
}

// 模拟 API 调用
function mockAsk(question, topK = 3) {
    return new Promise((resolve, reject) => {
        // 模拟网络延迟
        const response = getMockResponse(question);
        const delay = response.data ? response.data.latency_ms : 800;
        
        setTimeout(() => {
            // 模拟偶尔的网络错误（5%概率）
            if (Math.random() < 0.05) {
                reject(new Error('网络连接失败，请检查网络设置'));
                return;
            }
            resolve(response);
        }, delay);
    });
}