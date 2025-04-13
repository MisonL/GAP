# app/core/utils.py
# 导入必要的库
import random  # 用于生成随机数和随机选择
from fastapi import HTTPException, Request  # FastAPI 框架的异常和请求对象
import time      # 用于时间相关操作 (例如速率限制、时间戳)
import re        # 用于正则表达式 (提取 API 密钥)
from datetime import datetime, timedelta  # 用于日期和时间计算
# from apscheduler.schedulers.background import BackgroundScheduler # 不再需要，已移至 reporting.py
import os        # 用于访问环境变量
import requests  # 用于发送同步 HTTP 请求 (处理错误)
import httpx     # 用于发送异步 HTTP 请求 (测试密钥)
from threading import Lock # 用于线程锁
import logging   # 用于日志记录
import sys       # 用于系统相关操作
import pytz      # 用于处理时区 (太平洋时间)
from typing import Optional, Dict, Any, Set # 增加类型注解, Set
import json      # 增加 json 导入
import copy      # 增加 copy 导入
from collections import defaultdict # 增加 defaultdict
# 注意：调整导入路径
from ..handlers.log_config import format_log_message # 从 handlers.log_config 模块导入日志格式化函数
# 从 tracking 模块导入共享数据结构、锁和常量
from .tracking import ( # 同级目录导入
    usage_data, usage_lock,
    key_scores_cache, cache_lock, cache_last_updated, update_cache_timestamp,
    daily_rpd_totals, daily_totals_lock,
    ip_daily_counts, ip_counts_lock, ip_daily_input_token_counts, ip_input_token_counts_lock, # 确保已导入 (更新了 ip token 变量名)
    RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, CACHE_REFRESH_INTERVAL_SECONDS
)
# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

# --- 自定义异常 ---
class StreamProcessingError(Exception):
    """用于表示流处理中可恢复错误的自定义异常"""
    pass

