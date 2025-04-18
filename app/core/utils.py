# app/core/utils.py
# 导入必要的库
import random  # 用于生成随机数和随机选择
from fastapi import HTTPException, Request  # FastAPI 框架的异常和请求对象
import time      # 用于时间相关操作 (例如速率限制、时间戳)
import re        # 用于正则表达式 (提取 API 密钥)
from datetime import datetime, timedelta  # 用于日期和时间计算
# from apscheduler.schedulers.background import BackgroundScheduler # 不再需要，已移至 reporting.py
import os        # 用于访问环境变量
import httpx     # 用于发送异步 HTTP 请求 (测试密钥)
from threading import Lock # 用于线程锁
import logging   # 用于日志记录
import sys       # 用于系统相关操作
import pytz      # 用于处理时区 (太平洋时间)
from typing import Optional, Dict, Any, Set, List, Tuple # 确保导入 List 和 Tuple
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

    def get_initial_key_count(self) -> int:
        """返回初始配置的密钥数量"""
        return self.initial_key_count

    def get_next_key(self) -> Optional[str]:
        """
        轮询获取下一个 API 密钥。
        如果所有密钥都已尝试过，则返回 None。
        """
        with self.keys_lock:
            if not self.api_keys:
                return None
            # 找到第一个未尝试过的 Key
            available_keys = [k for k in self.api_keys if k not in self.tried_keys_for_request]
            if not available_keys:
                return None # 所有 Key 都已尝试

            # 简单轮询：取列表第一个
            # 更复杂的策略可以在这里实现
            key_to_use = available_keys[0]
            # self.tried_keys_for_request.add(key_to_use) # 不在这里标记，由调用者标记
            return key_to_use

    def select_best_key(self, model_name: str, model_limits: Dict[str, Any]) -> Optional[str]:
        """
        基于缓存的健康度评分选择最佳 API 密钥。
        如果缓存无效或所有 Key 都超限/已尝试，则返回 None。
        """
        with cache_lock:
            now = time.time()
            # 检查缓存是否需要刷新
            if now - cache_last_updated.get(model_name, 0) > CACHE_REFRESH_INTERVAL_SECONDS:
                logger.info(f"模型 '{model_name}' 的 Key 分数缓存过期，正在刷新...")
                self._update_key_scores(model_name, model_limits)
                update_cache_timestamp(model_name) # 更新时间戳

            # 获取当前模型的缓存分数
            scores = key_scores_cache.get(model_name, {})
            if not scores:
                logger.warning(f"模型 '{model_name}' 没有可用的 Key 分数缓存。")
                # 尝试立即更新一次缓存
                self._update_key_scores(model_name, model_limits)
                scores = key_scores_cache.get(model_name, {})
                if not scores:
                     logger.error(f"更新后仍然无法获取模型 '{model_name}' 的 Key 分数缓存。")
                     return self.get_next_key() # 回退到简单轮询

            # 过滤掉当前请求已尝试过的 Key
            available_scores = {k: v for k, v in scores.items() if k not in self.tried_keys_for_request}

            if not available_scores:
                logger.warning(f"模型 '{model_name}' 的所有可用 Key 均已在此请求中尝试过。")
                return None

            # 按分数降序排序，选择分数最高的 Key
            # sorted_keys = sorted(available_scores, key=available_scores.get, reverse=True) # type: ignore
            # 改为直接查找最大值
            best_key = max(available_scores, key=available_scores.get) # type: ignore
            best_score = available_scores[best_key]

            logger.info(f"为模型 '{model_name}' 选择的最佳 Key: {best_key[:8]}... (分数: {best_score:.2f})")
            return best_key


    def _update_key_scores(self, model_name: str, model_limits: Dict[str, Any]):
        """
        内部方法：更新指定模型的 API 密钥健康度评分缓存。
        """
        global key_scores_cache # 声明修改全局变量
        with self.keys_lock: # 访问当前有效的 api_keys
            if not self.api_keys:
                key_scores_cache[model_name] = {} # 没有有效 Key，清空缓存
                return

            current_scores = {}
            limits = model_limits.get(model_name)
            if not limits:
                logger.warning(f"模型 '{model_name}' 的限制未定义，无法计算健康度评分。")
                # 为所有 Key 设置默认分数 (例如 1.0)，或者不设置？
                # 设置为 1.0 允许它们被选中，但可能不准确
                current_scores = {key: 1.0 for key in self.api_keys}
            else:
                with usage_lock: # 访问 usage_data
                    for key in self.api_keys:
                        key_usage = usage_data.get(key, {}).get(model_name, {})
                        score = self._calculate_key_health(key_usage, limits)
                        current_scores[key] = score
                        logger.debug(f"计算 Key {key[:8]}... 对模型 '{model_name}' 的分数: {score:.2f}")

            key_scores_cache[model_name] = current_scores
            logger.debug(f"模型 '{model_name}' 的 Key 分数缓存已更新。") # *** 改为 DEBUG 级别 ***


    def _calculate_key_health(self, key_usage: Dict[str, Any], limits: Dict[str, Any]) -> float:
        """
        计算单个 API 密钥针对特定模型的健康度评分 (0.0 - 1.0+)。
        分数越高越好。综合考虑 RPD, TPD_Input, RPM, TPM_Input 的剩余百分比。
        """
        # 定义各项指标的权重
        # 权重可以根据实际情况调整，例如更看重日限制还是分钟限制
        weights = {
            "rpd": 0.4,
            "tpd_input": 0.3,
            "rpm": 0.2,
            "tpm_input": 0.1
        }
        total_score = 0.0
        active_metrics = 0 # 计算有效指标的数量

        # 计算 RPD 剩余百分比
        rpd_limit = limits.get("rpd")
        if rpd_limit is not None and rpd_limit > 0:
            rpd_used = key_usage.get("rpd_count", 0)
            rpd_remaining_ratio = max(0.0, 1.0 - (rpd_used / rpd_limit))
            total_score += rpd_remaining_ratio * weights["rpd"]
            active_metrics += weights["rpd"]
        elif rpd_limit == 0: # 如果限制为 0，则此指标无效
             pass
        # else: RPD 限制未定义，忽略此指标

        # 计算 TPD_Input 剩余百分比
        tpd_input_limit = limits.get("tpd_input")
        if tpd_input_limit is not None and tpd_input_limit > 0:
            tpd_input_used = key_usage.get("tpd_input_count", 0)
            tpd_input_remaining_ratio = max(0.0, 1.0 - (tpd_input_used / tpd_input_limit))
            total_score += tpd_input_remaining_ratio * weights["tpd_input"]
            active_metrics += weights["tpd_input"]
        elif tpd_input_limit == 0:
             pass
        # else: TPD_Input 限制未定义

        # 计算 RPM 剩余百分比 (基于当前窗口)
        rpm_limit = limits.get("rpm")
        if rpm_limit is not None and rpm_limit > 0:
            rpm_used = 0
            if time.time() - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS:
                rpm_used = key_usage.get("rpm_count", 0)
            rpm_remaining_ratio = max(0.0, 1.0 - (rpm_used / rpm_limit))
            total_score += rpm_remaining_ratio * weights["rpm"]
            active_metrics += weights["rpm"]
        elif rpm_limit == 0:
             pass
        # else: RPM 限制未定义

        # 计算 TPM_Input 剩余百分比 (基于当前窗口)
        tpm_input_limit = limits.get("tpm_input")
        if tpm_input_limit is not None and tpm_input_limit > 0:
            tpm_input_used = 0
            if time.time() - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                tpm_input_used = key_usage.get("tpm_input_count", 0)
            tpm_input_remaining_ratio = max(0.0, 1.0 - (tpm_input_used / tpm_input_limit))
            total_score += tpm_input_remaining_ratio * weights["tpm_input"]
            active_metrics += weights["tpm_input"]
        elif tpm_input_limit == 0:
             pass
        # else: TPM_Input 限制未定义

        # 如果没有任何有效指标，返回一个默认值（例如 1.0，表示可用）
        if active_metrics == 0:
            return 1.0

        # 返回加权平均分 (理论上在 0.0 到 1.0 之间，但可能因权重略超)
        # 归一化分数
        normalized_score = total_score / active_metrics if active_metrics > 0 else 1.0
        return normalized_score


    def remove_key(self, key_to_remove: str):
        """从管理器中移除指定的 API 密钥"""
        with self.keys_lock:
            if key_to_remove in self.api_keys:
                self.api_keys.remove(key_to_remove)
                logger.info(f"API Key {key_to_remove[:10]}... 已从活动池中移除。")
                # 同时从缓存中移除该 Key 的分数记录 (所有模型)
                with cache_lock:
                    for model_name in key_scores_cache:
                        if key_to_remove in key_scores_cache[model_name]:
                            del key_scores_cache[model_name][key_to_remove]
            else:
                logger.warning(f"尝试移除不存在的 API Key: {key_to_remove[:10]}...")

    def mark_key_issue(self, api_key: str, issue_type: str = "unknown"):
        """
        标记某个 Key 可能存在问题（例如，被安全阻止）。
        当前实现：降低其在缓存中的分数，使其在一段时间内不太可能被选中。
        """
        with cache_lock:
            for model_name in key_scores_cache:
                if api_key in key_scores_cache[model_name]:
                    # 显著降低分数，例如降到 0.1 或更低
                    key_scores_cache[model_name][api_key] = 0.1
                    logger.warning(f"Key {api_key[:8]}... 因问题 '{issue_type}' 被标记，分数暂时降低。")
                    # 可以在这里添加逻辑，例如一定次数后彻底移除 Key
                    break # 假设标记一次即可

    def get_active_keys_count(self) -> int:
        """返回当前管理器中有效（未被移除）的密钥数量"""
        with self.keys_lock:
            return len(self.api_keys)

    def reset_tried_keys_for_request(self):
        """为新的 API 请求重置已尝试的密钥集合"""
        self.tried_keys_for_request.clear()
        logger.debug("已重置当前请求的已尝试密钥集合。")


