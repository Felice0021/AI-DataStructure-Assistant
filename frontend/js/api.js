// frontend/js/api.js

class ApiClient {
    constructor(config) {
        this.baseUrl = config.API_BASE_URL;
        this.endpoints = config.ENDPOINTS;
        this.timeout = config.TIMEOUT;
        this.useMock = config.USE_MOCK;
    }
    
    // 通用请求方法
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);
        
        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });
            
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const apiError = new Error(
                    (errorData.error && errorData.error.message) || `HTTP ${response.status}`
                );
                apiError.code = (errorData.error && errorData.error.code) || `HTTP_${response.status}`;
                apiError.status = response.status;
                apiError.statusText = response.statusText;
                apiError.data = errorData;
                throw apiError;
            }
            
            return await response.json();
        } catch (error) {
            clearTimeout(timeoutId);
            
            if (error.name === 'AbortError') {
                // 超出 CONFIG.TIMEOUT 后由 AbortController 中断
                const timeoutError = new Error('请求超时，请稍后重试');
                timeoutError.code = 'TIMEOUT';
                timeoutError.status = 408;
                timeoutError.statusText = 'Request Timeout';
                timeoutError.isTimeout = true;
                timeoutError.data = {
                    error: {
                        code: 'TIMEOUT',
                        message: '请求超时，请稍后重试'
                    }
                };
                throw timeoutError;
            }
            
            if (!error.status) {
                // fetch 层失败：DNS 解析失败 / 连接被拒 / 断网
                const networkError = new Error(error.message || '网络连接失败');
                networkError.code = 'NETWORK_ERROR';
                networkError.isNetworkError = true;
                throw networkError;
            }
            
            throw error;
        }
    }
    
    // 健康检查 - 带超时控制
    async healthCheck() {
        if (this.useMock) {
            // mock 模式立即返回
            return {
                status: 'ok',
                rag_ready: true,
                version: '1.0.0',
                timestamp: new Date().toISOString()
            };
        }
        
        // 健康检查使用较短的超时时间（3秒）
        const HEALTH_CHECK_TIMEOUT = 3000;
        
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT);
            
            const response = await fetch(`${this.baseUrl}${this.endpoints.HEALTH}`, {
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                return {
                    status: 'error',
                    rag_ready: false,
                    error: `HTTP ${response.status}`,
                    timestamp: new Date().toISOString()
                };
            }
            
            const data = await response.json();
            return {
                ...data,
                timestamp: new Date().toISOString()
            };
            
        } catch (error) {
            // 超时或网络错误
            let errorMsg = '连接失败';
            if (error.name === 'AbortError') {
                errorMsg = '连接超时';
            } else if (error.message) {
                errorMsg = error.message;
            }
            
            return {
                status: 'unreachable',
                rag_ready: false,
                error: errorMsg,
                timestamp: new Date().toISOString()
            };
        }
    }
    
    // 问答接口
    // 后端 /api/v1/ask 返回结构：
    //   { request_id, success, error,
    //     data: { answer, sources[], mode, out_of_scope, latency_ms } }
    //   sources[]  : { chunk_id, chapter, section, source_file, page, content_type }
    //   mode       : 'qa' | 'exercise' | 'code'
    //   latency_ms : { retrieval, rerank, generation, total }
    // top_k 为可选参数，不传时由后端按自身配置决定，因此这里默认不发送。
    async ask(question, topK = null) {
        if (this.useMock) {
            return mockAsk(question, topK ?? 5);
        }

        const payload = {
            question: question
        };

        if (topK !== null && topK !== undefined) {
            payload.top_k = topK;
        }
        
        return this.request(this.endpoints.ASK, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    }
    
    setMockMode(enabled) {
        this.useMock = enabled;
    }
}

const apiClient = new ApiClient(CONFIG);
window.apiClient = apiClient;