# --- API 密钥管理器类 ---
class APIKeyManager:
    """
    管理 Gemini API 密钥，包括轮询、随机化、无效密钥处理以及基于使用情况的智能选择。
    """
    def __init__(self):
        """初始化 APIKeyManager"""
        raw_keys = os.environ.get('GEMINI_API_KEYS', "")
        self.api_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", raw_keys)
        self.keys_lock = Lock() # 保护 api_keys 列表
        self.tried_keys_for_request: Set[str] = set() # 存储当前请求已尝试过的 Key
        self.initial_key_count = len(self.api_keys) # 存储初始密钥数量

    def _reset_key_stack(self): # 这个方法现在主要用于移除 key 后更新状态
         """(内部方法) 在 api_keys 列表更改后可能需要调用以更新状态"""
         with self.keys_lock:
             logger.info(f"API Keys 列表已更新，当前数量: {len(self.api_keys)}")

    def get_active_keys_count(self):
        """获取当前有效 API Key 的数量 (线程安全)"""
        with self.keys_lock:
            return len(self.api_keys)

    def get_initial_key_count(self):
        """获取初始配置的 API Key 数量"""
        return self.initial_key_count

    def select_best_key(self, model_name: str, model_limits: Dict) -> Optional[str]:
        """
        根据缓存的健康度得分选择最适合处理指定模型的 API 密钥。
        优先选择得分最高的、且未在当前请求中尝试过的 Key。
        如果缓存为空或所有 Key 都不可用/已尝试，则返回 None。

        Args:
            model_name (str): 请求的目标模型名称。
            model_limits (Dict): 包含所有模型限制的字典。

        Returns:
            Optional[str]: 选中的最佳 API 密钥，或 None。
        """
        best_key = None
        max_score = -1.0

        # 检查缓存新鲜度
        now = time.time()
        with cache_lock:
            last_update_time = cache_last_updated
            # 优化：改用 copy.deepcopy
            current_cache = copy.deepcopy(key_scores_cache) # 使用 copy.deepcopy

        if now - last_update_time > CACHE_REFRESH_INTERVAL_SECONDS * 2: # 如果超过2个更新周期未更新
            logger.warning(f"Key 得分缓存可能已过期 (上次更新于 {now - last_update_time:.1f} 秒前)。依赖后台任务进行更新。")

        with self.keys_lock:
            current_valid_keys = self.api_keys[:]

        valid_keys_in_cache = [key for key in current_valid_keys if key in current_cache]

        if not valid_keys_in_cache:
            logger.warning("Key 得分缓存为空或所有有效 Key 均不在缓存中。")
            available_untried_keys = [k for k in current_valid_keys if k not in self.tried_keys_for_request]
            if available_untried_keys:
                fallback_key = random.choice(available_untried_keys)
                logger.warning(f"回退：随机选择一个未尝试的 Key：{fallback_key[:8]}...")
                return fallback_key
            else:
                logger.error("没有可用的或未尝试的 API Key。")
                return None

        sorted_keys = sorted(
            valid_keys_in_cache,
            key=lambda k: current_cache.get(k, {}).get(model_name, -1.0),
            reverse=True
        )

        for key in sorted_keys:
            if key not in self.tried_keys_for_request:
                limits = model_limits.get(model_name)
                if limits:
                    with usage_lock: # 使用导入的 usage_lock
                        # 使用导入的 usage_data, 并确保使用 defaultdict 的行为
                        key_usage = usage_data[key][model_name] # defaultdict 会自动创建
                        # 确保所有计数器存在，以防万一 (理论上 defaultdict 会处理)
                        key_usage.setdefault("rpd_count", 0)
                        key_usage.setdefault("tpd_input_count", 0) # 新增
                        key_usage.setdefault("rpm_count", 0) # 新增 (虽然之前可能已存在)
                        key_usage.setdefault("rpm_timestamp", 0.0) # 新增
                        key_usage.setdefault("tpm_input_count", 0) # 新增
                        key_usage.setdefault("tpm_input_timestamp", 0.0) # 新增

                        rpd_count = key_usage.get("rpd_count", 0)
                        tpd_input_count = key_usage.get("tpd_input_count", 0) # 新增
                        rpm_count = key_usage.get("rpm_count", 0) # 新增
                        rpm_timestamp = key_usage.get("rpm_timestamp", 0.0) # 新增
                        tpm_input_count = key_usage.get("tpm_input_count", 0) # 新增
                        tpm_input_timestamp = key_usage.get("tpm_input_timestamp", 0.0) # 新增

                    rpd_limit = limits.get("rpd", 0) # 提供默认值0
                    if rpd_limit > 0 and rpd_count >= rpd_limit:
                        logger.warning(f"Key {key[:8]}... RPD 已达限制 ({rpd_count}/{rpd_limit})，跳过。")
                        self.tried_keys_for_request.add(key)
                        continue

                    # 新增：检查 TPD_Input
                    tpd_input_limit = limits.get("tpd_input") # 可能为 None
                    if tpd_input_limit is not None and tpd_input_count >= tpd_input_limit:
                        logger.warning(f"Key {key[:8]}... TPD_Input 已达限制 ({tpd_input_count}/{tpd_input_limit})，跳过。")
                        self.tried_keys_for_request.add(key)
                        continue

                    # 新增：检查 RPM (考虑时间窗口)
                    rpm_limit = limits.get("rpm", 0)
                    if rpm_limit > 0 and (now - rpm_timestamp < RPM_WINDOW_SECONDS) and rpm_count >= rpm_limit:
                        logger.warning(f"Key {key[:8]}... RPM 已达限制 ({rpm_count}/{rpm_limit} 在窗口期内)，跳过。")
                        self.tried_keys_for_request.add(key)
                        continue

                    # 新增：检查 TPM_Input (考虑时间窗口)
                    tpm_input_limit = limits.get("tpm_input") # 可能为 None
                    if tpm_input_limit is not None and (now - tpm_input_timestamp < TPM_WINDOW_SECONDS) and tpm_input_count >= tpm_input_limit:
                        logger.warning(f"Key {key[:8]}... TPM_Input 已达限制 ({tpm_input_count}/{tpm_input_limit} 在窗口期内)，跳过。")
                        self.tried_keys_for_request.add(key)
                        continue

                best_key = key
                break

        if best_key:
            score = current_cache.get(best_key, {}).get(model_name, -1.0)
            logger.debug(f"为模型 {model_name} 选择的最佳 Key：{best_key[:8]}... (得分: {score:.2f})")
        else:
            logger.warning(f"未能为模型 {model_name} 选择合适的 Key (可能所有 Key 都已尝试或 RPD/TPD_Input 超限)。")

        return best_key

    def update_key_scores_cache(self, model_limits: Dict):
        """
        计算并更新所有有效 Key 对所有已知模型的健康度得分缓存。
        此函数应由后台定时任务调用。

        Args:
            model_limits (Dict): 包含模型限制信息的字典。
        """
        logger.debug("开始更新 API Key 得分缓存...")
        new_cache = {}
        now = time.time()
        with self.keys_lock:
            current_valid_keys = self.api_keys[:]
        with usage_lock: # 使用导入的 usage_lock
            # 优化：改用 copy.deepcopy
            usage_data_copy = copy.deepcopy(usage_data) # 使用 copy.deepcopy

        for key in current_valid_keys:
            key_model_scores = {}
            for model_name, limits in model_limits.items():
                model_usage = usage_data_copy.get(key, {}).get(model_name, {})
                rpd_limit = limits.get("rpd", 0)
                rpm_limit = limits.get("rpm", 0)
                tpm_input_limit = limits.get("tpm_input") # 读取 tpm_input 限制
                tpd_input_limit = limits.get("tpd_input") # 读取 tpd_input 限制
                rpd_count = model_usage.get("rpd_count", 0)
                rpm_count = model_usage.get("rpm_count", 0)
                tpm_input_count = model_usage.get("tpm_input_count", 0) # 读取 tpm_input 计数
                tpd_input_count = model_usage.get("tpd_input_count", 0) # 读取 tpd_input 计数
                rpm_timestamp = model_usage.get("rpm_timestamp", 0)
                tpm_input_timestamp = model_usage.get("tpm_input_timestamp", 0) # 读取 tpm_input 时间戳

                # 计算 RPD 剩余百分比
                rpd_remaining_pct = (rpd_limit - rpd_count) / rpd_limit if rpd_limit > 0 else 1.0

                # 计算 RPM 剩余百分比 (考虑时间窗口)
                if now - rpm_timestamp >= RPM_WINDOW_SECONDS:
                    rpm_remaining_pct = 1.0
                else:
                    rpm_remaining_pct = (rpm_limit - rpm_count) / rpm_limit if rpm_limit > 0 else 1.0

                # 计算 TPM_Input 剩余百分比 (考虑时间窗口和 None)
                if tpm_input_limit is None:
                    tpm_input_remaining_pct = 1.0 # 没有限制视为 100%
                elif now - tpm_input_timestamp >= TPM_WINDOW_SECONDS:
                    tpm_input_remaining_pct = 1.0
                else:
                    tpm_input_remaining_pct = (tpm_input_limit - tpm_input_count) / tpm_input_limit if tpm_input_limit > 0 else 1.0

                # 计算 TPD_Input 剩余百分比 (考虑 None)
                if tpd_input_limit is None:
                    tpd_input_remaining_pct = 1.0 # 没有限制视为 100%
                else:
                    tpd_input_remaining_pct = (tpd_input_limit - tpd_input_count) / tpd_input_limit if tpd_input_limit > 0 else 1.0

                # 确保百分比不小于 0
                rpd_remaining_pct = max(0, rpd_remaining_pct)
                rpm_remaining_pct = max(0, rpm_remaining_pct)
                tpm_input_remaining_pct = max(0, tpm_input_remaining_pct)
                tpd_input_remaining_pct = max(0, tpd_input_remaining_pct)

                # 计算得分，如果 RPD 或 TPD_Input 耗尽则得分为 0
                score = 0.0
                if (rpd_limit > 0 and rpd_remaining_pct <= 0) or \
                   (tpd_input_limit is not None and tpd_input_limit > 0 and tpd_input_remaining_pct <= 0):
                    score = 0.0
                else:
                    # 调整权重：RPD 60%, TPD_Input 20%, RPM 15%, TPM_Input 5%
                    score = (0.60 * rpd_remaining_pct +
                             0.20 * tpd_input_remaining_pct +
                             0.15 * rpm_remaining_pct +
                             0.05 * tpm_input_remaining_pct)

                key_model_scores[model_name] = score
            new_cache[key] = key_model_scores

        with cache_lock: # 使用导入的 cache_lock
            # 更新全局缓存和时间戳
            key_scores_cache.clear()
            key_scores_cache.update(new_cache)
            # 调用导入的函数来更新时间戳
            update_cache_timestamp()
            # logger.debug(f"缓存时间戳已更新: {cache_last_updated}") # 可选调试日志

        logger.debug(f"API Key 得分缓存已更新，包含 {len(new_cache)} 个 Key 的信息。")

    def show_all_keys(self):
        """显示所有当前有效的 API Key (部分隐藏)"""
        with self.keys_lock:
            keys_to_show = self.api_keys[:]
            log_msg = format_log_message('INFO', f"当前可用API key个数: {len(keys_to_show)} ")
            logger.info(log_msg)
            for i, api_key in enumerate(keys_to_show):
                log_msg = format_log_message('INFO', f"API Key{i}: {api_key[:8]}...{api_key[-3:]}")
                logger.info(log_msg)

    def reset_tried_keys_for_request(self):
        """重置当前请求已尝试的 Key 集合"""
        self.tried_keys_for_request = set()

    def mark_key_issue(self, api_key: str, issue_type: str):
        """标记某个 Key 遇到了问题 (例如 safety_block)，以便后续处理或观察"""
        # TODO: 可以实现更复杂的逻辑，例如暂时降低 Key 的分数或记录问题次数
        logger.warning(f"标记 Key {api_key[:8]}... 遇到问题：{issue_type}")
        pass # 暂时只记录日志

