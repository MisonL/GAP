// API 路径常量
export const API_ENDPOINTS = {
    BASE_V1: '/api/v1',
    BASE_MANAGE: '/api/manage',
    BASE_V2: '/api/v2',

    KEYS: {
        DATA: '/api/manage/keys/data',
        ADD: '/api/manage/keys/add',
        UPDATE: '/api/manage/keys/update', // 注意：此路径需要动态拼接 keyString
        DELETE: '/api/manage/keys/delete', // 注意：此路径需要动态拼接 keyString
    },
    CONTEXT: {
        DATA: '/api/manage/context/data',
        UPDATE_TTL: '/api/manage/context/update_ttl',
        DELETE: '/api/manage/context/delete',
    },
};