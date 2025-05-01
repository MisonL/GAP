# -*- coding: utf-8 -*-
"""
API 请求处理相关的辅助函数。
"""
import pytz # 导入 pytz 模块
import json # 导入 json 模块
import logging # 导入 logging 模块
import time # 导入 time 模块
from datetime import datetime # 导入 datetime
from collections import Counter # 导入 Counter
from collections import defaultdict # 导入 defaultdict
from typing import Tuple, List, Dict, Any, Optional # 导入类型提示
from fastapi import Request # 导入 Request
# 导入配置以获取默认值和模型限制
from app import config as app_config # 导入 app_config 模块
from app.core.tracking import ip_daily_input_token_counts, ip_input_token_counts_lock # 导入 IP 每日输入 token 计数和锁
from app.core.tracking import usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS # 导入使用数据、锁、RPM/TPM 窗口

logger = logging.getLogger('my_logger') # 获取日志记录器实例

def get_client_ip(request: Request) -> str:
    """
    从 FastAPI Request 对象中获取客户端 IP 地址。
    优先使用 X-Forwarded-For Header。
    """
    x_forwarded_for = request.headers.get("x-forwarded-for") # 获取 X-Forwarded-For Header
    if x_forwarded_for: # 如果存在 X-Forwarded-For
        # X-Forwarded-For 可能包含多个 IP，取第一个
        client_ip = x_forwarded_for.split(',')[0].strip() # 分割并获取第一个 IP
    else:
        # 回退到 request.client.host
        client_ip = request.client.host if request.client else "unknown_ip" # 获取客户端主机 IP # 如果 client 不存在，则为 "unknown_ip"
    return client_ip # 返回客户端 IP

def get_current_timestamps() -> Tuple[str, str]:
    """
    获取当前的 CST 时间字符串和 PT 日期字符串。

                         例如 ('2024-01-01 10:00:00 CST', '2023-12-31')
    """
    cst_tz = pytz.timezone('Asia/Shanghai') # 设置时区为亚洲/上海
    cst_now = datetime.now(cst_tz) # 获取当前 CST 时间
    cst_time_str = cst_now.strftime('%Y-%m-%d %H:%M:%S %Z') # 格式化 CST 时间字符串

    pt_tz = pytz.timezone('America/Los_Angeles') # 设置时区为美国/洛杉矶
    today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d') # 格式化 PT 日期字符串

    return cst_time_str, today_date_str_pt # 返回时间戳元组


def estimate_token_count(contents: List[Dict[str, Any]]) -> int:
    """
    """
    if not contents: # 如果内容为空
        return 0 # 返回 0
    try:
        char_count = len(json.dumps(contents, ensure_ascii=False)) # 序列化并获取字符数
        return char_count // 4 # 返回估算 Token 数
    except TypeError as e:
        logger.error(f"序列化 contents 进行 Token 估算时出错: {e}", exc_info=True) # 记录序列化错误
        return 0 # 如果序列化失败则返回 0

