# app/core/utils.py
# 导入必要的库
# Import necessary libraries
import random  # 用于生成随机数和进行随机选择 (Used for generating random numbers and making random selections)
from fastapi import HTTPException, Request  # FastAPI 框架的 HTTP 异常和请求对象 (HTTP exceptions and request objects for FastAPI framework)
import time      # 用于时间相关操作（例如速率限制、时间戳） (Used for time-related operations (e.g., rate limiting, timestamps))
import re        # 用于正则表达式操作（例如提取 API 密钥） (Used for regular expression operations (e.g., extracting API keys))
from datetime import datetime, timedelta  # 用于日期和时间计算 (Used for date and time calculations)
import os        # 用于访问操作系统环境变量 (Used for accessing operating system environment variables)
import httpx     # 用于发送异步 HTTP 请求（例如测试密钥有效性） (Used for sending asynchronous HTTP requests (e.g., testing key validity))
from threading import Lock # 用于线程同步的锁 (Used for thread synchronization locks)
import logging   # 用于应用程序的日志记录 (Used for application logging)
import sys       # 用于访问系统特定的参数和函数 (Used for accessing system-specific parameters and functions)
from typing import Dict, Any, Optional, List, Tuple, Set # 确保导入了 Dict, Any, Optional, List, Tuple, Set (Ensure Dict, Any, Optional, List, Tuple, Set are imported)
import pytz      # 用于处理不同的时区（例如太平洋时间） (Used for handling different time zones (e.g., Pacific Time))
from typing import Optional, Dict, Any, Set, List, Tuple # 类型提示，确保导入 List 和 Tuple (Type hints, ensure List and Tuple are imported)
import json      # 用于处理 JSON 数据 (Used for handling JSON data)
import copy      # 用于创建对象的深拷贝或浅拷贝 (Used for creating deep or shallow copies of objects)
from collections import defaultdict # 提供默认值的字典子类 (Subclass of dictionary that provides default values)
# from ..handlers.log_config import format_log_message # 未在此文件中使用 (Not used in this file)
# 从 tracking 模块导入共享的数据结构、锁和常量
# Import shared data structures, locks, and constants from the tracking module
from .tracking import ( # 从同级目录导入 (Import from sibling directory)
    usage_data, usage_lock, # 使用情况数据和锁 (Usage data and lock)
    key_scores_cache, cache_lock, cache_last_updated, update_cache_timestamp, # Key 分数缓存、锁、最后更新时间戳和更新函数 (Key scores cache, lock, last updated timestamp, and update function)
    # daily_rpd_totals, daily_totals_lock, # 未在此文件中使用 (Not used in this file)
    # ip_daily_counts, ip_counts_lock, # 未在此文件中使用 (使用本文件的 ip_daily_request_counts) (Not used in this file (using ip_daily_request_counts from this file))
    # ip_daily_input_token_counts, ip_input_token_counts_lock, # 未在此文件中使用 (Not used in this file)
    RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, CACHE_REFRESH_INTERVAL_SECONDS # 常量：RPM/TPM 窗口和缓存刷新间隔 (Constants: RPM/TPM window and cache refresh interval)
)
# 获取名为 'my_logger' 的日志记录器实例
# Get the logger instance named 'my_logger'
logger = logging.getLogger("my_logger")

