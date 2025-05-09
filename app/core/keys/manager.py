# -*- coding: utf-8 -*-
# app/core/keys/manager.py (原 key_manager_class.py)
# 导入必要的库
import os        # 用于访问操作系统环境变量
import re        # 用于正则表达式操作（例如提取 API 密钥）
import time      # 用于时间相关操作（例如速率限制、时间戳）
import logging   # 用于应用程序的日志记录
from threading import Lock # 用于线程同步的锁，保护共享资源
from typing import Dict, Any, Optional, List, Tuple, Set # 导入类型提示
import copy      # 用于创建对象的深拷贝或浅拷贝
from collections import defaultdict # 提供默认值的字典子类
import asyncio # 导入 asyncio 模块，用于异步操作
from sqlalchemy.orm import Session # 导入 SQLAlchemy 同步会话 (可能用于某些旧代码或特定场景)
from sqlalchemy.ext.asyncio import AsyncSession # 导入 SQLAlchemy 异步会话

# 从 tracking 模块导入共享的数据结构、锁和常量
from app.core.tracking import (
    usage_data, usage_lock, # Key 使用情况数据 (字典) 和对应的锁
    key_scores_cache, cache_lock, cache_last_updated, update_cache_timestamp, # Key 分数缓存、锁、最后更新时间戳和更新函数
    RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, CACHE_REFRESH_INTERVAL_SECONDS # 常量：RPM/TPM 窗口秒数和缓存刷新间隔秒数
)

# 导入 datetime 和 pytz 用于处理时间和时区
from datetime import datetime, timezone # 添加 timezone 导入
import pytz

# 导入数据库模型和工具函数
from app.core.database import utils as db_utils # 导入数据库工具函数
from app.core.database.models import UserKeyAssociation, ApiKey # 导入数据库模型
# 导入配置模块
from app import config # 导入应用配置

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

