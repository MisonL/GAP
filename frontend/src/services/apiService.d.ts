// app/frontend/src/services/apiService.d.ts
declare module '@/services/apiService' {
  /**
   * 登录
   * @param {object} formData - 登录凭据
   * @returns {Promise<object>} 包含 token 的 Promise
   */
  export function login(formData: any): Promise<any>;

  /**
   * 验证 token
   * @param {string} token - 要验证的 token 字符串
   * @returns {Promise<object>} 包含验证结果的 Promise
   */
  export function verifyToken(token: string): Promise<any>;

  /**
   * 添加新的 API Key
   * @param {object} payload - 包含 API Key 数据的对象
   * @param {string} [payload.key_string] - API Key 字符串（添加时可选）
   * @param {boolean} [payload.is_active] - 是否激活
   * @param {string} [payload.description] - 描述信息
   * @param {string|null} [payload.expires_at] - 过期时间
   * @param {boolean} [payload.enable_context_completion] - 是否启用上下文补全
   * @returns {Promise<object>} 包含操作结果的 Promise
   */
  export function addKey(payload: any): Promise<any>;
  
  /**
   * 更新 API Key
   * @param {string} keyString - 要更新的 API Key 字符串
   * @param {object} payload - 包含更新数据的对象
   * @param {boolean} [payload.is_active] - 是否激活
   * @param {string} [payload.description] - 描述信息
   * @param {string|null} [payload.expires_at] - 过期时间
   * @param {boolean} [payload.enable_context_completion] - 是否启用上下文补全
   * @returns {Promise<object>} 包含操作结果的 Promise
   */
  export function updateKey(keyString: string, payload: any): Promise<any>;

  /**
   * 删除 API Key
   * @param {string} keyString - 要删除的 API Key 字符串
   * @returns {Promise<object>} 包含操作结果的 Promise
   */
  export function deleteKey(keyString: string): Promise<any>;

  /**
   * 获取上下文数据
   * @returns {Promise<object>} 包含上下文数据的 Promise
   */
  export function getContextData(): Promise<any>;

  /**
   * 更新上下文 TTL
   * @param {object} ttlData - 包含 TTL 数据的对象
   * @returns {Promise<object>} 包含操作结果的 Promise
   */
  export function updateContextTTL(ttlData: any): Promise<any>;

  /**
   * 删除上下文
   * @param {string} contextId - 要删除的上下文 ID
   * @returns {Promise<object>} 包含操作结果的 Promise
   */
  export function deleteContext(contextId: string): Promise<any>;
}