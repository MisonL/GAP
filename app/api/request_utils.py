# -*- coding: utf-8 -*-
"""
API 请求处理相关的辅助函数。
"""
import pytz
import json
import logging
import time
from datetime import datetime
from collections import Counter
from collections import defaultdict
from typing import Tuple, List, Dict, Any, Optional
from fastapi import Request
# 导入配置以获取默认值和模型限制
from .. import config as app_config
from ..core.tracking import ip_daily_input_token_counts, ip_input_token_counts_lock
from ..core.tracking import usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS

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



# --- 速率限制检查与计数更新 ---

def check_rate_limits_and_update_counts(
    api_key: str,
    model_name: str,
    limits: Optional[Dict[str, Any]]
) -> bool:
    """
    检查给定 API Key 和模型的速率限制 (RPD, TPD_Input, RPM, TPM_Input)。
    如果未达到限制，则更新 RPM 和 RPD 计数，并返回 True。
    如果达到任何限制，则记录警告并返回 False。

    Args:
        api_key: 当前尝试使用的 API Key。
        model_name: 请求的模型名称。
        limits: 从配置中获取的该模型的限制字典。

    Returns:
        bool: 如果可以继续进行 API 调用则返回 True，否则返回 False。
    """
    if not limits:
        logger.warning(f"模型 '{model_name}' 不在 model_limits.json 中，跳过本地速率限制检查。")
        return True # 没有限制信息，允许调用

    now = time.time()
    perform_api_call = True

    with usage_lock:
        # 使用 setdefault 确保 key 和 model 的条目存在
        key_usage = usage_data.setdefault(api_key, defaultdict(lambda: defaultdict(int)))[model_name]

        # 检查 RPD
        rpd_limit = limits.get("rpd")
        if rpd_limit is not None and key_usage.get("rpd_count", 0) >= rpd_limit:
            logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPD 达到限制 ({key_usage.get('rpd_count', 0)}/{rpd_limit})。跳过此 Key。")
            perform_api_call = False

        # 检查 TPD_Input (仅检查，不在此处增加，因为 token 数未知)
        if perform_api_call:
            tpd_input_limit = limits.get("tpd_input")
            if tpd_input_limit is not None and key_usage.get("tpd_input_count", 0) >= tpd_input_limit:
                logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPD_Input 达到限制 ({key_usage.get('tpd_input_count', 0)}/{tpd_input_limit})。跳过此 Key。")
                perform_api_call = False

        # 检查 RPM
        if perform_api_call:
            rpm_limit = limits.get("rpm")
            if rpm_limit is not None:
                if now - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS:
                    if key_usage.get("rpm_count", 0) >= rpm_limit:
                         logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPM 达到限制 ({key_usage.get('rpm_count', 0)}/{rpm_limit})。跳过此 Key。")
                         perform_api_call = False
                else:
                    # 窗口已过期，重置计数和时间戳（将在下面增加）
                    key_usage["rpm_count"] = 0
                    key_usage["rpm_timestamp"] = 0

        # 检查 TPM_Input (仅检查，不在此处增加)
        if perform_api_call:
            tpm_input_limit = limits.get("tpm_input")
            if tpm_input_limit is not None:
                if now - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                     if key_usage.get("tpm_input_count", 0) >= tpm_input_limit:
                         logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPM_Input 达到限制 ({key_usage.get('tpm_input_count', 0)}/{tpm_input_limit})。跳过此 Key。")
                         perform_api_call = False
                else:
                    # 窗口已过期，重置计数和时间戳
                    key_usage["tpm_input_count"] = 0
                    key_usage["tpm_input_timestamp"] = 0

        # --- 如果预检查通过，增加计数 ---
        if perform_api_call:
            # 再次获取 key_usage 以防 setdefault 创建了新条目
            key_usage = usage_data[api_key][model_name]
            # 更新 RPM
            if now - key_usage.get("rpm_timestamp", 0) >= RPM_WINDOW_SECONDS:
                key_usage["rpm_count"] = 1
                key_usage["rpm_timestamp"] = now
            else:
                key_usage["rpm_count"] = key_usage.get("rpm_count", 0) + 1
            # 更新 RPD
            key_usage["rpd_count"] = key_usage.get("rpd_count", 0) + 1
            # 更新最后请求时间戳
            key_usage["last_request_timestamp"] = now
            logger.debug(f"速率限制计数增加 (Key: {api_key[:8]}, Model: {model_name}): RPM={key_usage['rpm_count']}, RPD={key_usage['rpd_count']}")

    return perform_api_call



