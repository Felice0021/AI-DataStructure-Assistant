const CONFIG = {
    // API 基础地址 - 开发阶段使用 mock，后期替换为真实后端地址
    API_BASE_URL: 'http://localhost:8000',
    
    // API 端点
    ENDPOINTS: {
        ASK: '/api/v1/ask',
        HEALTH: '/api/v1/health'
    },
    
    // 默认 top_k 值
    DEFAULT_TOP_K: 5,
    
    // 请求超时时间（毫秒）
    TIMEOUT: 30000,
    
    // 是否使用 mock 数据（开发阶段设为 true）
    USE_MOCK: true
};

// 如果使用 mock，API_BASE_URL 可以不用真实地址
// 切换为真实后端时，将 USE_MOCK 设为 false，并修改 API_BASE_URL