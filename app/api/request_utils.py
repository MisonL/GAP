# -*- coding: utf-8 -*-
"""
API 请求处理相关的辅助函数。
"""
import pytz
import json
import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any
from fastapi import Request
# 导入配置以获取默认值和模型限制
from .. import config as app_config

logger = logging.getLogger('my_logger')

def get_client_ip(request: Request) -> str:
    """
    从 FastAPI Request 对象中获取客户端 IP 地址。
    优先使用 X-Forwarded-For Header。
    """
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        # X-Forwarded-For 可能包含多个 IP，取第一个
        client_ip = x_forwarded_for.split(',')[0].strip()
    else:
        # 回退到 request.client.host
        client_ip = request.client.host if request.client else "unknown_ip" # 如果 client 不存在，则为 "unknown_ip"
    return client_ip

def get_current_timestamps() -> Tuple[str, str]:
    """
    获取当前的 CST 时间字符串和 PT 日期字符串。

    Returns:
        元组[str, str]: (cst_time_str, today_date_str_pt)
                         例如 ('2024-01-01 10:00:00 CST', '2023-12-31')
    """
    # 中国标准时间 (CST)
    cst_tz = pytz.timezone('Asia/Shanghai') # 设置时区为亚洲/上海
    cst_now = datetime.now(cst_tz)
    cst_time_str = cst_now.strftime('%Y-%m-%d %H:%M:%S %Z')

    # 太平洋时间 (PT) 日期 (用于 IP 统计)
    pt_tz = pytz.timezone('America/Los_Angeles') # 设置时区为美国/洛杉矶
    today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d')

    return cst_time_str, today_date_str_pt

# --- Token 估算与上下文截断 ---

def estimate_token_count(contents: List[Dict[str, Any]]) -> int:
    """
    估算 Gemini contents 列表的 Token 数量。
    使用简单的字符数估算方法 (1 个 token 大约等于 4 个字符)。
    """
    if not contents:
        return 0
    try:
        # 计算 JSON 序列化后的字符数 (ensure_ascii=False 保证中文字符正确计数)
        char_count = len(json.dumps(contents, ensure_ascii=False))
        # 除以 4 作为 Token 估算值
        return char_count // 4
    except TypeError as e:
        logger.error(f"序列化 contents 进行 Token 估算时出错: {e}", exc_info=True)
        return 0 # 如果序列化失败则返回 0

def truncate_context(
    contents: List[Dict[str, Any]],
    model_name: str
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    根据模型限制截断对话历史 (contents)。
    从开头成对移除消息，直到满足 Token 限制。

    Args:
        contents: 完整的对话历史列表 (Gemini 格式)。
        model_name: 当前请求使用的模型名称。

    Returns:
        元组[List[Dict[str, Any]], bool]:
            - 截断后的对话历史列表。
            - 一个布尔值，指示截断后是否仍然超限（True 表示超限，False 表示未超限或无需截断）。
              如果为 True，调用者不应保存此上下文。
    """
    if not contents:
        return [], False

    # 从配置中获取默认最大上下文 Token 数和安全边际
    # 使用 getattr 安全地访问配置项，避免因配置项不存在而报错
    default_max_tokens = getattr(app_config, 'DEFAULT_MAX_CONTEXT_TOKENS', 30000) # 默认上下文 Token 上限
    safety_margin = getattr(app_config, 'CONTEXT_TOKEN_SAFETY_MARGIN', 200) # Token 安全边际

    # 1. 获取模型的输入 Token 限制 (input_token_limit)
    # model_limits 应该从 config 模块加载，确保它在应用启动时已加载
    model_limits = getattr(app_config, 'MODEL_LIMITS', {}) # 获取已加载的模型限制字典
    limit_info = model_limits.get(model_name)
    max_tokens = default_max_tokens
    if limit_info and isinstance(limit_info, dict) and limit_info.get("input_token_limit"):
        try:
            limit_value = limit_info["input_token_limit"]
            if limit_value is not None: # 确保值不是 None (JSON 中的 null)
                 max_tokens = int(limit_value)
            else:
                 logger.warning(f"模型 '{model_name}' 的 input_token_limit 值为 null，使用默认值 {default_max_tokens}")
        except (ValueError, TypeError):
             logger.warning(f"模型 '{model_name}' 的 input_token_limit 值无效 ('{limit_info.get('input_token_limit')}')，使用默认值 {default_max_tokens}")
    else:
        logger.warning(f"模型 '{model_name}' 或其 input_token_limit 未在 model_limits.json 中定义，使用默认值 {default_max_tokens}")

    truncation_threshold = max(0, max_tokens - safety_margin) # 计算截断阈值，确保不为负数

    # 2. 估算当前上下文的 Token 数量
    estimated_tokens = estimate_token_count(contents)

    # 3. 判断是否需要截断
    if estimated_tokens > truncation_threshold:
        logger.info(f"上下文估算 Token ({estimated_tokens}) 超出阈值 ({truncation_threshold} for model {model_name})，开始截断...")
        # 创建上下文列表的副本进行修改，避免影响原始列表
        truncated_contents = list(contents)
        # 循环截断，直到 Token 数量满足阈值或无法再截断
        while estimate_token_count(truncated_contents) > truncation_threshold:
            # 检查是否至少有两条消息可以成对移除
            if len(truncated_contents) >= 2:
                # 从列表开头移除两个元素 (通常是 user 和 model 的消息对)
                removed_first = truncated_contents.pop(0)
                removed_second = truncated_contents.pop(0)
                logger.debug(f"移除旧消息对: roles={removed_first.get('role')}, {removed_second.get('role')}")
            elif len(truncated_contents) == 1:
                # 只剩下一条消息，但仍然超过 Token 限制
                logger.warning("截断过程中只剩一条消息，但其 Token 数量仍然超过阈值。")
                break # 停止循环，将在下面检查最终状态
            else: # truncated_contents 列表已为空
                break # 无法再截断，跳出循环

        final_estimated_tokens = estimate_token_count(truncated_contents)

        # 检查截断后的最终 Token 数量
        if final_estimated_tokens > truncation_threshold:
             # 即使经过截断（可能只剩下一条消息），最终 Token 数量仍然超过阈值
             logger.error(f"截断后上下文估算 Token ({final_estimated_tokens}) 仍然超过阈值 ({truncation_threshold})。本次交互的上下文不应被保存。")
             # 返回截断后的结果，并标记为超限状态
             return truncated_contents, True
        else:
            logger.info(f"上下文截断完成，剩余消息数: {len(truncated_contents)}, 最终估算 Token: {final_estimated_tokens}")
            return truncated_contents, False # 截断成功，并且最终 Token 未超限
    else:
        # Token 未超限，无需截断
        return contents, False # 返回原始列表，标记为未超限