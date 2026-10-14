// frontend/js/config.js

const CONFIG = {
    // API 基础地址
    API_BASE_URL: 'http://localhost:8000',
    
    // API 端点
    ENDPOINTS: {
        ASK: '/api/v1/ask',
        HEALTH: '/api/v1/health'
    },
    
    // 问答请求超时时间（毫秒）
    // 新版链路为 Query Expansion → Hybrid 检索 → Rerank → 生成，
    // 复杂问题整体耗时可能超过 30s，这里放宽到 60s，避免生成未完成就被中断。
    // 注意：健康检查使用独立的 3s 超时，见 api.js 中的 HEALTH_CHECK_TIMEOUT。
    TIMEOUT: 60000,
    
    // 是否使用 mock 数据
    USE_MOCK: false  // 保持 false，使用真实后端
};