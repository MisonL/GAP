# -*- coding: utf-8 -*-
"""
API 请求处理相关的辅助函数。
Helper functions related to API request processing.
"""
import pytz # 导入 pytz 模块 (Import pytz module)
import json # 导入 json 模块 (Import json module)
import logging # 导入 logging 模块 (Import logging module)
import time # 导入 time 模块 (Import time module)
from datetime import datetime # 导入 datetime (Import datetime)
from collections import Counter # 导入 Counter (Import Counter)
from collections import defaultdict # 导入 defaultdict (Import defaultdict)
from typing import Tuple, List, Dict, Any, Optional # 导入类型提示 (Import type hints)
from fastapi import Request # 导入 Request (Import Request)
# 导入配置以获取默认值和模型限制
# Import configuration to get default values and model limits
from .. import config as app_config # 导入 app_config 模块 (Import app_config module)
from ..core.tracking import ip_daily_input_token_counts, ip_input_token_counts_lock # 导入 IP 每日输入 token 计数和锁 (Import IP daily input token counts and lock)
from ..core.tracking import usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS # 导入使用数据、锁、RPM/TPM 窗口 (Import usage data, locks, RPM/TPM windows)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

def get_client_ip(request: Request) -> str:
    """
    从 FastAPI Request 对象中获取客户端 IP 地址。
    优先使用 X-Forwarded-For Header。
    Gets the client's IP address from the FastAPI Request object.
    Prioritizes using the X-Forwarded-For Header.
    """
    x_forwarded_for = request.headers.get("x-forwarded-for") # 获取 X-Forwarded-For Header (Get X-Forwarded-For Header)
    if x_forwarded_for: # 如果存在 X-Forwarded-For (If X-Forwarded-For exists)
        # X-Forwarded-For 可能包含多个 IP，取第一个
        # X-Forwarded-For may contain multiple IPs, take the first one
        client_ip = x_forwarded_for.split(',')[0].strip() # 分割并获取第一个 IP (Split and get the first IP)
    else:
        # 回退到 request.client.host
        # Fallback to request.client.host
        client_ip = request.client.host if request.client else "unknown_ip" # 获取客户端主机 IP (Get client host IP) # 如果 client 不存在，则为 "unknown_ip" (If client does not exist, it's "unknown_ip")
    return client_ip # 返回客户端 IP (Return client IP)

def get_current_timestamps() -> Tuple[str, str]:
    """
    获取当前的 CST 时间字符串和 PT 日期字符串。
    Gets the current CST time string and PT date string.

    Returns:
        元组[str, str]: (cst_time_str, today_date_str_pt)
                         例如 ('2024-01-01 10:00:00 CST', '2023-12-31')
        Tuple[str, str]: (cst_time_str, today_date_str_pt)
                         e.g., ('2024-01-01 10:00:00 CST', '2023-12-31')
    """
    # 中国标准时间 (CST)
    # China Standard Time (CST)
    cst_tz = pytz.timezone('Asia/Shanghai') # 设置时区为亚洲/上海 (Set timezone to Asia/Shanghai)
    cst_now = datetime.now(cst_tz) # 获取当前 CST 时间 (Get current CST time)
    cst_time_str = cst_now.strftime('%Y-%m-%d %H:%M:%S %Z') # 格式化 CST 时间字符串 (Format CST time string)

    # 太平洋时间 (PT) 日期 (用于 IP 统计)
    # Pacific Time (PT) Date (for IP statistics)
    pt_tz = pytz.timezone('America/Los_Angeles') # 设置时区为美国/洛杉矶 (Set timezone to America/Los_Angeles)
    today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d') # 格式化 PT 日期字符串 (Format PT date string)

    return cst_time_str, today_date_str_pt # 返回时间戳元组 (Return timestamp tuple)

# --- Token 估算与上下文截断 ---
# --- Token Estimation and Context Truncation ---

