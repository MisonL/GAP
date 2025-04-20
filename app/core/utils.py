# app/core/utils.py
# 导入必要的库
import random  # 用于生成随机数和进行随机选择
from fastapi import HTTPException, Request  # FastAPI 框架的 HTTP 异常和请求对象
import time      # 用于时间相关操作（例如速率限制、时间戳）
import re        # 用于正则表达式操作（例如提取 API 密钥）
from datetime import datetime, timedelta  # 用于日期和时间计算
import os        # 用于访问操作系统环境变量
import httpx     # 用于发送异步 HTTP 请求（例如测试密钥有效性）
from threading import Lock # 用于线程同步的锁
import logging   # 用于应用程序的日志记录
import sys       # 用于访问系统特定的参数和函数
import pytz      # 用于处理不同的时区（例如太平洋时间）
from typing import Optional, Dict, Any, Set, List, Tuple # 类型提示，确保导入 List 和 Tuple
import json      # 用于处理 JSON 数据
import copy      # 用于创建对象的深拷贝或浅拷贝
from collections import defaultdict # 提供默认值的字典子类
# from ..handlers.log_config import format_log_message # 未在此文件中使用
# 从 tracking 模块导入共享的数据结构、锁和常量
from .tracking import ( # 从同级目录导入
    usage_data, usage_lock,
    key_scores_cache, cache_lock, cache_last_updated, update_cache_timestamp,
    # daily_rpd_totals, daily_totals_lock, # 未在此文件中使用
    # ip_daily_counts, ip_counts_lock, # 未在此文件中使用 (使用本文件的 ip_daily_request_counts)
    # ip_daily_input_token_counts, ip_input_token_counts_lock, # 未在此文件中使用
    RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, CACHE_REFRESH_INTERVAL_SECONDS
)
# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

