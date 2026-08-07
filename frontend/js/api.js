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
                throw {
                    status: response.status,
                    statusText: response.statusText,
                    data: errorData
                };
            }
            
            return await response.json();
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw {
                    status: 408,
                    statusText: 'Request Timeout',
                    data: {
                        error: {
                            code: 'TIMEOUT',
                            message: '请求超时，请稍后重试'
                        }
                    }
                };
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
    async ask(question, topK = 3) {
        if (this.useMock) {
            return mockAsk(question, topK);
        }
        
        return this.request(this.endpoints.ASK, {
            method: 'POST',
            body: JSON.stringify({
                question: question,
                top_k: topK
            })
        });
    }
    
    setMockMode(enabled) {
        this.useMock = enabled;
    }
}

const apiClient = new ApiClient(CONFIG);
window.apiClient = apiClient;