# --- API 密钥管理器类 ---
# --- API Key Manager Class ---
class APIKeyManager:
    """
    管理 Gemini API 密钥，包括轮询、随机化、无效密钥处理以及基于使用情况的智能选择。
    Manages Gemini API keys, including polling, randomization, invalid key handling, and smart selection based on usage.
    """
    def __init__(self):
        """
        初始化 APIKeyManager。
        Initializes the APIKeyManager.
        """
        raw_keys = os.environ.get('GEMINI_API_KEYS', "") # 从环境变量获取原始 Key 字符串 (Get raw key string from environment variable)
        # 使用正则表达式查找并提取有效的 API Key
        # Use regular expression to find and extract valid API keys
        self.api_keys: List[str] = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", raw_keys)
        # 初始化 Key 配置字典
        # Initialize the key configuration dictionary
        self.key_configs: Dict[str, Dict[str, Any]] = {}
        # 为每个加载的 Key 设置默认配置
        # Set default configuration for each loaded key
        for key in self.api_keys:
            self.key_configs[key] = {'enable_context_completion': True} # 默认启用上下文补全 (Enable context completion by default)

        self.keys_lock = Lock() # 用于保护 api_keys 和 key_configs 访问的线程锁 (Thread lock to protect access to api_keys and key_configs)
        self.tried_keys_for_request: Set[str] = set() # 存储当前 API 请求已尝试过的 Key 集合 (Set to store keys already attempted for the current API request)

    def get_key_config(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 API Key 的配置。
        Gets the configuration for the specified API key.

        Args:
            api_key: 要获取配置的 API Key。The API key to get the configuration for.

        Returns:
            包含配置的字典，如果 Key 不存在则返回 None。A dictionary containing the configuration, or None if the key does not exist.
        """
        with self.keys_lock: # 获取锁以安全访问配置 (Acquire lock for safe access to configuration)
            return self.key_configs.get(api_key) # 返回配置，不存在则为 None (Return config, None if not exists)

    def update_key_config(self, api_key: str, config_update: Dict[str, Any]):
        """
        更新指定 API Key 的配置。
        Updates the configuration for the specified API key.

        Args:
            api_key: 要更新配置的 API Key。The API key to update the configuration for.
            config_update: 包含要更新的配置项的字典。A dictionary containing the configuration items to update.
        """
        with self.keys_lock: # 获取锁以安全修改配置 (Acquire lock for safe modification of configuration)
            if api_key in self.key_configs:
                self.key_configs[api_key].update(config_update) # 更新现有配置 (Update existing configuration)
                logger.info(f"API Key {api_key[:10]}... 的配置已更新: {config_update}") # 记录配置更新日志 (Log configuration update)
            else:
                logger.warning(f"尝试更新不存在的 API Key 的配置: {api_key[:10]}...") # 记录警告日志 (Log warning)

    # Removed get_initial_key_count as it's no longer needed here
    # def get_initial_key_count(self) -> int:
    #     """返回初始配置的密钥数量"""
    #     return self.initial_key_count

    def get_next_key(self) -> Optional[str]:
        """
        轮询获取下一个 API 密钥。
        如果所有密钥都已尝试过，则返回 None。
        Polls for the next API key.
        Returns None if all keys have been attempted.
        """
        with self.keys_lock: # 获取 Key 列表锁 (Acquire the key list lock)
            if not self.api_keys:
                return None # 如果没有可用的 Key，返回 None (Return None if no keys are available)
            # 找到所有尚未在当前请求中尝试过的 Key
            # Find all keys that have not yet been attempted in the current request
            available_keys = [k for k in self.api_keys if k not in self.tried_keys_for_request]
            if not available_keys:
                return None # 如果所有 Key 都已尝试过，返回 None (Return None if all keys have been attempted)

            # 简单的轮询策略：选择可用列表中的第一个 Key
            # Simple polling strategy: select the first key in the available list
            # 更复杂的选择策略（例如随机、基于负载）可以在这里实现
            # More complex selection strategies (e.g., random, load-based) can be implemented here
            key_to_use = available_keys[0]
            # 注意：不在管理器内部将 Key 标记为已尝试，由调用 select_best_key 或 get_next_key 的函数负责标记
            # Note: Keys are not marked as attempted internally by the manager; the function calling select_best_key or get_next_key is responsible for marking them.
            return key_to_use

    def select_best_key(self, model_name: str, model_limits: Dict[str, Any]) -> Optional[str]:
        """
        基于缓存的健康度评分选择最佳 API 密钥。
        如果缓存无效或所有 Key 都超限/已尝试，则返回 None。
        Selects the best API key based on cached health scores.
        Returns None if the cache is invalid or all keys are over limit/attempted.
        """
        with cache_lock: # 获取缓存锁 (Acquire the cache lock)
            now = time.time()
            # 检查特定模型的缓存是否已超过刷新间隔
            # Check if the cache for the specific model has exceeded the refresh interval
            if now - cache_last_updated.get(model_name, 0) > CACHE_REFRESH_INTERVAL_SECONDS:
                logger.info(f"模型 '{model_name}' 的 Key 分数缓存已过期，正在后台刷新...") # Log cache expiration and refresh attempt
                # 注意：这里的更新是同步的，可能会阻塞请求。考虑改为异步任务。
                # Note: The update here is synchronous and might block requests. Consider changing to an asynchronous task.
                self._update_key_scores(model_name, model_limits) # 调用内部方法更新分数 (Call internal method to update scores)
                update_cache_timestamp(model_name) # 更新该模型缓存的最后更新时间戳 (Update the last updated timestamp for this model's cache)

            # 获取当前模型的缓存分数（字典：key -> score）
            # Get the cached scores for the current model (dictionary: key -> score)
            scores = key_scores_cache.get(model_name, {})
            if not scores:
                logger.warning(f"模型 '{model_name}' 没有可用的 Key 分数缓存数据。") # Log warning if no key score cache data is available
                # 尝试立即更新一次缓存，以防首次加载或数据丢失
                # Attempt to update the cache immediately in case of initial load or data loss
                self._update_key_scores(model_name, model_limits)
                scores = key_scores_cache.get(model_name, {}) # 重新获取分数 (Retrieve scores again)
                if not scores:
                     logger.error(f"尝试更新后，仍然无法获取模型 '{model_name}' 的 Key 分数缓存。") # Log error if still unable to get scores after update attempt
                     return self.get_next_key() # 如果仍然失败，回退到简单的轮询获取 Key (If still fails, fall back to simple polling to get a key)

            # 从缓存分数中过滤掉那些已在当前请求中尝试过的 Key
            # Filter out keys from cached scores that have already been attempted in the current request
            available_scores = {k: v for k, v in scores.items() if k not in self.tried_keys_for_request}

            if not available_scores:
                logger.warning(f"模型 '{model_name}' 的所有可用 Key（根据缓存）均已在此请求中尝试过。") # Log warning if all available keys (based on cache) have been attempted in this request
                return None # 没有可用的 Key (No available keys)

            # 按分数降序排序，选择分数最高的 Key（注释掉旧的排序方法）
            # Sort by score in descending order, select the key with the highest score (commented out old sorting method)
            # sorted_keys = sorted(available_scores, key=available_scores.get, reverse=True) # type: ignore
            # 改为直接查找分数最高的 Key
            # Changed to directly find the key with the highest score
            best_key = max(available_scores, key=available_scores.get) # type: ignore # 忽略类型检查器的潜在警告 (Ignore potential warning from type checker)
            best_score = available_scores[best_key] # 获取最高分 (Get the highest score)

            logger.info(f"为模型 '{model_name}' 选择的最佳 Key: {best_key[:8]}... (分数: {best_score:.2f})") # Log the best key selected
            return best_key


    def _update_key_scores(self, model_name: str, model_limits: Dict[str, Any]):
        """
        内部方法：更新指定模型的 API 密钥健康度评分缓存。
        Internal method: Updates the API key health score cache for the specified model.
        """
        global key_scores_cache # 声明将要修改全局变量 key_scores_cache (Declare that the global variable key_scores_cache will be modified)
        with self.keys_lock: # 获取锁以安全访问 api_keys 列表 (Acquire lock for safe access to the api_keys list)
            if not self.api_keys:
                key_scores_cache[model_name] = {} # 如果没有活动的 Key，清空该模型的缓存 (If there are no active keys, clear the cache for this model)
                return # 直接返回 (Return directly)

            current_scores = {} # 用于存储本次计算的分数 (Used to store scores calculated in this run)
            limits = model_limits # 直接使用传入的 model_limits (Use the passed model_limits directly)
            if not limits:
                logger.warning(f"模型 '{model_name}' 的限制信息未提供，无法计算健康度评分。将为所有 Key 设置默认分数 1.0。") # Log warning if limit information is not provided
                # 为所有当前活动的 Key 设置默认分数 1.0
                # Set a default score of 1.0 for all currently active keys
                # 这允许它们被选中，但选择可能不是最优的
                # This allows them to be selected, but the selection might not be optimal
                current_scores = {key: 1.0 for key in self.api_keys}
            else:
                with usage_lock: # 获取锁以安全访问 usage_data (Acquire lock for safe access to usage_data)
                    for key in self.api_keys: # 遍历所有当前活动的 Key (Iterate through all currently active keys)
                        # 获取该 Key 对该模型的使用数据，如果不存在则为空字典
                        # Get usage data for this key for this model, or an empty dictionary if it doesn't exist
                        key_usage = usage_data.get(key, {}).get(model_name, {})
                        # 调用内部方法计算健康度分数
                        # Call internal method to calculate health score
                        score = self._calculate_key_health(key_usage, limits)
                        current_scores[key] = score # 存储计算出的分数 (Store the calculated score)
                        logger.debug(f"计算 Key {key[:8]}... 对模型 '{model_name}' 的健康度分数: {score:.2f}") # Log the calculated score (DEBUG level)

            key_scores_cache[model_name] = current_scores # 更新该模型的缓存分数 (Update the cached scores for this model)
            logger.debug(f"模型 '{model_name}' 的 Key 分数缓存已更新。") # 将日志级别改为 DEBUG，因为这会频繁发生 (Changed log level to DEBUG as this happens frequently)


    def _calculate_key_health(self, key_usage: Dict[str, Any], limits: Dict[str, Any]) -> float:
        """
        计算单个 API 密钥针对特定模型的健康度评分 (0.0 - 1.0+)。
        分数越高越好。综合考虑 RPD, TPD_Input, RPM, TPM_Input 的剩余百分比。
        Calculates the health score (0.0 - 1.0+) for a single API key for a specific model.
        Higher score is better. Considers the remaining percentage of RPD, TPD_Input, RPM, and TPM_Input.
        """
        # 定义各项指标的权重
        # Define weights for each metric
        # 权重可以根据实际情况调整，例如更看重日限制还是分钟限制
        # Weights can be adjusted based on actual needs, e.g., prioritizing daily limits or minute limits
        weights = {
            "rpd": 0.4,
            "tpd_input": 0.3,
            "rpm": 0.2,
            "tpm_input": 0.1
        }
        total_score = 0.0 # 初始化总加权分数 (Initialize total weighted score)
        active_metrics = 0.0 # 初始化有效指标的总权重 (Initialize total weight of active metrics)

        # 计算 RPD 剩余百分比
        # Calculate RPD remaining percentage
        rpd_limit = limits.get("rpd")
        if rpd_limit is not None and rpd_limit > 0:
            rpd_used = key_usage.get("rpd_count", 0)
            rpd_remaining_ratio = max(0.0, 1.0 - (rpd_used / rpd_limit))
            total_score += rpd_remaining_ratio * weights["rpd"] # 累加加权分数 (Accumulate weighted score)
            active_metrics += weights["rpd"] # 累加权重 (Accumulate weight)
        elif rpd_limit == 0: # 如果 RPD 限制明确设置为 0，则此指标无效
             # If RPD limit is explicitly set to 0, this metric is invalid
             pass
        # else: RPD 限制未定义或为 None，忽略此指标
        # else: RPD limit is undefined or None, ignore this metric

        # 计算 TPD_Input 剩余百分比
        # Calculate TPD_Input remaining percentage
        tpd_input_limit = limits.get("tpd_input")
        if tpd_input_limit is not None and tpd_input_limit > 0:
            tpd_input_used = key_usage.get("tpd_input_count", 0)
            tpd_input_remaining_ratio = max(0.0, 1.0 - (tpd_input_used / tpd_input_limit))
            total_score += tpd_input_remaining_ratio * weights["tpd_input"]
            active_metrics += weights["tpd_input"]
        elif tpd_input_limit == 0: # 如果 TPD_Input 限制明确设置为 0，则此指标无效
             # If TPD_Input limit is explicitly set to 0, this metric is invalid
             pass
        # else: TPD_Input 限制未定义或为 None，忽略此指标
        # else: TPD_Input limit is undefined or None, ignore this metric

        # 计算 RPM 剩余百分比 (基于当前窗口)
        # Calculate RPM remaining percentage (based on current window)
        rpm_limit = limits.get("rpm")
        if rpm_limit is not None and rpm_limit > 0:
            rpm_used = 0
            if time.time() - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS:
                rpm_used = key_usage.get("rpm_count", 0)
            rpm_remaining_ratio = max(0.0, 1.0 - (rpm_used / rpm_limit))
            total_score += rpm_remaining_ratio * weights["rpm"]
            active_metrics += weights["rpm"]
        elif rpm_limit == 0: # 如果 RPM 限制明确设置为 0，则此指标无效
             # If RPM limit is explicitly set to 0, this metric is invalid
             pass
        # else: RPM 限制未定义或为 None，忽略此指标
        # else: RPM limit is undefined or None, ignore this metric

        # 计算 TPM_Input 剩余百分比 (基于当前窗口)
        # Calculate TPM_Input remaining percentage (based on current window)
        tpm_input_limit = limits.get("tpm_input")
        if tpm_input_limit is not None and tpm_input_limit > 0:
            tpm_input_used = 0
            if time.time() - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                tpm_input_used = key_usage.get("tpm_input_count", 0)
            tpm_input_remaining_ratio = max(0.0, 1.0 - (tpm_input_used / tpm_input_limit))
            total_score += tpm_input_remaining_ratio * weights["tpm_input"]
            active_metrics += weights["tpm_input"]
        elif tpm_input_limit == 0: # 如果 TPM_Input 限制明确设置为 0，则此指标无效
             # If TPM_Input limit is explicitly set to 0, this metric is invalid
             pass
        # else: TPM_Input 限制未定义或为 None，忽略此指标
        # else: TPM_Input limit is undefined or None, ignore this metric

        # 如果没有任何有效指标，返回一个默认值（例如 1.0，表示可用）
        # If there are no active metrics, return a default value (e.g., 1.0, indicating available)
        if active_metrics == 0:
            return 1.0

        # 返回归一化的加权平均分
        # Return the normalized weighted average score
        normalized_score = total_score / active_metrics if active_metrics > 0 else 1.0
        # 确保分数在 0.0 到 1.0 之间（尽管理论上应该如此）
        # Ensure the score is between 0.0 and 1.0 (although it should theoretically be)
        return max(0.0, min(1.0, normalized_score))


    def remove_key(self, key_to_remove: str):
        """
        从管理器中移除指定的 API 密钥。
        Removes the specified API key from the manager.
        """
        with self.keys_lock: # 获取 Key 列表和配置锁 (Acquire the key list and config lock)
            if key_to_remove in self.api_keys:
                self.api_keys.remove(key_to_remove) # 从列表中移除 Key (Remove the key from the list)
                # 同时从配置字典中移除
                # Also remove from the configuration dictionary
                if key_to_remove in self.key_configs:
                    del self.key_configs[key_to_remove] # 删除 Key 配置 (Delete key configuration)

                logger.info(f"API Key {key_to_remove[:10]}... 已从活动池和配置中移除。") # Log key removal from pool and config
                # 同时从所有模型的缓存中移除该 Key 的分数记录
                # Also remove the score record for this key from the cache for all models
                with cache_lock: # 获取缓存锁 (Acquire the cache lock)
                    for model_name in list(key_scores_cache.keys()): # 迭代 key 的副本以允许修改 (Iterate over a copy of keys to allow modification)
                        if key_to_remove in key_scores_cache[model_name]:
                            del key_scores_cache[model_name][key_to_remove] # 删除该 Key 的分数条目 (Delete the score entry for this key)
            else:
                logger.warning(f"尝试移除不存在的 API Key: {key_to_remove[:10]}...") # Log warning if attempting to remove a non-existent key

    def mark_key_issue(self, api_key: str, issue_type: str = "unknown"):
        """
        标记某个 Key 可能存在问题（例如，被安全阻止）。
        当前实现：降低其在缓存中的分数，使其在一段时间内不太可能被选中。
        Marks a key as potentially having an issue (e.g., being safety blocked).
        Current implementation: Reduces its score in the cache, making it less likely to be selected for a period.
        """
        with cache_lock: # 获取缓存锁 (Acquire the cache lock)
            for model_name in key_scores_cache: # 遍历所有模型的缓存 (Iterate through the cache for all models)
                if api_key in key_scores_cache[model_name]:
                    # 显著降低分数，例如降到 0.1 或更低
                    # Significantly reduce the score, e.g., to 0.1 or lower
                    key_scores_cache[model_name][api_key] = 0.1
                    logger.warning(f"Key {api_key[:8]}... 因问题 '{issue_type}' 被标记，其在模型 '{model_name}' 的分数暂时降低。") # Log that the key is marked and score is reduced
                    # 可以在这里添加更复杂的逻辑，例如：
                    # More complex logic can be added here, such as:
                    # - 记录标记次数，达到阈值后彻底移除 Key
                    # - Recording the number of times marked, and permanently removing the key after reaching a threshold
                    # - 设置一个标记过期时间，之后恢复分数
                    # - Setting an expiration time for the mark, after which the score is restored
                    # break # 移除 break，以便为所有模型降低分数 (Removed break to lower the score for all models)

    def get_active_keys_count(self) -> int:
        """
        返回当前管理器中有效（未被移除）的密钥数量。
        Returns the number of valid (not removed) keys in the current manager.
        """
        with self.keys_lock: # 获取 Key 列表锁 (Acquire the key list lock)
            return len(self.api_keys) # 返回 Key 列表的长度 (Return the length of the api_keys list)

    def reset_tried_keys_for_request(self):
        """
        为新的 API 请求重置已尝试的密钥集合。
        Resets the set of attempted keys for a new API request.
        """
        self.tried_keys_for_request.clear() # 清空已尝试的 Key 集合 (Clear the set of attempted keys)
        logger.debug("已重置当前请求的已尝试密钥集合。") # Log that the set has been reset (DEBUG level)


# --- 全局 Key Manager 实例 ---
# --- Global Key Manager Instance ---
# 在模块加载时创建单例
# Create a singleton instance when the module is loaded
key_manager_instance = APIKeyManager()

# --- API 密钥测试函数 ---
# --- API Key Test Function ---
async def test_api_key(api_key: str) -> bool:
    """
    [异步] 测试单个 Gemini API 密钥的有效性。
    尝试调用一个轻量级的 API 端点，例如列出模型。
    [Async] Tests the validity of a single Gemini API key.
    Attempts to call a lightweight API endpoint, such as listing models.

    Args:
        api_key: 要测试的 API 密钥。The API key to test.

    Returns:
        如果密钥有效则返回 True，否则返回 False。Returns True if the key is valid, False otherwise.
    """
    # 使用 httpx 进行异步请求
    # Use httpx for asynchronous requests
    async with httpx.AsyncClient() as client: # 创建异步 HTTP 客户端 (Create an asynchronous HTTP client)
        test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}" # 使用列出模型的端点进行测试 (Use the list models endpoint for testing)
        try:
            response = await client.get(test_url, timeout=10.0) # 发送 GET 请求，设置 10 秒超时 (Send a GET request with a 10-second timeout)
            # 检查 HTTP 状态码是否为 200 (OK)
            # Check if the HTTP status code is 200 (OK)
            if response.status_code == 200:
                # 进一步检查响应内容是否符合预期（包含 'models' 列表）
                # Further check if the response content matches expectations (contains a 'models' list)
                try:
                    data = response.json() # 解析 JSON 响应 (Parse the JSON response)
                    if "models" in data and isinstance(data["models"], list):
                        logger.info(f"测试 Key {api_key[:10]}... 成功。") # Log successful test
                        return True # Key 有效 (Key is valid)
                    else:
                         logger.warning(f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但响应 JSON 格式不符合预期: {data}") # Log warning if JSON format is unexpected
                         return False # 响应格式不正确，视为无效 (Incorrect response format, considered invalid)
                except json.JSONDecodeError:
                     logger.warning(f"测试 Key {api_key[:10]}... 成功 (状态码 200)，但无法解析响应体为 JSON。") # Log warning if response body cannot be parsed as JSON
                     return False # 无法解析 JSON，视为无效 (Cannot parse JSON, considered invalid)
            else:
                # 如果状态码不是 200，记录错误详情
                # If the status code is not 200, log error details
                error_detail = f"状态码: {response.status_code}"
                try:
                    # 尝试解析错误响应体
                    # Attempt to parse the error response body
                    error_json = response.json()
                    # 提取 Google API 返回的错误消息
                    # Extract the error message returned by the Google API
                    error_detail += f", 错误: {error_json.get('error', {}).get('message', '未知 API 错误')}"
                except json.JSONDecodeError:
                    # 如果响应体不是 JSON，记录原始文本
                    # If the response body is not JSON, log the raw text
                    error_detail += f", 响应体: {response.text}"
                logger.warning(f"测试 Key {api_key[:10]}... 失败 ({error_detail})") # Log failed test with details
                return False # Key 无效 (Key is invalid)
        except httpx.TimeoutException:
            # 处理请求超时的情况
            # Handle request timeout cases
            logger.warning(f"测试 Key {api_key[:10]}... 请求超时。") # Log request timeout
            return False # 超时视为无效（或网络问题） (Timeout considered invalid (or network issue))
        except httpx.RequestError as e:
            # 处理网络连接错误等请求相关错误
            # Handle request-related errors such as network connection errors
            logger.warning(f"测试 Key {api_key[:10]}... 时发生网络请求错误: {e}") # Log network request error
            return False # 网络错误视为无效（或网络问题） (Network error considered invalid (or network issue))
        except Exception as e:
            # 捕获其他所有未预料到的异常
            # Catch all other unexpected exceptions
            logger.error(f"测试 Key {api_key[:10]}... 时发生未知错误: {e}", exc_info=True) # 记录完整错误信息和堆栈跟踪 (Log full error information and stack trace)
            return False # 未知错误视为无效 (Unknown error considered invalid)

# --- 错误处理辅助函数 ---
# --- Error Handling Helper Function ---
def handle_gemini_error(e: Exception, api_key: Optional[str], key_manager: APIKeyManager) -> str:
    """
    统一处理 Gemini API 调用中可能发生的异常。
    根据异常类型决定是否移除 API Key 并返回错误消息。
    Uniformly handles exceptions that may occur during Gemini API calls.
    Decides whether to remove the API key based on the exception type and returns an error message.

    Args:
        e: 发生的异常。The exception that occurred.
        api_key: 发生错误的 API 密钥 (如果可用)。The API key that caused the error (if available).
        key_manager: APIKeyManager 实例。The APIKeyManager instance.

    Returns:
        格式化的错误消息字符串。A formatted error message string.
    """
    key_identifier = f"Key: {api_key[:10]}..." if api_key else "Key: N/A" # 用于日志记录的 Key 标识符（部分显示） (Key identifier for logging (partially displayed))
    error_message = f"发生未知错误 ({key_identifier}): {e}" # 设置默认错误消息 (Set default error message)

    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code # 获取 HTTP 状态码 (Get HTTP status code)
        error_body = e.response.text # 获取响应体文本 (Get response body text)
        try:
            error_json = e.response.json() # 尝试解析 JSON 响应体 (Attempt to parse JSON response body)
            api_error_message = error_json.get("error", {}).get("message", error_body) # 提取 API 错误消息 (Extract API error message)
        except json.JSONDecodeError:
            api_error_message = error_body # 如果不是 JSON，使用原始文本 (If not JSON, use raw text)

        error_message = f"API 错误 (状态码 {status_code}, {key_identifier}): {api_error_message}" # 格式化错误消息 (Format the error message)
        logger.error(error_message) # 使用 ERROR 级别记录 API 返回的错误 (Log the API error using ERROR level)

        # 根据状态码判断是否移除 Key
        # Determine whether to remove the key based on the status code
        # 400 (通常是请求问题，例如无效参数或内容策略), 404 (模型不存在) - 不移除 Key
        # 400 (usually request issues, e.g., invalid parameters or content policy), 404 (model not found) - Do not remove key
        # 401, 403 (认证/权限问题) - 移除 Key
        # 401, 403 (authentication/permission issues) - Remove key
        # 429 (速率限制) - 不移除 Key (本地限制应处理，或等待 Google 解除)
        # 429 (rate limit) - Do not remove key (local limits should handle, or wait for Google to lift)
        # 500, 503 (服务器错误) - 可能暂时移除或标记，这里选择移除
        # 500, 503 (server errors) - May temporarily remove or mark, here choosing to remove
        if status_code in [401, 403, 500, 503] and api_key:
            logger.warning(f"由于 API 错误 (状态码 {status_code})，将移除无效或有问题的 Key: {api_key[:10]}...") # Log warning and key removal
            key_manager.remove_key(api_key) # 移除 Key (Remove the key)
        elif status_code == 400 and "API key not valid" in api_error_message and api_key:
             logger.warning(f"API 报告 Key 无效 (400 Bad Request)，将移除 Key: {api_key[:10]}...") # Log warning and key removal for invalid key (400)
             key_manager.remove_key(api_key) # 移除 Key (Remove the key)

    elif isinstance(e, httpx.TimeoutException):
        error_message = f"请求超时 ({key_identifier}): {e}" # 格式化超时错误消息 (Format timeout error message)
        logger.error(error_message) # 记录错误 (Log the error)
        # 超时通常不代表 Key 本身无效，可能是网络波动或服务端暂时问题，因此不移除 Key
        # Timeout usually does not mean the key itself is invalid, it might be network fluctuation or temporary server issue, so do not remove the key
    elif isinstance(e, httpx.RequestError):
        error_message = f"网络连接错误 ({key_identifier}): {e}" # 格式化网络错误消息 (Format network error message)
        logger.error(error_message) # 记录错误 (Log the error)
        # 网络连接问题不移除 Key
        # Network connection issues do not remove the key
    # elif isinstance(e, StreamProcessingError): # 移除未使用的异常处理 (Removed unused exception handling)
    #      error_message = f"流处理错误 ({key_identifier}): {e}"
    #      logger.error(error_message)
    #      # 流处理错误通常与响应内容有关，不代表 Key 无效，不移除 Key
    #      # Stream processing errors are usually related to response content, do not mean the key is invalid, do not remove the key
    else:
        # 处理所有其他类型的 Python 异常
        # Handle all other types of Python exceptions
        logger.error(error_message, exc_info=True) # 使用 ERROR 级别记录，并包含异常信息和堆栈跟踪 (Log using ERROR level and include exception info and stack trace)

    return error_message # 返回格式化的错误消息 (Return the formatted error message)

# --- 防滥用检查 ---
# --- Abuse Protection Check ---
# 简单的基于 IP 的速率限制器（内存实现，非分布式）
# Simple IP-based rate limiter (in-memory implementation, not distributed)
ip_request_timestamps: Dict[str, List[float]] = defaultdict(list) # 存储每个 IP 最近一分钟的请求时间戳列表 (Stores a list of request timestamps for each IP in the last minute)
ip_daily_request_counts: Dict[Tuple[str, str], int] = defaultdict(int) # 存储每个 IP 在太平洋时间某天的请求总数 (date_str_pt, ip) -> count (Stores the total number of requests for each IP on a given day in Pacific Time (date_str_pt, ip) -> count)
ip_rate_limit_lock = Lock() # 用于保护上述两个字典访问的线程锁 (Thread lock to protect access to the above two dictionaries)

def get_client_ip(request: Request) -> str:
    """
    从请求中获取客户端 IP 地址。
    Retrieves the client's IP address from the request.
    """
    # 优先检查 X-Forwarded-For (常见于反向代理)
    # Prioritize checking X-Forwarded-For (common with reverse proxies)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For 可能包含多个 IP，取第一个
        # X-Forwarded-For may contain multiple IPs, take the first one
        client_ip = x_forwarded_for.split(",")[0].strip()
        return client_ip
    # 其次检查 X-Real-IP (一些代理使用)
    # Secondly, check X-Real-IP (used by some proxies)
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()
    # 最后回退到直接连接的客户端 IP
    # Finally, fall back to the directly connected client IP
    if request.client and request.client.host:
        return request.client.host
    return "unknown_ip" # 如果都无法获取 (If none can be obtained)

def protect_from_abuse(request: Request, max_rpm: int, max_rpd: int):
    """
    基于 IP 地址执行速率限制 (RPM 和 RPD)。
    如果超过限制，则引发 HTTPException(429)。
    Performs rate limiting (RPM and RPD) based on the IP address.
    Raises HTTPException(429) if the limit is exceeded.

    Args:
        request: FastAPI 请求对象。The FastAPI request object.
        max_rpm: 每分钟最大请求数限制。The maximum requests per minute limit.
        max_rpd: 每日最大请求数限制。The maximum requests per day limit.

    Raises:
        HTTPException: 如果超过速率限制。If the rate limit is exceeded.
    """
    client_ip = get_client_ip(request) # 使用之前的辅助函数 (Use the previous helper function)
    if client_ip == "unknown_ip":
        logger.warning("无法获取客户端 IP，跳过速率限制检查。") # Log warning if client IP cannot be obtained
        return

    now = time.time()
    # 获取太平洋时间的日期字符串
    # Get the date string in Pacific Time
    pt_tz = pytz.timezone('America/Los_Angeles')
    today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d')

    with ip_rate_limit_lock: # 获取 IP 速率限制锁 (Acquire the IP rate limit lock)
        # --- RPD 检查 ---
        # --- RPD Check ---
        daily_key = (today_date_str_pt, client_ip) # 构建每日计数 Key (Build the daily count key)
        current_daily_count = ip_daily_request_counts.get(daily_key, 0) # 获取当前每日计数 (Get the current daily count)
        if current_daily_count >= max_rpd:
            logger.warning(f"IP {client_ip} 已达到每日请求限制 ({max_rpd})。") # Log warning if daily limit is reached
            raise HTTPException(status_code=429, detail=f"您已达到每日请求限制。请稍后再试。") # 引发 429 异常 (Raise 429 exception)

        # --- RPM (Requests Per Minute) 检查 ---
        # --- RPM (Requests Per Minute) Check ---
        timestamps = ip_request_timestamps[client_ip] # 获取该 IP 的时间戳列表 (Get the list of timestamps for this IP)
        # 清理掉列表中所有超过一分钟的时间戳
        # Clean up all timestamps in the list that are older than one minute
        one_minute_ago = now - 60 # 计算一分钟前的时间点 (Calculate the time point one minute ago)
        # 使用列表切片赋值原地修改列表，移除旧时间戳
        # Use list slicing assignment to modify the list in place, removing old timestamps
        timestamps[:] = [ts for ts in timestamps if ts > one_minute_ago]
        # 检查清理后，剩余时间戳的数量（即最近一分钟的请求数）是否达到限制
        # Check if the number of remaining timestamps after cleanup (i.e., requests in the last minute) has reached the limit
        if len(timestamps) >= max_rpm:
            logger.warning(f"IP {client_ip} 已达到每分钟请求速率限制 ({max_rpm} RPM)。") # Log warning if RPM limit is reached
            raise HTTPException(status_code=429, detail=f"请求过于频繁。请稍后再试。") # 返回 429 Too Many Requests (Return 429 Too Many Requests)

        # --- 如果检查通过，则更新计数 ---
        # --- If checks pass, update counts ---
        # 添加当前请求的时间戳（用于 RPM 跟踪）
        # Add the timestamp of the current request (for RPM tracking)
        timestamps.append(now)
        # 增加该 IP 当日的请求总数（用于 RPD 跟踪）
        # Increment the total number of requests for this IP on the current day (for RPD tracking)
        ip_daily_request_counts[daily_key] = current_daily_count + 1

    logger.debug(f"IP {client_ip} 速率限制检查通过 (RPM: {len(timestamps)}/{max_rpm}, RPD: {ip_daily_request_counts[daily_key]}/{max_rpd})") # Log successful rate limit check (DEBUG level)