# --- Gemini API 错误处理函数 ---
def handle_gemini_error(error, current_api_key, key_manager) -> str:
    """
    处理调用 Gemini API 时可能发生的各种异常，并根据错误类型执行相应操作 (如移除无效密钥)。
    不再直接触发密钥切换，由调用者 (process_request) 处理重试和切换。

    Args:
        error: 捕获到的异常对象。
        current_api_key: 当前正在使用的 API 密钥。
        key_manager: APIKeyManager 实例。

    Returns:
        str: 格式化或翻译后的错误消息字符串，用于向客户端返回。
    """
    error_message = f"发生未知错误: {error}"
    key_identifier = current_api_key[:8] if current_api_key else 'N/A'

    if isinstance(error, requests.exceptions.HTTPError) or isinstance(error, httpx.HTTPStatusError):
        response = error.response if hasattr(error, 'response') else None
        if response is None:
             error_message = f"HTTP 请求错误，无响应对象：{error}"
             log_msg = format_log_message('ERROR', error_message, extra={'key': key_identifier, 'error_message': str(error)})
             logger.error(log_msg)
        else:
            status_code = response.status_code
            if status_code == 400:
                try:
                    error_data = response.json()
                    if 'error' in error_data:
                        error_info = error_data['error']
                        if error_info.get('status') == 'INVALID_ARGUMENT' or "API key not valid" in error_info.get('message', ''):
                            error_message = "无效的 API 密钥"
                            extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': error_message}
                            log_msg = format_log_message('ERROR', f"{key_identifier}... → 无效，将从列表中移除。", extra=extra_log)
                            logger.error(log_msg)
                            with key_manager.keys_lock:
                                if current_api_key in key_manager.api_keys:
                                    key_manager.api_keys.remove(current_api_key)
                                    key_manager._reset_key_stack() # 内部日志记录更新
                            with usage_lock: # 使用导入的锁
                                usage_data.pop(current_api_key, None) # 使用导入的数据结构
                            with cache_lock: # 使用导入的锁
                                key_scores_cache.pop(current_api_key, None) # 使用导入的数据结构
                        else:
                            error_message = error_info.get('message', '错误请求') # 翻译 'Bad Request'
                            extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': error_message}
                            log_msg = format_log_message('WARNING', f"400 错误请求：{error_message}", extra=extra_log)
                            logger.warning(log_msg)
                            error_message = f"400 错误请求：{error_message}"
                    else:
                        error_message = "400 错误请求：未知的错误结构"
                        extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': response.text}
                        log_msg = format_log_message('WARNING', error_message, extra=extra_log)
                        logger.warning(log_msg)
                except ValueError:
                    error_message = "400 错误请求：响应不是有效的 JSON 格式"
                    extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': response.text}
                    log_msg = format_log_message('WARNING', error_message, extra=extra_log)
                    logger.warning(log_msg)

            elif status_code == 429:
                error_message = "API 密钥配额已用尽或达到速率限制"
                extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': error_message}
                log_msg = format_log_message('WARNING', f"{key_identifier}... → 429 资源耗尽或速率限制", extra=extra_log)
                logger.warning(log_msg)

            elif status_code == 403:
                error_message = "权限被拒绝"
                extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': error_message}
                log_msg = format_log_message('ERROR', f"{key_identifier}... → 403 权限被拒绝。将从列表中移除。", extra=extra_log)
                logger.error(log_msg)
                with key_manager.keys_lock:
                    if current_api_key in key_manager.api_keys:
                        key_manager.api_keys.remove(current_api_key)
                        key_manager._reset_key_stack() # 内部日志记录更新
                with usage_lock: # 使用导入的锁
                    usage_data.pop(current_api_key, None) # 使用导入的数据结构
                with cache_lock: # 使用导入的锁
                    key_scores_cache.pop(current_api_key, None) # 使用导入的数据结构

            elif status_code == 500:
                error_message = "Gemini API 服务器内部错误"
                extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': error_message}
                log_msg = format_log_message('WARNING', f"{key_identifier}... → 500 服务器内部错误", extra=extra_log)
                logger.warning(log_msg)

            elif status_code == 503:
                error_message = "Gemini API 服务不可用"
                extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': error_message}
                log_msg = format_log_message('WARNING', f"{key_identifier}... → 503 服务不可用", extra=extra_log)
                logger.warning(log_msg)
            else:
                error_message = f"未知的 HTTP 错误: {status_code}"
                extra_log = {'key': key_identifier, 'status_code': status_code, 'error_message': response.text}
                log_msg = format_log_message('WARNING', f"{key_identifier}... → {status_code} 未知 HTTP 错误", extra=extra_log)
                logger.warning(log_msg)

    elif isinstance(error, requests.exceptions.ConnectionError) or isinstance(error, httpx.ConnectError):
        error_message = "连接错误"
        log_msg = format_log_message('WARNING', error_message, extra={'key': key_identifier, 'error_message': str(error)})
        logger.warning(log_msg)

    elif isinstance(error, requests.exceptions.Timeout) or isinstance(error, httpx.TimeoutException):
        error_message = "请求超时"
        log_msg = format_log_message('WARNING', error_message, extra={'key': key_identifier, 'error_message': str(error)})
        logger.warning(log_msg)

    elif isinstance(error, StreamProcessingError): # 捕获自定义流错误
         error_message = str(error)
         log_msg = format_log_message('WARNING', f"流处理错误：{error_message}", extra={'key': key_identifier, 'error_message': error_message})
         logger.warning(log_msg)
    else: # 其他未知错误
        error_message = f"发生未知错误：{error}"
        log_msg = format_log_message('ERROR', error_message, extra={'key': key_identifier, 'error_message': str(error)})
        logger.error(log_msg, exc_info=True) # 添加 exc_info=True

    # 不再直接触发切换 Key
    return error_message