def truncate_context(
    contents: List[Dict[str, Any]],
    model_name: str
) -> Tuple[List[Dict[str, Any]], bool]:
    """


    """
    if not contents: # 如果内容为空
        return [], False # 返回空列表和 False

    default_max_tokens = getattr(app_config, 'DEFAULT_MAX_CONTEXT_TOKENS', 30000) # 默认上下文 Token 上限
    safety_margin = getattr(app_config, 'CONTEXT_TOKEN_SAFETY_MARGIN', 200) # Token 安全边际

    model_limits = getattr(app_config, 'MODEL_LIMITS', {}) # 获取已加载的模型限制字典
    limit_info = model_limits.get(model_name) # 获取特定模型的限制信息
    max_tokens = default_max_tokens # 初始化最大 Token 数为默认值
    if limit_info and isinstance(limit_info, dict) and limit_info.get("input_token_limit"): # 如果找到限制信息且包含 input_token_limit
        try:
            limit_value = limit_info["input_token_limit"] # 获取限制值
            if limit_value is not None: # 确保值不是 None (JSON 中的 null)
                 max_tokens = int(limit_value) # 将限制值转换为整数
            else:
                 logger.warning(f"模型 '{model_name}' 的 input_token_limit 值为 null，使用默认值 {default_max_tokens}") # 模型 input_token_limit 值为 null
        except (ValueError, TypeError):
             logger.warning(f"模型 '{model_name}' 的 input_token_limit 值无效 ('{limit_info.get('input_token_limit')}')，使用默认值 {default_max_tokens}") # 模型 input_token_limit 值无效
    else:
        logger.warning(f"模型 '{model_name}' 或其 input_token_limit 未在 model_limits.json 中定义，使用默认值 {default_max_tokens}") # 模型或 input_token_limit 未在 model_limits.json 中定义

    truncation_threshold = max(0, max_tokens - safety_margin) # 计算截断阈值，确保不为负数

    # 2. 估算当前上下文的 Token 数量
    estimated_tokens = estimate_token_count(contents) # 估算 Token 数量

    if estimated_tokens > truncation_threshold: # 如果估算 Token 数超过阈值
        logger.info(f"上下文估算 Token ({estimated_tokens}) 超出阈值 ({truncation_threshold} for model {model_name})，开始截断...") # 上下文估算 Token 超出阈值，开始截断
        # 创建上下文列表的副本进行修改，避免影响原始列表
        truncated_contents = list(contents) # 创建副本
        # 循环截断，直到 Token 数量满足阈值或无法再截断
        while estimate_token_count(truncated_contents) > truncation_threshold: # 当估算 Token 数仍超过阈值时
            # 检查是否至少有两条消息可以成对移除
            if len(truncated_contents) >= 2: # 如果消息数大于等于 2
                removed_first = truncated_contents.pop(0) # 移除第一个元素
                removed_second = truncated_contents.pop(0) # 移除第二个元素
                logger.debug(f"移除旧消息对: roles={removed_first.get('role')}, {removed_second.get('role')}") # 移除旧消息对
            elif len(truncated_contents) == 1: # 如果只剩下一条消息
                logger.warning("截断过程中只剩一条消息，但其 Token 数量仍然超过阈值。") # 截断过程中只剩一条消息，但其 Token 数量仍然超过阈值
                break # 停止循环，将在下面检查最终状态
            else: # truncated_contents 列表已为空
                break # 无法再截断，跳出循环

        final_estimated_tokens = estimate_token_count(truncated_contents) # 估算截断后的最终 Token 数

        # 检查截断后的最终 Token 数量
        if final_estimated_tokens > truncation_threshold: # 如果最终 Token 数仍然超限
             logger.error(f"截断后上下文估算 Token ({final_estimated_tokens}) 仍然超过阈值 ({truncation_threshold})。本次交互的上下文不应被保存。") # 截断后上下文仍然超限
             return truncated_contents, True # 返回截断后的内容和 True
        else:
            logger.info(f"上下文截断完成，剩余消息数: {len(truncated_contents)}, 最终估算 Token: {final_estimated_tokens}") # 上下文截断完成
            return truncated_contents, False # 截断成功，并且最终 Token 未超限
    else:
        return contents, False # 返回原始列表，标记为未超限




