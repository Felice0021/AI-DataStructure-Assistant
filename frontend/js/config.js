// frontend/js/config.js

const CONFIG = {
    // API 基础地址
    API_BASE_URL: 'http://localhost:8000',
    
    // API 端点
    ENDPOINTS: {
        ASK: '/api/v1/ask',
        HEALTH: '/api/v1/health'
    },
    
    // 默认 top_k 值（统一为 3）
    DEFAULT_TOP_K: 3,
    
    // 请求超时时间（毫秒）
    TIMEOUT: 30000,
    
    // 是否使用 mock 数据
    USE_MOCK: false  // 保持 false，使用真实后端
};