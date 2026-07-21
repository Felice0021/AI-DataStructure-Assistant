// frontend/js/app.js

class ChatApp {
    constructor() {
        // DOM 元素引用
        this.elements = {
            // 输入
            questionInput: document.getElementById('questionInput'),
            submitBtn: document.getElementById('submitBtn'),
            
            // 状态
            statusBar: document.getElementById('statusBar'),
            mockBadge: document.getElementById('mockBadge'),
            
            // 加载
            loadingSection: document.getElementById('loadingSection'),
            loadingText: document.getElementById('loadingText'),
            loadingTime: document.getElementById('loadingTime'),
            
            // 回答
            answerSection: document.getElementById('answerSection'),
            answerContent: document.getElementById('answerContent'),
            answerLatency: document.getElementById('answerLatency'),
            
            // 来源
            sourcesList: document.getElementById('sourcesList'),
            sourcesCount: document.getElementById('sourcesCount'),
            emptySources: document.getElementById('emptySources'),
            
            // 错误
            errorSection: document.getElementById('errorSection'),
            errorCode: document.getElementById('errorCode'),
            errorMessage: document.getElementById('errorMessage'),
            
            // 历史
            historyList: document.getElementById('historyList'),
            historyCount: document.getElementById('historyCount'),
            clearHistoryBtn: document.getElementById('clearHistoryBtn')
        };
        
        // 历史记录
        this.history = [];
        this.maxHistory = 50;
        
        // 是否正在请求
        this.isLoading = false;
        
        // 初始化
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadHistoryFromStorage();
        this.updateStatusBar();
        this.updateHistoryUI();
        this.focusInput();
    }
    
    bindEvents() {
        // 提交按钮
        this.elements.submitBtn.addEventListener('click', () => {
            this.handleSubmit();
        });
        
        // Enter 键提交（Ctrl+Enter 换行）
        this.elements.questionInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.handleSubmit();
            }
        });
        
        // 清空历史
        this.elements.clearHistoryBtn.addEventListener('click', () => {
            this.clearHistory();
        });
        
        // 输入框自动调整高度
        this.elements.questionInput.addEventListener('input', () => {
            this.autoResizeTextarea();
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
    
    updateStatusBar() {
        const isMock = CONFIG.USE_MOCK;
        this.elements.mockBadge.textContent = isMock ? '🔧 Mock 模式' : '🔗 已连接';
        this.elements.mockBadge.className = isMock ? 'mock-badge' : 'online-badge';
    }
    
    async handleSubmit() {
        const question = this.elements.questionInput.value.trim();
        
        // 验证
        if (!question) {
            this.showError('EMPTY_QUESTION', '请输入您的问题后再提交。');
            return;
        }
        
        if (this.isLoading) {
            return;
        }
        
        // 清空之前的显示
        this.hideAllSections();
        
        // 显示加载状态
        this.showLoading('正在检索知识库并生成回答...');
        
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
            
            // 处理响应
            this.handleResponse(response, question, elapsed);
            
        } catch (error) {
            this.hideLoading();
            this.showNetworkError(error);
        } finally {
            this.isLoading = false;
            this.elements.submitBtn.disabled = false;
            this.elements.questionInput.disabled = false;
            this.elements.questionInput.focus();
        }
    }
    
    handleResponse(response, question, elapsed) {
        if (response.success) {
            const data = response.data;
            const answer = data.answer || '';
            const sources = data.sources || [];
            const latency = data.latency_ms || elapsed;
            
            // 显示回答
            this.showAnswer(answer, latency);
            
            // 显示来源
            this.showSources(sources);
            
            // 隐藏错误
            this.hideError();
            
            // 添加历史记录
            this.addHistory(question, answer, sources, latency);
            
        } else {
            // 业务错误
            const error = response.error || {};
            this.showError(error.code || 'UNKNOWN_ERROR', error.message || '未知错误，请稍后重试。');
            this.hideAnswer();
            this.hideSources();
        }
    }
    
    // ===== 显示/隐藏方法 =====
    
    showLoading(text) {
        this.elements.loadingSection.classList.add('active');
        this.elements.loadingText.textContent = text || '正在思考...';
        this.elements.loadingTime.textContent = '';
        
        // 启动计时器
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
    
    showAnswer(answer, latency) {
        this.elements.answerSection.classList.add('active');
        this.elements.answerContent.textContent = answer || '（无回答内容）';
        this.elements.answerLatency.textContent = latency ? `⏱ ${latency}ms` : '';
    }
    
    hideAnswer() {
        this.elements.answerSection.classList.remove('active');
    }
    
    showSources(sources) {
        const list = this.elements.sourcesList;
        const countEl = this.elements.sourcesCount;
        const emptyEl = this.elements.emptySources;
        
        // 清空列表
        list.innerHTML = '';
        
        if (!sources || sources.length === 0) {
            // 来源为空
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
    
    showError(code, message) {
        this.elements.errorSection.classList.add('active');
        this.elements.errorCode.textContent = code || 'ERROR';
        this.elements.errorMessage.textContent = message || '发生未知错误';
    }
    
    hideError() {
        this.elements.errorSection.classList.remove('active');
    }
    
    showNetworkError(error) {
        let message = '网络请求失败，请检查网络连接';
        if (error.status === 408 || error.statusText === 'Request Timeout') {
            message = '请求超时，请稍后重试';
        } else if (error.message) {
            message = error.message;
        }
        this.showError('NETWORK_ERROR', message);
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
        
        // 限制数量
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
        
        this.history.forEach((entry, index) => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.innerHTML = `
                <span class="history-q">${this.escapeHtml(entry.question)}</span>
                <span class="history-time">${entry.timestamp}</span>
            `;
            
            // 点击历史记录，填充到输入框并提交
            item.addEventListener('click', () => {
                this.elements.questionInput.value = entry.question;
                this.elements.questionInput.focus();
                this.autoResizeTextarea();
                // 可选：自动提交
                // this.handleSubmit();
            });
            
            list.appendChild(item);
        });
    }
    
    clearHistory() {
        if (this.history.length === 0) return;
        if (confirm('确定要清空所有历史记录吗？')) {
            this.history = [];
            this.saveHistoryToStorage();
            this.updateHistoryUI();
        }
    }
    
    // ===== 本地存储 =====
    
    saveHistoryToStorage() {
        try {
            localStorage.setItem('chatHistory', JSON.stringify(this.history));
        } catch (e) {
            // 存储失败忽略
        }
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

// ===== 页面加载完成后初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    const app = new ChatApp();
    // 暴露到全局方便调试
    window.app = app;
});