def check_rate_limits_and_update_counts(
    api_key: str,
    model_name: str,
    limits: Optional[Dict[str, Any]]
) -> bool:
    """


    """
    if not limits: # 如果没有限制信息
        logger.warning(f"模型 '{model_name}' 不在 model_limits.json 中，跳过本地速率限制检查。") # 模型不在 model_limits.json 中，跳过本地速率限制检查
        return True # 没有限制信息，允许调用

    now = time.time() # 获取当前时间戳
    perform_api_call = True # 初始化是否执行 API 调用标志

    with usage_lock: # 获取使用数据锁
        # 使用 setdefault 确保 key 和 model 的条目存在
        key_usage = usage_data.setdefault(api_key, defaultdict(lambda: defaultdict(int)))[model_name] # 获取或创建 Key 和模型的用法条目

        # 检查 RPD
        rpd_limit = limits.get("rpd") # 获取 RPD 限制
        if rpd_limit is not None and key_usage.get("rpd_count", 0) >= rpd_limit: # 如果达到 RPD 限制
            logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPD 达到限制 ({key_usage.get('rpd_count', 0)}/{rpd_limit})。跳过此 Key。") # RPD 达到限制，跳过此 Key
            perform_api_call = False # 不执行 API 调用

        # 检查 TPD_Input (仅检查，不在此处增加，因为 token 数未知)
        if perform_api_call: # 如果可以执行 API 调用
            tpd_input_limit = limits.get("tpm_input") # 获取 TPD_Input 限制
            if tpd_input_limit is not None and key_usage.get("tpd_input_count", 0) >= tpd_input_limit: # 如果达到 TPD_Input 限制
                logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPD_Input 达到限制 ({key_usage.get('tpd_input_count', 0)}/{tpd_input_limit})。跳过此 Key。") # TPD_Input 达到限制，跳过此 Key
                perform_api_call = False # 不执行 API 调用

        # 检查 RPM
        if perform_api_call: # 如果可以执行 API 调用
            rpm_limit = limits.get("rpm") # 获取 RPM 限制
            if rpm_limit is not None: # 如果设置了 RPM 限制
                if now - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS: # 如果在 RPM 窗口期内
                    if key_usage.get("rpm_count", 0) >= rpm_limit: # 如果达到 RPM 限制
                         logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPM 达到限制 ({key_usage.get('rpm_count', 0)}/{rpm_limit})。跳过此 Key。") # RPM 达到限制，跳过此 Key
                         perform_api_call = False # 不执行 API 调用
                else:
                    # 窗口已过期，重置计数和时间戳（将在下面增加）
                    key_usage["rpm_count"] = 0 # 重置 RPM 计数
                    key_usage["rpm_timestamp"] = 0 # 重置 TPM_Input 时间戳

        # 检查 TPM_Input (仅检查，不在此处增加)
        if perform_api_call: # 如果可以执行 API 调用
            tpm_input_limit = limits.get("tpm_input") # 获取 TPM_Input 限制
            if tpm_input_limit is not None: # 如果设置了 TPM_Input 限制
                if now - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS: # 如果在 TPM_Input 窗口期内
                     if key_usage.get("tpm_input_count", 0) >= tpm_input_limit: # 如果达到 TPM_Input 限制
                         logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPM_Input 达到限制 ({key_usage.get('tpm_input_count', 0)}/{tpm_input_limit})。跳过此 Key。") # TPM_Input 达到限制，跳过此 Key
                         perform_api_call = False # 不执行 API 调用
                else:
                    # 窗口已过期，重置计数和时间戳
                    key_usage["tpm_input_count"] = 0 # 重置 TPM_Input 计数
                    key_usage["tpm_input_timestamp"] = 0 # 重置 TPM_Input 时间戳

        # --- 如果预检查通过，增加计数 ---
        if perform_api_call: # 如果可以执行 API 调用
            # 再次获取 key_usage 以防 setdefault 创建了新条目
            key_usage = usage_data[api_key][model_name] # 获取 Key 和模型的用法条目
            # 更新 RPM
            if now - key_usage.get("rpm_timestamp", 0) >= RPM_WINDOW_SECONDS: # 如果 RPM 窗口已过期
                key_usage["rpm_count"] = 1 # 重置 RPM 计数为 1
                key_usage["rpm_timestamp"] = now # 更新 RPM 时间戳
            else:
                key_usage["rpm_count"] = key_usage.get("rpm_count", 0) + 1 # 增加 RPM 计数
            # 更新 RPD
            key_usage["rpd_count"] = key_usage.get("rpd_count", 0) + 1 # 增加 RPD 计数
            # 更新最后请求时间戳
            key_usage["last_request_timestamp"] = now # 更新最后请求时间戳
            logger.debug(f"速率限制计数增加 (Key: {api_key[:8]}, Model: {model_name}): RPM={key_usage['rpm_count']}, RPD={key_usage['rpd_count']}") # 速率限制计数增加

    return perform_api_call # 返回是否执行 API 调用




