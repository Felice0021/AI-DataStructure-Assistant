// frontend/js/app.js

// 后端回答模式 → 界面文案（mode 由后端自动判定，前端只做展示）
const MODE_LABELS = {
    qa: '概念问答',
    exercise: '习题讲解',
    code: '代码分析'
};

// 知识片段内容类型 → 界面文案
const CONTENT_TYPE_LABELS = {
    concept: '概念',
    algorithm: '算法',
    code: '代码',
    exercise: '习题',
    comparison: '对比',
    example: '示例',
    other: '其他'
};

// 后端把 Python 异常类名直接当作 error.code 返回（见 rag/main.py:550 与 :661），
// message 则是异常的 str()，形如：
//   ('Connection aborted.', ConnectionResetError(10054, '远程主机强迫关闭了一个现有的连接。', ...))
// 这种"后端可达、但它连不上模型服务"的故障本质是网络问题，需要转成用户看得懂的提示，
// 不能把异常元组原样甩到界面上。
const UPSTREAM_NETWORK_ERROR_CODES = new Set([
    'ConnectionError', 'ConnectionResetError', 'ConnectionAbortedError',
    'ConnectionRefusedError', 'ConnectError', 'ConnectTimeout',
    'ReadTimeout', 'Timeout', 'TimeoutError', 'NewConnectionError',
    'MaxRetryError', 'ProtocolError', 'RemoteDisconnected', 'SSLError',
    'URLError', 'ProxyError', 'IncompleteRead', 'ChunkedEncodingError'
]);

// "模型服务不可用"这个软状态的保留时长。
// 健康检查只看 RAG 有没有初始化完成，感知不到后端到模型的实时连通性，
// 因此用最近一次问答的结果来补充判断；超过这个时长后交回健康检查结论。
const MODEL_UNAVAILABLE_WINDOW_MS = 5 * 60 * 1000;

class ChatApp {
    constructor() {
        this.elements = {
            questionInput: document.getElementById('questionInput'),
            submitBtn: document.getElementById('submitBtn'),
            statusBar: document.getElementById('statusBar'),
            statusBadge: document.getElementById('statusBadge'),
            statusDetail: document.getElementById('statusDetail'),
            retryHint: document.getElementById('retryHint'),
            loadingSection: document.getElementById('loadingSection'),
            loadingText: document.getElementById('loadingText'),
            loadingTime: document.getElementById('loadingTime'),
            answerSection: document.getElementById('answerSection'),
            questionDisplayContent: document.getElementById('questionDisplayContent'),
            renderNotice: document.getElementById('renderNotice'),
            scopeNotice: document.getElementById('scopeNotice'),
            scopeNoticeText: document.getElementById('scopeNoticeText'),
            modeBadge: document.getElementById('modeBadge'),
            answerContent: document.getElementById('answerContent'),
            answerLatency: document.getElementById('answerLatency'),
            sourcesList: document.getElementById('sourcesList'),
            sourcesCount: document.getElementById('sourcesCount'),
            emptySources: document.getElementById('emptySources'),
            errorSection: document.getElementById('errorSection'),
            errorCode: document.getElementById('errorCode'),
            errorMessage: document.getElementById('errorMessage'),
            historyList: document.getElementById('historyList'),
            historyCount: document.getElementById('historyCount'),
            clearHistoryBtn: document.getElementById('clearHistoryBtn')
        };
        
        this.history = [];
        this.maxHistory = 50;
        this.isLoading = false;
        this.currentAnswer = null;
        this.currentSources = null;
        this.currentLatency = null;
        this.currentMode = '';
        this.currentOutOfScope = false;
        // 上一轮成功回答的快照，请求失败时用于恢复显示
        this.lastGoodResult = null;
        // 最近一次"后端连不上模型服务"的时间戳；健康检查测不出这种情况，用它兜住
        this.modelUnavailableSince = null;
        
        // 状态管理
        this.statusCheckTimer = null;
        this.isStatusChecking = false;
        this.connectionRetries = 0;
        this.MAX_RETRIES = 3;
        
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadHistoryFromStorage();
        this.updateHistoryUI();
        this.focusInput();
        
        // 启动时检测连接状态
        this.updateConnectionStatus();
        
        // 每 30 秒自动重新检测一次
        this.statusCheckTimer = setInterval(() => {
            this.updateConnectionStatus();
        }, 30000);
    }
    
