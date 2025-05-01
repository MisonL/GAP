# app/core/key_utils.py
import httpx     # 用于发送异步 HTTP 请求（例如测试密钥有效性）
import json      # 用于处理 JSON 数据
import logging   # 用于应用程序的日志记录
from typing import Optional # 类型提示

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

# --- API 密钥测试函数 ---
async def test_api_key(api_key: str, http_client: httpx.AsyncClient) -> bool:
    """
    [异步] 测试单个 Gemini API 密钥的有效性。
    尝试调用一个轻量级的 API 端点，例如列出模型。
    使用传入的共享 httpx.AsyncClient 实例。

    Args:
        api_key: 要测试的 API 密钥。
        http_client: 用于发送请求的共享 httpx 客户端实例。

    Returns:
        如果密钥有效则返回 True，否则返回 False。
    """
    # 使用传入的共享 httpx 客户端进行异步请求
    test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}" # 使用列出模型的端点进行测试
    try:
        response = await http_client.get(test_url, timeout=10.0) # 使用共享客户端发送 GET 请求
        # 检查 HTTP 状态码是否为 200 (OK)
        if response.status_code == 200:
            # 进一步检查响应内容是否符合预期（包含 'models' 列表）
            try:
                data = response.json() # 解析 JSON 响应
                if "models" in data and isinstance(data["models"], list):
                    logger.info(f"测试 Key {api_key[:10]}... 成功。")
                    return True # Key 有效
                else:
                     logger.warning(f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但响应 JSON 格式不符合预期: {data}")
                     return False # 响应格式不正确，视为无效
            except json.JSONDecodeError:
                 logger.warning(f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但无法解析响应体为 JSON。")
                 return False # 无法解析 JSON，视为无效
        else:
            # 如果状态码不是 200，记录错误详情
            error_detail = f"状态码: {response.status_code}"
            try:
                # 尝试解析错误响应体
                error_json = response.json()
                # 提取 Google API 返回的错误消息
                error_detail += f", 错误: {error_json.get('error', {}).get('message', '未知 API 错误')}"
            except json.JSONDecodeError:
                # 如果响应体不是 JSON，记录原始文本
                error_detail += f", 响应体: {response.text}"
            logger.warning(f"测试 Key {api_key[:10]}... 失败 ({error_detail})")
            return False # Key 无效
    except httpx.TimeoutException:
        # 处理请求超时的情况
        logger.warning(f"测试 Key {api_key[:10]}... 请求超时。")
        return False # 超时视为无效（或网络问题）
    except httpx.RequestError as e:
        # 处理网络连接错误等请求相关错误
        logger.warning(f"测试 Key {api_key[:10]}... 时发生网络请求错误: {e}")
        return False # 网络错误视为无效（或网络问题）
    except Exception as e:
        # 捕获其他所有未预料到的异常
        logger.error(f"测试 Key {api_key[:10]}... 时发生未知错误: {e}", exc_info=True)
        return False # 未知错误视为无效

# 注意：原 utils.py 中没有明确的 refresh_key_scores 函数，
# APIKeyManager._update_key_scores 是内部方法，不适合移到这里。
# 如果有其他与 Key 测试/评分相关的 *独立* 辅助函数，也应移到此处。