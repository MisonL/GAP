# app/core/key_manager_class.py
# 导入必要的库
import os        # 用于访问操作系统环境变量 (Used for accessing operating system environment variables)
import re        # 用于正则表达式操作（例如提取 API 密钥） (Used for regular expression operations (e.g., extracting API keys))
import time      # 用于时间相关操作（例如速率限制、时间戳） (Used for time-related operations (e.g., rate limiting, timestamps))
import logging   # 用于应用程序的日志记录 (Used for application logging)
from threading import Lock # 用于线程同步的锁 (Used for thread synchronization locks)
from typing import Dict, Any, Optional, List, Tuple, Set # 确保导入了 Dict, Any, Optional, List, Tuple, Set (Ensure Dict, Any, Optional, List, Tuple, Set are imported)
import copy      # 用于创建对象的深拷贝或浅拷贝 (Used for creating deep or shallow copies of objects)
from collections import defaultdict # 提供默认值的字典子类 (Subclass of dictionary that provides default values)
import asyncio # 导入 asyncio模块

# 从 tracking 模块导入共享的数据结构、锁和常量
# 注意：这里需要将相对导入改为绝对导入
from app.core.tracking import (
    usage_data, usage_lock, # 使用情况数据和锁
    key_scores_cache, cache_lock, cache_last_updated, update_cache_timestamp, # Key 分数缓存、锁、最后更新时间戳和更新函数
    RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, CACHE_REFRESH_INTERVAL_SECONDS # 常量：RPM/TPM 窗口和缓存刷新间隔
)

# 导入 datetime 和 pytz 用于处理时间和时区
from datetime import datetime
import pytz

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