class APIKeyManager:
    """
    管理 Gemini API 密钥的核心类。
    负责加载、存储、选择和管理 API Key 的状态。
    主要功能包括：
    - 根据配置从环境变量或数据库加载 Keys。
    - 提供 Key 的轮询和基于策略的最佳 Key 选择。
    - 处理无效或达到限制的 Key (每日配额耗尽、临时不可用)。
    - 支持粘性会话 (优先使用用户上次使用的 Key)。
    - 支持缓存关联 (优先使用与缓存内容关联的 Key)。
    - 跟踪 Key 选择过程中的决策原因。
    - 提供内存模式下的 Key 管理方法 (用于测试或特定场景)。
    """
    # db_session = None # 移除类属性 db_session，应通过依赖注入传入

    def __init__(self):
        """
        初始化 APIKeyManager 实例。
        - 初始化存储 API Key 字符串的列表 (api_keys)。
        - 初始化存储 Key 配置信息的字典 (key_configs)。
        - 创建线程锁 (keys_lock) 以保护对 Key 列表和配置的并发访问。
        - 初始化用于跟踪当前请求已尝试 Key 的集合 (tried_keys_for_request)。
        - 初始化存储每日配额耗尽 Key 的字典 (daily_exhausted_keys)。
        - 初始化存储临时不可用 Key 及其过期时间戳的字典 (temporary_issue_keys)。
        - 获取当前日期字符串 (_today_date_str)，用于每日配额检查。
        - 初始化用于粘性会话的用户-Key 映射 (user_key_map，目前未使用，逻辑在数据库中)。
        - 初始化用于记录 Key 选择原因的列表 (key_selection_records) 和对应的锁 (records_lock)。
        """
        self.api_keys: List[str] = [] # 存储当前有效的 API Key 字符串列表
        self.key_configs: Dict[str, Dict[str, Any]] = {} # 存储每个 Key 的配置信息 (描述、状态、过期时间等)

        self.keys_lock = Lock() # 线程锁，用于保护 self.api_keys 和 self.key_configs 的并发访问
        self.tried_keys_for_request: Set[str] = set() # 存储在当前单个 API 请求处理过程中已经尝试过的 Key，避免重复尝试
        self.daily_exhausted_keys: Dict[str, str] = {} # 存储已达到每日配额限制的 Key 及其达到限制的日期 (YYYY-MM-DD)
        self.temporary_issue_keys: Dict[str, float] = {} # 存储临时不可用的 Key 及其恢复可用的时间戳 (Unix timestamp)
        self._today_date_str = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d') # 获取当前上海时区的日期字符串
        # self.user_key_map: Dict[str, str] = defaultdict(str) # 用户-Key 映射，用于粘性会话 (数据库模式下此逻辑在数据库中)
        self.key_selection_records: List[Dict[str, Any]] = [] # 记录 Key 选择过程的详细信息，用于调试和分析
        self.records_lock = Lock() # 保护 key_selection_records 列表的线程锁

    async def reload_keys(self, db: Optional[AsyncSession] = None):
        """
        根据配置的 KEY_STORAGE_MODE (内存或数据库) 异步重新加载 API Key 列表和配置。
        此方法会清除当前的内存状态 (api_keys, key_configs)，并从指定源重新加载。
        通常在应用启动时或需要刷新 Key 列表时调用。

        Args:
            db (Optional[AsyncSession]): 数据库模式下需要传入 SQLAlchemy 异步数据库会话。
                                         内存模式下不需要。
        """
        logger.info(f"开始重新加载 API Keys (模式: {config.KEY_STORAGE_MODE})...") # 记录开始重新加载日志
        new_api_keys: List[str] = [] # 用于存储新加载的活动 Key 字符串
        new_key_configs: Dict[str, Dict[str, Any]] = {} # 用于存储新加载的所有 Key 配置

        if config.KEY_STORAGE_MODE == 'memory': # --- 内存模式 ---
            logger.info("内存模式：从环境变量 GEMINI_API_KEYS 重新加载...") # 记录日志
            raw_keys = config.GEMINI_API_KEYS or "" # 从配置获取原始 Key 字符串 (逗号分隔)
            # 分割字符串，去除空白，过滤空字符串
            env_keys = [k.strip() for k in raw_keys.split(',') if k.strip()]
            # 为每个 Key 创建默认配置
            for key in env_keys:
                new_api_keys.append(key) # 添加到活动 Key 列表
                new_key_configs[key] = { # 创建默认配置
                    'description': "从环境变量加载",
                    'is_active': True, # 默认激活
                    'expires_at': None, # 默认永不过期
                    'enable_context_completion': True, # 默认启用上下文
                    'user_id': None # 环境变量模式无用户关联
                }
            logger.info(f"内存模式：重新加载了 {len(new_api_keys)} 个 Key。") # 记录加载数量

        elif config.KEY_STORAGE_MODE == 'database': # --- 数据库模式 ---
            logger.info("数据库模式：从数据库重新加载 API Keys...") # 记录日志
            if not db: # 检查是否传入了数据库会话
                logger.error("数据库模式下重新加载 Key 需要数据库会话，但未提供。") # 记录错误
                return # 无法加载，直接返回

            try:
                # 调用数据库工具函数获取所有 Key 对象
                db_api_key_objects: List[ApiKey] = await db_utils.get_all_api_keys_from_db(db)
                # 遍历数据库中的 Key 对象
                for key_obj in db_api_key_objects:
                    # 只将状态为激活 (is_active=True) 的 Key 添加到内存中的活动 Key 列表
                    if key_obj.is_active:
                        new_api_keys.append(key_obj.key_string)
                    # 总是加载所有 Key (包括非激活的) 的配置信息到 key_configs 字典
                    new_key_configs[key_obj.key_string] = {
                        'description': key_obj.description,
                        'is_active': key_obj.is_active,
                        'expires_at': key_obj.expires_at,
                        'enable_context_completion': key_obj.enable_context_completion,
                        'user_id': key_obj.user_id
                    }
                # 记录从数据库加载的 Key 数量和活动 Key 数量
                logger.info(f"数据库模式：重新加载了 {len(db_api_key_objects)} 个 Key 配置，其中 {len(new_api_keys)} 个为活动状态。")
            except Exception as e: # 捕获数据库查询过程中可能发生的异常
                logger.error(f"从数据库重新加载 API Key 失败: {e}", exc_info=True) # 记录错误
                # 加载失败时，可以选择保持现有的 Key 状态不变，或者清空。
                # 当前实现为保持不变，避免因临时数据库问题导致服务完全不可用。
                return # 直接返回
        else: # --- 未知模式 ---
            logger.error(f"未知的 KEY_STORAGE_MODE: {config.KEY_STORAGE_MODE}。无法重新加载 API Key。") # 记录错误
            return # 直接返回

        # --- 更新管理器状态 ---
        # 使用线程锁确保更新过程的原子性
        with self.keys_lock:
            self.api_keys = new_api_keys # 更新活动 Key 列表
            self.key_configs = new_key_configs # 更新 Key 配置字典
            # 可选：是否需要在此处重置 daily_exhausted_keys 和 temporary_issue_keys？
            # 决定：暂时不重置，让这些状态在它们各自的逻辑中过期或被清理，
            # 避免 reload 操作意外恢复了实际上仍然受限的 Key。
            logger.info("APIKeyManager 状态已更新。") # 记录状态更新完成


    def get_key_config(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 API Key 的配置信息。

        Args:
            api_key (str): 要查询的 API Key 字符串。

        Returns:
            Optional[Dict[str, Any]]: 包含 Key 配置的字典，如果 Key 不存在则返回 None。
                                      返回的是配置的深拷贝，防止外部修改影响内部状态。
        """
        with self.keys_lock: # 获取锁以安全访问 key_configs
            config_data = self.key_configs.get(api_key) # 从字典获取配置
            # 返回配置的深拷贝，如果找到了配置；否则返回 None
            return copy.deepcopy(config_data) if config_data else None

    # update_key_config 方法已移除，因为 Key 的更新应通过 API -> 数据库/环境变量 -> reload_keys 的流程完成，
    # 而不是直接修改内存中的 KeyManager 状态。

    def get_next_key(self) -> Optional[str]:
        """
        (简单轮询，可能已废弃) 获取下一个可用的 API 密钥。
        此方法实现了一个简单的轮询逻辑，但可能不如 select_best_key 智能。
        它会跳过当前请求已尝试、每日耗尽或临时不可用的 Key。

        Returns:
            Optional[str]: 下一个可用的 API Key 字符串，如果没有可用的 Key 则返回 None。
        """
        logger.warning("调用了简单的 get_next_key (轮询) 方法，可能已被 select_best_key 替代。") # 记录警告
        with self.keys_lock: # 获取锁
            if not self.api_keys: # 如果没有加载任何 Key
                return None # 返回 None
            # 筛选出当前可用的 Key
            available_keys = [
                k for k in self.api_keys # 遍历所有活动 Key
                if k not in self.tried_keys_for_request # 排除当前请求已尝试的
                and not self._is_key_daily_exhausted_nolock(k) # 排除每日配额耗尽的 (无锁版本检查)
                and not self.is_key_temporarily_unavailable(k) # 排除临时不可用的
            ]
            if not available_keys: # 如果没有可用的 Key
                return None # 返回 None
            # 返回可用列表中的第一个 Key (简单轮询)
            key_to_use = available_keys[0]
            return key_to_use

    async def select_best_key(self, model_name: str, model_limits: Dict[str, Any], estimated_input_tokens: int,
                         user_id: Optional[str] = None, enable_sticky_session: bool = False, request_id: Optional[str] = None,
                         cached_content_id: Optional[str] = None,
                         db: Optional[AsyncSession] = None # 数据库会话，用于数据库模式下的查询
                         ) -> Tuple[Optional[str], int]:
        """
        基于多种策略异步选择最佳的 API 密钥用于当前请求。
        选择策略优先级：
        1. 缓存关联 Key (如果启用原生缓存且命中缓存)
        2. 用户上次使用 Key (如果启用粘性会话)
        3. 基于评分和最近最少使用的轮转选择 (回退策略)

        Args:
            model_name (str): 请求的目标模型名称。
            model_limits (Dict[str, Any]): 该模型的速率限制配置。
            estimated_input_tokens (int): 本次请求估算的输入 Token 数量，用于预检查 TPM/TPD 限制。
            user_id (Optional[str]): 发起请求的用户 ID，用于粘性会话和缓存关联。
            enable_sticky_session (bool): 是否启用粘性会话策略。
            request_id (Optional[str]): 当前请求的唯一 ID，用于日志跟踪。
            cached_content_id (Optional[str]): 如果缓存命中，传递缓存内容的 ID，用于缓存关联 Key 查找。
            db (Optional[AsyncSession]): 数据库模式下需要传入 SQLAlchemy 异步数据库会话。

        Returns:
            Tuple[Optional[str], int]:
            - 第一个元素：选定的最佳 API Key 字符串，如果找不到合适的 Key 则为 None。
            - 第二个元素：选定 Key 当前可用的输入 Token 容量估算值 (基于 TPM 限制)。
                         如果 Key 没有 TPM 限制或无法估算，可能返回 float('inf') 或 0。
        """
        # 优先获取 keys_lock，因为后续大部分操作都需要访问共享的 Key 状态
        with self.keys_lock:
            # --- 跟踪与准备 ---
            # 增加 Key 选择尝试的总次数 (用于统计)
            from app.core import tracking # 导入 tracking 模块
            with tracking.cache_tracking_lock: # 获取缓存跟踪锁
                tracking.key_selection_total_attempts += 1 # 增加总尝试次数

            selected_key = None # 初始化选定的 Key 为 None
            available_input_tokens = 0 # 初始化可用输入 Token 容量为 0

            # --- 准备不可用 Key 集合 ---
            # 获取当天日期字符串，用于检查每日配额
            self._today_date_str = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
            # 获取当天已耗尽配额的 Key 集合
            daily_exhausted = {k for k, date_str in self.daily_exhausted_keys.items() if date_str == self._today_date_str}
            # 获取当前请求已经尝试过的 Key 集合 (创建副本以防迭代问题)
            tried_keys = self.tried_keys_for_request.copy()
            # 获取当前内存中所有标记为活动的 Key 列表 (创建副本)
            current_active_keys = self.api_keys[:]
            # 获取临时不可用的 Key 集合 (is_key_temporarily_unavailable 内部会清理过期标记)
            temporarily_unavailable_keys = {k for k in current_active_keys if self.is_key_temporarily_unavailable(k)}

            # --- 策略 1: 缓存关联 Key 优先级 ---
            # 仅在数据库模式、启用原生缓存、提供了缓存 ID 且有数据库会话时执行
            if config.KEY_STORAGE_MODE == 'database' and config.ENABLE_NATIVE_CACHING and cached_content_id and db:
                logger.debug(f"请求 {request_id} - 策略 1: 尝试缓存关联 Key (Cache ID: {cached_content_id})") # 记录日志
                try:
                    # 调用数据库工具函数查找与缓存 ID 关联的 Key ID
                    associated_key_id = await db_utils.get_key_id_by_cached_content_id(db, cached_content_id)
                    if associated_key_id: # 如果找到了关联的 Key ID
                        # 根据 Key ID 查找 Key 字符串
                        associated_key_str = await db_utils.get_key_string_by_id(db, associated_key_id)
                        if associated_key_str: # 如果找到了 Key 字符串
                            logger.debug(f"请求 {request_id} - 找到与缓存 {cached_content_id} 关联的 Key: {associated_key_str[:8]}...") # 记录日志
                            reason_prefix = "Cache Assoc." # 定义日志原因前缀
                            # --- 检查关联 Key 的可用性 ---
                            if associated_key_str not in current_active_keys: # 是否在当前活动 Key 列表中
                                reason = f"{reason_prefix} - Key not active/found in manager" # 不可用原因
                                logger.warning(f"请求 {request_id} - {reason}") # 记录警告
                                self.record_selection_reason(associated_key_str, reason, request_id) # 记录选择原因
                            elif associated_key_str in tried_keys: # 是否已在本请求中尝试过
                                reason = f"{reason_prefix} - Key already tried"
                                logger.warning(f"请求 {request_id} - {reason}")
                                self.record_selection_reason(associated_key_str, reason, request_id)
                            elif associated_key_str in daily_exhausted: # 是否已达到每日配额
                                reason = f"{reason_prefix} - Daily Quota Exhausted"
                                logger.warning(f"请求 {request_id} - {reason}")
                                self.record_selection_reason(associated_key_str, reason, request_id)
                            elif associated_key_str in temporarily_unavailable_keys: # 是否临时不可用
                                reason = f"{reason_prefix} - Temporarily Unavailable"
                                logger.warning(f"请求 {request_id} - {reason}")
                                self.record_selection_reason(associated_key_str, reason, request_id)
                            else: # --- Key 可用，进行 Token 预检查 ---
                                logger.debug(f"请求 {request_id} - 关联 Key {associated_key_str[:8]}... 可用，进行 Token 预检查...")
                                with usage_lock: # 获取使用数据锁
                                    key_usage = usage_data.get(associated_key_str, {}).get(model_name, {}) # 获取该 Key 对该模型的使用数据
                                    tpm_input_limit = model_limits.get("tpm_input") # 获取 TPM 输入限制
                                    tpm_input_used = key_usage.get("tpm_input_count", 0) # 获取当前 TPM 输入计数
                                    potential_tpm_input = tpm_input_used + estimated_input_tokens # 计算潜在的总输入 Token
                                    # 检查是否会超过 TPM 限制 (如果有限制)
                                    if tpm_input_limit is None or tpm_input_limit <= 0 or potential_tpm_input <= tpm_input_limit:
                                        # --- Token 预检查通过，选定此 Key ---
                                        selected_key = associated_key_str # 选定 Key
                                        # 计算剩余可用输入 Token 容量
                                        available_input_tokens = max(0, tpm_input_limit - tpm_input_used) if tpm_input_limit is not None and tpm_input_limit > 0 else float('inf')
                                        reason = f"{reason_prefix} - Successful Selection" # 成功原因
                                        logger.info(f"请求 {request_id} - {reason}: {selected_key[:8]}...。可用输入 Token: {available_input_tokens}") # 记录成功日志
                                        self.record_selection_reason(selected_key, reason, request_id) # 记录选择原因
                                        # 增加成功选择计数
                                        with tracking.cache_tracking_lock:
                                            tracking.key_selection_successful_selections += 1
                                        self.tried_keys_for_request.add(selected_key) # 将选定的 Key 加入本请求的已尝试集合
                                        return selected_key, available_input_tokens # 返回选定的 Key 和可用 Token 容量
                                    else: # --- Token 预检查失败 ---
                                        reason = f"{reason_prefix} - Token Precheck Failed" # 失败原因
                                        logger.warning(f"请求 {request_id} - {reason}: {associated_key_str[:8]}... 潜在总输入 Token: {potential_tpm_input}, 限制: {tpm_input_limit}") # 记录警告
                                        self.record_selection_reason(associated_key_str, reason, request_id) # 记录原因
                        else: # 如果根据 Key ID 未找到 Key 字符串
                            reason = f"{reason_prefix} - Key string not found for ID {associated_key_id}"
                            logger.warning(f"请求 {request_id} - {reason}")
                            self.record_selection_reason(f"ID:{associated_key_id}", reason, request_id)
                    else: # 如果未找到与缓存关联的 Key ID
                        reason = f"{reason_prefix} - No associated Key ID found"
                        logger.debug(f"请求 {request_id} - {reason}")
                        self.record_selection_reason("N/A", reason, request_id)
                except Exception as e: # 捕获数据库查询异常
                    logger.error(f"请求 {request_id} - 查找缓存关联 Key 时出错: {e}", exc_info=True) # 记录错误
                    self.record_selection_reason("N/A", "Cache Assoc. - DB Error", request_id) # 记录原因
            elif config.KEY_STORAGE_MODE == 'database' and config.ENABLE_NATIVE_CACHING and not db: # 如果需要数据库但未提供会话
                 logger.warning(f"请求 {request_id} - 数据库模式下原生缓存已启用但未提供 db session，无法查找缓存关联 Key。") # 记录警告
                 self.record_selection_reason("N/A", "Cache Assoc. - DB Session Missing", request_id) # 记录原因
            else: # 其他跳过缓存关联查找的情况
                 logger.debug(f"请求 {request_id} - 跳过缓存关联 Key 查找 (非数据库模式或原生缓存禁用或无 Cache ID)。") # 记录调试信息
                 self.record_selection_reason("N/A", "Cache Assoc. - Skipped", request_id) # 记录原因


            # --- 策略 2: 用户上次使用 Key 优先级 (粘性会话) ---
            user_association_reason = "User Assoc. - Skipped" # 初始化原因为跳过
            # 仅在数据库模式、未选定 Key、提供了用户 ID、启用了粘性会话且有数据库会话时执行
            if config.KEY_STORAGE_MODE == 'database' and selected_key is None and user_id and enable_sticky_session and db:
                logger.debug(f"请求 {request_id} - 策略 2: 尝试用户上次使用 Key (User ID: {user_id})") # 记录日志
                try:
                    # 调用数据库工具函数获取用户上次使用的 Key ID
                    last_used_key_id = await db_utils.get_user_last_used_key_id(db, user_id)
                    if last_used_key_id: # 如果找到了上次使用的 Key ID
                        # 根据 Key ID 获取 Key 字符串
                        last_used_key_str = await db_utils.get_key_string_by_id(db, last_used_key_id)
                        if last_used_key_str: # 如果找到了 Key 字符串
                            logger.debug(f"请求 {request_id} - 用户 {user_id} 上次使用 Key: {last_used_key_str[:8]}...") # 记录日志
                            reason_prefix = "User Assoc." # 定义日志原因前缀
                            # --- 检查上次使用 Key 的可用性 ---
                            if last_used_key_str not in current_active_keys: # 是否在当前活动 Key 列表中
                                user_association_reason = f"{reason_prefix} - Key not active/found in manager"
                                logger.warning(f"请求 {request_id} - {user_association_reason}")
                                self.record_selection_reason(last_used_key_str, user_association_reason, request_id)
                            elif last_used_key_str in tried_keys: # 是否已在本请求中尝试过
                                user_association_reason = f"{reason_prefix} - Key already tried"
                                logger.warning(f"请求 {request_id} - {user_association_reason}")
                                self.record_selection_reason(last_used_key_str, user_association_reason, request_id)
                            elif last_used_key_str in daily_exhausted: # 是否已达到每日配额
                                user_association_reason = f"{reason_prefix} - Daily Quota Exhausted"
                                logger.warning(f"请求 {request_id} - {user_association_reason}")
                                self.record_selection_reason(last_used_key_str, user_association_reason, request_id)
                            elif last_used_key_str in temporarily_unavailable_keys: # 是否临时不可用
                                user_association_reason = f"{reason_prefix} - Temporarily Unavailable"
                                logger.warning(f"请求 {request_id} - {user_association_reason}")
                                self.record_selection_reason(last_used_key_str, user_association_reason, request_id)
                            else: # --- Key 可用，进行 Token 预检查 ---
                                logger.debug(f"请求 {request_id} - 上次使用 Key {last_used_key_str[:8]}... 可用，进行 Token 预检查...")
                                with usage_lock: # 获取使用数据锁
                                    key_usage = usage_data.get(last_used_key_str, {}).get(model_name, {}) # 获取使用数据
                                    tpm_input_limit = model_limits.get("tpm_input") # 获取 TPM 限制
                                    tpm_input_used = key_usage.get("tpm_input_count", 0) # 获取当前 TPM 计数
                                    potential_tpm_input = tpm_input_used + estimated_input_tokens # 计算潜在总输入
                                    # 检查是否会超过 TPM 限制
                                    if tpm_input_limit is None or tpm_input_limit <= 0 or potential_tpm_input <= tpm_input_limit:
                                        # --- Token 预检查通过，选定此 Key ---
                                        selected_key = last_used_key_str # 选定 Key
                                        # 计算剩余可用输入 Token
                                        available_input_tokens = max(0, tpm_input_limit - tpm_input_used) if tpm_input_limit is not None and tpm_input_limit > 0 else float('inf')
                                        user_association_reason = f"{reason_prefix} - Successful Selection" # 成功原因
                                        logger.info(f"请求 {request_id} - {user_association_reason}: {selected_key[:8]}...。可用输入 Token: {available_input_tokens}") # 记录成功日志
                                        self.record_selection_reason(selected_key, user_association_reason, request_id) # 记录原因
                                        # 增加成功选择计数
                                        with tracking.cache_tracking_lock:
                                            tracking.key_selection_successful_selections += 1
                                        self.tried_keys_for_request.add(selected_key) # 加入已尝试集合
                                        return selected_key, available_input_tokens # 返回结果
                                    else: # --- Token 预检查失败 ---
                                        user_association_reason = f"{reason_prefix} - Token Precheck Failed" # 失败原因
                                        logger.warning(f"请求 {request_id} - {user_association_reason}: {last_used_key_str[:8]}... 潜在总输入 Token: {potential_tpm_input}, 限制: {tpm_input_limit}") # 记录警告
                                        self.record_selection_reason(last_used_key_str, user_association_reason, request_id) # 记录原因
                        else: # 如果根据 Key ID 未找到 Key 字符串
                            user_association_reason = f"{reason_prefix} - Key string not found for ID {last_used_key_id}"
                            logger.warning(f"请求 {request_id} - {user_association_reason}")
                            self.record_selection_reason(f"ID:{last_used_key_id}", user_association_reason, request_id)
                    else: # 如果未找到用户上次使用的 Key
                        user_association_reason = f"{reason_prefix} - No last used Key found"
                        logger.debug(f"请求 {request_id} - {user_association_reason}")
                        self.record_selection_reason("N/A", user_association_reason, request_id)
                except Exception as e: # 捕获数据库查询异常
                    logger.error(f"请求 {request_id} - 查找用户上次使用 Key 时出错: {e}", exc_info=True) # 记录错误
                    user_association_reason = "User Assoc. - DB Error"
                    self.record_selection_reason("N/A", user_association_reason, request_id)
            elif selected_key is None: # 如果未执行用户关联查找，记录跳过原因
                 if config.KEY_STORAGE_MODE != 'database': user_association_reason = "User Assoc. - Skipped (Not DB Mode)"
                 elif not user_id: user_association_reason = "User Assoc. - User ID Missing"
                 elif not enable_sticky_session: user_association_reason = "User Assoc. - Sticky Session Disabled"
                 elif not db: user_association_reason = "User Assoc. - DB Session Missing"
                 logger.debug(f"请求 {request_id} - 跳过用户关联 Key 查找 ({user_association_reason})。") # 记录调试信息
                 self.record_selection_reason("N/A", user_association_reason, request_id) # 记录原因


            # --- 策略 3: 基于评分和最近最少使用的轮转选择 (回退策略) ---
            if selected_key is None: # 如果经过前两种策略仍未选定 Key
                logger.debug(f"请求 {request_id} - 策略 3: 执行评分和轮转选择。") # 记录日志
                # --- 获取 Key 分数 (可能从缓存或数据库) ---
                with cache_lock: # 获取分数缓存锁
                    now = time.time() # 获取当前时间
                    # 检查分数缓存是否需要刷新
                    if now - cache_last_updated.get(model_name, 0) > CACHE_REFRESH_INTERVAL_SECONDS:
                        logger.info(f"请求 {request_id} - 模型 '{model_name}' 的 Key 分数缓存已过期，正在异步刷新...") # 记录日志
                        try:
                            # 创建一个异步任务来更新分数缓存，避免阻塞当前请求
                            asyncio.create_task(self._async_update_key_scores(model_name, model_limits))
                        except RuntimeError: # 如果当前不在事件循环中 (例如，在同步代码中调用)
                            logger.warning(f"请求 {request_id} - 不在异步事件循环中，无法启动异步刷新任务。依赖后台任务或下次调用刷新。") # 记录警告
                        update_cache_timestamp(model_name) # 更新缓存时间戳，防止短时间内重复触发刷新
                    scores = key_scores_cache.get(model_name, {}) # 从缓存获取分数

                if not scores: # 如果没有分数数据
                    logger.warning(f"请求 {request_id} - 模型 '{model_name}' 没有可用的 Key 分数缓存数据。") # 记录警告
                    self.record_selection_reason("N/A", "Score Selection - No Key Score Cache Data", request_id) # 记录原因
                    # 增加失败选择计数
                    with tracking.cache_tracking_lock:
                        tracking.key_selection_failed_selections += 1
                        tracking.key_selection_failure_reasons["Score Selection - No Key Score Cache Data"] += 1
                else: # 如果有分数数据
                    # --- 筛选可用的 Key ---
                    available_scores = {} # 存储筛选后的 Key 及其分数
                    reason_prefix = "Score Selection" # 定义日志原因前缀
                    # 遍历缓存中的所有 Key 分数
                    for k, v in scores.items():
                        # 检查 Key 是否在当前活动的 Key 列表中
                        if k not in current_active_keys:
                             self.record_selection_reason(k, f"{reason_prefix} - Key not active in manager", request_id)
                             continue # 跳过非活动 Key
                        # 检查 Key 是否已在本请求中尝试过
                        if k in tried_keys:
                            self.record_selection_reason(k, f"{reason_prefix} - Key already tried", request_id)
                            continue # 跳过已尝试 Key
                        # 检查 Key 是否已达到每日配额
                        if k in daily_exhausted:
                            self.record_selection_reason(k, f"{reason_prefix} - Daily Quota Exhausted", request_id)
                            continue # 跳过每日耗尽 Key
                        # 检查 Key 是否临时不可用
                        if k in temporarily_unavailable_keys:
                            self.record_selection_reason(k, f"{reason_prefix} - Temporarily Unavailable", request_id)
                            continue # 跳过临时不可用 Key
                        # 如果 Key 可用，添加到 available_scores 字典
                        available_scores[k] = v

                    if not available_scores: # 如果筛选后没有可用的 Key
                        logger.warning(f"请求 {request_id} - 模型 '{model_name}' 的所有可用 Key（根据缓存）均已尝试、当天耗尽或临时不可用。") # 记录警告
                        self.record_selection_reason("N/A", f"{reason_prefix} - All available keys tried/exhausted/unavailable", request_id) # 记录原因
                        # 增加失败选择计数
                        with tracking.cache_tracking_lock:
                            tracking.key_selection_failed_selections += 1
                            tracking.key_selection_failure_reasons[f"{reason_prefix} - All available keys tried/exhausted/unavailable"] += 1
                    else: # 如果有可用的 Key
                        # --- 执行轮转选择 ---
                        # 1. 按分数降序排序
                        sorted_keys_by_score = sorted(available_scores.items(), key=lambda item: item[1], reverse=True)
                        # 2. 确定轮转范围 (例如，分数在前 95% 的 Key)
                        rotation_threshold = 0.95 # 定义轮转阈值
                        best_score = sorted_keys_by_score[0][1] if sorted_keys_by_score else 0 # 获取最高分
                        # 筛选出分数在阈值范围内的 Key
                        keys_in_rotation_range = [(k, score) for k, score in sorted_keys_by_score if score >= best_score * rotation_threshold]

                        # 3. 在轮转范围内的 Key 中，按最近最少使用排序
                        with usage_lock: # 获取使用数据锁
                            # 对轮转范围内的 Key 按 last_used_timestamp 升序排序（越小越优先）
                            sorted_keys_for_rotation = sorted(
                                keys_in_rotation_range,
                                key=lambda item: usage_data.get(item[0], {}).get(model_name, {}).get('last_used_timestamp', 0.0) # 获取上次使用时间戳，默认为 0
                            )
                            # 4. 遍历排序后的 Key，进行 Token 预检查并选择第一个通过的 Key
                            for candidate_key, candidate_score in sorted_keys_for_rotation:
                                key_usage = usage_data.get(candidate_key, {}).get(model_name, {}) # 获取使用数据
                                tpm_input_limit = model_limits.get("tpm_input") # 获取 TPM 限制
                                tpm_input_used = key_usage.get("tpm_input_count", 0) # 获取当前 TPM 计数
                                potential_tpm_input = tpm_input_used + estimated_input_tokens # 计算潜在总输入
                                # 检查是否会超过 TPM 限制
                                if tpm_input_limit is None or tpm_input_limit <= 0 or potential_tpm_input <= tpm_input_limit:
                                    # --- Token 预检查通过，选定此 Key ---
                                    selected_key = candidate_key # 选定 Key
                                    # 计算剩余可用输入 Token
                                    available_input_tokens = max(0, tpm_input_limit - tpm_input_used) if tpm_input_limit is not None and tpm_input_limit > 0 else float('inf')
                                    reason = f"{reason_prefix} - Successful Selection (Score: {candidate_score:.4f})" # 成功原因
                                    logger.info(f"请求 {request_id} - {reason}: {selected_key[:8]}...。可用输入 Token: {available_input_tokens}") # 记录成功日志
                                    self.record_selection_reason(selected_key, reason, request_id) # 记录原因
                                    # 增加成功选择计数
                                    with tracking.cache_tracking_lock:
                                        tracking.key_selection_successful_selections += 1
                                    break # 找到合适的 Key，跳出循环
                                else: # --- Token 预检查失败 ---
                                    reason = f"{reason_prefix} - Token Precheck Failed" # 失败原因
                                    logger.warning(f"请求 {request_id} - {reason}: {candidate_key[:8]}... 潜在总输入 Token: {potential_tpm_input}, 限制: {tpm_input_limit}") # 记录警告
                                    self.record_selection_reason(candidate_key, reason, request_id) # 记录原因
                                    continue # 继续检查下一个候选 Key

            # --- 最终检查和返回 ---
            if selected_key: # 如果最终选定了一个 Key
                # 将选定的 Key 加入本请求的已尝试集合
                self.tried_keys_for_request.add(selected_key)
                return selected_key, available_input_tokens # 返回选定的 Key 和可用 Token 容量
            else: # 如果所有策略都尝试后仍未选定 Key
                final_reason = "Final Failure - No suitable key found after all strategies" # 最终失败原因
                logger.error(f"请求 {request_id} - {final_reason}") # 记录错误日志
                self.record_selection_reason("N/A", final_reason, request_id) # 记录原因
                # 增加失败选择计数
                with tracking.cache_tracking_lock:
                    tracking.key_selection_failed_selections += 1
                    tracking.key_selection_failure_reasons[final_reason] += 1
                return None, 0 # 返回 None 表示未选定 Key

    def _is_key_daily_exhausted_nolock(self, api_key: str) -> bool:
        """
        (内部方法) 检查 API 密钥是否已达到每日配额限制。
        此方法不获取 keys_lock，调用者需要确保已持有锁。

        Args:
            api_key (str): 要检查的 API Key 字符串。

        Returns:
            bool: 如果 Key 已达到当日配额限制，返回 True；否则返回 False。
        """
        # 检查 daily_exhausted_keys 字典中是否存在该 Key，并且其记录的日期是否与当天日期相同
        return self.daily_exhausted_keys.get(api_key) == self._today_date_str

    def mark_key_daily_exhausted(self, api_key: str):
        """
        将指定的 API 密钥标记为当天已耗尽配额。
        记录当前日期到 daily_exhausted_keys 字典。

        Args:
            api_key (str): 要标记的 API Key 字符串。
        """
        with self.keys_lock: # 获取锁以安全修改共享字典
            self.daily_exhausted_keys[api_key] = self._today_date_str # 记录 Key 和当天日期
            logger.warning(f"API Key {api_key[:10]}... 已达到每日配额限制。") # 记录警告日志

    def is_key_temporarily_unavailable(self, api_key: str) -> bool:
        """
        检查指定的 API 密钥当前是否因临时问题（例如，短暂的 API 错误）而不可用。
        同时会清理掉已经过期的临时不可用标记。

        Args:
            api_key (str): 要检查的 API Key 字符串。

        Returns:
            bool: 如果 Key 当前处于临时不可用状态，返回 True；否则返回 False。
        """
        with self.keys_lock: # 获取锁以安全访问和修改共享字典
            # 获取该 Key 的过期时间戳，如果不存在则为 None
            expiration_timestamp = self.temporary_issue_keys.get(api_key)
            # 检查是否存在过期时间戳，并且该时间戳是否已小于当前时间
            if expiration_timestamp and expiration_timestamp < time.time():
                # 如果标记已过期，从字典中安全地移除该 Key 的条目
                self.temporary_issue_keys.pop(api_key, None) # pop 避免 Key 不存在时出错
                logger.info(f"API Key {api_key[:10]}... 的临时问题标记已过期，恢复可用。") # 记录恢复日志
                return False # 返回 False 表示 Key 不再临时不可用
            # 如果存在未过期的标记，或者标记不存在，根据 expiration_timestamp 是否为 None 判断
            return expiration_timestamp is not None # 如果存在时间戳 (未过期)，则返回 True

    def mark_key_temporarily_unavailable(self, api_key: str, duration_seconds: int = 60):
        """
        将指定的 API 密钥标记为临时不可用一段时间。
        这通常在遇到可重试的 API 错误（如 5xx）时调用。

        Args:
            api_key (str): 要标记的 API Key 字符串。
            duration_seconds (int, optional): 临时不可用的持续时间（秒）。默认为 60 秒。
        """
        with self.keys_lock: # 获取锁以安全修改共享字典
            # 计算并存储 Key 恢复可用的时间戳
            self.temporary_issue_keys[api_key] = time.time() + duration_seconds
            logger.warning(f"API Key {api_key[:10]}... 临时不可用 {duration_seconds} 秒。") # 记录警告日志

    def record_selection_reason(self, key: str, reason: str, request_id: Optional[str] = None):
        """
        记录在 Key 选择过程中，某个 Key 被选中或被跳过的原因。
        用于调试和分析 Key 选择策略的效果。

        Args:
            key (str): 相关的 API Key 字符串 (或 "N/A" 表示未涉及特定 Key)。
            reason (str): 选择或跳过的具体原因。
            request_id (Optional[str]): 与此记录关联的请求 ID。
        """
        with self.records_lock: # 获取记录列表的锁
            # 将记录信息（Key、原因、请求 ID、时间戳）添加到列表中
            self.key_selection_records.append(
                {
                    "key": key, # 相关 Key
                    "reason": reason, # 原因描述
                    "request_id": request_id, # 请求 ID
                    "timestamp": datetime.now(pytz.timezone('Asia/Shanghai')).isoformat() # 记录时间 (带时区)
                }
            )

    def get_active_keys_count(self) -> int:
        """
        返回当前内存中加载的活动 API 密钥的数量。

        Returns:
            int: 活动 API 密钥的数量。
        """
        with self.keys_lock: # 获取锁以安全访问 api_keys 列表
            return len(self.api_keys) # 返回列表长度

    async def _async_update_key_scores(self, model_name: str, model_limits: Dict[str, Any]):
        """
        (内部异步方法) 异步更新指定模型的 Key 分数缓存。
        此方法应在后台任务中调用，以避免阻塞主请求处理。
        目前依赖于 db_utils.get_key_scores 的实现。

        Args:
            model_name (str): 需要更新分数的模型名称。
            model_limits (Dict[str, Any]): 该模型的限制配置 (可能在评分计算中使用)。
        """
        try:
            # TODO: 实现或确认 db_utils.get_key_scores 的逻辑
            # 假设 db_utils.get_key_scores 是一个异步函数，从数据库或其他来源获取分数
            new_scores = await db_utils.get_key_scores(model_name) # 调用函数获取新分数
            with cache_lock: # 获取分数缓存锁
                key_scores_cache[model_name] = new_scores # 更新缓存
            logger.info(f"模型 '{model_name}' 的 Key 分数缓存已成功更新。") # 记录成功日志
        except Exception as e: # 捕获更新过程中可能发生的异常
            logger.error(f"更新模型 '{model_name}' 的 Key 分数缓存时出错: {e}", exc_info=True) # 记录错误日志

    def get_and_clear_all_selection_records(self) -> List[Dict[str, Any]]:
        """
        获取当前存储的所有 Key 选择记录，并清空记录列表。
        通常用于定期导出或分析选择日志。

        Returns:
            List[Dict[str, Any]]: 包含所有 Key 选择记录的列表。
        """
        with self.records_lock: # 获取记录列表的锁
            records = copy.deepcopy(self.key_selection_records)  # 创建记录列表的深拷贝
            self.key_selection_records.clear()  # 清空原始记录列表
            return records # 返回记录的副本

    # load_keys_from_db 方法已移除，功能合并到 reload_keys 中。

    # --- 新增：内存模式下的 Key 操作方法 (用于测试或特定场景) ---
    # 这些方法允许在不涉及数据库的情况下，直接操作内存中的 Key 列表和配置。
    # 注意：这些更改只影响当前运行的实例，不会持久化。

    def add_key_memory(self, key_string: str, config_data: Dict[str, Any]) -> bool:
        """
        (内存模式) 添加一个新的 API Key 到内存中的 `api_keys` 列表和 `key_configs` 字典。

        Args:
            key_string (str): 要添加的 Key 字符串。
            config_data (Dict[str, Any]): 与该 Key 关联的配置数据。

        Returns:
            bool: 如果成功添加返回 True，如果 Key 已存在则返回 False。
        """
        with self.keys_lock: # 获取锁
            if key_string in self.api_keys: # 检查 Key 是否已存在
                logger.warning(f"内存模式：尝试添加已存在的 Key: {key_string[:8]}...") # 记录警告
                return False # 返回 False
            self.api_keys.append(key_string) # 添加到 Key 列表
            # 更新 config_data 以包含 _ui_generated 标记，并确保其他字段存在
            updated_config_data = {
                "description": config_data.get("description"),
                "is_active": config_data.get("is_active", True),
                "expires_at": config_data.get("expires_at"),
                "enable_context_completion": config_data.get("enable_context_completion", True),
                "user_id": config_data.get("user_id"),
                "created_at": config_data.get("created_at", datetime.now(timezone.utc).isoformat()),
                "_ui_generated": True # 添加 UI 生成标记
            }
            self.key_configs[key_string] = updated_config_data # 添加到配置字典
            logger.info(f"内存模式：成功添加临时 Key (UI生成): {key_string[:8]}...") # 记录成功日志
            return True # 返回 True

    def update_key_memory(self, key_string: str, updates: Dict[str, Any]) -> bool:
        """
        (内存模式) 更新内存中指定 API Key 的配置信息。

        Args:
            key_string (str): 要更新的 Key 字符串。
            updates (Dict[str, Any]): 包含要更新的配置字段和新值的字典。

        Returns:
            bool: 如果成功更新返回 True，如果 Key 不存在则返回 False。
        """
        with self.keys_lock: # 获取锁
            if key_string not in self.key_configs: # 检查 Key 是否存在于配置中
                logger.warning(f"内存模式：尝试更新不存在的 Key: {key_string[:8]}...") # 记录警告
                return False # 返回 False
            # 过滤掉不允许直接更新的字段 (例如 key_string 本身)
            allowed_updates = {k: v for k, v in updates.items() if k != 'key_string'}
            # 更新配置字典中对应 Key 的信息
            self.key_configs[key_string].update(allowed_updates)
            logger.info(f"内存模式：成功更新临时 Key {key_string[:8]}... 的配置: {allowed_updates}") # 记录成功日志
            return True # 返回 True

    def delete_key_memory(self, key_string: str) -> bool:
        """
        (内存模式) 从内存中删除指定的 API Key 及其配置。

        Args:
            key_string (str): 要删除的 Key 字符串。

        Returns:
            bool: 如果成功删除（或 Key 原本就不存在于配置中）返回 True，否则返回 False。
        """
        with self.keys_lock: # 获取锁
            key_existed_in_list = False # 标记 Key 是否在列表中存在过
            try:
                if key_string in self.api_keys: # 检查 Key 是否在活动列表中
                    self.api_keys.remove(key_string) # 从列表中移除
                    key_existed_in_list = True # 标记存在过
            except ValueError: # 处理 remove 可能抛出的 ValueError (如果并发导致 Key 已被移除)
                 logger.warning(f"内存模式：尝试从 api_keys 列表删除 Key {key_string[:8]}... 时出错 (可能已不存在)。")

            # 无论列表删除是否成功，都尝试从配置字典中移除
            config_removed = self.key_configs.pop(key_string, None) is not None # pop 返回被移除的值或 None

            # 可选：是否需要清理其他相关状态？
            # 例如：usage_data, daily_exhausted_keys, temporary_issue_keys
            # 暂时不清理，以保留历史信息或临时状态。

            if key_existed_in_list or config_removed: # 如果至少从列表或配置中移除了
                logger.info(f"内存模式：成功删除临时 Key: {key_string[:8]}... (从列表: {key_existed_in_list}, 从配置: {config_removed})") # 记录成功日志
                return True # 返回 True
            else: # 如果 Key 原本就不在列表和配置中
                logger.warning(f"内存模式：尝试删除不存在的 Key: {key_string[:8]}...") # 记录警告
                return False # 返回 False
