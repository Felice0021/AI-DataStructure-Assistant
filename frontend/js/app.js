// frontend/js/app.js

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
            if (result.status === 'unreachable' || result.rag_ready === false) {
                // 连接失败或 RAG 不可用
                if (result.error === '连接超时') {
                    this.setStatus('timeout', '⏰ 连接超时', '请检查后端服务是否启动');
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
                this.setStatus('connected', '🟢 已连接', 'RAG 服务就绪');
            } else {
                this.setStatus('degraded', '🟠 服务异常', 'RAG 服务不可用');
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
    
    // ===== Markdown 渲染（使用 marked + DOMPurify） =====
    renderMarkdown(text) {
        if (!text) return '';
        
        try {
            // 使用 marked 解析 Markdown
            const rawHtml = marked.parse(text, {
                breaks: true,
                gfm: true,
                headerIds: false,
                mangle: false
            });
            
            // 使用 DOMPurify 清洗 HTML
            const cleanHtml = DOMPurify.sanitize(rawHtml, {
                ADD_TAGS: ['math'],
                ADD_ATTR: ['xmlns', 'display', 'inline'],
                FORBID_TAGS: ['script', 'style'],
                FORBID_ATTR: ['onerror', 'onload', 'onclick']
            });
            
            return cleanHtml;
        } catch (error) {
            console.warn('Markdown 渲染失败，使用纯文本:', error);
            return this.escapeHtml(text);
        }
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
        
        // 清空旧回答、来源、错误
        this.hideAllSections();
        this.currentAnswer = null;
        this.currentSources = null;
        this.currentLatency = null;
        
        // 显示加载状态
        this.showLoading('正在检索知识库并生成回答...');
        
        // 禁用输入
        this.isLoading = true;
        this.elements.submitBtn.disabled = true;
        this.elements.questionInput.disabled = true;
        
        const startTime = performance.now();
        
        try {
            const topK = CONFIG.DEFAULT_TOP_K;
            const response = await apiClient.ask(question, topK);
            const endTime = performance.now();
            const elapsed = Math.round(endTime - startTime);
            
            this.hideLoading();
            this.handleResponse(response, question, elapsed);
            
        } catch (error) {
            this.hideLoading();
            
            // 检查是否是后端返回的标准错误格式
            if (error.data && error.data.error) {
                const backendError = error.data.error;
                let code = backendError.code || 'UNKNOWN_ERROR';
                let message = backendError.message || '服务异常';
                
                // 网络相关错误 → 显示友好提示
                const networkKeywords = [
                    'connection', 'connect', 'network', 'dns', 
                    'failed to resolve', 'getaddrinfo', 'enotfound',
                    'econnrefused', 'timeout', 'ConnectionError',
                    'Max retries exceeded', 'HTTPSConnectionPool'
                ];
                const isNetworkError = networkKeywords.some(keyword => 
                    message.toLowerCase().includes(keyword.toLowerCase()) ||
                    code.toLowerCase().includes('connection') ||
                    code.toLowerCase().includes('network')
                );
                
                if (isNetworkError) {
                    code = 'NETWORK_ERROR';
                    message = '网络连接失败，请检查网络设置后重试';
                }
                
                this.showError(code, message);
            } else {
                // 网络层面的错误
                this.showNetworkError(error);
            }
            
            this.hideAnswer();
            this.hideSources();
            
        } finally {
            this.isLoading = false;
            this.elements.submitBtn.disabled = false;
            this.elements.questionInput.disabled = false;
            this.elements.questionInput.focus();
            this.updateConnectionStatus();
        }
    }
    
    // ===== 处理响应 =====
    handleResponse(response, question, elapsed) {
        if (response.success) {
            const data = response.data;
            let answer = data.answer || '';
            const sources = data.sources || [];
            const latency = data.latency_ms || elapsed;
            
            // 检测是否是模型调用失败的兜底话术
            const fallbackPhrases = [
                '根据当前资料无法确定',
                '无法确定',
                '没有找到相关内容',
                '抱歉，我无法回答'
            ];
            
            const isFallbackAnswer = fallbackPhrases.some(phrase => 
                answer.includes(phrase)
            );
            
            if (isFallbackAnswer) {
                // 回答保留原样，只隐藏来源
                this.showAnswer(answer, latency);  // ← 保留原回答
                this.showSources([]);              // ← 只隐藏来源
                return;
            }
            // 正常显示
            this.currentAnswer = answer;
            this.currentSources = sources;
            this.currentLatency = latency;
            
            this.showAnswer(answer, latency);
            this.showSources(sources);
            this.hideError();
            this.addHistory(question, answer, sources, latency);
            
        } else {
            const error = response.error || {};
            
            // 检查是否是网络相关错误
            const networkKeywords = [
                'connection', 'connect', 'network', 'dns',
                'failed to resolve', 'getaddrinfo', 'enotfound',
                'econnrefused', 'timeout', 'ConnectionError',
                'Max retries exceeded', 'HTTPSConnectionPool'
            ];
            const isNetworkError = networkKeywords.some(keyword =>
                (error.message || '').toLowerCase().includes(keyword.toLowerCase()) ||
                (error.code || '').toLowerCase().includes('connection') ||
                (error.code || '').toLowerCase().includes('network')
            );
            
            if (isNetworkError) {
                this.showError('NETWORK_ERROR', '网络连接失败，请检查网络设置后重试');
            } else {
                this.showError(error.code || 'UNKNOWN_ERROR', error.message || '未知错误，请稍后重试。');
            }
            
            this.hideAnswer();
            this.hideSources();
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
    showAnswer(answer, latency) {
        this.elements.answerSection.classList.add('active');
        const renderedHtml = this.renderMarkdown(answer);
        this.elements.answerContent.innerHTML = renderedHtml || '<em>（无回答内容）</em>';
        this.elements.answerLatency.textContent = latency ? `⏱ ${latency}ms` : '';
        
        // 触发 MathJax 渲染
        this.renderMath();
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
            
            const title = source.section || source.chapter || source.source_file || '未知来源';
            const chapter = source.chapter || '';
            const section = source.section || '';
            const file = source.source_file || '';
            const page = source.page ? `第${source.page}页` : '';
            const chunkId = source.chunk_id || '';
            
            item.innerHTML = `
                <span class="source-index">[${index + 1}]</span>
                <div class="source-info">
                    <div class="source-title">${this.escapeHtml(title)}</div>
                    <div class="source-meta">
                        ${chapter ? `<span>📖 ${this.escapeHtml(chapter)}</span>` : ''}
                        ${section && chapter ? `<span class="sep">·</span>` : ''}
                        ${section ? `<span>📝 ${this.escapeHtml(section)}</span>` : ''}
                        ${file && (chapter || section) ? `<span class="sep">·</span>` : ''}
                        ${file ? `<span>📄 ${this.escapeHtml(file)}</span>` : ''}
                        ${page ? `<span class="sep">·</span><span>📄 ${page}</span>` : ''}
                        ${chunkId ? `<div class="source-chunk-id">ID: ${this.escapeHtml(chunkId)}</div>` : ''}
                    </div>
                </div>
            `;
            
            list.appendChild(item);
        });
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
    
    // ===== 显示网络错误（增强版） =====
    showNetworkError(error) {
        let code = 'NETWORK_ERROR';
        let message = '网络请求失败，请检查网络连接';
        
        if (error.status === 408 || error.statusText === 'Request Timeout') {
            code = 'TIMEOUT_ERROR';
            message = '请求超时，请稍后重试';
        } else if (error.message) {
            const msg = error.message.toLowerCase();
            if (msg.includes('failed to resolve') || 
                msg.includes('getaddrinfo') || 
                msg.includes('enotfound') ||
                msg.includes('econnrefused') ||
                msg.includes('connectionerror') ||
                msg.includes('connection') ||
                msg.includes('network') ||
                msg.includes('connect') ||
                msg.includes('max retries exceeded') ||
                msg.includes('httpsconnectionpool')) {
                code = 'CONNECTION_ERROR';
                message = '网络连接失败，请检查网络设置后重试';
            } else {
                // 截断过长的错误消息
                message = error.message.length > 100 ? error.message.substring(0, 100) + '...' : error.message;
            }
        }
        
        this.showError(code, message);
        this.hideAnswer();
        this.hideSources();
    }
    
    hideAllSections() {
        this.hideLoading();
        this.hideAnswer();
        this.hideSources();
        this.hideError();
    }
    
    // ===== 历史记录 =====
    addHistory(question, answer, sources, latency) {
        const entry = {
            id: Date.now(),
            question: question,
            answer: answer,
            sources: sources || [],
            latency: latency || 0,
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
            item.innerHTML = `
                <span class="history-q">${this.escapeHtml(entry.question)}</span>
                <span class="history-time">${entry.timestamp}</span>
            `;
            
            // 点击历史记录：恢复完整内容
            item.addEventListener('click', () => {
                this.restoreHistoryEntry(entry);
            });
            
            list.appendChild(item);
        });
    }
    
    // 恢复历史记录的完整内容
    restoreHistoryEntry(entry) {
        this.elements.questionInput.value = entry.question;
        this.elements.questionInput.focus();
        this.autoResizeTextarea();
        
        this.currentAnswer = entry.answer;
        this.currentSources = entry.sources || [];
        this.currentLatency = entry.latency || 0;
        
        this.hideAllSections();
        this.showAnswer(entry.answer, entry.latency);
        this.showSources(entry.sources || []);
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
            if (data) {
                const parsed = JSON.parse(data);
                if (Array.isArray(parsed)) {
                    this.history = parsed.slice(0, this.maxHistory);
                }
            }
        } catch (e) {
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