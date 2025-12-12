# -*- coding: utf-8 -*-
# app/core/keys/manager.py (原 key_manager_class.py)
# 导入必要的库
import asyncio  # 导入 asyncio 模块，用于异步操作
import copy  # 用于创建对象的深拷贝或浅拷贝
import logging  # 用于应用程序的日志记录
import time  # 用于时间相关操作（例如速率限制、时间戳）

# 导入 datetime 和 pytz 用于处理时间和时区
from datetime import datetime, timezone  # 添加 timezone 导入
from threading import Lock  # 用于线程同步的锁，保护共享资源
from typing import Any, Dict, List, Optional, Set, Tuple, Union  # 导入类型提示

import pytz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # 导入 SQLAlchemy 异步会话
# 导入配置模块
from gap import config  # 导入应用配置

# 导入数据库模型和工具函数
from gap.core.database import utils as db_utils  # 导入数据库工具函数
from gap.core.database.models import ApiKey  # 导入数据库模型

# 从 tracking 模块导入共享的数据结构、锁和常量
from gap.core.tracking import CACHE_REFRESH_INTERVAL_SECONDS  # 常量：RPM/TPM 窗口秒数和缓存刷新间隔秒数
from gap.core.tracking import update_cache_timestamp  # Key 分数缓存、锁、最后更新时间戳和更新函数
from gap.core.tracking import usage_lock  # Key 使用情况数据 (字典) 和对应的锁
from gap.core.tracking import (
    cache_last_updated,
    cache_lock,
    key_scores_cache,
    usage_data,
)

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

# 导入统一锁管理器
try:
    from gap.core.concurrency.lock_manager import lock_manager
