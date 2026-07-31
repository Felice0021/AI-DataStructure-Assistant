// frontend/js/app.js

class ChatApp {
    constructor() {
        this.elements = {
            questionInput: document.getElementById('questionInput'),
            submitBtn: document.getElementById('submitBtn'),
            statusBar: document.getElementById('statusBar'),
            mockBadge: document.getElementById('mockBadge'),
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
        
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadHistoryFromStorage();
        this.updateStatusBar();
        this.updateHistoryUI();
        this.focusInput();
        setTimeout(() => this.updateConnectionStatus(), 500);
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
    
    async updateConnectionStatus() {
        try {
            const response = await apiClient.healthCheck();
            const isConnected = response.status === 'ok' || response.status === 'healthy';
            this.elements.mockBadge.textContent = isConnected ? '🟢 已连接' : '🔴 未连接';
            this.elements.mockBadge.className = isConnected ? 'online-badge' : 'mock-badge';
            return isConnected;
        } catch (error) {
            this.elements.mockBadge.textContent = '🔴 未连接';
            this.elements.mockBadge.className = 'mock-badge';
            return false;
        }
    }
    
    // ===== Markdown 渲染（关键修复：处理反斜杠） =====
    renderMarkdown(text) {
        if (!text) return '';
        
        // 关键：将 \ 替换为 \\，这样在 HTML 中显示为 \
        let html = text.replace(/\\/g, '\\\\');
        
        // 1. 代码块
        html = html.replace(/```([\s\S]*?)```/g, (match, code) => {
            return `<pre><code>${this.escapeHtml(code.trim())}</code></pre>`;
        });
        
        // 2. 行内代码
        html = html.replace(/`([^`]+)`/g, (match, code) => {
            return `<code>${this.escapeHtml(code)}</code>`;
        });
        
        // 3. 粗体
        html = html.replace(/\*\*([^*]+)\*\*/g, (match, content) => {
            return `<strong>${content}</strong>`;
        });
        
        // 4. 斜体（避免匹配到公式中的 *）
        html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, (match, content) => {
            if (match.includes('$') || match.includes('\\')) {
                return match;
            }
            return `<em>${content}</em>`;
        });
        
        // 5. 列表
        html = html.replace(/^[-*]\s+(.+)$/gm, (match, content) => {
            return `<li>${content}</li>`;
        });
        html = html.replace(/(<li>.*?<\/li>\s*)+/g, (match) => {
            return `<ul>${match}</ul>`;
        });
        
        // 6. 换行
        html = html.replace(/\n/g, '<br />');
        html = html.replace(/(<br \/>\s*){2,}/g, '<br /><br />');
        
        return html;
    }
    
    async handleSubmit() {
        const question = this.elements.questionInput.value.trim();
        
        if (!question) {
            this.showError('EMPTY_QUESTION', '请输入您的问题后再提交。');
            return;
        }
        
        if (this.isLoading) {
            return;
        }
        
        this.hideAllSections();
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
            
            this.showAnswer(answer, latency);
            this.showSources(sources);
            this.hideError();
            this.addHistory(question, answer, sources, latency);
            
        } else {
            const error = response.error || {};
            this.showError(error.code || 'UNKNOWN_ERROR', error.message || '未知错误，请稍后重试。');
            this.hideAnswer();
            this.hideSources();
        }
    }
    
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
    
    showAnswer(answer, latency) {
        this.elements.answerSection.classList.add('active');
        const renderedHtml = this.renderMarkdown(answer);
        this.elements.answerContent.innerHTML = renderedHtml || '<em>（无回答内容）</em>';
        this.elements.answerLatency.textContent = latency ? `⏱ ${latency}ms` : '';
        
        // 触发 MathJax 渲染
        this.renderMath();
    }
    
    renderMath() {
        const element = this.elements.answerContent;
        
        if (window.MathJax && window.MathJax.typesetPromise) {
            window.MathJax.typesetPromise([element])
                .catch((err) => console.warn('MathJax 渲染失败:', err));
        } else if (window.MathJax && window.MathJax.Hub) {
            window.MathJax.Hub.Queue(['Typeset', window.MathJax.Hub, element]);
        } else {
            // 等待 MathJax 加载
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
            
            item.addEventListener('click', () => {
                this.elements.questionInput.value = entry.question;
                this.elements.questionInput.focus();
                this.autoResizeTextarea();
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