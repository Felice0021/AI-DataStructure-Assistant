// frontend/js/api.js

class ApiClient {
    constructor(config) {
        this.baseUrl = config.API_BASE_URL;
        this.endpoints = config.ENDPOINTS;
        this.timeout = config.TIMEOUT;
        this.useMock = config.USE_MOCK;
        this.mockEnabled = config.USE_MOCK;
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
    
    // 健康检查
    async healthCheck() {
        if (this.useMock) {
            return { status: 'ok', version: '1.0.0' };
        }
        return this.request(this.endpoints.HEALTH);
    }
    
    // 问答接口
    async ask(question, topK = 5) {
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