class APIKeyManager:
    """
    管理 Gemini API 密钥，包括轮询、随机化、无效密钥处理以及基于使用情况的智能选择。
    """
    def __init__(self):
        """
        初始化 APIKeyManager。
        """
        # 密钥加载逻辑已移至 app/core/key_management.py 中的 check_keys 函数
        self.api_keys: List[str] = [] # 初始化为空列表，密钥将在 lifespan 中加载
        # 初始化 Key 配置字典
        self.key_configs: Dict[str, Dict[str, Any]] = {}
        # 为每个加载的 Key 设置默认配置
        for key in self.api_keys:
            self.key_configs[key] = {'enable_context_completion': True} # 默认启用上下文补全

        self.keys_lock = Lock() # 用于保护 api_keys 和 key_configs 访问的线程锁
        self.tried_keys_for_request: Set[str] = set() # 存储当前 API 请求已尝试过的 Key 集合
        # 新增：存储因每日配额耗尽而被标记为当天不可用的 Key 及其标记日期 (YYYY-MM-DD)
        self.daily_exhausted_keys: Dict[str, str] = {}
        # 缓存今天的日期字符串，避免在 is_key_daily_exhausted 中频繁获取
        self._today_date_str = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    def get_key_config(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 API Key 的配置。

        Args:
            api_key: 要获取配置的 API Key。

        Returns:
            包含配置的字典，如果 Key 不存在则返回 None。
        """
        with self.keys_lock:
            return self.key_configs.get(api_key)

    def update_key_config(self, api_key: str, config_update: Dict[str, Any]):
        """
        更新指定 API Key 的配置。

        Args:
            api_key: 要更新配置的 API Key。
            config_update: 包含要更新的配置项的字典。
        """
        with self.keys_lock:
            if api_key in self.key_configs:
                self.key_configs[api_key].update(config_update)
                logger.info(f"API Key {api_key[:10]}... 的配置已更新: {config_update}")
            else:
                logger.warning(f"尝试更新不存在的 API Key 的配置: {api_key[:10]}...") # 记录警告日志 (Log warning)


    def get_next_key(self) -> Optional[str]:
        """
        轮询获取下一个 API 密钥。
        如果所有密钥都已尝试过或当天不可用，则返回 None。
        """
        with self.keys_lock:
            if not self.api_keys:
                return None
            # 找到所有尚未在当前请求中尝试过且当天可用的 Key (使用内部不加锁方法)
            available_keys = [k for k in self.api_keys if k not in self.tried_keys_for_request and not self._is_key_daily_exhausted_nolock(k)]
            if not available_keys:
                return None

            # 简单的轮询策略：选择可用列表中的第一个 Key
            # 更复杂的选择策略（例如随机、基于负载）可以在这里实现
            key_to_use = available_keys[0]
            # 注意：不在管理器内部将 Key 标记为已尝试，由调用 select_best_key 或 get_next_key 的函数负责标记
            return key_to_use

    def select_best_key(self, model_name: str, model_limits: Dict[str, Any]) -> Optional[str]:
        """
        基于缓存的健康度评分选择最佳 API 密钥。
        排除当天已耗尽的 Key。如果缓存无效或所有 Key 都超限/已尝试/当天耗尽，则返回 None。
        """
        # 优先获取 keys_lock
        with self.keys_lock:
            # 获取当天不可用的 Key 集合
            daily_exhausted = {k for k, date_str in self.daily_exhausted_keys.items() if date_str == self._today_date_str}
            # 获取当前请求已尝试过的 Key 集合的副本
            tried_keys = self.tried_keys_for_request.copy()

            # 然后获取 cache_lock
            with cache_lock:
                now = time.time()
                # 检查特定模型的缓存是否已超过刷新间隔
                if now - cache_last_updated.get(model_name, 0) > CACHE_REFRESH_INTERVAL_SECONDS:
                    logger.info(f"模型 '{model_name}' 的 Key 分数缓存已过期，正在异步刷新...")
                    try:
                        import asyncio
                        asyncio.create_task(self._async_update_key_scores(model_name, model_limits))
                    except RuntimeError:
                        logger.warning("不在异步事件循环中，回退到同步刷新 Key 分数缓存。")
                        pass # 依赖于后台任务或下次调用刷新
                    update_cache_timestamp(model_name)

                # 获取当前模型的缓存分数（字典：key -> score）
                scores = key_scores_cache.get(model_name, {})
                if not scores:
                    logger.warning(f"模型 '{model_name}' 没有可用的 Key 分数缓存数据。尝试回退到轮询策略。")
                    # 如果缓存为空，回退到简单的轮询策略
                    # 过滤 Keys 列表，排除已尝试和当天耗尽的 Key
                    available_keys_for_polling = [k for k in self.api_keys if k not in tried_keys and k not in daily_exhausted]
                    if not available_keys_for_polling:
                         logger.warning(f"模型 '{model_name}' 没有 Key 分数缓存，且所有 Key 已在此请求中尝试过或当天已耗尽。")
                         return None # 没有 Key 可用，即使回退到轮询

                    # 简单的轮询：选择可用列表中的第一个 Key
                    key_to_use = available_keys_for_polling[0]
                    logger.info(f"模型 '{model_name}' 没有 Key 分数缓存，回退到轮询策略，选择 Key: {key_to_use[:8]}...")
                    return key_to_use


                # 过滤缓存分数，排除已尝试和当天耗尽的 Key
                available_scores = {}
                for k, v in scores.items():
                    # 检查是否已尝试、是否当天耗尽
                    if k not in tried_keys and k not in daily_exhausted:
                        available_scores[k] = v

                if not available_scores:
                    logger.warning(f"模型 '{model_name}' 的所有可用 Key（根据缓存）均已在此请求中尝试过或当天已耗尽。")
                    return None

                # 按分数降序排序，选择分数最高的 Key
                best_key = max(available_scores, key=available_scores.get) # type: ignore
                best_score = available_scores[best_key]

                logger.info(f"为模型 '{model_name}' 选择的最佳 Key: {best_key[:8]}... (分数: {best_score:.2f})")
                return best_key


    async def _async_update_key_scores(self, model_name: str, model_limits: Dict[str, Any]):
        """
        内部异步方法：更新指定模型的 API 密钥健康度评分缓存。
        """
        global key_scores_cache
        with self.keys_lock:
            if not self.api_keys:
                key_scores_cache[model_name] = {}
                return

            current_scores = {}
            limits = model_limits
            if not limits:
                logger.warning(f"模型 '{model_name}' 的限制信息未提供，无法计算健康度评分。将为所有 Key 设置默认分数 1.0。")
                # 为所有当前活动的 Key 设置默认分数 1.0
                # 这允许它们被选中，但选择可能不是最优的
                current_scores = {key: 1.0 for key in self.api_keys}
            else:
                with usage_lock:
                    for key in self.api_keys:
                        # 获取该 Key 对该模型的使用数据，如果不存在则为空字典
                        key_usage = usage_data.get(key, {}).get(model_name, {})
                        # 调用内部方法计算健康度分数
                        score = self._calculate_key_health(key_usage, limits)
                        current_scores[key] = score
                        logger.debug(f"计算 Key {key[:8]}... 对模型 '{model_name}' 的健康度分数: {score:.2f}")

            with cache_lock: # 在更新缓存前获取 cache_lock
                 key_scores_cache[model_name] = current_scores
                 logger.debug(f"模型 '{model_name}' 的 Key 分数缓存已更新。")

    def _calculate_remaining_ratio(self, used: int, limit: Optional[int]) -> float:
        """计算剩余百分比，处理 None 或 0 限制的情况。"""
        if limit is None or limit <= 0:
            return 1.0 # 无限制或限制为 0，视为始终可用
        return max(0.0, 1.0 - (used / limit))

    def _calculate_key_health(self, key_usage: Dict[str, Any], limits: Dict[str, Any]) -> float:
        """
        计算单个 API 密钥针对特定模型的健康度评分 (0.0 - 1.0+)。
        分数越高越好。综合考虑 RPD, TPD_Input, RPM, TPM_Input 的剩余百分比。
        """
        # 定义各项指标的权重
        weights = {
            "rpd": 0.4,
            "tpd_input": 0.3,
            "rpm": 0.2,
            "tpm_input": 0.1
        }
        total_score = 0.0
        active_weights_sum = 0.0 # 累加有有效限制的指标权重

        # 计算 RPD 剩余百分比
        rpd_limit = limits.get("rpd")
        rpd_used = key_usage.get("rpd_count", 0)
        rpd_remaining_ratio = self._calculate_remaining_ratio(rpd_used, rpd_limit)
        if rpd_limit is not None and rpd_limit > 0:
             total_score += rpd_remaining_ratio * weights["rpd"]
             active_weights_sum += weights["rpd"]


        # 计算 TPD_Input 剩余百分比
        tpd_input_limit = limits.get("tpd_input")
        tpd_input_used = key_usage.get("tpd_input_count", 0)
        tpd_input_remaining_ratio = self._calculate_remaining_ratio(tpd_input_used, tpd_input_limit)
        if tpd_input_limit is not None and tpd_input_limit > 0:
             total_score += tpd_input_remaining_ratio * weights["tpd_input"]
             active_weights_sum += weights["tpd_input"]

        # 计算 RPM 剩余百分比 (基于当前窗口)
        rpm_limit = limits.get("rpm")
        rpm_used = 0
        if time.time() - key_usage.get("rpm_timestamp", 0) < RPM_WINDOW_SECONDS:
            rpm_used = key_usage.get("rpm_count", 0)
        rpm_remaining_ratio = self._calculate_remaining_ratio(rpm_used, rpm_limit)
        if rpm_limit is not None and rpm_limit > 0:
             total_score += rpm_remaining_ratio * weights["rpm"]
             active_weights_sum += weights["rpm"]

        # 计算 TPM_Input 剩余百分比 (基于当前窗口)
        tpm_input_limit = limits.get("tpm_input")
        tpm_input_used = 0
        if time.time() - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
            tpm_input_used = key_usage.get("tpm_input_count", 0)
        tpm_input_remaining_ratio = self._calculate_remaining_ratio(tpm_input_used, tpm_input_limit)
        if tpm_input_limit is not None and tpm_input_limit > 0:
             total_score += tpm_input_remaining_ratio * weights["tpm_input"]
             active_weights_sum += weights["tpm_input"]


        # 如果没有任何有效指标，返回一个默认值（例如 1.0，表示可用）
        if active_weights_sum == 0:
            return 1.0

        # 返回归一化的加权平均分
        normalized_score = total_score / active_weights_sum if active_weights_sum > 0 else 1.0
        # 确保分数在 0.0 到 1.0 之间（尽管理论上应该如此）
        return max(0.0, min(1.0, normalized_score))


    def remove_key(self, key_to_remove: str):
        """
        从管理器中移除指定的 API 密钥。
        """
        with self.keys_lock:
            if key_to_remove in self.api_keys:
                self.api_keys.remove(key_to_remove)
                # 同时从配置字典中移除
                if key_to_remove in self.key_configs:
                    del self.key_configs[key_to_remove]

                logger.info(f"API Key {key_to_remove[:10]}... 已从活动池和配置中移除。")
                # 同时从所有模型的缓存中移除该 Key 的分数记录
                with cache_lock:
                    for model_name in list(key_scores_cache.keys()):
                        if key_to_remove in key_scores_cache.get(model_name, {}): # 增加检查 model_name 是否存在
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
                if api_key in key_scores_cache.get(model_name, {}):
                    # 显著降低分数，例如降到 0.1 或更低
                    key_scores_cache[model_name][api_key] = 0.1
                    logger.warning(f"Key {api_key[:8]}... 因问题 '{issue_type}' 被标记，其在模型 '{model_name}' 的分数暂时降低。")
                    # 可以在这里添加更复杂的逻辑，例如：
                    # - 记录标记次数，达到阈值后彻底移除 Key
                    # - 设置一个标记过期时间，之后恢复分数
                    # break # 移除 break，以便为所有模型降低分数

    def get_active_keys_count(self) -> int:
        """
        返回当前管理器中有效（未被移除且当天可用）的密钥数量。
        """
        with self.keys_lock:
            # 使用内部不加锁的方法进行检查，避免死锁
            active_keys = [key for key in self.api_keys if not self._is_key_daily_exhausted_nolock(key)]
            return len(active_keys)

    def reset_tried_keys_for_request(self):
        """
        为新的 API 请求重置已尝试的密钥集合。
        """
        self.tried_keys_for_request.clear()
        logger.debug("已重置当前请求的已尝试密钥集合。")

    def mark_key_daily_exhausted(self, api_key: str):
        """
        标记某个 Key 因达到每日配额而当天不可用。
        """
        today_date_str = self._today_date_str # 使用缓存的日期字符串
        with self.keys_lock:
            self.daily_exhausted_keys[api_key] = today_date_str # 记录 Key 和今天的日期
            logger.warning(f"API Key {api_key[:8]}... 已被标记为 {today_date_str} 当天配额耗尽。") # 记录警告日志
            # 同时降低其分数，确保即使在某些边缘情况下也能避免被选中
            with cache_lock:
                for model_name in key_scores_cache:
                    if api_key in key_scores_cache.get(model_name, {}): # 增加检查 model_name 是否存在
                        key_scores_cache[model_name][api_key] = 0.0 # 将分数降到最低

    def _is_key_daily_exhausted_nolock(self, api_key: str) -> bool:
        """
        内部方法：检查某个 Key 是否被标记为当天不可用（不获取锁）。
        调用者必须确保已持有 self.keys_lock。
        """
        today_date_str = self._today_date_str # 使用缓存的日期字符串
        # 检查 Key 是否在字典中，并且记录的日期是今天
        is_exhausted = self.daily_exhausted_keys.get(api_key) == today_date_str
        # 不在此处记录日志，避免锁内 I/O
        return is_exhausted

    def is_key_daily_exhausted(self, api_key: str) -> bool:
        """
        检查某个 Key 是否被标记为当天不可用（获取锁）。
        """
        with self.keys_lock:
            is_exhausted = self._is_key_daily_exhausted_nolock(api_key)
            if is_exhausted:
                 # 在锁外记录日志可能更安全，但这里影响不大
                 logger.debug(f"Key {api_key[:8]}... 被标记为 {self._today_date_str} 当天配额耗尽，跳过选择。")
            return is_exhausted


    def reset_daily_exhausted_keys(self):
        """
        重置所有 Key 的每日配额耗尽标记。应在每日重置时调用。
        """
        with self.keys_lock:
            self.daily_exhausted_keys.clear() # 清空字典
            # 在重置每日耗尽 Key 时更新缓存的日期字符串
            self._today_date_str = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
            logger.info("已重置所有 Key 的每日配额耗尽标记。") # 已重置所有 Key 的每日配额耗尽标记


# --- 全局 Key Manager 实例 ---
# 在模块加载时创建单例
key_manager_instance = APIKeyManager()