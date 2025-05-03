# app/api/rate_limit_utils.py
"""
速率限制检查与计数更新相关的辅助函数。
"""
import time # 导入 time 模块
import logging # 导入 logging 模块
from collections import Counter # 导入 Counter
from collections import defaultdict # 导入 defaultdict
from typing import Dict, Any, Optional # 导入类型提示

# 导入跟踪相关的数据结构和常量，需要绝对路径
from app.core.tracking import (
    ip_daily_input_token_counts, ip_input_token_counts_lock, # IP 每日输入 token 计数和锁
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS # 使用数据、锁、RPM/TPM 窗口
)

logger = logging.getLogger('my_logger') # 获取日志记录器实例

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

    now = time.time() # 获取当前时间戳
    perform_api_call = True # 初始化是否执行 API 调用标志

    with usage_lock: # 获取使用数据锁
        # 使用 setdefault 确保 key 和 model 的条目存在
        key_usage = usage_data.setdefault(api_key, defaultdict(lambda: defaultdict(int)))[model_name] # 获取或创建 Key 和模型的用法条目

        # 检查并更新 RPM
        rpm_limit = limits.get("rpm")
        if rpm_limit is not None:
            current_rpm_count = key_usage.get("rpm_count", 0)
            rpm_timestamp = key_usage.get("rpm_timestamp", 0)

            if now - rpm_timestamp >= RPM_WINDOW_SECONDS:
                # 窗口已过期，重置计数并增加
                key_usage["rpm_count"] = 1 # 第一个请求在新的窗口
                key_usage["rpm_timestamp"] = now
                logger.debug(f"RPM 窗口过期，重置计数并增加 (Key: {api_key[:8]}, Model: {model_name}): 新 RPM=1")
            else:
                # 窗口未过期，检查是否达到限制
                if current_rpm_count + 1 > rpm_limit: # 检查加上当前请求是否超限
                     logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPM 达到限制 ({current_rpm_count}/{rpm_limit})。跳过此 Key。")
                     perform_api_call = False
                else:
                    # 未达到限制，增加计数
                    key_usage["rpm_count"] = current_rpm_count + 1
                    # timestamp remains the same as it's within the window
                    logger.debug(f"RPM 计数增加 (Key: {api_key[:8]}, Model: {model_name}): 新 RPM={key_usage['rpm_count']}")

        # 检查并更新 RPD (RPD 检查和更新可以保持原样，因为它不依赖于时间窗口)
        if perform_api_call:
            rpd_limit = limits.get("rpd")
            if rpd_limit is not None:
                current_rpd_count = key_usage.get("rpd_count", 0)
                if current_rpd_count + 1 > rpd_limit: # 检查加上当前请求是否超限
                    logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPD 达到限制 ({current_rpd_count}/{rpd_limit})。跳过此 Key。")
                    perform_api_call = False
                else:
                    # 未达到限制，增加计数
                    key_usage["rpd_count"] = current_rpd_count + 1
                    logger.debug(f"RPD 计数增加 (Key: {api_key[:8]}, Model: {model_name}): 新 RPD={key_usage['rpd_count']}")

        # 检查 TPD_Input (仅检查，不在此处增加，因为 token 数未知)
        if perform_api_call:
             tpd_input_limit = limits.get("tpd_input")
             if tpd_input_limit is not None and key_usage.get("tpd_input_count", 0) >= tpd_input_limit:
                 logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPD_Input 达到限制 ({key_usage.get('tpd_input_count', 0)}/{tpd_input_limit})。跳过此 Key。")
                 perform_api_call = False

        # 检查 TPM_Input (仅检查，不在此处增加)
        if perform_api_call:
             tpm_input_limit = limits.get("tpm_input")
             if tpm_input_limit is not None:
                 if now - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                      if key_usage.get("tpm_input_count", 0) >= tpm_input_limit:
                          logger.warning(f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPM_Input 达到限制 ({key_usage.get('tpm_input_count', 0)}/{tpm_input_limit})。跳过此 Key。")
                          perform_api_call = False
                 # Note: No else block here to reset TPM_Input count/timestamp if window expires,
                 # because the update_token_counts handles the reset and increment for TPM_Input.

        # Update last_request_timestamp if the call is performed
        if perform_api_call:
            key_usage["last_request_timestamp"] = now

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