def estimate_token_count(contents: List[Dict[str, Any]]) -> int:
    """
    估算 Gemini contents 列表的 Token 数量。
    使用简单的字符数估算方法 (1 个 token 大约等于 4 个字符)。
    Estimates the token count of a Gemini contents list.
    Uses a simple character count estimation method (1 token is approximately equal to 4 characters).
    """
    if not contents: # 如果内容为空 (If contents is empty)
        return 0 # 返回 0 (Return 0)
    try:
        # 计算 JSON 序列化后的字符数 (ensure_ascii=False 保证中文字符正确计数)
        # Calculate the number of characters after JSON serialization (ensure_ascii=False ensures correct counting of Chinese characters)
        char_count = len(json.dumps(contents, ensure_ascii=False)) # 序列化并获取字符数 (Serialize and get character count)
        # 除以 4 作为 Token 估算值
        # Divide by 4 as the token estimation
        return char_count // 4 # 返回估算 Token 数 (Return estimated token count)
    except TypeError as e:
        logger.error(f"序列化 contents 进行 Token 估算时出错: {e}", exc_info=True) # 记录序列化错误 (Log serialization error)
        return 0 # 如果序列化失败则返回 0 (Return 0 if serialization fails)

def truncate_context(
    contents: List[Dict[str, Any]],
    model_name: str
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    根据模型限制截断对话历史 (contents)。
    从开头成对移除消息，直到满足 Token 限制。
    Truncates the conversation history (contents) based on model limits.
    Removes messages in pairs from the beginning until the token limit is met.

    Args:
        contents: 完整的对话历史列表 (Gemini 格式)。The complete conversation history list (Gemini format).
        model_name: 当前请求使用的模型名称。The name of the model used for the current request.

    Returns:
        元组[List[Dict[str, Any]], bool]:
            - 截断后的对话历史列表。The truncated conversation history list.
            - 一个布尔值，指示截断后是否仍然超限（True 表示超限，False 表示未超限或无需截断）。
              A boolean value indicating whether it is still over the limit after truncation (True means over limit, False means not over limit or no truncation needed).
              如果为 True，调用者不应保存此上下文。
              If True, the caller should not save this context.
    """
    if not contents: # 如果内容为空 (If contents is empty)
        return [], False # 返回空列表和 False (Return empty list and False)

    # 从配置中获取默认最大上下文 Token 数和安全边际
    # Get default maximum context tokens and safety margin from configuration
    # 使用 getattr 安全地访问配置项，避免因配置项不存在而报错
    # Use getattr to safely access configuration items and avoid errors if they don't exist
    default_max_tokens = getattr(app_config, 'DEFAULT_MAX_CONTEXT_TOKENS', 30000) # 默认上下文 Token 上限 (Default context token limit)
    safety_margin = getattr(app_config, 'CONTEXT_TOKEN_SAFETY_MARGIN', 200) # Token 安全边际 (Token safety margin)

    # 1. 获取模型的输入 Token 限制 (input_token_limit)
    # 1. Get the model's input token limit (input_token_limit)
    # model_limits 应该从 config 模块加载，确保它在应用启动时已加载
    # model_limits should be loaded from the config module, ensure it is loaded at application startup
    model_limits = getattr(app_config, 'MODEL_LIMITS', {}) # 获取已加载的模型限制字典 (Get the loaded model limits dictionary)
    limit_info = model_limits.get(model_name) # 获取特定模型的限制信息 (Get limit information for the specific model)
    max_tokens = default_max_tokens # 初始化最大 Token 数为默认值 (Initialize max tokens to default value)
    if limit_info and isinstance(limit_info, dict) and limit_info.get("input_token_limit"): # 如果找到限制信息且包含 input_token_limit (If limit info is found and contains input_token_limit)
        try:
            limit_value = limit_info["input_token_limit"] # 获取限制值 (Get the limit value)
            if limit_value is not None: # 确保值不是 None (JSON 中的 null) (Ensure the value is not None (null in JSON))
                 max_tokens = int(limit_value) # 将限制值转换为整数 (Convert limit value to integer)
            else:
                 logger.warning(f"模型 '{model_name}' 的 input_token_limit 值为 null，使用默认值 {default_max_tokens}") # Log warning if input_token_limit is null
        except (ValueError, TypeError):
             logger.warning(f"模型 '{model_name}' 的 input_token_limit 值无效 ('{limit_info.get('input_token_limit')}')，使用默认值 {default_max_tokens}") # Log warning if input_token_limit value is invalid
    else:
        logger.warning(f"模型 '{model_name}' 或其 input_token_limit 未在 model_limits.json 中定义，使用默认值 {default_max_tokens}") # Log warning if model or its input_token_limit is not defined

    truncation_threshold = max(0, max_tokens - safety_margin) # 计算截断阈值，确保不为负数 (Calculate truncation threshold, ensure it's not negative)

    # 2. 估算当前上下文的 Token 数量
    # 2. Estimate the token count of the current context
    estimated_tokens = estimate_token_count(contents) # 估算 Token 数量 (Estimate token count)

    # 3. 判断是否需要截断
    # 3. Determine if truncation is needed
    if estimated_tokens > truncation_threshold: # 如果估算 Token 数超过阈值 (If estimated token count exceeds threshold)
        logger.info(f"上下文估算 Token ({estimated_tokens}) 超出阈值 ({truncation_threshold} for model {model_name})，开始截断...") # Log that context exceeds threshold and truncation starts
        # 创建上下文列表的副本进行修改，避免影响原始列表
        # Create a copy of the context list for modification to avoid affecting the original list
        truncated_contents = list(contents) # 创建副本 (Create a copy)
        # 循环截断，直到 Token 数量满足阈值或无法再截断
        # Loop and truncate until the token count meets the threshold or no more truncation is possible
        while estimate_token_count(truncated_contents) > truncation_threshold: # 当估算 Token 数仍超过阈值时 (While estimated token count is still over threshold)
            # 检查是否至少有两条消息可以成对移除
            # Check if there are at least two messages that can be removed in pairs
            if len(truncated_contents) >= 2: # 如果消息数大于等于 2 (If number of messages is greater than or equal to 2)
                # 从列表开头移除两个元素 (通常是 user 和 model 的消息对)
                # Remove two elements from the beginning of the list (usually a user and model message pair)
                removed_first = truncated_contents.pop(0) # 移除第一个元素 (Remove the first element)
                removed_second = truncated_contents.pop(0) # 移除第二个元素 (Remove the second element)
                logger.debug(f"移除旧消息对: roles={removed_first.get('role')}, {removed_second.get('role')}") # Log removed message pair (DEBUG level)
            elif len(truncated_contents) == 1: # 如果只剩下一条消息 (If only one message remains)
                # 只剩下一条消息，但仍然超过 Token 限制
                # Only one message remains, but its token count is still over the limit
                logger.warning("截断过程中只剩一条消息，但其 Token 数量仍然超过阈值。") # Log warning
                break # 停止循环，将在下面检查最终状态 (Stop the loop, final state will be checked below)
            else: # truncated_contents 列表已为空 (truncated_contents list is already empty)
                break # 无法再截断，跳出循环 (Cannot truncate further, break the loop)

        final_estimated_tokens = estimate_token_count(truncated_contents) # 估算截断后的最终 Token 数 (Estimate final token count after truncation)

        # 检查截断后的最终 Token 数量
        # Check the final token count after truncation
        if final_estimated_tokens > truncation_threshold: # 如果最终 Token 数仍然超限 (If final token count is still over limit)
             # 即使经过截断（可能只剩下一条消息），最终 Token 数量仍然超过阈值
             # Even after truncation (possibly only one message remaining), the final token count is still over the threshold
             logger.error(f"截断后上下文估算 Token ({final_estimated_tokens}) 仍然超过阈值 ({truncation_threshold})。本次交互的上下文不应被保存。") # Log error and indicate context should not be saved
             # 返回截断后的结果，并标记为超限状态
             # Return the truncated result and mark it as over limit
             return truncated_contents, True # 返回截断后的内容和 True (Return truncated contents and True)
        else:
            logger.info(f"上下文截断完成，剩余消息数: {len(truncated_contents)}, 最终估算 Token: {final_estimated_tokens}") # Log truncation completion info
            return truncated_contents, False # 截断成功，并且最终 Token 未超限 (Truncation successful, and final token is not over limit)
    else:
        # Token 未超限，无需截断
        # Token is not over limit, no truncation needed
        return contents, False # 返回原始列表，标记为未超限 (Return original list, marked as not over limit)



# --- 速率限制检查与计数更新 ---
# --- Rate Limit Check and Count Update ---

def check_rate_limits_and_update_counts(
    api_key: str,
    model_name: str,
    limits: Optional[Dict[str, Any]]
) -> bool:
    """
    检查给定 API Key 和模型的速率限制 (RPD, TPD_Input, RPM, TPM_Input)。
    如果未达到限制，则更新 RPM 和 RPD 计数，并返回 True。
    如果达到任何限制，则记录警告并返回 False。
    Checks the rate limits (RPD, TPD_Input, RPM, TPM_Input) for the given API Key and model.
    If limits are not reached, updates RPM and RPD counts and returns True.
    If any limit is reached, logs a warning and returns False.

    Args:
        api_key: 当前尝试使用的 API Key。The API Key currently being attempted.
        model_name: 请求的模型名称。The name of the requested model.
        limits: 从配置中获取的该模型的限制字典。The limits dictionary for this model obtained from the configuration.

    Returns:
        bool: 如果可以继续进行 API 调用则返回 True，否则返回 False。Returns True if the API call can proceed, False otherwise.
    """
    if not limits: # 如果没有限制信息 (If no limit information)
        logger.warning(f"模型 '{model_name}' 不在 model_limits.json 中，跳过本地速率限制检查。") # Log warning and skip local rate limit check
        return True # 没有限制信息，允许调用 (No limit information, allow call)

    now = time.time() # 获取当前时间戳 (Get current timestamp)
    perform_api_call = True # 初始化是否执行 API 调用标志 (Initialize flag for performing API call)

    with usage_lock: # 获取使用数据锁 (Acquire usage data lock)
        # 使用 setdefault 确保 key 和 model 的条目存在
        # Use setdefault to ensure entries for key and model exist
        key_usage = usage_data.setdefault(api_key, defaultdict(lambda: defaultdict(int)))[model_name] # 获取或创建 Key 和模型的用法条目 (Get or create usage entry for key and model)

        # 检查 RPD
        # Check RPD
        rpd_limit = limits.get("rpd") # 获取 RPD 限制 (Get RPD limit)
        if rpd_limit is not None and key_usage.get("rpd_count", 0) >= rpd_limit: # 如果达到 RPD 限制 (If RPD limit is reached)
            logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPD 达到限制 ({key_usage.get('rpd_count', 0)}/{rpd_limit})。跳过此 Key。") # Log warning and skip key
            perform_api_call = False # 不执行 API 调用 (Do not perform API call)

        # 检查 TPD_Input (仅检查，不在此处增加，因为 token 数未知)
        # Check TPD_Input (check only, not incremented here as token count is unknown)
        if perform_api_call: # 如果可以执行 API 调用 (If API call can be performed)
            tpd_input_limit = limits.get("tpd_input") # 获取 TPD_Input 限制 (Get TPD_Input limit)
            if tpd_input_limit is not None and key_usage.get("tpd_input_count", 0) >= tpd_input_limit: # 如果达到 TPD_Input 限制 (If TPD_Input limit is reached)
                logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPD_Input 达到限制 ({key_usage.get('tpd_input_count', 0)}/{tpd_input_limit})。跳过此 Key。") # Log warning and skip key
                perform_api_call = False # 不执行 API 调用 (Do not perform API call)

        # 检查 RPM
        # Check RPM
        if perform_api_call: # 如果可以执行 API 调用 (If API call can be performed)
            rpm_limit = limits.get("rpm") # 获取 RPM 限制 (Get RPM limit)
            if rpm_limit is not None: # 如果设置了 RPM 限制 (If RPM limit is set)
                if now - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS: # 如果在 RPM 窗口期内 (If within RPM window)
                    if key_usage.get("rpm_count", 0) >= rpm_limit: # 如果达到 RPM 限制 (If RPM limit is reached)
                         logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPM 达到限制 ({key_usage.get('rpm_count', 0)}/{rpm_limit})。跳过此 Key。") # Log warning and skip key
                         perform_api_call = False # 不执行 API 调用 (Do not perform API call)
                else:
                    # 窗口已过期，重置计数和时间戳（将在下面增加）
                    # Window has expired, reset count and timestamp (will be incremented below)
                    key_usage["rpm_count"] = 0 # 重置 RPM 计数 (Reset RPM count)
                    key_usage["rpm_timestamp"] = 0 # 重置 RPM 时间戳 (Reset RPM timestamp)

        # 检查 TPM_Input (仅检查，不在此处增加)
        # Check TPM_Input (check only, not incremented here)
        if perform_api_call: # 如果可以执行 API 调用 (If API call can be performed)
            tpm_input_limit = limits.get("tpm_input") # 获取 TPM_Input 限制 (Get TPM_Input limit)
            if tpm_input_limit is not None: # 如果设置了 TPM_Input 限制 (If TPM_Input limit is set)
                if now - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS: # 如果在 TPM_Input 窗口期内 (If within TPM_Input window)
                     if key_usage.get("tpm_input_count", 0) >= tpm_input_limit: # 如果达到 TPM_Input 限制 (If TPM_Input limit is reached)
                         logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPM_Input 达到限制 ({key_usage.get('tpm_input_count', 0)}/{tpm_input_limit})。跳过此 Key。") # Log warning and skip key
                         perform_api_call = False # 不执行 API 调用 (Do not perform API call)
                else:
                    # 窗口已过期，重置计数和时间戳
                    # Window has expired, reset count and timestamp
                    key_usage["tpm_input_count"] = 0 # 重置 TPM_Input 计数 (Reset TPM_Input count)
                    key_usage["tpm_input_timestamp"] = 0 # 重置 TPM_Input 时间戳 (Reset TPM_Input timestamp)

        # --- 如果预检查通过，增加计数 ---
        # --- If pre-check passes, increment counts ---
        if perform_api_call: # 如果可以执行 API 调用 (If API call can be performed)
            # 再次获取 key_usage 以防 setdefault 创建了新条目
            # Get key_usage again in case setdefault created a new entry
            key_usage = usage_data[api_key][model_name] # 获取 Key 和模型的用法条目 (Get usage entry for key and model)
            # 更新 RPM
            # Update RPM
            if now - key_usage.get("rpm_timestamp", 0) >= RPM_WINDOW_SECONDS: # 如果 RPM 窗口已过期 (If RPM window has expired)
                key_usage["rpm_count"] = 1 # 重置 RPM 计数为 1 (Reset RPM count to 1)
                key_usage["rpm_timestamp"] = now # 更新 RPM 时间戳 (Update RPM timestamp)
            else:
                key_usage["rpm_count"] = key_usage.get("rpm_count", 0) + 1 # 增加 RPM 计数 (Increment RPM count)
            # 更新 RPD
            # Update RPD
            key_usage["rpd_count"] = key_usage.get("rpd_count", 0) + 1 # 增加 RPD 计数 (Increment RPD count)
            # 更新最后请求时间戳
            # Update last request timestamp
            key_usage["last_request_timestamp"] = now # 更新最后请求时间戳 (Update last request timestamp)
            logger.debug(f"速率限制计数增加 (Key: {api_key[:8]}, Model: {model_name}): RPM={key_usage['rpm_count']}, RPD={key_usage['rpd_count']}") # Log incremented counts (DEBUG level)

    return perform_api_call # 返回是否执行 API 调用 (Return whether to perform API call)



# --- Token 计数更新 ---
# --- Token Count Update ---

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
    Updates TPD_Input and TPM_Input counts for the given API Key and model.
    Also records IP-based daily input token consumption.

    Args:
        api_key: 当前使用的 API Key。The API Key currently used.
        model_name: 请求的模型名称。The name of the requested model.
        limits: 从配置中获取的该模型的限制字典。The limits dictionary for this model obtained from the configuration.
        prompt_tokens: 从 API 响应中获取的输入 Token 数量。The number of input tokens obtained from the API response.
        client_ip: 客户端 IP 地址。The client's IP address.
        today_date_str_pt: 当前的太平洋时区日期字符串。The current Pacific Timezone date string.
    """
    if not limits or not prompt_tokens or prompt_tokens <= 0: # 如果没有限制信息或 prompt_tokens 无效 (If no limit information or prompt_tokens is invalid)
        if limits and (not prompt_tokens or prompt_tokens <= 0): # 如果有限制信息但 prompt_tokens 无效 (If there is limit information but prompt_tokens is invalid)
             logger.warning(f"Token 计数更新跳过 (Key: {api_key[:8]}, Model: {model_name}): 无效的 prompt_tokens ({prompt_tokens})。") # Log warning for invalid prompt_tokens
        # 如果没有限制信息或 prompt_tokens 无效，则不执行更新
        # If there is no limit information or prompt_tokens is invalid, do not perform update
        return # 返回 (Return)

    with usage_lock: # 获取使用数据锁 (Acquire usage data lock)
        # 确保 key 和 model 的条目存在
        # Ensure entries for key and model exist
        key_usage = usage_data.setdefault(api_key, defaultdict(lambda: defaultdict(int)))[model_name] # 获取或创建 Key 和模型的用法条目 (Get or create usage entry for key and model)

        # 更新 TPD_Input
        # Update TPD_Input
        key_usage["tpd_input_count"] = key_usage.get("tpd_input_count", 0) + prompt_tokens # 增加 TPD_Input 计数 (Increment TPD_Input count)

        # 更新 TPM_Input
        # Update TPM_Input
        tpm_input_limit = limits.get("tpm_input") # 获取 TPM_Input 限制 (Get TPM_Input limit)
        if tpm_input_limit is not None: # 如果设置了 TPM_Input 限制 (If TPM_Input limit is set)
            now_tpm = time.time() # 获取当前时间戳 (Get current timestamp)
            if now_tpm - key_usage.get("tpm_input_timestamp", 0) >= TPM_WINDOW_SECONDS: # 如果 TPM_Input 窗口已过期 (If TPM_Input window has expired)
                key_usage["tpm_input_count"] = prompt_tokens # 重置 TPM_Input 计数为 prompt_tokens (Reset TPM_Input count to prompt_tokens)
                key_usage["tpm_input_timestamp"] = now_tpm # 更新 TPM_Input 时间戳 (Update TPM_Input timestamp)
            else:
                key_usage["tpm_input_count"] = key_usage.get("tpm_input_count", 0) + prompt_tokens # 增加 TPM_Input 计数 (Increment TPM_Input count)
            logger.debug(f"输入 Token 计数更新 (Key: {api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}") # Log updated counts (DEBUG level)

    # 记录 IP 输入 Token 消耗
    # Record IP input token consumption
    with ip_input_token_counts_lock: # 获取 IP 输入 token 计数锁 (Acquire IP input token counts lock)
        ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[client_ip] += prompt_tokens # 增加 IP 每日输入 token 计数 (Increment IP daily input token count)


# --- 辅助函数 (例如处理工具调用) ---
# --- Helper Functions (e.g., for processing tool calls) ---

def process_tool_calls(gemini_tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
    """
    将 Gemini 返回的 functionCall 列表转换为 OpenAI 兼容的 tool_calls 格式。
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    Converts the list of functionCalls returned by Gemini to the OpenAI compatible tool_calls format.
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    """
    if not isinstance(gemini_tool_calls, list): # 如果不是列表 (If it's not a list)
        logger.warning(f"期望 gemini_tool_calls 是列表，但得到 {type(gemini_tool_calls)}") # Log warning
        return None # 返回 None (Return None)

    openai_tool_calls = [] # 初始化 OpenAI 格式工具调用列表 (Initialize OpenAI format tool calls list)
    for i, call in enumerate(gemini_tool_calls): # 遍历 Gemini 工具调用列表 (Iterate through Gemini tool calls list)
        if not isinstance(call, dict): # 如果元素不是字典 (If element is not a dictionary)
             logger.warning(f"工具调用列表中的元素不是字典: {call}") # Log warning
             continue # 跳过 (Skip)

        func_call = call # Gemini 直接返回 functionCall 字典 (Gemini directly returns the functionCall dictionary)

        if not isinstance(func_call, dict): # 如果 functionCall 不是字典 (If functionCall is not a dictionary)
             logger.warning(f"functionCall 元素不是字典: {func_call}") # Log warning
             continue # 跳过 (Skip)

        func_name = func_call.get('name') # 获取函数名称 (Get function name)
        func_args = func_call.get('args') # 获取函数参数 (Get function arguments)

        if not func_name or not isinstance(func_args, dict): # 如果缺少名称或参数不是字典 (If name is missing or args is not a dictionary)
            logger.warning(f"functionCall 缺少 name 或 args 不是字典: {func_call}") # Log warning
            continue # 跳过 (Skip)

        try:
            # OpenAI 需要 arguments 是 JSON 字符串
            # OpenAI requires arguments to be a JSON string
            arguments_str = json.dumps(func_args, ensure_ascii=False) # 将参数序列化为 JSON 字符串 (Serialize arguments to JSON string)
        except TypeError as e:
            logger.error(f"序列化工具调用参数失败 (Name: {func_name}): {e}", exc_info=True) # 记录序列化失败错误 (Log serialization failure error)
            continue # 跳过这个调用 (Skip this call)

        openai_tool_calls.append({ # 添加到 OpenAI 格式列表 (Append to OpenAI format list)
            "id": f"call_{int(time.time()*1000)}_{i}", # 生成唯一 ID (Generate unique ID)
            "type": "function", # 类型为 function (Type is function)
            "function": {
                "name": func_name, # 函数名称 (Function name)
                "arguments": arguments_str, # 参数 JSON 字符串 (Arguments JSON string)
            }
        })

    return openai_tool_calls if openai_tool_calls else None # 返回 OpenAI 格式列表或 None (Return OpenAI format list or None)