# --- Token 计数更新 ---

def update_token_counts(
    api_key: str,
    model_name: str,
    limits: Optional[Dict[str, Any]],
    prompt_tokens: Optional[int],
    client_ip: str,
    today_date_str_pt: str
) -> None:
    """
    更新给定 API Key 和模型的 TPD_Input 和 TPM_Input 计数。
    同时记录基于 IP 的每日输入 Token 消耗。

    Args:
        api_key: 当前使用的 API Key。
        model_name: 请求的模型名称。
        limits: 从配置中获取的该模型的限制字典。
        prompt_tokens: 从 API 响应中获取的输入 Token 数量。
        client_ip: 客户端 IP 地址。
        today_date_str_pt: 当前的太平洋时区日期字符串。
    """
    if not limits or not prompt_tokens or prompt_tokens <= 0:
        if limits and (not prompt_tokens or prompt_tokens <= 0):
             logger.warning(f"Token 计数更新跳过 (Key: {api_key[:8]}, Model: {model_name}): 无效的 prompt_tokens ({prompt_tokens})。")
        # 如果没有限制信息或 prompt_tokens 无效，则不执行更新
        return

    with usage_lock:
        # 确保 key 和 model 的条目存在
        key_usage = usage_data.setdefault(api_key, defaultdict(lambda: defaultdict(int)))[model_name]

        # 更新 TPD_Input
        key_usage["tpd_input_count"] = key_usage.get("tpd_input_count", 0) + prompt_tokens

        # 更新 TPM_Input
        tpm_input_limit = limits.get("tpm_input")
        if tpm_input_limit is not None:
            now_tpm = time.time()
            if now_tpm - key_usage.get("tpm_input_timestamp", 0) >= TPM_WINDOW_SECONDS:
                key_usage["tpm_input_count"] = prompt_tokens
                key_usage["tpm_input_timestamp"] = now_tpm
            else:
                key_usage["tpm_input_count"] = key_usage.get("tpm_input_count", 0) + prompt_tokens
            logger.debug(f"输入 Token 计数更新 (Key: {api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}")

    # 记录 IP 输入 Token 消耗
    with ip_input_token_counts_lock:
        ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[client_ip] += prompt_tokens


# --- 辅助函数 (例如处理工具调用) ---

def process_tool_calls(gemini_tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
    """
    将 Gemini 返回的 functionCall 列表转换为 OpenAI 兼容的 tool_calls 格式。
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    """
    if not isinstance(gemini_tool_calls, list):
        logger.warning(f"期望 gemini_tool_calls 是列表，但得到 {type(gemini_tool_calls)}")
        return None

    openai_tool_calls = []
    for i, call in enumerate(gemini_tool_calls):
        if not isinstance(call, dict):
             logger.warning(f"工具调用列表中的元素不是字典: {call}")
             continue

        func_call = call # Gemini 直接返回 functionCall 字典

        if not isinstance(func_call, dict):
             logger.warning(f"functionCall 元素不是字典: {func_call}")
             continue

        func_name = func_call.get('name')
        func_args = func_call.get('args')

        if not func_name or not isinstance(func_args, dict):
            logger.warning(f"functionCall 缺少 name 或 args 不是字典: {func_call}")
            continue

        try:
            # OpenAI 需要 arguments 是 JSON 字符串
            arguments_str = json.dumps(func_args, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"序列化工具调用参数失败 (Name: {func_name}): {e}", exc_info=True)
            continue # 跳过这个调用

        openai_tool_calls.append({
            "id": f"call_{int(time.time()*1000)}_{i}", # 生成唯一 ID
            "type": "function",
            "function": {
                "name": func_name,
                "arguments": arguments_str,
            }
        })

    return openai_tool_calls if openai_tool_calls else None
