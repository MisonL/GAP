# -*- coding: utf-8 -*-
"""
API Key 相关的工具函数。
"""
import json  # 导入 JSON 库，用于处理 JSON 数据
import logging  # 导入日志库
import secrets  # 导入 secrets 模块用于生成安全的随机字符串
import string  # 导入 string 模块用于获取字符集

import httpx  # 导入 HTTP 客户端库，用于发送异步 HTTP 请求

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")


# --- API 密钥生成函数 ---
def generate_random_key(length: int = 40) -> str:
    """
    生成一个指定长度的安全随机字符串，可用作 API Key。
    默认长度为 40。

    Args:
        length (int): 生成的 Key 的长度。

    Returns:
        str: 生成的随机 Key 字符串。
    """
    # 定义包含字母和数字的字符集
    alphabet = string.ascii_letters + string.digits
    # 使用 secrets.choice 从字符集中随机选择字符，生成指定长度的字符串
    random_key = "".join(secrets.choice(alphabet) for _ in range(length))
    # 可以选择添加前缀，例如 'sk-'
    # random_key = "sk-" + random_key
    logger.debug(f"生成了新的随机 Key (长度: {length})")
    return random_key


# --- API 密钥测试函数 ---
async def test_api_key(api_key: str, http_client: httpx.AsyncClient) -> bool:
    """
    异步测试单个 Gemini API 密钥的有效性。
    通过尝试调用一个轻量级的、通常不需要特殊权限的 API 端点（例如列出可用模型）
    来验证密钥是否能够成功认证并与 Gemini API 通信。
    使用传入的共享 httpx.AsyncClient 实例以提高效率。

    Args:
        api_key (str): 需要测试的 Gemini API 密钥字符串。
        http_client (httpx.AsyncClient): 用于发送 HTTP 请求的共享异步客户端实例。

    Returns:
        bool: 如果 API 密钥测试通过（能够成功调用 API 并获得预期响应），则返回 True；
              否则（包括网络错误、超时、认证失败、响应格式错误等），返回 False。
    """
    # 构建测试用的 API 端点 URL，这里使用列出模型的端点
    test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        # 使用共享的 http_client 发送异步 GET 请求，使用配置的超时时间
        from gap import config

        response = await http_client.get(test_url, timeout=config.API_TIMEOUT_KEY_TEST)

        # 检查 HTTP 响应状态码
        if response.status_code == 200:  # --- 状态码 200 OK ---
            # 状态码 200 表示请求成功，但需要进一步检查响应内容是否符合预期
            try:
                data = response.json()  # 尝试将响应体解析为 JSON
                # 检查 JSON 数据中是否包含 'models' 键，并且其值是一个列表
                if "models" in data and isinstance(data["models"], list):
                    # 如果格式符合预期，认为 Key 有效
                    logger.info(f"测试 Key {api_key[:10]}... 成功。")  # 记录成功日志
                    return True  # 返回 True
                else:
                    # 如果状态码是 200 但 JSON 格式不正确，记录警告并视为无效
                    logger.warning(
                        f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但响应 JSON 格式不符合预期: {data}"
                    )  # 记录警告日志
                    return False  # 返回 False
            except json.JSONDecodeError:  # 捕获 JSON 解析错误
                # 如果状态码是 200 但无法解析响应体，记录警告并视为无效
                logger.warning(
                    f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但无法解析响应体为 JSON。"
                )  # 记录警告日志
                return False  # 返回 False
        else:  # --- 状态码非 200 ---
            # 如果状态码不是 200，表示请求失败（例如 400, 401, 403, 429, 500 等）
            error_detail = f"状态码: {response.status_code}"  # 初始化错误详情字符串
            try:
                # 尝试解析错误响应体以获取更详细的错误信息
                error_json = response.json()
                # 提取 Google API 标准错误格式中的 message 字段
                error_detail += f", 错误: {error_json.get('error', {}).get('message', '未知 API 错误')}"
            except json.JSONDecodeError:
                # 如果响应体不是 JSON 格式，则记录原始响应文本
                error_detail += f", 响应体: {response.text}"
            # 记录测试失败的警告日志，包含错误详情
            logger.warning(f"测试 Key {api_key[:10]}... 失败 ({error_detail})")
            return False  # 返回 False 表示 Key 无效

    except httpx.TimeoutException:  # 捕获请求超时异常
        # 处理请求超时的情况
        logger.warning(f"测试 Key {api_key[:10]}... 请求超时。")  # 记录警告日志
        return False  # 超时通常意味着网络问题或 API 不可用，视为无效

    except (
        httpx.RequestError
    ) as e:  # 捕获其他 httpx 请求相关的错误 (如 DNS 解析、连接错误等)
        # 处理网络连接错误等请求相关错误
        logger.warning(
            f"测试 Key {api_key[:10]}... 时发生网络请求错误: {e}"
        )  # 记录警告日志
        return False  # 网络错误视为无效

    except Exception as e:  # 捕获其他所有未预料到的异常
        # 捕获并记录测试过程中发生的任何其他未知错误
        logger.error(
            f"测试 Key {api_key[:10]}... 时发生未知错误: {e}", exc_info=True
        )  # 记录错误日志，包含堆栈信息
        return False  # 未知错误视为无效


# --- 其他可能的 Key 相关工具函数 ---
# 例如：
# - 验证 Key 格式的函数
# - 从 Key 中提取特定信息的函数 (如果 Key 包含元数据)
# - 与 Key 评分或健康度相关的独立计算函数 (如果 _refresh_all_key_scores 逻辑复杂需要拆分)
# 目前此文件只包含 test_api_key 函数。