except ImportError:
    logger.warning("统一锁管理器不可用，将使用传统锁机制")
    lock_manager = None


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
        self.api_keys: List[str] = []  # 存储当前有效的 API Key 字符串列表
        self.key_configs: Dict[str, Dict[str, Any]] = (
            {}
        )  # 存储每个 Key 的配置信息 (描述、状态、过期时间等)

        self.keys_lock = (
            Lock()
        )  # 线程锁，用于保护 self.api_keys 和 self.key_configs 的并发访问 (保留作为备用)
        self.tried_keys_for_request: Set[str] = (
            set()
        )  # 存储在当前单个 API 请求处理过程中已经尝试过的 Key，避免重复尝试
        self.daily_exhausted_keys: Dict[str, str] = (
            {}
        )  # 存储已达到每日配额限制的 Key 及其达到限制的日期 (YYYY-MM-DD)
        self.temporary_issue_keys: Dict[str, float] = (
            {}
        )  # 存储临时不可用的 Key 及其恢复可用的时间戳 (Unix timestamp)
        self._today_date_str = datetime.now(pytz.timezone("Asia/Shanghai")).strftime(
            "%Y-%m-%d"
        )  # 获取当前上海时区的日期字符串
        # self.user_key_map: Dict[str, str] = defaultdict(str) # 用户-Key 映射，用于粘性会话 (数据库模式下此逻辑在数据库中)
        self.key_selection_records: List[Dict[str, Any]] = (
            []
        )  # 记录 Key 选择过程的详细信息，用于调试和分析
        self.records_lock = (
            Lock()
        )  # 保护 key_selection_records 列表的线程锁 (保留作为备用)
        self.session_hidden_web_ui_keys: Set[str] = (
            set()
        )  # 存储在当前会话中被"虚拟删除"的 WEB_UI_PASSWORDS
        self.session_env_key_configs: Dict[str, Dict[str, Any]] = (
            {}
        )  # 存储环境变量Key在当前会话中的临时配置

    def _get_lock(self, lock_name: str):
        """获取统一锁管理器中的锁，如果不可用则回退到传统锁"""
        if lock_manager:
            return lock_manager.get_thread_lock(lock_name)
        else:
            # 回退到传统锁映射
            lock_map = {
                "api_keys": self.keys_lock,
                "selection_records": self.records_lock,
            }
            return lock_map.get(lock_name)

    async def reload_keys(self, db: Optional[AsyncSession] = None):
        """
        根据配置的 KEY_STORAGE_MODE (内存或数据库) 异步重新加载 API Key 列表和配置。
        此方法会清除当前的内存状态 (api_keys, key_configs)，并从指定源重新加载。
        通常在应用启动时或需要刷新 Key 列表时调用。

        Args:
            db (Optional[AsyncSession]): 数据库模式下需要传入 SQLAlchemy 异步数据库会话。
                                         内存模式下不需要。
        """
        logger.info(
            f"开始重新加载 API Keys (模式: {config.KEY_STORAGE_MODE})..."
        )  # 记录开始重新加载日志
        new_api_keys: List[str] = []  # 用于存储新加载的活动 Key 字符串
        new_key_configs: Dict[str, Dict[str, Any]] = {}  # 用于存储新加载的所有 Key 配置

        if config.KEY_STORAGE_MODE == "memory":  # --- 内存模式 ---
            logger.info("内存模式：从环境变量 GEMINI_API_KEYS 重新加载...")  # 记录日志
            raw_keys = (
                config.GEMINI_API_KEYS or ""
            )  # 从配置获取原始 Key 字符串 (逗号分隔)
            # 分割字符串，去除空白，过滤空字符串
            env_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
            # 为每个 Key 创建默认配置
            for key in env_keys:
                new_api_keys.append(key)  # 添加到活动 Key 列表
                new_key_configs[key] = {  # 创建默认配置
                    "description": "从环境变量加载",
                    "is_active": True,  # 默认激活
                    "expires_at": None,  # 默认永不过期
                    "enable_context_completion": True,  # 默认启用上下文
                    "user_id": None,  # 环境变量模式无用户关联
                }

            # 添加管理员 API Key 作为有效的登录密钥
            if config.ADMIN_API_KEY:
                admin_key = config.ADMIN_API_KEY.strip()
                if admin_key and admin_key not in new_api_keys:
                    new_api_keys.append(admin_key)
                    new_key_configs[admin_key] = {
                        "description": "管理员 API Key",
                        "is_active": True,
                        "expires_at": None,
                        "enable_context_completion": True,
                        "user_id": None,
                    }
                    logger.info("已添加管理员 API Key 到有效密钥列表。")

            logger.info(
                f"内存模式：重新加载了 {len(new_api_keys)} 个 Key。"
            )  # 记录加载数量

        elif config.KEY_STORAGE_MODE == "database":  # --- 数据库模式 ---
            logger.info("数据库模式：从数据库重新加载 API Keys...")  # 记录日志
            if not db:  # 检查是否传入了数据库会话
                logger.error(
                    "数据库模式下重新加载 Key 需要数据库会话，但未提供。"
                )  # 记录错误
                return  # 无法加载，直接返回

            try:
                # 调用数据库工具函数获取所有 Key 对象
                db_api_key_objects: List[ApiKey] = (
                    await db_utils.get_all_api_keys_from_db(db)
                )
                # 遍历数据库中的 Key 对象
                for key_obj in db_api_key_objects:
                    # 只将状态为激活 (is_active=True) 的 Key 添加到内存中的活动 Key 列表
                    # 检查 is_active 属性的实际值
                    # 访问ORM对象的实际属性值
                    if key_obj.is_active:  # type: ignore
                        new_api_keys.append(key_obj.key_string)  # type: ignore
                    # 总是加载所有 Key (包括非激活的) 的配置信息到 key_configs 字典
                    # 访问ORM对象的实际属性值
                    new_key_configs[key_obj.key_string] = {  # type: ignore
                        "description": key_obj.description,
                        "is_active": key_obj.is_active,
                        "expires_at": key_obj.expires_at,
                        "enable_context_completion": key_obj.enable_context_completion,
                        "user_id": key_obj.user_id,
                    }
                # 记录从数据库加载的 Key 数量和活动 Key 数量
                logger.info(
                    f"数据库模式：重新加载了 {len(db_api_key_objects)} 个 Key 配置，其中 {len(new_api_keys)} 个为活动状态。"
                )
            except Exception as e:  # 捕获数据库查询过程中可能发生的异常
                logger.error(
                    f"从数据库重新加载 API Key 失败: {e}", exc_info=True
                )  # 记录错误
                # 加载失败时，可以选择保持现有的 Key 状态不变，或者清空。
                # 当前实现为保持不变，避免因临时数据库问题导致服务完全不可用。
                return  # 直接返回
        else:  # --- 未知模式 ---
            logger.error(
                f"未知的 KEY_STORAGE_MODE: {config.KEY_STORAGE_MODE}。无法重新加载 API Key。"
            )  # 记录错误
            return  # 直接返回

        # --- 更新管理器状态 ---
        # 使用线程锁确保更新过程的原子性
        with self._get_lock("api_keys"):
            self.api_keys = new_api_keys  # 更新活动 Key 列表
            self.key_configs = new_key_configs  # 更新 Key 配置字典
            # 可选：是否需要在此处重置 daily_exhausted_keys 和 temporary_issue_keys？
            # 决定：暂时不重置，让这些状态在它们各自的逻辑中过期或被清理，
            # 避免 reload 操作意外恢复了实际上仍然受限的 Key。
            logger.info("APIKeyManager 状态已更新。")  # 记录状态更新完成

    def get_key_config(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 API Key 的配置信息。

        Args:
            api_key (str): 要查询的 API Key 字符串。

        Returns:
            Optional[Dict[str, Any]]: 包含 Key 配置的字典，如果 Key 不存在则返回 None。
                                      返回的是配置的深拷贝，防止外部修改影响内部状态。
        """
        with self._get_lock("api_keys"):  # 获取锁以安全访问 key_configs
            config_data = self.key_configs.get(api_key)  # 从字典获取配置
            # 返回配置的深拷贝，如果找到了配置；否则返回 None
            return copy.deepcopy(config_data) if config_data else None

    # update_key_config 方法已移除，因为 Key 的更新应通过 API -> 数据库/环境变量 -> reload_keys 的流程完成，
    # 而不是直接修改内存中的 KeyManager 状态。

        # get_next_key method removed as it is deprecated and unused.

    async def get_key_id(
        self, api_key: str, db: Optional[AsyncSession] = None
    ) -> Optional[int]:
        """根据 Key 字符串获取其在数据库中的 ID。

        仅在 KEY_STORAGE_MODE == "database" 且提供了 AsyncSession 时有效。
        """
        if config.KEY_STORAGE_MODE != "database":
            logger.debug("get_key_id 在非数据库模式下被调用，直接返回 None。")
            return None
        if db is None:
            logger.warning(
                "get_key_id 在数据库模式下被调用，但未提供 AsyncSession，返回 None。"
            )
            return None
        try:
            api_key_obj = await db_utils.get_api_key_by_string(db, api_key)
            return api_key_obj.id if api_key_obj is not None else None
        except Exception as e:
            logger.error(
                f"根据 Key 字符串获取 ID 失败 (Key: {api_key[:8]}...): {e}",
                exc_info=True,
            )
            return None

    async def update_user_key_association(
        self, db: AsyncSession, user_id: str, api_key: str
    ) -> None:
        """更新指定用户与 Key 之间的关联信息。

        该方法会将用户最近一次成功使用的 Key 记录到 user_key_associations 表，
        以支持粘性会话等特性。
        """
        try:
            from gap.core.database.models import ApiKey, UserKeyAssociation

            # 查找对应的 ApiKey 记录
            stmt_key = select(ApiKey.id).where(ApiKey.key_string == api_key)
            result_key = await db.execute(stmt_key)
            key_id = result_key.scalar_one_or_none()
            if key_id is None:
                logger.warning(
                    f"update_user_key_association: 未在数据库中找到 Key {api_key[:8]}...，跳过关联更新。"
                )
                return

            # 插入或更新 UserKeyAssociation 记录
            now_ts = time.time()
            stmt_select = select(UserKeyAssociation).where(
                UserKeyAssociation.user_id == user_id,
                UserKeyAssociation.key_id == key_id,
            )
            result_assoc = await db.execute(stmt_select)
            assoc_obj = result_assoc.scalar_one_or_none()
            if assoc_obj is None:
                assoc_obj = UserKeyAssociation(
                    user_id=user_id,
                    key_id=key_id,
                    last_used_timestamp=now_ts,
                )
                db.add(assoc_obj)
            else:
                assoc_obj.last_used_timestamp = now_ts

            await db.commit()
            logger.debug(
                f"已更新用户 {user_id} 与 Key {api_key[:8]}... 的关联 (key_id={key_id})。"
            )
        except Exception as e:
            await db.rollback()
            logger.error(
                f"更新用户 {user_id} 与 Key {api_key[:8]}... 的关联失败: {e}",
                exc_info=True,
            )

    async def select_best_key(
        self,
        model_name: str,
        model_limits: Dict[str, Any],
        estimated_input_tokens: int,
        user_id: Optional[str] = None,
        enable_sticky_session: bool = False,
        request_id: Optional[str] = None,
        cached_content_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,  # 数据库会话，用于数据库模式下的查询
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
        with self._get_lock("api_keys"):
            # --- 跟踪与准备 ---
            # 增加 Key 选择尝试的总次数 (用于统计)
            from gap.core import tracking  # 导入 tracking 模块

            with tracking.cache_tracking_lock:  # 获取缓存跟踪锁
                tracking.key_selection_total_attempts += 1  # 增加总尝试次数

            selected_key: str | None = None  # 初始化选定的 Key 为 None
            available_input_tokens = 0  # 初始化可用输入 Token 容量为 0
            reason_prefix = "N/A"  # 初始化 reason_prefix
            user_association_reason = (
                "User Assoc. - Skipped"  # 初始化 user_association_reason
            )

            # --- 准备不可用 Key 集合 ---
            # 获取当天日期字符串，用于检查每日配额
            self._today_date_str = datetime.now(
                pytz.timezone("Asia/Shanghai")
            ).strftime("%Y-%m-%d")
            # 获取当天已耗尽配额的 Key 集合
            daily_exhausted = {
                k
                for k, date_str in self.daily_exhausted_keys.items()
                if date_str == self._today_date_str
            }
            # 获取当前请求已经尝试过的 Key 集合 (创建副本以防迭代问题)
            tried_keys = self.tried_keys_for_request.copy()
            # 获取当前内存中所有标记为活动的 Key 列表 (创建副本)
            current_active_keys = self.api_keys[:]
            # 获取临时不可用的 Key 集合 (is_key_temporarily_unavailable 内部会清理过期标记)
            temporarily_unavailable_keys = {
                k for k in current_active_keys if self.is_key_temporarily_unavailable(k)
            }

            # --- 策略 1: 缓存关联 Key 优先级 ---
            # 仅在数据库模式、启用原生缓存、提供了缓存 ID 且有数据库会话时执行
            if (
                config.KEY_STORAGE_MODE == "database"
                and config.ENABLE_NATIVE_CACHING
                and cached_content_id
                and db
            ):
                logger.debug(
                    f"请求 {request_id} - 策略 1: 尝试缓存关联 Key (Cache ID: {cached_content_id})"
                )  # 记录日志
                try:
                    # 调用数据库工具函数查找与缓存 ID 关联的 Key ID
                    associated_key_id = await db_utils.get_key_id_by_cached_content_id(
                        db, cached_content_id
                    )
                    if associated_key_id:  # 如果找到了关联的 Key ID
                        # 根据 Key ID 查找 Key 字符串
                        associated_key_str = await db_utils.get_key_string_by_id(
                            db, associated_key_id
                        )
                        if associated_key_str:  # 如果找到了 Key 字符串
                            logger.debug(
                                f"请求 {request_id} - 找到与缓存 {cached_content_id} 关联的 Key: {associated_key_str[:8]}..."
                            )  # 记录日志
                            reason_prefix = "Cache Assoc."  # 定义日志原因前缀
                            # --- 检查关联 Key 的可用性 ---
                            if (
                                associated_key_str not in current_active_keys
                            ):  # 是否在当前活动 Key 列表中
                                reason = f"{reason_prefix} - Key not active/found in manager"  # 不可用原因
                                logger.warning(
                                    f"请求 {request_id} - {reason}"
                                )  # 记录警告
                                self.record_selection_reason(
                                    associated_key_str, reason, request_id
                                )  # 记录选择原因
                            elif (
                                associated_key_str in tried_keys
                            ):  # 是否已在本请求中尝试过
                                reason = f"{reason_prefix} - Key already tried"
                                logger.warning(f"请求 {request_id} - {reason}")
                                self.record_selection_reason(
                                    associated_key_str, reason, request_id
                                )
                            elif (
                                associated_key_str in daily_exhausted
                            ):  # 是否已达到每日配额
                                reason = f"{reason_prefix} - Daily Quota Exhausted"
                                logger.warning(f"请求 {request_id} - {reason}")
                                self.record_selection_reason(
                                    associated_key_str, reason, request_id
                                )
                            elif (
                                associated_key_str in temporarily_unavailable_keys
                            ):  # 是否临时不可用
                                reason = f"{reason_prefix} - Temporarily Unavailable"
                                logger.warning(f"请求 {request_id} - {reason}")
                                self.record_selection_reason(
                                    associated_key_str, reason, request_id
                                )
                            else:  # --- Key 可用，进行 Token 预检查 ---
                                logger.debug(
                                    f"请求 {request_id} - 关联 Key {associated_key_str[:8]}... 可用，进行 Token 预检查..."
                                )
                                with usage_lock:  # 获取使用数据锁
                                    key_usage = usage_data.get(
                                        associated_key_str, {}
                                    ).get(
                                        model_name, {}
                                    )  # 获取该 Key 对该模型的使用数据
                                    tpm_input_limit = model_limits.get(
                                        "tpm_input"
                                    )  # 获取 TPM 输入限制
                                    tpm_input_used = key_usage.get(
                                        "tpm_input_count", 0
                                    )  # 获取当前 TPM 输入计数
                                    potential_tpm_input = (
                                        tpm_input_used + estimated_input_tokens
                                    )  # 计算潜在的总输入 Token
                                    # 检查是否会超过 TPM 限制 (如果有限制)
                                    if (
                                        tpm_input_limit is None
                                        or tpm_input_limit <= 0
                                        or potential_tpm_input <= tpm_input_limit
                                    ):
                                        # --- Token 预检查通过，选定此 Key ---
                                        selected_key = associated_key_str  # 选定 Key
                                        # 计算剩余可用输入 Token 容量
                                        available_input_tokens = (
                                            max(0, tpm_input_limit - tpm_input_used)
                                            if tpm_input_limit is not None
                                            and tpm_input_limit > 0
                                            else 10**18
                                        )
                                        reason = f"{reason_prefix} - Successful Selection"  # 成功原因
                                        logger.info(
                                            f"请求 {request_id} - {reason}: {selected_key[:8]}...。可用输入 Token: {available_input_tokens}"
                                        )  # 记录成功日志
                                        self.record_selection_reason(
                                            selected_key, reason, request_id
                                        )  # 记录选择原因
                                        # 增加成功选择计数
                                        with tracking.cache_tracking_lock:
                                            tracking.key_selection_successful_selections += (
                                                1
                                            )
                                        self.tried_keys_for_request.add(
                                            selected_key
                                        )  # 将选定的 Key 加入本请求的已尝试集合
                                        return selected_key, int(
                                            available_input_tokens
                                        )  # 返回选定的 Key 和可用 Token 容量
                                    else:  # --- Token 预检查失败 ---
                                        reason = f"{reason_prefix} - Token Precheck Failed"  # 失败原因
                                        logger.warning(
                                            f"请求 {request_id} - {reason}: {associated_key_str[:8]}... 潜在总输入 Token: {potential_tpm_input}, 限制: {tpm_input_limit}"
                                        )  # 记录警告
                                        self.record_selection_reason(
                                            associated_key_str, reason, request_id
                                        )  # 记录原因
                        else:  # 如果根据 Key ID 未找到 Key 字符串
                            reason = f"{reason_prefix} - Key string not found for ID {associated_key_id}"
                            logger.warning(f"请求 {request_id} - {reason}")
                            self.record_selection_reason(
                                f"ID:{associated_key_id}", reason, request_id
                            )
                    else:  # 如果未找到与缓存关联的 Key ID
                        reason = f"{reason_prefix} - No associated Key ID found"
                        logger.debug(f"请求 {request_id} - {reason}")
                        self.record_selection_reason("N/A", reason, request_id)
                except Exception as e:  # 捕获数据库查询异常
                    logger.error(
                        f"请求 {request_id} - 查找缓存关联 Key 时出错: {e}",
                        exc_info=True,
                    )  # 记录错误
                    self.record_selection_reason(
                        "N/A", "Cache Assoc. - DB Error", request_id
                    )  # 记录原因
            elif (
                config.KEY_STORAGE_MODE == "database"
                and config.ENABLE_NATIVE_CACHING
                and not db
            ):  # 如果需要数据库但未提供会话
                logger.warning(
                    f"请求 {request_id} - 数据库模式下原生缓存已启用但未提供 db session，无法查找缓存关联 Key。"
                )  # 记录警告
                self.record_selection_reason(
                    "N/A", "Cache Assoc. - DB Session Missing", request_id
                )  # 记录原因
            else:  # 其他跳过缓存关联查找的情况
                logger.debug(
                    f"请求 {request_id} - 跳过缓存关联 Key 查找 (非数据库模式或原生缓存禁用或无 Cache ID)。"
                )  # 记录调试信息
                self.record_selection_reason(
                    "N/A", "Cache Assoc. - Skipped", request_id
                )  # 记录原因

            # --- 策略 2: 用户上次使用 Key 优先级 (粘性会话) ---
            user_association_reason = "User Assoc. - Skipped"  # 初始化原因为跳过
            # 仅在数据库模式、未选定 Key、提供了用户 ID、启用了粘性会话且有数据库会话时执行
            if (
                config.KEY_STORAGE_MODE == "database"
                and selected_key is None
                and user_id
                and enable_sticky_session
                and db
            ):
                logger.debug(
                    f"请求 {request_id} - 策略 2: 尝试用户上次使用 Key (User ID: {user_id})"
                )  # 记录日志
                try:
                    # 调用数据库工具函数获取用户上次使用的 Key ID
                    last_used_key_id = await db_utils.get_user_last_used_key_id(
                        db, user_id
                    )
                    if last_used_key_id:  # 如果找到了上次使用的 Key ID
                        # 根据 Key ID 获取 Key 字符串
                        last_used_key_str = await db_utils.get_key_string_by_id(
                            db, last_used_key_id
                        )
                        if last_used_key_str:  # 如果找到了 Key 字符串
                            logger.debug(
                                f"请求 {request_id} - 用户 {user_id} 上次使用 Key: {last_used_key_str[:8]}..."
                            )  # 记录日志
                            reason_prefix = "User Assoc."  # 定义日志原因前缀
                            # --- 检查上次使用 Key 的可用性 ---
                            if (
                                last_used_key_str not in current_active_keys
                            ):  # 是否在当前活动 Key 列表中
                                user_association_reason = (
                                    f"{reason_prefix} - Key not active/found in manager"
                                )
                                logger.warning(
                                    f"请求 {request_id} - {user_association_reason}"
                                )
                                self.record_selection_reason(
                                    last_used_key_str,
                                    user_association_reason,
                                    request_id,
                                )
                            elif (
                                last_used_key_str in tried_keys
                            ):  # 是否已在本请求中尝试过
                                user_association_reason = (
                                    f"{reason_prefix} - Key already tried"
                                )
                                logger.warning(
                                    f"请求 {request_id} - {user_association_reason}"
                                )
                                self.record_selection_reason(
                                    last_used_key_str,
                                    user_association_reason,
                                    request_id,
                                )
                            elif (
                                last_used_key_str in daily_exhausted
                            ):  # 是否已达到每日配额
                                user_association_reason = (
                                    f"{reason_prefix} - Daily Quota Exhausted"
                                )
                                logger.warning(
                                    f"请求 {request_id} - {user_association_reason}"
                                )
                                self.record_selection_reason(
                                    last_used_key_str,
                                    user_association_reason,
                                    request_id,
                                )
                            elif (
                                last_used_key_str in temporarily_unavailable_keys
                            ):  # 是否临时不可用
                                user_association_reason = (
                                    f"{reason_prefix} - Temporarily Unavailable"
                                )
                                logger.warning(
                                    f"请求 {request_id} - {user_association_reason}"
                                )
                                self.record_selection_reason(
                                    last_used_key_str,
                                    user_association_reason,
                                    request_id,
                                )
                            else:  # --- Key 可用，进行 Token 预检查 ---
                                logger.debug(
                                    f"请求 {request_id} - 上次使用 Key {last_used_key_str[:8]}... 可用，进行 Token 预检查..."
                                )
                                with usage_lock:  # 获取使用数据锁
                                    key_usage = usage_data.get(
                                        last_used_key_str, {}
                                    ).get(
                                        model_name, {}
                                    )  # 获取使用数据
                                    tpm_input_limit = model_limits.get(
                                        "tpm_input"
                                    )  # 获取 TPM 限制
                                    tpm_input_used = key_usage.get(
                                        "tpm_input_count", 0
                                    )  # 获取当前 TPM 计数
                                    potential_tpm_input = (
                                        tpm_input_used + estimated_input_tokens
                                    )  # 计算潜在总输入
                                    # 检查是否会超过 TPM 限制
                                    if (
                                        tpm_input_limit is None
                                        or tpm_input_limit <= 0
                                        or potential_tpm_input <= tpm_input_limit
                                    ):
                                        # --- Token 预检查通过，选定此 Key ---
                                        selected_key = last_used_key_str  # 选定 Key
                                        # 计算剩余可用输入 Token
                                        available_input_tokens = (
                                            max(0, tpm_input_limit - tpm_input_used)
                                            if tpm_input_limit is not None
                                            and tpm_input_limit > 0
                                            else 10**18
                                        )
                                        user_association_reason = f"{reason_prefix} - Successful Selection"  # 成功原因
                                        logger.info(
                                            f"请求 {request_id} - {user_association_reason}: {selected_key[:8]}...。可用输入 Token: {available_input_tokens}"
                                        )  # 记录成功日志
                                        self.record_selection_reason(
                                            selected_key,
                                            user_association_reason,
                                            request_id,
                                        )  # 记录原因
                                        # 增加成功选择计数
                                        with tracking.cache_tracking_lock:
                                            tracking.key_selection_successful_selections += (
                                                1
                                            )
                                        self.tried_keys_for_request.add(
                                            selected_key
                                        )  # 加入已尝试集合
                                        return selected_key, int(
                                            available_input_tokens
                                        )  # 返回结果
                                    else:  # --- Token 预检查失败 ---
                                        user_association_reason = f"{reason_prefix} - Token Precheck Failed"  # 失败原因
                                        logger.warning(
                                            f"请求 {request_id} - {user_association_reason}: {last_used_key_str[:8]}... 潜在总输入 Token: {potential_tpm_input}, 限制: {tpm_input_limit}"
                                        )  # 记录警告
                                        self.record_selection_reason(
                                            last_used_key_str,
                                            user_association_reason,
                                            request_id,
                                        )  # 记录原因
                        else:  # 如果根据 Key ID 未找到 Key 字符串
                            user_association_reason = f"{reason_prefix} - Key string not found for ID {last_used_key_id}"
                            logger.warning(
                                f"请求 {request_id} - {user_association_reason}"
                            )
                            self.record_selection_reason(
                                f"ID:{last_used_key_id}",
                                user_association_reason,
                                request_id,
                            )
                    else:  # 如果未找到用户上次使用的 Key
                        user_association_reason = (
                            f"{reason_prefix} - No last used Key found"
                        )
                        logger.debug(f"请求 {request_id} - {user_association_reason}")
                        self.record_selection_reason(
                            "N/A", user_association_reason, request_id
                        )
                except Exception as e:  # 捕获数据库查询异常
                    logger.error(
                        f"请求 {request_id} - 查找用户上次使用 Key 时出错: {e}",
                        exc_info=True,
                    )  # 记录错误
                    user_association_reason = "User Assoc. - DB Error"
                    self.record_selection_reason(
                        "N/A", user_association_reason, request_id
                    )
            elif selected_key is None:  # 如果未执行用户关联查找，记录跳过原因
                if config.KEY_STORAGE_MODE != "database":
                    user_association_reason = "User Assoc. - Skipped (Not DB Mode)"
                elif not user_id:
                    user_association_reason = "User Assoc. - User ID Missing"
                elif not enable_sticky_session:
                    user_association_reason = "User Assoc. - Sticky Session Disabled"
                elif not db:
                    user_association_reason = "User Assoc. - DB Session Missing"
                logger.debug(
                    f"请求 {request_id} - 跳过用户关联 Key 查找 ({user_association_reason})。"
                )  # 记录调试信息
                self.record_selection_reason(
                    "N/A", user_association_reason, request_id
                )  # 记录原因

            # --- 策略 3: 基于评分和最近最少使用的轮转选择 (回退策略) ---
            if selected_key is None:  # 如果经过前两种策略仍未选定 Key
                logger.debug(
                    f"请求 {request_id} - 策略 3: 执行评分和轮转选择。"
                )  # 记录日志
                # --- 获取 Key 分数 (可能从缓存或数据库) ---
                with cache_lock:  # 获取分数缓存锁
                    now = time.time()  # 获取当前时间
                    # 检查分数缓存是否需要刷新
                    if (
                        now - cache_last_updated.get(model_name, 0)
                        > CACHE_REFRESH_INTERVAL_SECONDS
                    ):
                        logger.info(
                            f"请求 {request_id} - 模型 '{model_name}' 的 Key 分数缓存已过期，正在异步刷新..."
                        )  # 记录日志
                        try:
                            # 创建一个异步任务来更新分数缓存，避免阻塞当前请求
                            asyncio.create_task(
                                self._async_update_key_scores(model_name, model_limits)
                            )
                        except (
                            RuntimeError
                        ):  # 如果当前不在事件循环中 (例如，在同步代码中调用)
                            logger.warning(
                                f"请求 {request_id} - 不在异步事件循环中，无法启动异步刷新任务。依赖后台任务或下次调用刷新。"
                            )  # 记录警告
                        update_cache_timestamp(
                            model_name
                        )  # 更新缓存时间戳，防止短时间内重复触发刷新
                    # 显式声明scores类型为Dict[str, float]
                    # 显式声明scores类型
                    scores: Dict[str, float] = key_scores_cache.get(model_name, {})
                    # 显式声明available_scores类型
                    available_scores: Dict[str, float] = {}

                if not scores:  # 如果没有分数数据
                    logger.warning(
                        f"请求 {request_id} - 模型 '{model_name}' 没有可用的 Key 分数缓存数据。"
                    )  # 记录警告
                    self.record_selection_reason(
                        "N/A", "Score Selection - No Key Score Cache Data", request_id
                    )  # 记录原因
                    # 增加失败选择计数
                    with tracking.cache_tracking_lock:
                        tracking.key_selection_failed_selections += 1
                        tracking.key_selection_failure_reasons[
                            "Score Selection - No Key Score Cache Data"
                        ] += 1
                else:  # 如果有分数数据
                    # --- 筛选可用的 Key ---
                    available_scores = {}  # 存储筛选后的 Key 及其分数
                    reason_prefix = "Score Selection"  # 定义日志原因前缀
                    # 遍历缓存中的所有 Key 分数
                    for k, v in scores.items():
                        # 检查 Key 是否在当前活动的 Key 列表中
                        if k not in current_active_keys:
                            self.record_selection_reason(
                                k,
                                f"{reason_prefix} - Key not active in manager",
                                request_id,
                            )
                            continue  # 跳过非活动 Key
                        # 检查 Key 是否已在本请求中尝试过
                        if k in tried_keys:
                            self.record_selection_reason(
                                k, f"{reason_prefix} - Key already tried", request_id
                            )
                            continue  # 跳过已尝试 Key
                        # 检查 Key 是否已达到每日配额
                        if k in daily_exhausted:
                            self.record_selection_reason(
                                k,
                                f"{reason_prefix} - Daily Quota Exhausted",
                                request_id,
                            )
                            continue  # 跳过每日耗尽 Key
                        # 检查 Key 是否临时不可用
                        if k in temporarily_unavailable_keys:
                            self.record_selection_reason(
                                k,
                                f"{reason_prefix} - Temporarily Unavailable",
                                request_id,
                            )
                            continue  # 跳过临时不可用 Key
                        # 如果 Key 可用，添加到 available_scores 字典
                        available_scores[k] = v

                    if not available_scores:  # 如果筛选后没有可用的 Key
                        logger.warning(
                            f"请求 {request_id} - 模型 '{model_name}' 的所有可用 Key（根据缓存）均已尝试、当天耗尽或临时不可用。"
                        )  # 记录警告
                        self.record_selection_reason(
                            "N/A",
                            f"{reason_prefix} - All available keys tried/exhausted/unavailable",
                            request_id,
                        )  # 记录原因
                        # 增加失败选择计数
                        with tracking.cache_tracking_lock:
                            tracking.key_selection_failed_selections += 1
                            tracking.key_selection_failure_reasons[
                                f"{reason_prefix} - All available keys tried/exhausted/unavailable"
                            ] += 1
                    else:  # 如果有可用的 Key
                        # --- 执行轮转选择 ---
                        # 1. 按分数降序排序
                        # 显式声明变量类型
                        sorted_keys_by_score: List[Tuple[str, float]] = sorted(
                            available_scores.items(),
                            key=lambda item: item[1],
                            reverse=True,
                        )
                        # 2. 确定轮转范围 (例如，分数在前 95% 的 Key)
                        rotation_threshold = 0.95  # 定义轮转阈值
                        best_score: float = (
                            sorted_keys_by_score[0][1] if sorted_keys_by_score else 0.0
                        )
                        # 筛选出分数在阈值范围内的 Key
                        keys_in_rotation_range: List[Tuple[str, float]] = [
                            (k, score)
                            for k, score in sorted_keys_by_score
                            if score >= best_score * rotation_threshold
                        ]

                        # 3. 在轮转范围内的 Key 中，按最近最少使用排序
                        with usage_lock:  # 获取使用数据锁
                            # 对轮转范围内的 Key 按 last_used_timestamp 升序排序（越小越优先）
                            sorted_keys_for_rotation: List[Tuple[str, float]] = sorted(
                                keys_in_rotation_range,
                                key=lambda item: usage_data.get(item[0], {})
                                .get(model_name, {})
                                .get(
                                    "last_used_timestamp", 0.0
                                ),  # 获取上次使用时间戳，默认为 0
                            )
                            # 4. 遍历排序后的 Key，进行 Token 预检查并选择第一个通过的 Key
                            for candidate_key, candidate_score in sorted_keys_for_rotation:  # type: ignore
                                key_usage = usage_data.get(candidate_key, {}).get(
                                    model_name, {}
                                )  # 获取使用数据
                                tpm_input_limit = model_limits.get(
                                    "tpm_input"
                                )  # 获取 TPM 限制
                                tpm_input_used = key_usage.get(
                                    "tpm_input_count", 0
                                )  # 获取当前 TPM 计数
                                potential_tpm_input = (
                                    tpm_input_used + estimated_input_tokens
                                )  # 计算潜在总输入
                                # 检查是否会超过 TPM 限制
                                if (
                                    tpm_input_limit is None
                                    or tpm_input_limit <= 0
                                    or potential_tpm_input <= tpm_input_limit
                                ):
                                    # --- Token 预检查通过，选定此 Key ---
                                    selected_key = candidate_key  # 选定 Key
                                    # 计算剩余可用输入 Token
                                    available_input_tokens = (
                                        max(0, tpm_input_limit - tpm_input_used)
                                        if tpm_input_limit is not None
                                        and tpm_input_limit > 0
                                        else 10**18
                                    )
                                    reason = f"{reason_prefix} - Successful Selection (Score: {candidate_score:.4f})"  # 成功原因
                                    logger.info(
                                        f"请求 {request_id} - {reason}: {selected_key[:8]}...。可用输入 Token: {available_input_tokens}"
                                    )  # 记录成功日志
                                    self.record_selection_reason(
                                        selected_key, reason, request_id
                                    )  # 记录原因
                                    # 增加成功选择计数
                                    with tracking.cache_tracking_lock:
                                        tracking.key_selection_successful_selections += (
                                            1
                                        )
                                    break  # 找到合适的 Key，跳出循环
                                else:  # --- Token 预检查失败 ---
                                    reason = f"{reason_prefix} - Token Precheck Failed"  # 失败原因
                                    logger.warning(
                                        f"请求 {request_id} - {reason}: {candidate_key[:8]}... 潜在总输入 Token: {potential_tpm_input}, 限制: {tpm_input_limit}"
                                    )  # 记录警告
                                    self.record_selection_reason(
                                        candidate_key, reason, request_id
                                    )  # 记录原因
                                    continue  # 继续检查下一个候选 Key

            # --- 最终检查和返回 ---
            if selected_key:  # 如果最终选定了一个 Key
                # 将选定的 Key 加入本请求的已尝试集合
                self.tried_keys_for_request.add(selected_key)
                return selected_key, int(
                    available_input_tokens
                )  # 返回选定的 Key 和可用 Token 容量
            else:  # 如果所有策略都尝试后仍未选定 Key
                final_reason = "Final Failure - No suitable key found after all strategies"  # 最终失败原因
                logger.error(f"请求 {request_id} - {final_reason}")  # 记录错误日志
                self.record_selection_reason(
                    "N/A", final_reason, request_id
                )  # 记录原因
                # 增加失败选择计数
                with tracking.cache_tracking_lock:
                    tracking.key_selection_failed_selections += 1
                    tracking.key_selection_failure_reasons[final_reason] += 1
                return None, 0  # 返回 None 表示未选定 Key

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
        with self._get_lock("api_keys"):  # 获取锁以安全修改共享字典
            self.daily_exhausted_keys[api_key] = (
                self._today_date_str
            )  # 记录 Key 和当天日期
            logger.warning(
                f"API Key {api_key[:10]}... 已达到每日配额限制。"
            )  # 记录警告日志

    def reset_daily_exhausted_keys(self):
        """
        重置所有 API 密钥的每日配额耗尽标记。
        此方法通常在每日重置任务中调用。
        """
        with self._get_lock("api_keys"):  # 获取锁以安全修改共享字典
            keys_count = len(self.daily_exhausted_keys)
            self.daily_exhausted_keys.clear()  # 清空所有每日配额耗尽标记
            if keys_count > 0:
                logger.info(
                    f"已重置 {keys_count} 个 API Key 的每日配额耗尽标记。"
                )  # 记录日志

    def is_key_temporarily_unavailable(self, api_key: str) -> bool:
        """
        检查指定的 API 密钥当前是否因临时问题（例如，短暂的 API 错误）而不可用。
        同时会清理掉已经过期的临时不可用标记。

        Args:
            api_key (str): 要检查的 API Key 字符串。

        Returns:
            bool: 如果 Key 当前处于临时不可用状态，返回 True；否则返回 False。
        """
        with self._get_lock("api_keys"):  # 获取锁以安全访问和修改共享字典
            # 获取该 Key 的过期时间戳，如果不存在则为 None
            expiration_timestamp = self.temporary_issue_keys.get(api_key)
            # 检查是否存在过期时间戳，并且该时间戳是否已小于当前时间
            if expiration_timestamp and expiration_timestamp < time.time():
                # 如果标记已过期，从字典中安全地移除该 Key 的条目
                self.temporary_issue_keys.pop(
                    api_key, None
                )  # pop 避免 Key 不存在时出错
                logger.info(
                    f"API Key {api_key[:10]}... 的临时问题标记已过期，恢复可用。"
                )  # 记录恢复日志
                return False  # 返回 False 表示 Key 不再临时不可用
            # 如果存在未过期的标记，或者标记不存在，根据 expiration_timestamp 是否为 None 判断
            return (
                expiration_timestamp is not None
            )  # 如果存在时间戳 (未过期)，则返回 True

    def mark_key_temporarily_unavailable(
        self, api_key: str, duration_seconds: int = 60, issue_type: Optional[str] = None
    ):
        """
        将指定的 API 密钥标记为临时不可用一段时间。
        这通常在遇到可重试的 API 错误（如 5xx、网络错误或鉴权错误）时调用。

        Args:
            api_key (str): 要标记的 API Key 字符串。
            duration_seconds (int, optional): 临时不可用的持续时间（秒）。默认为 60 秒。
            issue_type (Optional[str], optional): 触发临时不可用状态的原因描述，用于日志记录。
        """
        with self._get_lock("api_keys"):  # 获取锁以安全修改共享字典
            # 计算并存储 Key 恢复可用的时间戳
            self.temporary_issue_keys[api_key] = time.time() + duration_seconds
            reason_suffix = f" (原因: {issue_type})" if issue_type else ""
            logger.warning(
                f"API Key {api_key[:10]}... 临时不可用 {duration_seconds} 秒{reason_suffix}。"
            )  # 记录警告日志

    def record_selection_reason(
        self, key: str, reason: str, request_id: Optional[str] = None
    ):
        """
        记录在 Key 选择过程中，某个 Key 被选中或被跳过的原因。
        用于调试和分析 Key 选择策略的效果。

        Args:
            key (str): 相关的 API Key 字符串 (或 "N/A" 表示未涉及特定 Key)。
            reason (str): 选择或跳过的具体原因。
            request_id (Optional[str]): 与此记录关联的请求 ID。
        """
        with self._get_lock("selection_records"):  # 获取记录列表的锁
            # 将记录信息（Key、原因、请求 ID、时间戳）添加到列表中
            self.key_selection_records.append(
                {
                    "key": key,  # 相关 Key
                    "reason": reason,  # 原因描述
                    "request_id": request_id,  # 请求 ID
                    "timestamp": datetime.now(
                        pytz.timezone("Asia/Shanghai")
                    ).isoformat(),  # 记录时间 (带时区)
                }
            )

    def get_active_keys_count(self) -> int:
        """
        返回当前内存中加载的活动 API 密钥的数量。

        Returns:
            int: 活动 API 密钥的数量。
        """
        with self._get_lock("api_keys"):  # 获取锁以安全访问 api_keys 列表
            return len(self.api_keys)  # 返回列表长度

    def is_key_valid(self, api_key: str) -> bool:
        """
        检查给定的 API Key 是否有效（存在于管理器中，且处于活动状态，未过期）。
        """
        with self._get_lock("api_keys"):
            if api_key not in self.api_keys:  # 首先检查是否在活动 Key 列表中
                return False

            key_config = self.key_configs.get(api_key)  # 获取 Key 配置
            if not key_config:  # 如果没有配置，则认为无效
                return False

            # 检查 is_active 状态
            if not key_config.get("is_active", False):
                return False

            # 检查过期时间
            expires_at = key_config.get("expires_at")
            # 使用时区感知的当前时间
            if expires_at and expires_at < datetime.now(timezone.utc):
                return False

            return True  # 所有检查通过，Key 有效

    def is_admin_key(self, api_key: str) -> bool:
        """检查给定的 API Key 是否是管理员 Key。"""
        return api_key == config.ADMIN_API_KEY

    # --- 兼容测试和性能基准的简化 API 接口 ---
    async def add_api_key(
        self,
        key_id: str,
        api_key: str,
        provider: str,
        model: str,
        max_daily_requests: int = 1000,
    ) -> bool:
        """为性能测试提供的兼容接口，内部委托给 add_key_memory。

        该方法不会触及真实数据库，只在当前进程内维护内存状态。
        """
        config_data: Dict[str, Any] = {
            "id": key_id,
            "api_key": api_key,
            "provider": provider,
            "model": model,
            "description": f"perf:{provider}:{model}:{key_id}",
            "is_active": True,
            "expires_at": None,
            "enable_context_completion": True,
            "user_id": None,
            "max_daily_requests": max_daily_requests,
            "current_daily_requests": 0,
            "health_score": 100.0,
            "success_count": 0,
            "error_count": 0,
        }
        return self.add_key_memory(api_key, config_data)

    async def remove_api_key(self, key_id: str) -> bool:
        """与性能测试兼容的删除接口，根据配置中的 id 查找并删除 Key。"""
        with self._get_lock("api_keys"):
            target_key_string: Optional[str] = None
            for key_string, conf in self.key_configs.items():
                if conf.get("id") == key_id:
                    target_key_string = key_string
                    break
        if not target_key_string:
            logger.warning(f"尝试移除不存在的 Key id={key_id}")
            return False
        return self.delete_key_memory(target_key_string)

    async def _async_update_key_scores(
        self, model_name: str, model_limits: Dict[str, Any]
    ):
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
            new_scores = await db_utils.get_key_scores(model_name)  # 调用函数获取新分数
            with cache_lock:  # 获取分数缓存锁
                key_scores_cache[model_name] = new_scores  # 更新缓存
            logger.info(
                f"模型 '{model_name}' 的 Key 分数缓存已成功更新。"
            )  # 记录成功日志
        except Exception as e:  # 捕获更新过程中可能发生的异常
            logger.error(
                f"更新模型 '{model_name}' 的 Key 分数缓存时出错: {e}", exc_info=True
            )  # 记录错误日志

    def get_and_clear_all_selection_records(self) -> List[Dict[str, Any]]:
        """
        获取当前存储的所有 Key 选择记录，并清空记录列表。
        通常用于定期导出或分析选择日志。

        Returns:
            List[Dict[str, Any]]: 包含所有 Key 选择记录的列表。
        """
        with self._get_lock("selection_records"):  # 获取记录列表的锁
            records = copy.deepcopy(self.key_selection_records)  # 创建记录列表的深拷贝
            self.key_selection_records.clear()  # 清空原始记录列表
            return records  # 返回记录的副本

    # load_keys_from_db 方法已移除，功能合并到 reload_keys 中。

    async def get_api_key_for_cached_content(
        self,
        db: AsyncSession,  # 需要异步数据库会话
        cached_content_identifier: Union[
            int, str
        ],  # 可以是 CachedContent.id 或 CachedContent.content_id
    ) -> Optional[Dict[str, Any]]:  # 返回 Key 的配置字典或 None
        """
        根据缓存内容的标识符 (数据库主键 ID 或 Gemini cache ID/content_id)
        异步查询并返回创建该缓存时所使用的 API Key 的详细信息。

        Args:
            db (AsyncSession): SQLAlchemy 异步数据库会话。
            cached_content_identifier (Union[int, str]):
                - 如果是整数，则假定为 CachedContent 表的主键 ID。
                - 如果是字符串，则假定为 CachedContent 表的 content_id (例如 Gemini 的 cache name)。

        Returns:
            Optional[Dict[str, Any]]: 如果找到关联的 API Key，则返回其配置信息字典
                                      (与 self.key_configs 中的结构类似，但包含 key_string)；否则返回 None。
                                      返回的是配置的深拷贝。
        """
        if not db:
            logger.error("get_api_key_for_cached_content: 数据库会话 (db) 未提供。")
            return None
        # 简化参数检查
        if not db:
            return None
        if not cached_content_identifier:
            return None
            logger.warning(
                "get_api_key_for_cached_content: cached_content_identifier 为 None。"
            )
            return None

        from sqlalchemy.future import select  # 使用新的 select

        from gap.core.database.models import ApiKey, CachedContent  # 延迟导入模型

        api_key_id_to_find: Optional[int] = None

        try:
            if isinstance(cached_content_identifier, int):
                # 假设是 CachedContent 表的主键 ID
                stmt = select(CachedContent.key_id).where(
                    CachedContent.id == cached_content_identifier
                )
                result = await db.execute(stmt)
                api_key_id_to_find = result.scalar_one_or_none()
                if not api_key_id_to_find:
                    logger.info(
                        f"未找到 CachedContent 记录 (ID: {cached_content_identifier}) 或其没有关联的 key_id。"
                    )

            elif isinstance(cached_content_identifier, str):  # type: ignore
                # 假设是 CachedContent 表的 content_id (Gemini cache name)
                stmt = select(CachedContent.key_id).where(
                    CachedContent.content_id == cached_content_identifier
                )
                result = await db.execute(stmt)
                api_key_id_to_find = result.scalar_one_or_none()
                if not api_key_id_to_find:
                    logger.info(
                        f"未找到 CachedContent 记录 (content_id: {cached_content_identifier}) 或其没有关联的 key_id。"
                    )
            else:
                logger.warning(
                    f"无效的 cached_content_identifier 类型: {type(cached_content_identifier)}"
                )
                return None

            if not api_key_id_to_find:
                # logger.info(f"未能从缓存标识符 {cached_content_identifier} 中找到关联的 api_key_id。") # 上面已有更具体的日志
                return None

            # 现在我们有了 api_key_id，需要获取 API Key 的详细信息
            # 此功能主要依赖于数据库模式，因为 ApiKey.id 是数据库概念
            if config.KEY_STORAGE_MODE == "database":
                stmt_api_key = select(ApiKey).where(ApiKey.id == api_key_id_to_find)
                result_api_key = await db.execute(stmt_api_key)
                api_key_record: Optional[ApiKey] = result_api_key.scalar_one_or_none()

                if api_key_record:
                    key_config_from_db: Dict[str, Any] = {
                        "key_string": api_key_record.key_string,
                        "description": api_key_record.description,
                        "is_active": api_key_record.is_active,
                        # 访问ORM对象的实际属性值
                        "expires_at": api_key_record.expires_at.isoformat() if api_key_record.expires_at else None,  # type: ignore
                        "enable_context_completion": api_key_record.enable_context_completion,
                        "user_id": api_key_record.user_id,
                        "id": api_key_record.id,  # 也包含id
                    }
                    logger.info(
                        f"成功为缓存标识符 {cached_content_identifier} (api_key_id: {api_key_id_to_find}) 找到关联的 API Key (来自数据库): {api_key_record.key_string[:8]}..."
                    )
                    return copy.deepcopy(key_config_from_db)  # type: ignore
                else:
                    logger.warning(
                        f"数据库模式：找到了 api_key_id {api_key_id_to_find} 但在 ApiKeys 表中未找到对应记录。"
                    )
                    return None

            elif config.KEY_STORAGE_MODE == "memory":
                # 在纯内存模式下，通过整数 api_key_id 查找 Key 的配置比较困难，
                # 因为 self.key_configs 是以 key_string 为键的。
                # 除非在填充 CachedContent.key_id 时有特殊约定。
                # 遍历 self.key_configs 效率不高，且没有直接的 ID 关联。
                # 我们可以尝试从 self.key_configs 中找到一个 'id' 字段匹配的（如果存在这样的字段）
                with self._get_lock("api_keys"):  # 保护对 key_configs 的访问
                    # 添加类型注解
                    for key_str, conf in self.key_configs.items():  # type: ignore
                        # 假设内存配置中可能有一个 'id' 字段（虽然目前没有明确定义）
                        # 或者如果 key_id 恰好是某种索引或特殊值
                        # 这是一个不完美的匹配，因为内存模式的 key_configs 通常不包含数据库 ID
                        # 但如果 CachedContent.key_id 被用来存储了 key_string (不推荐)
                        # if key_str == str(api_key_id_to_find): # 这是一个错误的假设
                        #    return self.get_key_config(key_str) # get_key_config 返回深拷贝

                        # 更现实的是，如果内存模式下，我们无法仅凭整数 ID 找到 Key
                        pass  # 暂时无法仅凭整数 ID 在内存模式下可靠查找

                logger.warning(
                    f"在 KEY_STORAGE_MODE='memory' 时，通过整数 api_key_id ({api_key_id_to_find}) "
                    f"从内存 key_configs 查找 API Key 详细信息的功能受限或不支持。"
                )
                return None

        except Exception as e:
            logger.error(
                f"查询关联 API Key 时发生错误 (标识符: {cached_content_identifier}): {e}",
                exc_info=True,
            )
            return None

        return None  # 默认返回 None

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
        with self._get_lock("api_keys"):  # 获取锁
            if key_string in self.api_keys:  # 检查 Key 是否已存在
                logger.warning(
                    f"内存模式：尝试添加已存在的 Key: {key_string[:8]}..."
                )  # 记录警告
                return False  # 返回 False
            self.api_keys.append(key_string)  # 添加到 Key 列表
            # 更新 config_data 以包含 _ui_generated 标记，并确保其他字段存在
            # 显式声明类型
            updated_config_data: Dict[str, Any] = {
                "description": config_data.get("description"),
                "is_active": config_data.get("is_active", True),
                "expires_at": config_data.get("expires_at"),
                "enable_context_completion": config_data.get(
                    "enable_context_completion", True
                ),
                "user_id": config_data.get("user_id"),
                "created_at": config_data.get(
                    "created_at", datetime.now(timezone.utc).isoformat()
                ),
                "_ui_generated": True,  # 添加 UI 生成标记
            }
            self.key_configs[key_string] = updated_config_data  # 添加到配置字典
            logger.info(
                f"内存模式：成功添加临时 Key (UI生成): {key_string[:8]}..."
            )  # 记录成功日志
            return True  # 返回 True

    def update_key_memory(self, key_string: str, updates: Dict[str, Any]) -> bool:
        """
        (内存模式) 更新内存中指定 API Key 的配置信息。

        Args:
            key_string (str): 要更新的 Key 字符串。
            updates (Dict[str, Any]): 包含要更新的配置字段和新值的字典。

        Returns:
            bool: 如果成功更新返回 True，如果 Key 不存在则返回 False。
        """
        with self._get_lock("api_keys"):  # 获取锁
            if key_string not in self.key_configs:  # 检查 Key 是否存在于配置中
                logger.warning(
                    f"内存模式：尝试更新不存在的 Key: {key_string[:8]}..."
                )  # 记录警告
                return False  # 返回 False
            # 过滤掉不允许直接更新的字段 (例如 key_string 本身)
            allowed_updates = {k: v for k, v in updates.items() if k != "key_string"}
            # 更新配置字典中对应 Key 的信息
            self.key_configs[key_string].update(allowed_updates)
            logger.info(
                f"内存模式：成功更新临时 Key {key_string[:8]}... 的配置: {allowed_updates}"
            )  # 记录成功日志
            return True  # 返回 True

    def delete_key_memory(self, key_string: str) -> bool:
        """
        (内存模式) 从内存中删除指定的 API Key 及其配置。

        Args:
            key_string (str): 要删除的 Key 字符串。

        Returns:
            bool: 如果成功删除（或 Key 原本就不存在于配置中）返回 True，否则返回 False。
        """
        with self._get_lock("api_keys"):  # 获取锁
            key_existed_in_list = False  # 标记 Key 是否在列表中存在过
            try:
                if key_string in self.api_keys:  # 检查 Key 是否在活动列表中
                    self.api_keys.remove(key_string)  # 从列表中移除
                    key_existed_in_list = True  # 标记存在过
            except (
                ValueError
            ):  # 处理 remove 可能抛出的 ValueError (如果并发导致 Key 已被移除)
                logger.warning(
                    f"内存模式：尝试从 api_keys 列表删除 Key {key_string[:8]}... 时出错 (可能已不存在)。"
                )

            # 无论列表删除是否成功，都尝试从配置字典中移除
            config_removed = (
                self.key_configs.pop(key_string, None) is not None
            )  # pop 返回被移除的值或 None

            # 可选：是否需要清理其他相关状态？
            # 例如：usage_data, daily_exhausted_keys, temporary_issue_keys
            # 暂时不清理，以保留历史信息或临时状态。

            if key_existed_in_list or config_removed:  # 如果至少从列表或配置中移除了
                logger.info(
                    f"内存模式：成功删除临时 Key: {key_string[:8]}... (从列表: {key_existed_in_list}, 从配置: {config_removed})"
                )  # 记录成功日志
                return True  # 返回 True
            else:  # 如果 Key 原本就不在列表和配置中
                logger.warning(
                    f"内存模式：尝试删除不存在的 Key: {key_string[:8]}..."
                )  # 记录警告
                return False  # 返回 False