def update_token_counts(
    api_key: str,
    model_name: str,
    limits: Optional[Dict[str, Any]],
    prompt_tokens: Optional[int],
    client_ip: str,
    today_date_str_pt: str
) -> None:
    """

    """
    if not limits or not prompt_tokens or prompt_tokens <= 0: # 如果没有限制信息或 prompt_tokens 无效
        if limits and (not prompt_tokens or prompt_tokens <= 0): # 如果有限制信息但 prompt_tokens 无效
             logger.warning(f"Token 计数更新跳过 (Key: {api_key[:8]}, Model: {model_name}): 无效的 prompt_tokens ({prompt_tokens})。") # Token 计数更新跳过：无效的 prompt_tokens
        # 如果没有限制信息或 prompt_tokens 无效，则不执行更新
        return # 返回

    with usage_lock: # 获取使用数据锁
        # 确保 key 和 model 的条目存在
        key_usage = usage_data.setdefault(api_key, defaultdict(lambda: defaultdict(int)))[model_name] # 获取或创建 Key 和模型的用法条目

        # 更新 TPD_Input
        key_usage["tpd_input_count"] = key_usage.get("tpd_input_count", 0) + prompt_tokens # 增加 TPD_Input 计数

        # 更新 TPM_Input
        tpm_input_limit = limits.get("tpm_input") # 获取 TPM_Input 限制
        if tpm_input_limit is not None: # 如果设置了 TPM_Input 限制
            now_tpm = time.time() # 获取当前时间戳
            if now_tpm - key_usage.get("tpm_input_timestamp", 0) >= TPM_WINDOW_SECONDS: # 如果 TPM_Input 窗口已过期
                key_usage["tpm_input_count"] = prompt_tokens # 重置 TPM_Input 计数为 prompt_tokens
                key_usage["tpm_input_timestamp"] = now_tpm # 更新 TPM_Input 时间戳
            else:
                key_usage["tpm_input_count"] = key_usage.get("tpm_input_count", 0) + prompt_tokens # 增加 TPM_Input 计数
            logger.debug(f"输入 Token 计数更新 (Key: {api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}") # 输入 Token 计数更新

    # 记录 IP 输入 Token 消耗
    with ip_input_token_counts_lock: # 获取 IP 输入 token 计数锁
        ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[client_ip] += prompt_tokens # 增加 IP 每日输入 token 计数



def process_tool_calls(gemini_tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
    """
    将 Gemini 返回的 functionCall 列表转换为 OpenAI 兼容的 tool_calls 格式。
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    """
    if not isinstance(gemini_tool_calls, list): # 如果不是列表
        logger.warning(f"期望 gemini_tool_calls 是列表，但得到 {type(gemini_tool_calls)}") # 期望 gemini_tool_calls 是列表
        return None # 返回 None

    openai_tool_calls = [] # 初始化 OpenAI 格式工具调用列表
    for i, call in enumerate(gemini_tool_calls): # 遍历 Gemini 工具调用列表
        if not isinstance(call, dict): # 如果元素不是字典
             logger.warning(f"工具调用列表中的元素不是字典: {call}") # 工具调用列表中的元素不是字典
             continue # 跳过

        func_call = call # Gemini 直接返回 functionCall 字典

        if not isinstance(func_call, dict): # 如果 functionCall 不是字典
             logger.warning(f"functionCall 元素不是字典: {func_call}") # functionCall 元素不是字典
             continue # 跳过

        func_name = func_call.get('name') # 获取函数名称
        func_args = func_call.get('args') # 获取函数参数

        if not func_name or not isinstance(func_args, dict): # 如果缺少名称或参数不是字典
            logger.warning(f"functionCall 缺少 name 或 args 不是字典: {func_call}") # functionCall 缺少 name 或 args 不是字典
            continue # 跳过

        try:
            arguments_str = json.dumps(func_args, ensure_ascii=False) # 将参数序列化为 JSON 字符串
        except TypeError as e:
            logger.error(f"序列化工具调用参数失败 (Name: {func_name}): {e}", exc_info=True) # 序列化工具调用参数失败
            continue # 跳过这个调用

        openai_tool_calls.append({ # 添加到 OpenAI 格式列表
            "id": f"call_{int(time.time()*1000)}_{i}", # 生成唯一 ID
            "type": "function", # 类型为 function
            "function": {
                "name": func_name, # 函数名称
                "arguments": arguments_str, # 参数 JSON 字符串
            }
        })

    return openai_tool_calls if openai_tool_calls else None # 返回 OpenAI 格式列表或 None