    bindEvents() {
        this.elements.submitBtn.addEventListener('click', () => {
            this.handleSubmit();
        });
        
        this.elements.questionInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.handleSubmit();
            }
        });
        
        this.elements.clearHistoryBtn.addEventListener('click', () => {
            this.clearHistory();
        });
        
        this.elements.questionInput.addEventListener('input', () => {
            this.autoResizeTextarea();
        });
        
        // 点击状态栏重试连接
        this.elements.statusBar.addEventListener('click', () => {
            if (!this.isStatusChecking) {
                this.retryConnection();
            }
        });
    }
    
    focusInput() {
        this.elements.questionInput.focus();
    }
    
    autoResizeTextarea() {
        const textarea = this.elements.questionInput;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
    }
    
    // ===== 智能连接状态检测 =====
    async updateConnectionStatus() {
        // 防止重复检测
        if (this.isStatusChecking) {
            return;
        }
        
        this.isStatusChecking = true;
        this.elements.retryHint.style.display = 'none';
        
        // 先显示检测中
        this.setStatus('checking', '🟡 检测中...', '正在连接后端服务...');
        
        try {
            const result = await apiClient.healthCheck();
            
            // 检查结果
            // 只把真正的连通性问题判为"未连接"；
            // rag_ready=false 属于"后端在、但 RAG 未就绪"，走后面的 degraded 分支
            if (result.status === 'unreachable' || result.status === 'error') {
                // 连接层失败：后端未启动 / 连接被拒 / 健康检查超时 / HTTP 异常
                if (result.error === '连接超时') {
                    this.setStatus('timeout', '⏰ 连接超时', '请检查后端服务是否启动');
                } else if (result.status === 'error') {
                    this.setStatus('disconnected', '🔴 后端异常', result.error || '后端服务返回异常状态');
                } else {
                    this.setStatus('disconnected', '🔴 未连接', result.error || '后端服务不可达');
                }
                this.elements.retryHint.style.display = 'inline';
                
                // 自动重试（最多3次）
                if (this.connectionRetries < this.MAX_RETRIES) {
                    this.connectionRetries++;
                    setTimeout(() => {
                        this.updateConnectionStatus();
                    }, 2000);
                }
                return;
            }
            
            // 连接成功，重置重试计数
            this.connectionRetries = 0;
            
            if (result.rag_ready === true) {
                // /health 只反映"RAG 是否初始化完成"，测不出后端到模型服务的实时连通性。
                // 所以若最近一次问答是因为连不上模型服务而失败的，这里不能显示绿灯。
                if (this.isModelServiceUnavailable()) {
                    this.setStatus('degraded', '🟠 模型服务异常', '最近一次问答失败，模型服务可能不可用');
                    this.elements.retryHint.style.display = 'inline';
                } else {
                    this.setStatus('connected', '🟢 已连接', 'RAG 服务就绪');
                }
            } else {
                // 后端连通，但 RAG 未就绪（模型服务不可用、知识库加载失败等），
                // 这不等同于"后端不可达"，不能报成"未连接"
                this.setStatus('degraded', '🟠 服务异常', 'RAG 服务未就绪，问答功能暂不可用');
                this.elements.retryHint.style.display = 'inline';
            }
            
        } catch (error) {
            // 任何未捕获的异常
            this.setStatus('disconnected', '🔴 未连接', '连接异常');
            this.elements.retryHint.style.display = 'inline';
            
            // 自动重试
            if (this.connectionRetries < this.MAX_RETRIES) {
                this.connectionRetries++;
                setTimeout(() => {
                    this.updateConnectionStatus();
                }, 2000);
            }
        } finally {
            this.isStatusChecking = false;
        }
    }
    
    // ===== 设置状态显示 =====
    setStatus(state, label, detail) {
        const badge = this.elements.statusBadge;
        const detailEl = this.elements.statusDetail;
        
        // 更新徽章样式
        badge.textContent = label;
        badge.className = 'status-badge';
        
        switch (state) {
            case 'checking':
                badge.classList.add('status-checking');
                break;
            case 'connected':
                badge.classList.add('status-connected');
                break;
            case 'degraded':
                badge.classList.add('status-degraded');
                break;
            case 'timeout':
                badge.classList.add('status-timeout');
                break;
            case 'disconnected':
                badge.classList.add('status-disconnected');
                break;
            default:
                badge.classList.add('status-checking');
        }
        
        detailEl.textContent = detail || '';
    }
    
    // ===== 手动重试连接 =====
    async retryConnection() {
        this.connectionRetries = 0;
        await this.updateConnectionStatus();
    }
    
    // ===== Markdown 渲染（marked + DOMPurify） =====
    // 关键点：marked / DOMPurify 任一缺失，都不能把原始 Markdown 直接吐给用户 ——
    // 那样界面上会出现一整坨带 ### 和 ** 的文字，看起来"排版全乱、连换行都没有"。
    // 这里改为降级成保留换行的纯文本，并置位 renderingDegraded，由 showAnswer 给出可见提示。
    renderMarkdown(text) {
        if (!text) return '';
        
        const canParse = typeof window.marked !== 'undefined'
            && typeof window.marked.parse === 'function';
        const canSanitize = typeof window.DOMPurify !== 'undefined'
            && typeof window.DOMPurify.sanitize === 'function';
        
        if (!canParse) {
            console.warn('[render] marked 未加载，已降级为纯文本渲染');
            this.renderingDegraded = true;
            return this.plainTextFallback(text);
        }
        
        try {
            // 注：headerIds / mangle 在 marked v5 之后已移除，传了也是无操作，这里不再传
            const rawHtml = window.marked.parse(text, {
                breaks: true,
                gfm: true
            });
            
            if (!canSanitize) {
                // 没有 DOMPurify 就无法安全清洗，退回纯文本，而不是直接插入未净化的 HTML
                console.warn('[render] DOMPurify 未加载，已降级为纯文本渲染');
                this.renderingDegraded = true;
                return this.plainTextFallback(text);
            }
            
            return window.DOMPurify.sanitize(rawHtml, {
                ADD_TAGS: ['math'],
                ADD_ATTR: ['xmlns', 'display', 'inline'],
                FORBID_TAGS: ['script', 'style'],
                FORBID_ATTR: ['onerror', 'onload', 'onclick']
            });
        } catch (error) {
            console.error('[render] Markdown 渲染失败，已降级为纯文本:', error);
            this.renderingDegraded = true;
            return this.plainTextFallback(text);
        }
    }
    
    // 降级渲染：转义后交给 CSS 的 white-space: pre-wrap 保留换行结构
    plainTextFallback(text) {
        return `<div class="answer-plaintext">${this.escapeHtml(text)}</div>`;
    }
    
    // ===== 提交问题 =====
    async handleSubmit() {
        const question = this.elements.questionInput.value.trim();
        
        if (!question) {
            this.showError('EMPTY_QUESTION', '请输入您的问题后再提交。');
            return;
        }
        
        if (this.isLoading) {
            return;
        }
        
        // 提交前快照上一轮的有效结果。请求失败时用它恢复显示，
        // 避免"网络抖动一次就把用户正在看的回答整片清空"。
        this.lastGoodResult = this.elements.answerSection.classList.contains('active')
            ? {
                question: this.elements.questionDisplayContent.textContent,
                answer: this.currentAnswer,
                sources: this.currentSources,
                latency: this.currentLatency,
                mode: this.currentMode,
                outOfScope: this.currentOutOfScope
            }
            : null;

        // 清空旧回答、来源、错误
        this.hideAllSections();
        this.currentAnswer = null;
        this.currentSources = null;
        this.currentLatency = null;
        this.currentMode = '';
        this.currentOutOfScope = false;

        // 显示加载状态
        this.showLoading('正在检索知识库并生成回答...');
        
        // 禁用输入
        this.isLoading = true;
        this.elements.submitBtn.disabled = true;
        this.elements.questionInput.disabled = true;
        
        const startTime = performance.now();
        
        try {
            const response = await apiClient.ask(question);
            const endTime = performance.now();
            const elapsed = Math.round(endTime - startTime);
            
            this.hideLoading();
            this.handleResponse(response, question, elapsed);

            // 回答成功返回并渲染后再清空输入框。
            this.elements.questionInput.value = '';
            this.autoResizeTextarea();
            
        } catch (error) {
            this.hideLoading();
            this.showRequestError(error);
        } finally {
            this.isLoading = false;
            this.elements.submitBtn.disabled = false;
            this.elements.questionInput.disabled = false;
            this.elements.questionInput.focus();
            this.updateConnectionStatus();
        }
    }
    
    // ===== 处理响应 =====
    // 成功响应 data 结构：
    //   { answer, sources[], mode, out_of_scope,
    //     latency_ms: { retrieval, rerank, generation, total } }
    handleResponse(response, question, elapsed) {
        if (response && response.success && response.data) {
            const data = response.data;
            const answer = data.answer || '';
            const sources = Array.isArray(data.sources) ? data.sources : [];
            const mode = data.mode || '';
            const outOfScope = data.out_of_scope === true;
            const latency = this.normalizeLatency(data.latency_ms, elapsed);

            // 本次问答成功 —— 清掉"模型服务不可用"标记，状态徽章可以回到绿灯
            this.modelUnavailableSince = null;

            // 输入框会在回答成功后清空，因此将本轮问题保留在回答卡片中。
            this.elements.questionDisplayContent.textContent = question;
            
            this.currentAnswer = answer;
            this.currentSources = sources;
            this.currentLatency = latency;
            this.currentMode = mode;
            this.currentOutOfScope = outOfScope;
            
            this.hideError();
            // out_of_scope 表示"知识库资料不足"，不是系统错误，按正常回答渲染。
            this.showAnswer(answer, latency, mode);
            this.showScopeNotice(outOfScope);
            this.showSources(sources);
            this.addHistory({ question, answer, sources, mode, outOfScope, latency });
            
        } else {
            // success=false 或 data 缺失，按统一错误路径处理
            const backendError = (response && response.error) || {};
            this.showRequestError({
                code: backendError.code,
                message: backendError.message,
                data: { error: backendError }
            });
        }
    }
    
    // ===== 加载状态 =====
    showLoading(text) {
        this.elements.loadingSection.classList.add('active');
        this.elements.loadingText.textContent = text || '正在思考...';
        this.elements.loadingTime.textContent = '';
        
        let seconds = 0;
        this.loadingTimer = setInterval(() => {
            seconds++;
            this.elements.loadingTime.textContent = `已等待 ${seconds}s`;
        }, 1000);
    }
    
    hideLoading() {
        this.elements.loadingSection.classList.remove('active');
        if (this.loadingTimer) {
            clearInterval(this.loadingTimer);
            this.loadingTimer = null;
        }
    }
    
    // ===== 显示回答 =====
    showAnswer(answer, latency, mode) {
        this.elements.answerSection.classList.add('active');
        
        // renderMarkdown 内部会在降级时把 renderingDegraded 置位
        this.renderingDegraded = false;
        const renderedHtml = this.renderMarkdown(answer);
        
        this.elements.answerContent.innerHTML = renderedHtml || '<em>（无回答内容）</em>';
        this.showRenderNotice(this.renderingDegraded);
        this.showLatency(latency);
        this.showMode(mode);
        
        // 触发 MathJax 渲染
        this.renderMath();
    }
    
    // ===== 渲染降级提示 =====
    // 不静默降级：让用户知道"排版没出来"是组件没加载，而不是回答本身有问题
    showRenderNotice(degraded) {
        const el = this.elements.renderNotice;
        if (!el) return;
        el.style.display = degraded ? 'flex' : 'none';
    }
    
    hideRenderNotice() {
        const el = this.elements.renderNotice;
        if (el) el.style.display = 'none';
    }
    
    // ===== 耗时显示（默认展示 total） =====
    showLatency(latency) {
        const el = this.elements.answerLatency;
        const normalized = this.normalizeLatency(latency);
        
        if (!normalized || normalized.total <= 0) {
            el.textContent = '';
            el.removeAttribute('title');
            return;
        }
        
        el.textContent = `⏱ 耗时 ${this.formatDuration(normalized.total)}`;
        
        // 悬停查看分阶段耗时，便于定位是哪一步慢
        const stages = [];
        if (normalized.retrieval > 0) stages.push(`检索 ${this.formatDuration(normalized.retrieval)}`);
        if (normalized.rerank > 0) stages.push(`重排 ${this.formatDuration(normalized.rerank)}`);
        if (normalized.generation > 0) stages.push(`生成 ${this.formatDuration(normalized.generation)}`);
        
        if (stages.length) {
            el.setAttribute('title', stages.join(' · '));
        } else {
            el.removeAttribute('title');
        }
    }
    
    // 兼容三种形态：新版分阶段对象 / 旧版单个数字 / 缺失
    // 旧版历史记录里 latency 是数字，直接拼接会渲染成 [object Object] 或 undefined
    normalizeLatency(raw, fallback = null) {
        const zero = { retrieval: 0, rerank: 0, generation: 0, total: 0 };
        
        if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
            const pick = (key) => {
                const value = Number(raw[key]);
                return Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
            };
            const result = {
                retrieval: pick('retrieval'),
                rerank: pick('rerank'),
                generation: pick('generation'),
                total: pick('total')
            };
            if (result.total === 0) {
                // 分阶段齐全但缺 total 时用各阶段之和兜底
                result.total = result.retrieval + result.rerank + result.generation;
            }
            return result;
        }
        
        const numeric = Number(raw);
        if (Number.isFinite(numeric) && numeric > 0) {
            return { ...zero, total: Math.round(numeric) };
        }
        
        const fallbackNumeric = Number(fallback);
        if (Number.isFinite(fallbackNumeric) && fallbackNumeric > 0) {
            return { ...zero, total: Math.round(fallbackNumeric) };
        }
        
        return zero;
    }
    
    // 毫秒 → "5.8s" / "820ms"
    formatDuration(ms) {
        const value = Number(ms);
        if (!Number.isFinite(value) || value <= 0) return '0ms';
        return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`;
    }
    
    // ===== 回答模式徽章 =====
    // mode 由后端 rag/query_router.py 自动判定，前端只负责展示，不做手动切换。
    showMode(mode) {
        const badge = this.elements.modeBadge;
        const normalized = (mode || '').trim().toLowerCase();
        
        if (!normalized) {
            this.hideMode();
            return;
        }
        
        // 遇到未知模式降级显示原文，不抛错
        const label = MODE_LABELS[normalized] || normalized;
        badge.textContent = label;
        badge.className = 'mode-badge';
        if (MODE_LABELS[normalized]) {
            badge.classList.add(`mode-${normalized}`);
        }
        badge.style.display = 'inline-block';
    }
    
    hideMode() {
        const badge = this.elements.modeBadge;
        badge.style.display = 'none';
        badge.textContent = '';
        badge.className = 'mode-badge';
    }
    
    // ===== 范围外提示 =====
    // out_of_scope=true 表示知识库资料不足，属于正常业务结果，不是系统错误
    showScopeNotice(visible) {
        const notice = this.elements.scopeNotice;
        if (visible) {
            this.elements.scopeNoticeText.textContent =
                '当前知识库暂无足够资料，以下内容为系统的范围外提示。';
            notice.style.display = 'flex';
        } else {
            notice.style.display = 'none';
        }
    }
    
    hideScopeNotice() {
        this.elements.scopeNotice.style.display = 'none';
    }
    
    // ===== MathJax 渲染 =====
    renderMath() {
        const element = this.elements.answerContent;
        
        if (window.MathJax && window.MathJax.typesetPromise) {
            window.MathJax.typesetPromise([element])
                .catch((err) => console.warn('MathJax 渲染失败:', err));
        } else if (window.MathJax && window.MathJax.Hub) {
            window.MathJax.Hub.Queue(['Typeset', window.MathJax.Hub, element]);
        } else {
            let attempts = 0;
            const checkMathJax = setInterval(() => {
                attempts++;
                if (window.MathJax && window.MathJax.typesetPromise) {
                    clearInterval(checkMathJax);
                    window.MathJax.typesetPromise([element])
                        .catch((err) => console.warn('MathJax 渲染失败:', err));
                } else if (attempts > 20) {
                    clearInterval(checkMathJax);
                    console.warn('MathJax 加载超时');
                }
            }, 500);
        }
    }
    
    hideAnswer() {
        this.elements.answerSection.classList.remove('active');
    }
    
    // ===== 显示来源 =====
    showSources(sources) {
        const list = this.elements.sourcesList;
        const countEl = this.elements.sourcesCount;
        const emptyEl = this.elements.emptySources;
        
        list.innerHTML = '';
        
        if (!sources || sources.length === 0) {
            emptyEl.style.display = 'flex';
            countEl.textContent = '0';
            return;
        }
        
        emptyEl.style.display = 'none';
        countEl.textContent = sources.length;
        
        sources.forEach((source, index) => {
            const item = document.createElement('div');
            item.className = 'source-item';
            
            const chapter = (source.chapter || '').trim();
            const section = (source.section || '').trim();
            const file = (source.source_file || '').trim();
            // page 可能为 null / undefined / 0，此时不渲染该项，避免出现空值
            const page = Number(source.page) > 0 ? Number(source.page) : null;
            const contentType = this.contentTypeLabel(source.content_type);
            const chunkId = (source.chunk_id || '').trim();
            
            const title = section || chapter || file || '未知来源';
            
            const metaParts = [];
            if (chapter && chapter !== title) {
                metaParts.push(`📖 ${this.escapeHtml(chapter)}`);
            }
            if (section && section !== title) {
                metaParts.push(`📝 ${this.escapeHtml(section)}`);
            }
            if (file) {
                metaParts.push(`📄 ${this.escapeHtml(file)}`);
            }
            if (page !== null) {
                metaParts.push(`📑 第 ${page} 页`);
            }
            if (contentType) {
                metaParts.push(`🏷 ${this.escapeHtml(contentType)}`);
            }
            
            item.innerHTML = `
                <span class="source-index">[${index + 1}]</span>
                <div class="source-info">
                    <div class="source-title">${this.escapeHtml(title)}</div>
                    <div class="source-meta">
                        ${metaParts.join('<span class="sep">·</span>')}
                        ${chunkId ? `<div class="source-chunk-id">ID: ${this.escapeHtml(chunkId)}</div>` : ''}
                    </div>
                </div>
            `;
            
            list.appendChild(item);
        });
    }
    
    // content_type → 界面文案；未知值降级为原文，空值返回空串
    contentTypeLabel(contentType) {
        const normalized = (contentType || '').trim().toLowerCase();
        if (!normalized) return '';
        return CONTENT_TYPE_LABELS[normalized] || normalized;
    }
    
    hideSources() {
        this.elements.sourcesList.innerHTML = '';
        this.elements.sourcesCount.textContent = '0';
        this.elements.emptySources.style.display = 'none';
    }
    
    // ===== 错误显示 =====
    showError(code, message) {
        this.elements.errorSection.classList.add('active');
        this.elements.errorCode.textContent = code || 'ERROR';
        this.elements.errorMessage.textContent = message || '发生未知错误';
    }
    
    hideError() {
        this.elements.errorSection.classList.remove('active');
    }
    
    // ===== 请求失败分类处理 =====
    // 按「错误出现在链路的哪一段」分类，而不是靠消息文本里的关键词去猜。
    // 链路：前端 → 后端 → 上游模型服务。四类必须互不混淆：
    //   TIMEOUT        前端主动超时（AbortController）
    //   NETWORK_ERROR  前端连不上后端（fetch 层失败）—— 唯一真正的"网络"问题
    //   <后端错误码>    后端返回 200 但 success=false —— 业务结果，原样透传
    //   SERVER_ERROR   后端返回非 2xx —— 后端内部异常，与用户网络无关
    showRequestError(error) {
        if (!error) {
            this.showError('UNKNOWN_ERROR', '请求失败，请稍后重试。');
        } else if (error.isTimeout) {
            this.showError('TIMEOUT', '请求超时，请稍后重试。复杂问题生成耗时较长，可稍后重新提交。');
        } else if (error.isNetworkError) {
            // fetch 层失败：后端未启动、连接被拒、DNS 解析失败。
            // 这是唯一应该提示"检查网络"的场景。
            this.showError('NETWORK_ERROR', '无法连接到后端服务，请确认后端已启动，并检查本机网络连接。');
        } else if (this.isUpstreamNetworkError(error)) {
            // 后端可达，但它自己连不上模型服务（异常被后端捕获后原样透传）。
            // 本质是网络问题，但不能把 Python 异常元组展示给用户 —— 只写进控制台。
            const detail = (error.data && error.data.error && error.data.error.message) || error.message || '';
            console.warn('[upstream] 后端到模型服务的连接失败，原始信息：', detail);
            // 记下时间戳：健康检查看不出这个问题，需要它把状态徽章从绿灯降下来
            this.modelUnavailableSince = Date.now();
            this.showError(
                'MODEL_UNREACHABLE',
                '连接模型服务失败，可能是网络波动或服务端网络异常，请稍后重试。'
            );
        } else if (typeof error.status === 'number' && error.status >= 400) {
            // 后端已经响应了，只是状态码不是 2xx。问题在后端内部，与用户网络无关，
            // 也不能拿后端错误码去猜某段链路是不是网络问题。
            const backendMessage = (error.data && error.data.error && error.data.error.message) || '';
            this.showError(
                error.code || `HTTP_${error.status}`,
                `后端返回 HTTP ${error.status}` +
                    (backendMessage ? `：${backendMessage}` : '，请查看后端日志。')
            );
        } else if (error.data && error.data.error) {
            // HTTP 200 + success=false：后端明确给出的业务错误，原样展示，不覆盖、不加工
            this.showError(
                error.data.error.code || 'BUSINESS_ERROR',
                error.data.error.message || '请求未被处理，请稍后重试。'
            );
        } else {
            this.showError(
                'UNKNOWN_ERROR',
                `出现未预期的错误：${this.truncateText(error.message, 120)}`
            );
        }
        
        // 失败时保留上一轮的回答，而不是把整片区域清空 ——
        // 网络抖动一次不该让用户已经看到的内容消失，错误提示另行展示。
        this.restoreLastGoodResult();
    }
    
    // 过长信息截断，避免把整段堆栈甩到界面上
    truncateText(text, max) {
        const value = String(text || '').trim();
        if (!value) return '未知错误';
        return value.length > max ? value.slice(0, max) + '…' : value;
    }
    
    // 判断是否属于"后端到模型服务的连接类故障"。
    // 只看后端的 error.code（异常类名），不看 message 文本 —— 不靠自由文本猜。
    isUpstreamNetworkError(error) {
        if (!error) return false;
        const candidates = [
            error.code,
            error.data && error.data.error && error.data.error.code
        ];
        return candidates.some(c => c && UPSTREAM_NETWORK_ERROR_CODES.has(String(c)));
    }
    
    // 最近是否发生过"后端连不上模型服务"的失败。
    // 用于把状态徽章从绿灯降下来 —— 健康检查感知不到这种情况。
    // 一旦有一次问答成功，会清掉该标记，徽章随即恢复绿灯。
    isModelServiceUnavailable() {
        if (!this.modelUnavailableSince) return false;
        return (Date.now() - this.modelUnavailableSince) < MODEL_UNAVAILABLE_WINDOW_MS;
    }
    
    // ===== 失败时恢复上一轮回答 =====
    // 若本次请求前页面上已有成功回答，则把它原样恢复，而不是留一片空白。
    // 没有可恢复内容时（首次提问就失败），保持清空。
    restoreLastGoodResult() {
        const prev = this.lastGoodResult;
        
        if (!prev || !prev.answer) {
            this.hideAnswer();
            this.hideSources();
            return;
        }
        
        this.currentAnswer = prev.answer;
        this.currentSources = prev.sources || [];
        this.currentLatency = prev.latency;
        this.currentMode = prev.mode;
        this.currentOutOfScope = prev.outOfScope;
        
        this.elements.questionDisplayContent.textContent = prev.question || '';
        this.showAnswer(prev.answer, prev.latency, prev.mode);
        this.showScopeNotice(prev.outOfScope);
        this.showSources(prev.sources || []);
    }
    
    hideAllSections() {
        this.hideLoading();
        this.hideAnswer();
        this.hideMode();
        this.hideRenderNotice();
        this.hideScopeNotice();
        this.hideSources();
        this.hideError();
    }
    
    // ===== 历史记录 =====
    addHistory({ question, answer, sources, mode, outOfScope, latency }) {
        const entry = {
            id: Date.now(),
            question: question,
            answer: answer,
            sources: sources || [],
            mode: mode || '',
            out_of_scope: outOfScope === true,
            // 统一存成分阶段对象，避免新旧格式混用
            latency: this.normalizeLatency(latency),
            timestamp: new Date().toLocaleString('zh-CN')
        };
        
        this.history.unshift(entry);
        
        if (this.history.length > this.maxHistory) {
            this.history = this.history.slice(0, this.maxHistory);
        }
        
        this.saveHistoryToStorage();
        this.updateHistoryUI();
    }
    
    updateHistoryUI() {
        const list = this.elements.historyList;
        const count = this.elements.historyCount;
        
        list.innerHTML = '';
        count.textContent = `共 ${this.history.length} 条`;
        
        if (this.history.length === 0) {
            list.innerHTML = '<div class="empty-history">暂无问答记录</div>';
            return;
        }
        
        this.history.forEach((entry) => {
            const item = document.createElement('div');
            item.className = 'history-item';
            
            const mode = (entry.mode || '').trim().toLowerCase();
            const modeLabel = MODE_LABELS[mode] || '';
            const tags = `
                ${modeLabel ? `<span class="history-mode mode-${mode}">${modeLabel}</span>` : ''}
                ${entry.out_of_scope === true ? '<span class="history-scope">范围外</span>' : ''}
            `;
            
            item.innerHTML = `
                <span class="history-q">${this.escapeHtml(entry.question)}</span>
                <span class="history-tags">${tags}</span>
                <span class="history-time">${this.escapeHtml(entry.timestamp || '')}</span>
            `;
            
            // 点击历史记录：恢复完整内容
            item.addEventListener('click', () => {
                this.restoreHistoryEntry(entry);
            });
            
            list.appendChild(item);
        });
    }
    
    // 恢复历史记录的完整内容（回答、来源、模式、范围外状态、耗时）
    restoreHistoryEntry(entry) {
        const mode = entry.mode || '';
        const outOfScope = entry.out_of_scope === true;
        const sources = Array.isArray(entry.sources) ? entry.sources : [];
        // 兼容旧记录里是数字的 latency
        const latency = this.normalizeLatency(entry.latency);
        const answer = entry.answer || '';
        
        this.elements.questionInput.value = entry.question;
        this.elements.questionInput.focus();
        this.autoResizeTextarea();
        
        this.currentAnswer = answer;
        this.currentSources = sources;
        this.currentLatency = latency;
        this.currentMode = mode;
        this.currentOutOfScope = outOfScope;
        
        this.hideAllSections();
        this.elements.questionDisplayContent.textContent = entry.question || '';
        // 恢复时同样遵循"范围外不是系统错误"
        this.showAnswer(answer, latency, mode);
        this.showScopeNotice(outOfScope);
        this.showSources(sources);
        this.hideError();
        
        this.elements.answerSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    
    clearHistory() {
        if (this.history.length === 0) return;
        if (confirm('确定要清空所有历史记录吗？')) {
            this.history = [];
            this.saveHistoryToStorage();
            this.updateHistoryUI();
        }
    }
    
    saveHistoryToStorage() {
        try {
            localStorage.setItem('chatHistory', JSON.stringify(this.history));
        } catch (e) {}
    }
    
    loadHistoryFromStorage() {
        try {
            const data = localStorage.getItem('chatHistory');
            if (!data) return;
            
            const parsed = JSON.parse(data);
            if (!Array.isArray(parsed)) {
                this.history = [];
                return;
            }
            
            // 迁移旧版记录：旧数据里 latency 可能是单个数字，
            // 且没有 mode / out_of_scope 字段，直接使用会导致页面渲染异常。
            this.history = parsed.slice(0, this.maxHistory).map((raw) => {
                const entry = (raw && typeof raw === 'object') ? raw : {};
                return {
                    id: entry.id || Date.now(),
                    question: entry.question || '',
                    answer: entry.answer || '',
                    sources: Array.isArray(entry.sources) ? entry.sources : [],
                    mode: entry.mode || '',
                    out_of_scope: entry.out_of_scope === true,
                    latency: this.normalizeLatency(entry.latency),
                    timestamp: entry.timestamp || ''
                };
            });
        } catch (e) {
            console.warn('历史记录读取失败，已重置:', e);
            this.history = [];
        }
    }
    
    // ===== 工具方法 =====
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const app = new ChatApp();
    window.app = app;
});