# --- API 密钥管理器类 ---
class APIKeyManager:
    """
    管理 Gemini API 密钥，包括轮询、随机化、无效密钥处理以及基于使用情况的智能选择。
    """
    def __init__(self):
        """初始化 APIKeyManager"""
        raw_keys = os.environ.get('GEMINI_API_KEYS', "")
        self.api_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", raw_keys)
        self.keys_lock = Lock() # 用于保护 api_keys 列表访问的线程锁
        self.tried_keys_for_request: Set[str] = set() # 存储当前 API 请求已尝试过的 Key 集合
        self.initial_key_count = len(self.api_keys) # 存储初始加载的密钥数量

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
                return None # 如果没有可用的 Key，返回 None
            # 找到所有尚未在当前请求中尝试过的 Key
            available_keys = [k for k in self.api_keys if k not in self.tried_keys_for_request]
            if not available_keys:
                return None # 如果所有 Key 都已尝试过，返回 None

            # 简单的轮询策略：选择可用列表中的第一个 Key
            # 更复杂的选择策略（例如随机、基于负载）可以在这里实现
            key_to_use = available_keys[0]
            # 注意：不在管理器内部将 Key 标记为已尝试，由调用 select_best_key 或 get_next_key 的函数负责标记
            return key_to_use

    def select_best_key(self, model_name: str, model_limits: Dict[str, Any]) -> Optional[str]:
        """
        基于缓存的健康度评分选择最佳 API 密钥。
        如果缓存无效或所有 Key 都超限/已尝试，则返回 None。
        """
        with cache_lock:
            now = time.time()
            # 检查特定模型的缓存是否已超过刷新间隔
            if now - cache_last_updated.get(model_name, 0) > CACHE_REFRESH_INTERVAL_SECONDS:
                logger.info(f"模型 '{model_name}' 的 Key 分数缓存已过期，正在后台刷新...")
                # 注意：这里的更新是同步的，可能会阻塞请求。考虑改为异步任务。
                self._update_key_scores(model_name, model_limits) # 调用内部方法更新分数
                update_cache_timestamp(model_name) # 更新该模型缓存的最后更新时间戳

            # 获取当前模型的缓存分数（字典：key -> score）
            scores = key_scores_cache.get(model_name, {})
            if not scores:
                logger.warning(f"模型 '{model_name}' 没有可用的 Key 分数缓存数据。")
                # 尝试立即更新一次缓存，以防首次加载或数据丢失
                self._update_key_scores(model_name, model_limits)
                scores = key_scores_cache.get(model_name, {}) # 重新获取分数
                if not scores:
                     logger.error(f"尝试更新后，仍然无法获取模型 '{model_name}' 的 Key 分数缓存。")
                     return self.get_next_key() # 如果仍然失败，回退到简单的轮询获取 Key

            # 从缓存分数中过滤掉那些已在当前请求中尝试过的 Key
            available_scores = {k: v for k, v in scores.items() if k not in self.tried_keys_for_request}

            if not available_scores:
                logger.warning(f"模型 '{model_name}' 的所有可用 Key（根据缓存）均已在此请求中尝试过。")
                return None # 没有可用的 Key

            # 按分数降序排序，选择分数最高的 Key（注释掉旧的排序方法）
            # sorted_keys = sorted(available_scores, key=available_scores.get, reverse=True) # type: ignore
            # 改为直接查找分数最高的 Key
            best_key = max(available_scores, key=available_scores.get) # type: ignore # 忽略类型检查器的潜在警告
            best_score = available_scores[best_key] # 获取最高分

            logger.info(f"为模型 '{model_name}' 选择的最佳 Key: {best_key[:8]}... (分数: {best_score:.2f})")
            return best_key


    def _update_key_scores(self, model_name: str, model_limits: Dict[str, Any]):
        """
        内部方法：更新指定模型的 API 密钥健康度评分缓存。
        """
        global key_scores_cache # 声明将要修改全局变量 key_scores_cache
        with self.keys_lock: # 获取锁以安全访问 api_keys 列表
            if not self.api_keys:
                key_scores_cache[model_name] = {} # 如果没有活动的 Key，清空该模型的缓存
                return # 直接返回

            current_scores = {} # 用于存储本次计算的分数
            limits = model_limits # 直接使用传入的 model_limits
            if not limits:
                logger.warning(f"模型 '{model_name}' 的限制信息未提供，无法计算健康度评分。将为所有 Key 设置默认分数 1.0。")
                # 为所有当前活动的 Key 设置默认分数 1.0
                # 这允许它们被选中，但选择可能不是最优的
                current_scores = {key: 1.0 for key in self.api_keys}
            else:
                with usage_lock: # 获取锁以安全访问 usage_data
                    for key in self.api_keys: # 遍历所有当前活动的 Key
                        # 获取该 Key 对该模型的使用数据，如果不存在则为空字典
                        key_usage = usage_data.get(key, {}).get(model_name, {})
                        # 调用内部方法计算健康度分数
                        score = self._calculate_key_health(key_usage, limits)
                        current_scores[key] = score # 存储计算出的分数
                        logger.debug(f"计算 Key {key[:8]}... 对模型 '{model_name}' 的健康度分数: {score:.2f}")

            key_scores_cache[model_name] = current_scores
            logger.debug(f"模型 '{model_name}' 的 Key 分数缓存已更新。") # 将日志级别改为 DEBUG，因为这会频繁发生


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
        total_score = 0.0 # 初始化总加权分数
        active_metrics = 0.0 # 初始化有效指标的总权重

        # 计算 RPD 剩余百分比
        rpd_limit = limits.get("rpd")
        if rpd_limit is not None and rpd_limit > 0:
            rpd_used = key_usage.get("rpd_count", 0)
            rpd_remaining_ratio = max(0.0, 1.0 - (rpd_used / rpd_limit))
            total_score += rpd_remaining_ratio * weights["rpd"] # 累加加权分数
            active_metrics += weights["rpd"] # 累加权重
        elif rpd_limit == 0: # 如果 RPD 限制明确设置为 0，则此指标无效
             pass
        # else: RPD 限制未定义或为 None，忽略此指标

        # 计算 TPD_Input 剩余百分比
        tpd_input_limit = limits.get("tpd_input")
        if tpd_input_limit is not None and tpd_input_limit > 0:
            tpd_input_used = key_usage.get("tpd_input_count", 0)
            tpd_input_remaining_ratio = max(0.0, 1.0 - (tpd_input_used / tpd_input_limit))
            total_score += tpd_input_remaining_ratio * weights["tpd_input"]
            active_metrics += weights["tpd_input"]
        elif tpd_input_limit == 0: # 如果 TPD_Input 限制明确设置为 0，则此指标无效
             pass
        # else: TPD_Input 限制未定义或为 None，忽略此指标

        # 计算 RPM 剩余百分比 (基于当前窗口)
        rpm_limit = limits.get("rpm")
        if rpm_limit is not None and rpm_limit > 0:
            rpm_used = 0
            if time.time() - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS:
                rpm_used = key_usage.get("rpm_count", 0)
            rpm_remaining_ratio = max(0.0, 1.0 - (rpm_used / rpm_limit))
            total_score += rpm_remaining_ratio * weights["rpm"]
            active_metrics += weights["rpm"]
        elif rpm_limit == 0: # 如果 RPM 限制明确设置为 0，则此指标无效
             pass
        # else: RPM 限制未定义或为 None，忽略此指标

        # 计算 TPM_Input 剩余百分比 (基于当前窗口)
        tpm_input_limit = limits.get("tpm_input")
        if tpm_input_limit is not None and tpm_input_limit > 0:
            tpm_input_used = 0
            if time.time() - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                tpm_input_used = key_usage.get("tpm_input_count", 0)
            tpm_input_remaining_ratio = max(0.0, 1.0 - (tpm_input_used / tpm_input_limit))
            total_score += tpm_input_remaining_ratio * weights["tpm_input"]
            active_metrics += weights["tpm_input"]
        elif tpm_input_limit == 0: # 如果 TPM_Input 限制明确设置为 0，则此指标无效
             pass
        # else: TPM_Input 限制未定义或为 None，忽略此指标

        # 如果没有任何有效指标，返回一个默认值（例如 1.0，表示可用）
        if active_metrics == 0:
            return 1.0

        # 返回归一化的加权平均分
        normalized_score = total_score / active_metrics if active_metrics > 0 else 1.0
        # 确保分数在 0.0 到 1.0 之间（尽管理论上应该如此）
        return max(0.0, min(1.0, normalized_score))


    def remove_key(self, key_to_remove: str):
        """从管理器中移除指定的 API 密钥"""
        with self.keys_lock:
            if key_to_remove in self.api_keys:
                self.api_keys.remove(key_to_remove)
                logger.info(f"API Key {key_to_remove[:10]}... 已从活动池中移除。")
                # 同时从所有模型的缓存中移除该 Key 的分数记录
                with cache_lock: # 获取缓存锁
                    for model_name in list(key_scores_cache.keys()): # 迭代 key 的副本以允许修改
                        if key_to_remove in key_scores_cache[model_name]:
                            del key_scores_cache[model_name][key_to_remove] # 删除该 Key 的分数条目
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
                    logger.warning(f"Key {api_key[:8]}... 因问题 '{issue_type}' 被标记，其在模型 '{model_name}' 的分数暂时降低。")
                    # 可以在这里添加更复杂的逻辑，例如：
                    # - 记录标记次数，达到阈值后彻底移除 Key
                    # - 设置一个标记过期时间，之后恢复分数
                    # break # 移除 break，以便为所有模型降低分数

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
    async with httpx.AsyncClient() as client: # 创建异步 HTTP 客户端
        test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}" # 使用列出模型的端点进行测试
        try:
            response = await client.get(test_url, timeout=10.0) # 发送 GET 请求，设置 10 秒超时
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
                    error_body = response.json()
                    # 提取 Google API 返回的错误消息
                    error_detail += f", 错误: {error_body.get('error', {}).get('message', '未知 API 错误')}"
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
            logger.error(f"测试 Key {api_key[:10]}... 时发生未知错误: {e}", exc_info=True) # 记录完整错误信息和堆栈跟踪
            return False # 未知错误视为无效