# --- 全局 Key Manager 实例 ---
# 在模块加载时创建单例
key_manager_instance = APIKeyManager()

# --- API 密钥测试函数 ---
async def test_api_key(api_key: str) -> bool:
    """
    [异步] 测试单个 Gemini API 密钥的有效性。
    尝试调用一个轻量级的 API 端点，例如列出模型。
    """
    # 使用 httpx 进行异步请求
    async with httpx.AsyncClient() as client:
        test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        try:
            response = await client.get(test_url, timeout=10.0) # 设置超时
            # 状态码 200 表示成功
            if response.status_code == 200:
                # 可以进一步检查响应内容，例如是否包含 'models' 列表
                try:
                    data = response.json()
                    if "models" in data and isinstance(data["models"], list):
                        return True
                    else:
                         logger.warning(f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但响应格式意外: {data}")
                         return False # 格式不对也视为无效
                except json.JSONDecodeError:
                     logger.warning(f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但无法解析 JSON 响应。")
                     return False # 解析失败视为无效
            else:
                # 记录具体的错误状态码和可能的消息
                error_detail = f"状态码: {response.status_code}"
                try:
                    error_body = response.json()
                    error_detail += f", 错误: {error_body.get('error', {}).get('message', '未知 API 错误')}"
                except json.JSONDecodeError:
                    error_detail += f", 响应体: {response.text}" # 如果不是 JSON
                logger.warning(f"测试 Key {api_key[:10]}... 失败 ({error_detail})")
                return False
        except httpx.TimeoutException:
            logger.warning(f"测试 Key {api_key[:10]}... 超时。")
            return False
        except httpx.RequestError as e:
            # 处理网络连接等错误
            logger.warning(f"测试 Key {api_key[:10]}... 时发生网络错误: {e}")
            return False
        except Exception as e:
            # 捕获其他意外错误
            logger.error(f"测试 Key {api_key[:10]}... 时发生未知错误: {e}", exc_info=True)
            return False

# --- 错误处理辅助函数 ---
def handle_gemini_error(e: Exception, api_key: Optional[str], key_manager: APIKeyManager) -> str:
    """
    统一处理 Gemini API 调用中可能发生的异常。
    根据异常类型决定是否移除 API Key 并返回错误消息。
    """
    key_identifier = f"Key: {api_key[:10]}..." if api_key else "Key: N/A"
    error_message = f"发生未知错误 ({key_identifier}): {e}" # 默认消息

    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code
        error_body = e.response.text
        try:
            error_json = e.response.json()
            api_error_message = error_json.get("error", {}).get("message", error_body)
        except json.JSONDecodeError:
            api_error_message = error_body

        error_message = f"API 错误 (状态码 {status_code}, {key_identifier}): {api_error_message}"
        logger.error(error_message) # 记录详细错误

        # 根据状态码判断是否移除 Key
        # 400 (通常是请求问题，例如无效参数或内容策略), 404 (模型不存在) - 不移除 Key
        # 401, 403 (认证/权限问题) - 移除 Key
        # 429 (速率限制) - 不移除 Key (本地限制应处理，或等待 Google 解除)
        # 500, 503 (服务器错误) - 可能暂时移除或标记，这里选择移除
        if status_code in [401, 403, 500, 503] and api_key:
            logger.warning(f"由于 API 错误 (状态码 {status_code})，将移除无效或有问题的 Key: {api_key[:10]}...")
            key_manager.remove_key(api_key)
        elif status_code == 400 and "API key not valid" in api_error_message and api_key:
             logger.warning(f"API 报告 Key 无效 (400 Bad Request)，将移除 Key: {api_key[:10]}...")
             key_manager.remove_key(api_key)

    elif isinstance(e, httpx.TimeoutException):
        error_message = f"请求超时 ({key_identifier}): {e}"
        logger.error(error_message)
        # 超时通常不代表 Key 无效，不移除
    elif isinstance(e, httpx.RequestError):
        error_message = f"网络连接错误 ({key_identifier}): {e}"
        logger.error(error_message)
        # 网络问题不移除 Key
    elif isinstance(e, StreamProcessingError): # 处理自定义的流错误
         error_message = f"流处理错误 ({key_identifier}): {e}"
         logger.error(error_message) # 已在 stream_chat 中记录，这里可能重复
         # 不移除 Key，因为可能是内容问题
    else:
        # 其他未知 Python 异常
        logger.error(error_message, exc_info=True) # 记录完整堆栈

    return error_message # 返回格式化的错误消息

# --- 防滥用检查 ---
# 简单的基于 IP 的速率限制器 (内存实现)
ip_request_timestamps: Dict[str, List[float]] = defaultdict(list)
ip_daily_request_counts: Dict[Tuple[str, str], int] = defaultdict(int) # (date_str_pt, ip) -> count
ip_rate_limit_lock = Lock()

def get_client_ip(request: Request) -> str:
    """从请求中获取客户端 IP 地址"""
    # 优先检查 X-Forwarded-For (常见于反向代理)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For 可能包含多个 IP，取第一个
        client_ip = x_forwarded_for.split(",")[0].strip()
        return client_ip
    # 其次检查 X-Real-IP (一些代理使用)
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()
    # 最后回退到直接连接的客户端 IP
    if request.client and request.client.host:
        return request.client.host
    return "unknown_ip" # 如果都无法获取

def protect_from_abuse(request: Request, max_rpm: int, max_rpd: int):
    """
    基于 IP 地址执行速率限制 (RPM 和 RPD)。
    如果超过限制，则引发 HTTPException(429)。
    """
    client_ip = get_client_ip(request) # 使用之前的辅助函数
    if client_ip == "unknown_ip":
        logger.warning("无法获取客户端 IP，跳过速率限制检查。")
        return

    now = time.time()
    # 获取太平洋时间的日期字符串
    pt_tz = pytz.timezone('America/Los_Angeles')
    today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d')

    with ip_rate_limit_lock:
        # --- RPD 检查 ---
        daily_key = (today_date_str_pt, client_ip)
        current_daily_count = ip_daily_request_counts.get(daily_key, 0)
        if current_daily_count >= max_rpd:
            logger.warning(f"IP {client_ip} 已达到每日请求限制 ({max_rpd})。")
            raise HTTPException(status_code=429, detail=f"您已达到每日请求限制。请稍后再试。")

        # --- RPM 检查 ---
        timestamps = ip_request_timestamps[client_ip]
        # 移除一分钟前的时间戳
        one_minute_ago = now - 60
        timestamps[:] = [ts for ts in timestamps if ts > one_minute_ago]
        # 检查当前窗口内的请求数
        if len(timestamps) >= max_rpm:
            logger.warning(f"IP {client_ip} 已达到每分钟请求限制 ({max_rpm})。")
            raise HTTPException(status_code=429, detail=f"请求过于频繁。请稍后再试。")

        # --- 更新计数 ---
        # 添加当前时间戳 (RPM)
        timestamps.append(now)
        # 增加每日计数 (RPD)
        ip_daily_request_counts[daily_key] = current_daily_count + 1

    logger.debug(f"IP {client_ip} 速率限制检查通过 (RPM: {len(timestamps)}/{max_rpm}, RPD: {ip_daily_request_counts[daily_key]}/{max_rpd})")