async def test_api_key(api_key: str) -> bool:
    """
    异步测试单个 API 密钥是否有效。
    通过尝试调用获取模型列表的端点来判断。

    Args:
        api_key (str): 要测试的 API 密钥。

    Returns:
        bool: 如果密钥有效则返回 True，否则返回 False。
    """
    if not api_key: # 处理空密钥的情况
        return False
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models?key={}".format(api_key)
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            return True
    except httpx.HTTPStatusError as e:
        if e.response.status_code in [400, 403]:
            logger.debug(f"测试密钥 {api_key[:8]}... 时返回状态码 {e.response.status_code}，判定为无效。")
        else:
            logger.warning(f"测试密钥 {api_key[:8]}... 时发生 HTTP 错误：{e}")
        return False
    except Exception as e:
        logger.warning(f"测试密钥 {api_key[:8]}... 时发生异常：{e}")
        return False


# --- 速率限制 ---
rate_limit_data = {} # 用于存储速率限制计数和时间戳的字典
rate_limit_lock = Lock() # 用于保护 rate_limit_data 访问的线程锁


def protect_from_abuse(request: Request, max_requests_per_minute: int = 30, max_requests_per_day_per_ip: int = 600):
    """
    基于内存的速率限制和防滥用检查。
    限制每个端点每分钟的请求数 (本地处理) 和每个 IP 每天的请求数 (共享处理)。

    Args:
        request (Request): FastAPI 的请求对象。
        max_requests_per_minute (int): 每分钟允许的最大请求数。
        max_requests_per_day_per_ip (int): 每个 IP 每天允许的最大请求数。

    Raises:
        HTTPException: 如果请求超过了速率限制 (状态码 429)。
    """
    now = time.time()
    minute = int(now // 60)

    # --- 处理分钟限制 (保留本地逻辑) ---
    minute_key = f"{request.url.path}:{minute}"
    minute_count = 0
    with rate_limit_lock: # 使用本地锁保护本地分钟计数器
        # 清理过期的分钟数据 (简化清理逻辑)
        # 清理超过 10 分钟的记录
        keys_to_remove = [k for k, (_, timestamp) in rate_limit_data.items() if now - timestamp > 600]
        for key in keys_to_remove:
            rate_limit_data.pop(key, None)
        if keys_to_remove:
            logger.debug(f"已清理 {len(keys_to_remove)} 条过期的分钟速率限制记录。")

        # 更新并检查分钟限制
        minute_count, minute_timestamp = rate_limit_data.get(minute_key, (0, now))
        if now - minute_timestamp >= 60: # 检查是否过了 60 秒
            minute_count = 0
            minute_timestamp = now
        minute_count += 1
        rate_limit_data[minute_key] = (minute_count, minute_timestamp)

    # 检查是否超过分钟限制
    if minute_count > max_requests_per_minute:
        logger.warning(f"速率限制触发 (分钟)：路径={request.url.path}, 限制={max_requests_per_minute}")
        raise HTTPException(status_code=429, detail={
            "message": "每分钟请求过多", "limit": max_requests_per_minute}) # 翻译

    # --- 处理每日 IP 限制 (使用 tracking 中的共享数据) ---
    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown_ip"

    pt_timezone = pytz.timezone('America/Los_Angeles')
    today_date_str = datetime.now(pt_timezone).strftime('%Y-%m-%d')
    day_count = 0

    with ip_counts_lock: # 使用从 tracking 导入的共享锁
        # 清理过期的日期数据 (只保留当天和昨天的数据，因为重置任务会处理更早的)
        yesterday_date_str = (datetime.now(pt_timezone) - timedelta(days=1)).strftime('%Y-%m-%d')
        keys_to_delete = [d for d in ip_daily_counts if d not in [today_date_str, yesterday_date_str]]
        for d in keys_to_delete:
            ip_daily_counts.pop(d, None) # 使用 pop 更安全
        if keys_to_delete:
             logger.debug(f"已清理 {len(keys_to_delete)} 个过期的每日 IP 计数日期条目。")

        # 增加当前 IP 当天的计数
        ip_daily_counts[today_date_str][client_ip] += 1
        day_count = ip_daily_counts[today_date_str][client_ip]

    # 检查是否超过每日 IP 限制
    if day_count > max_requests_per_day_per_ip:
        logger.warning(f"速率限制触发 (天)：IP={client_ip}, 限制={max_requests_per_day_per_ip}")
        raise HTTPException(status_code=429, detail={"message": "此 IP 每日请求过多", "limit": max_requests_per_day_per_ip}) # 翻译

# --- 全局 Key Manager 实例 ---
# 在此处实例化，以便其他模块可以导入此共享实例
key_manager_instance = APIKeyManager()