# --- 错误处理辅助函数 ---
def handle_gemini_error(e: Exception, api_key: Optional[str], key_manager: APIKeyManager) -> str:
    """
    统一处理 Gemini API 调用中可能发生的异常。
    根据异常类型决定是否移除 API Key 并返回错误消息。
    """
    key_identifier = f"Key: {api_key[:10]}..." if api_key else "Key: N/A" # 用于日志记录的 Key 标识符（部分显示）
    error_message = f"发生未知错误 ({key_identifier}): {e}" # 设置默认错误消息

    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code
        error_body = e.response.text
        try:
            error_json = e.response.json()
            api_error_message = error_json.get("error", {}).get("message", error_body)
        except json.JSONDecodeError:
            api_error_message = error_body

        error_message = f"API 错误 (状态码 {status_code}, {key_identifier}): {api_error_message}" # 格式化错误消息
        logger.error(error_message) # 使用 ERROR 级别记录 API 返回的错误

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
        logger.error(error_message) # 记录错误
        # 超时通常不代表 Key 本身无效，可能是网络波动或服务端暂时问题，因此不移除 Key
    elif isinstance(e, httpx.RequestError):
        error_message = f"网络连接错误 ({key_identifier}): {e}"
        logger.error(error_message) # 记录错误
        # 网络连接问题不移除 Key
    # elif isinstance(e, StreamProcessingError): # 移除未使用的异常处理
    #      error_message = f"流处理错误 ({key_identifier}): {e}"
    #      logger.error(error_message)
    #      # 流处理错误通常与响应内容有关，不代表 Key 无效，不移除 Key
    else:
        # 处理所有其他类型的 Python 异常
        logger.error(error_message, exc_info=True) # 使用 ERROR 级别记录，并包含异常信息和堆栈跟踪

    return error_message # 返回格式化的错误消息

# --- 防滥用检查 ---
# 简单的基于 IP 的速率限制器（内存实现，非分布式）
ip_request_timestamps: Dict[str, List[float]] = defaultdict(list) # 存储每个 IP 最近一分钟的请求时间戳列表
ip_daily_request_counts: Dict[Tuple[str, str], int] = defaultdict(int) # 存储每个 IP 在太平洋时间某天的请求总数 (date_str_pt, ip) -> count
ip_rate_limit_lock = Lock() # 用于保护上述两个字典访问的线程锁

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

        # --- RPM (Requests Per Minute) 检查 ---
        timestamps = ip_request_timestamps[client_ip] # 获取该 IP 的时间戳列表
        # 清理掉列表中所有超过一分钟的时间戳
        one_minute_ago = now - 60 # 计算一分钟前的时间点
        # 使用列表切片赋值原地修改列表，移除旧时间戳
        timestamps[:] = [ts for ts in timestamps if ts > one_minute_ago]
        # 检查清理后，剩余时间戳的数量（即最近一分钟的请求数）是否达到限制
        if len(timestamps) >= max_rpm:
            logger.warning(f"IP {client_ip} 已达到每分钟请求速率限制 ({max_rpm} RPM)。")
            raise HTTPException(status_code=429, detail=f"请求过于频繁。请稍后再试。") # 返回 429 Too Many Requests

        # --- 如果检查通过，则更新计数 ---
        # 添加当前请求的时间戳（用于 RPM 跟踪）
        timestamps.append(now)
        # 增加该 IP 当日的请求总数（用于 RPD 跟踪）
        ip_daily_request_counts[daily_key] = current_daily_count + 1

    logger.debug(f"IP {client_ip} 速率限制检查通过 (RPM: {len(timestamps)}/{max_rpm}, RPD: {ip_daily_request_counts[daily_key]}/{max_rpd})")
