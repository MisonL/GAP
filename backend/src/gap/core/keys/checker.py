# -*- coding: utf-8 -*-
"""
API Key 有效性检查器。
在应用启动时检查配置的 API Key，并更新 Key 管理器的状态。
"""
import asyncio  # 导入异步 IO 库
import logging  # 导入日志库

# 导入类型提示
from typing import (  # 导入所需类型
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

import httpx  # 导入 HTTP 客户端库

# 导入 config 模块以访问配置项
from gap import config  # 导入应用配置

# 注意：根据实际项目结构调整导入路径
# 延迟导入 db_utils 以避免循环依赖
# from gap.core.database import utils as db_utils # 数据库工具函数 (新路径)
from gap.core.keys.manager import APIKeyManager  # Key 管理器类 (新路径)
from gap.core.keys.utils import test_api_key  # Key 测试函数 (新路径)
from gap.utils.log_config import format_log_message  # 日志格式化函数 (路径修正)

# 条件导入用于类型提示，以避免循环依赖（如果 APIKeyManager 稍后需要此处的类型）
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession  # 仅在类型检查时导入 AsyncSession

logger = logging.getLogger("my_logger")  # 获取日志记录器实例

# --- 全局变量，用于存储启动时 Key 检查的结果 ---
INITIAL_KEY_COUNT: int = 0  # 存储初始配置的 Key 总数
INVALID_KEYS: List[str] = []  # 存储检测到的无效或检查失败的 Key 列表
INVALID_KEY_COUNT_AT_STARTUP: int = 0  # 存储启动时发现的无效 Key 数量


def _process_key_check_results(
    results: List[
        Union[Tuple[bool, str], Exception]
    ],  # 并发检查的结果列表，可能包含元组或异常
    key_order: List[str],  # 保持与 results 对应的 Key 顺序列表
    keys_to_check_with_config: Dict[str, Dict[str, Any]],  # 包含 Key 及其配置的字典
) -> Tuple[List[str], List[str], Dict[str, Dict[str, Any]]]:
    """
    (内部辅助函数) 处理并发 Key 检查任务返回的结果。
    将 Key 分类为有效 (available) 和无效 (invalid)，并收集有效 Key 的配置信息。

    Args:
        results (List[Union[Tuple[bool, str], Exception]]): `asyncio.gather` 返回的结果列表。
        key_order (List[str]): 与 results 列表顺序一致的 API Key 字符串列表。
        keys_to_check_with_config (Dict[str, Dict[str, Any]]): 包含所有待检查 Key 及其配置的字典。

    Returns:
        Tuple[List[str], List[str], Dict[str, Dict[str, Any]]]:
            - available_keys: 有效的 API Key 字符串列表。
            - invalid_keys: 无效或检查失败的 API Key 字符串列表。
            - valid_keys_with_config: 包含有效 Key 及其配置信息的字典。
    """
    available_keys: List[str] = []  # 初始化有效 Key 列表
    invalid_keys: List[str] = []  # 初始化无效 Key 列表
    valid_keys_with_config: Dict[str, Dict[str, Any]] = {}  # 初始化有效 Key 配置字典

    # 遍历检查结果和对应的 Key
    for i, result in enumerate(results):
        key = key_order[i]  # 获取当前结果对应的 Key
        config_data = keys_to_check_with_config[key]  # 获取该 Key 的配置信息
        status_msg = "未知状态"  # 初始化状态消息

        if isinstance(result, Exception):  # --- 情况 1: 检查过程中发生异常 ---
            # 将异常视为 Key 无效
            logger.error(
                f"检查 Key {key[:10]}... 时发生异常: {result}", exc_info=result
            )  # 记录错误日志，包含异常信息
            invalid_keys.append(key)  # 将 Key 加入无效列表
            status_msg = f"无效 (检查时发生错误: {result})"  # 更新状态消息
        elif (
            isinstance(result, tuple) and len(result) == 2
        ):  # --- 情况 2: 正常返回结果元组 ---
            # 解包结果元组 (is_valid, status_msg)
            is_valid, status_msg = result
            if is_valid:  # 如果 Key 有效
                available_keys.append(key)  # 加入有效列表
                valid_keys_with_config[key] = config_data  # 保留其配置信息
            else:  # 如果 Key 无效
                invalid_keys.append(key)  # 加入无效列表
        else:  # --- 情况 3: 返回了未知类型的结果 ---
            logger.error(
                f"检查 Key {key[:10]}... 返回了未知类型的结果: {result}"
            )  # 记录错误日志
            invalid_keys.append(key)  # 将 Key 加入无效列表
            status_msg = "无效 (检查返回未知结果)"  # 更新状态消息

        # 记录每个 Key 的最终检查状态 (使用 DEBUG 级别)
        log_msg = format_log_message(
            "DEBUG", f"  - API Key {key[:10]}... {status_msg}."
        )  # 格式化日志消息
        logger.debug(log_msg)  # 记录调试日志

    # 返回分类后的列表和字典
    return available_keys, invalid_keys, valid_keys_with_config


async def check_keys(
    key_manager: APIKeyManager,
    http_client: httpx.AsyncClient,
    db: Optional["AsyncSession"] = None,
) -> Tuple[int, List[str], List[str]]:
    """
    在应用启动时异步检查所有已配置 API 密钥的有效性。
    此函数负责：
    1. 根据配置的 KEY_STORAGE_MODE 从环境变量或数据库加载所有 Key 及其配置。
    2. 并发地对每个 Key 进行有效性检查（包括数据库状态检查和 API 连通性测试）。
    3. 处理检查结果，区分有效和无效 Key。
    4. 使用检查后的有效 Key 列表和配置更新传入的 APIKeyManager 实例。
    5. 更新全局变量以记录检查结果（初始总数、无效列表、无效数量）。

    Args:
        key_manager (APIKeyManager): 要更新其状态的 APIKeyManager 实例。
        http_client (httpx.AsyncClient): 用于执行 API 测试的共享 HTTP 客户端实例。
        db (Optional[AsyncSession]): 数据库模式下需要传入 SQLAlchemy 异步数据库会话。

    Returns:
        Tuple[int, List[str], List[str]]:
            - initial_key_count_local: 初始加载的 Key 总数。
            - available_keys_local: 检查后确认有效的 Key 列表。
            - invalid_keys_local: 检查后确认无效或检查失败的 Key 列表。
    """
    global INITIAL_KEY_COUNT, INVALID_KEYS, INVALID_KEY_COUNT_AT_STARTUP  # 声明使用全局变量来存储最终结果
    initial_key_count_local = 0  # 本次加载的 Key 初始数量
    keys_to_check_with_config: Dict[str, Dict[str, Any]] = {}  # 存储待检查 Key 及其配置

    # --- 步骤 1: 加载 Keys 和配置 ---
    # 延迟导入 db_utils 和 ApiKey 模型，避免潜在的循环导入问题
    from gap.core.database import utils as db_utils
    from gap.core.database.models import ApiKey

    if config.KEY_STORAGE_MODE == "memory":  # --- 内存模式 ---
        logger.info("内存模式：从环境变量 GEMINI_API_KEYS 加载 API 密钥...")  # 记录日志
        raw_keys = config.GEMINI_API_KEYS or ""  # 从配置获取原始 Key 字符串
        # 按逗号分割，去除空白，过滤空字符串
        env_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        initial_key_count_local = len(env_keys)  # 记录初始数量
        logger.info(
            f"内存模式：找到 {initial_key_count_local} 个来自环境变量的 API 密钥。"
        )  # 记录找到的数量
        logger.debug(f"从环境变量加载的 Key: {env_keys}")  # 记录加载的 Key (DEBUG 级别)

        # 为每个 Key 创建默认配置
        for key in env_keys:
            keys_to_check_with_config[key] = {
                "description": "从环境变量加载",
                "is_active": True,  # 默认激活
                "expires_at": None,  # 默认永不过期
                "enable_context_completion": True,  # 默认启用上下文
                "user_id": None,  # 内存模式无用户关联
            }

    elif config.KEY_STORAGE_MODE == "database":  # --- 数据库模式 ---
        logger.info("数据库模式：从数据库加载 API Key 及其配置...")  # 记录日志
        if not db:  # 检查是否提供了数据库会话
            logger.error(
                "数据库模式需要有效的数据库会话 (db)，但收到 None。无法加载 Key。"
            )  # 记录错误
            # 设置全局变量为空/0，然后返回
            INITIAL_KEY_COUNT = 0
            INVALID_KEYS = []
            INVALID_KEY_COUNT_AT_STARTUP = 0
            return 0, [], []  # 返回空结果
        try:
            # 调用数据库工具函数获取所有 Key 对象
            db_api_key_objects: List[ApiKey] = await db_utils.get_all_api_keys_from_db(
                db
            )
            initial_key_count_local = len(db_api_key_objects)  # 记录初始数量
            logger.info(
                f"从数据库加载了 {initial_key_count_local} 个 API Key。开始检查有效性..."
            )  # 记录加载数量

            # 遍历数据库对象，提取 Key 字符串和配置信息
            for key_obj in db_api_key_objects:
                config_data = {
                    "description": key_obj.description,
                    "is_active": key_obj.is_active,
                    "expires_at": key_obj.expires_at,  # 从数据库读取的值已经是 datetime 对象或 None
                    "enable_context_completion": key_obj.enable_context_completion,
                    "user_id": key_obj.user_id,
                    # 如果需要，可以添加其他字段如 created_at
                }
                keys_to_check_with_config[key_obj.key_string] = (
                    config_data  # 存储 Key 及其配置
                )

        except Exception as e:  # 捕获数据库加载过程中的异常
            logger.error(f"从数据库加载 API Key 失败: {e}", exc_info=True)  # 记录错误
            initial_key_count_local = 0  # 重置计数
            # 设置全局变量为空/0，然后返回
            INITIAL_KEY_COUNT = 0
            INVALID_KEYS = []
            INVALID_KEY_COUNT_AT_STARTUP = 0
            return 0, [], []  # 返回空结果
    else:  # --- 未知模式 ---
        logger.error(
            f"未知的 KEY_STORAGE_MODE: {config.KEY_STORAGE_MODE}。无法加载 API Key。"
        )  # 记录错误
        initial_key_count_local = 0  # 重置计数
        # 设置全局变量为空/0，然后返回
        INITIAL_KEY_COUNT = 0
        INVALID_KEYS = []
        INVALID_KEY_COUNT_AT_STARTUP = 0
        return 0, [], []  # 返回空结果

    # --- 步骤 2: 并发检查 Key 有效性 ---
    tasks = []  # 用于存储并发任务的列表
    key_order = list(
        keys_to_check_with_config.keys()
    )  # 获取 Key 的列表，保持顺序以便后续匹配结果

    logger.info(f"开始并发检查 {len(key_order)} 个 Key 的有效性...")  # 记录开始检查日志

    # 为每个 Key 创建一个检查任务
    for key in key_order:
        config_data = keys_to_check_with_config[key]  # 获取 Key 的配置
        # 将数据库会话 db 传递给 _check_single_key
        tasks.append(
            _check_single_key(key, config_data, http_client, db)
        )  # 创建检查任务

    # 使用 asyncio.gather 并发执行所有检查任务
    # return_exceptions=True 确保即使某个任务抛出异常，gather 也会等待所有任务完成并返回结果（包括异常对象）
    results = await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("并发 Key 检查完成，开始处理结果...")  # 记录检查完成日志

    # --- 步骤 3: 处理检查结果 ---
    # 调用内部辅助函数处理 gather 返回的结果
    available_keys_local, invalid_keys_local, valid_keys_with_config = (
        _process_key_check_results(
            results,  # 传递结果列表
            key_order,  # 传递 Key 顺序列表
            keys_to_check_with_config,  # 传递包含配置的字典
        )
    )

    # 如果存在无效 Key，记录警告摘要
    if invalid_keys_local:
        logger.warning(
            f"检测到 {len(invalid_keys_local)} 个无效或检查失败的 API 密钥。"
        )  # (详细日志已在 _process_key_check_results 中记录)

    # 如果没有任何有效 Key，记录严重错误
    if not available_keys_local:
        error_msg = (
            "严重错误：没有找到任何有效的 API 密钥！应用程序可能无法正常处理请求。\n"
            f"请检查您的 API 密钥配置。当前 KEY_STORAGE_MODE 为 '{config.KEY_STORAGE_MODE}'。\n"
            f"  - 如果是 'memory' 模式, 请确保 GEMINI_API_KEYS 环境变量已正确设置且包含有效的密钥。\n"
            f"  - 如果是 'database' 模式, 请确保数据库中的 'api_keys' 表包含有效的、已激活的密钥。\n"
            f"  所有配置的密钥在启动时都未能通过验证 (详情请查看之前的日志，搜索 '测试 Key' 或 '检查 Key ... 时发生异常')。"
        )
        logger.error(error_msg, extra={"key": "N/A", "request_type": "startup"})

    # --- 步骤 4: 更新 Key 管理器状态 ---
    logger.info("准备使用锁更新 Key 管理器状态...")  # 记录日志
    with key_manager.keys_lock:  # 获取 Key 管理器的锁
        logger.debug("已获取 key_manager.keys_lock")  # 记录获取锁日志
        key_manager.api_keys = available_keys_local  # 更新活动 Key 列表
        key_manager.key_configs = valid_keys_with_config  # 更新有效 Key 的配置字典
        logger.debug(
            f"Key 管理器状态更新完成：有效 Key 数量 {len(available_keys_local)}"
        )  # 记录更新完成日志

    logger.info("API 密钥检查和管理器更新完成。")  # 记录最终完成日志

    # --- 步骤 5: 更新全局变量 ---
    INITIAL_KEY_COUNT = initial_key_count_local  # 更新全局初始总数
    INVALID_KEYS = invalid_keys_local  # 更新全局无效 Key 列表
    INVALID_KEY_COUNT_AT_STARTUP = len(invalid_keys_local)  # 更新全局无效 Key 数量

    # 返回本次检查的结果
    return initial_key_count_local, available_keys_local, invalid_keys_local


# --- 内部辅助函数 ---


async def _check_key_database_status(
    key: str, db: Optional["AsyncSession"]
) -> Tuple[bool, str]:
    """
    (内部辅助函数) 异步检查单个 API Key 在数据库中的状态（是否有效、是否过期）。
    仅在数据库存储模式下执行实际检查。

    Args:
        key (str): 要检查的 API Key 字符串。
        db (Optional[AsyncSession]): SQLAlchemy 异步数据库会话。

    Returns:
        Tuple[bool, str]:
            - 第一个元素：布尔值，指示 Key 在数据库层面是否有效。
            - 第二个元素：描述状态的字符串消息。
    """
    # 延迟导入，避免循环依赖
    from gap import config
    from gap.core.database import utils as db_utils

    if config.KEY_STORAGE_MODE == "memory":  # 内存模式
        # 内存模式下，Key 的有效性仅通过 API 测试判断，数据库层面视为有效
        return True, "有效 (内存模式)"
    elif config.KEY_STORAGE_MODE == "database":  # 数据库模式
        # 检查是否传入了有效的数据库会话
        if not db:
            logger.error(
                f"数据库模式下检查 Key {key[:10]}... 状态，但未提供数据库会话。"
            )  # 记录错误
            return False, "无效 (数据库检查失败 - 缺少会话)"  # 返回无效
        try:
            # 调用数据库工具函数检查 Key 是否有效 (存在且 is_active=True)
            is_db_valid = await db_utils.is_valid_proxy_key(db, key)
            if is_db_valid:  # 如果数据库检查通过
                return True, "有效 (数据库检查通过)"  # 返回有效
            else:
                # Key 在数据库中不存在或被标记为无效 (is_active=False) 或已过期 (如果 is_valid_proxy_key 包含过期检查)
                return False, "无效 (数据库状态或已过期)"  # 返回无效
        except Exception as db_exc:  # 捕获数据库查询异常
            logger.error(
                f"检查 Key {key[:10]}... 数据库状态时出错: {db_exc}", exc_info=True
            )  # 记录错误
            return False, f"无效 (数据库检查异常: {db_exc})"  # 返回无效
    else:  # 未知存储模式
        logger.error(
            f"未知的 KEY_STORAGE_MODE '{config.KEY_STORAGE_MODE}'，无法检查 Key {key[:10]}... 数据库状态。"
        )  # 记录错误
        return False, "无效 (未知存储模式)"  # 返回无效


async def _perform_api_test(
    key: str, http_client: httpx.AsyncClient
) -> Tuple[bool, str]:
    """
    (内部辅助函数) 对单个 API Key 进行实际的 API 调用测试，以验证其连通性和有效性。

    Args:
        key (str): 要测试的 API Key 字符串。
        http_client (httpx.AsyncClient): 用于执行 API 请求的 HTTP 客户端实例。

    Returns:
        Tuple[bool, str]:
            - 第一个元素：布尔值，指示 API 测试是否通过。
            - 第二个元素：描述测试结果的状态消息。
    """
    try:
        # 调用位于 keys.utils 中的测试函数
        is_api_valid = await test_api_key(key, http_client)
        if is_api_valid:  # 如果测试成功
            return True, "有效 (API 测试通过)"  # 返回有效
        else:  # 如果测试失败 (例如返回 4xx 错误)
            return False, "无效 (API 测试失败)"  # 返回无效
    except (
        httpx.RequestError
    ) as req_err:  # 捕获网络请求相关的错误 (如 DNS 解析失败、连接超时等)
        logger.warning(
            f"测试 Key {key[:10]}... 时发生网络请求错误: {req_err}"
        )  # 记录警告
        return False, f"无效 (API 测试网络错误: {req_err})"  # 返回无效
    except Exception as api_exc:  # 捕获其他在 API 测试中可能发生的未知异常
        logger.error(
            f"测试 Key {key[:10]}... 时发生未知 API 错误: {api_exc}", exc_info=True
        )  # 记录错误
        return False, f"无效 (API 测试未知错误: {api_exc})"  # 返回无效


async def _check_single_key(
    key: str,
    config_data: Dict[str, Any],
    http_client: httpx.AsyncClient,
    db: Optional["AsyncSession"] = None,
) -> Tuple[bool, str]:
    """
    (内部辅助函数) 异步检查单个 API Key 的完整有效性。
    首先检查数据库状态（如果适用），然后执行 API 连通性测试。

    Args:
        key (str): 要检查的 API Key 字符串。
        config_data (Dict[str, Any]): 与该 Key 关联的配置数据 (目前未使用，但保留以备将来扩展)。
        http_client (httpx.AsyncClient): 用于 API 请求的 HTTP 客户端实例。
        db (Optional[AsyncSession]): SQLAlchemy 异步数据库会话 (仅在数据库模式下需要)。

    Returns:
        Tuple[bool, str]:
            - 第一个元素：布尔值，指示 Key 是否最终有效。
            - 第二个元素：描述最终状态的字符串消息。
    """
    # 1. 检查数据库状态 (如果需要)
    is_db_valid, db_status_msg = await _check_key_database_status(key, db)
    if not is_db_valid:  # 如果数据库检查未通过
        return False, db_status_msg  # 直接返回数据库检查结果

    # 2. 如果数据库检查通过 (或内存模式)，则执行 API 测试
    return await _perform_api_test(key, http_client)


async def _refresh_all_key_scores(key_manager: "APIKeyManager"):
    """
    (内部辅助函数) 异步刷新所有已知模型的 Key 健康度分数缓存。
    此函数通常由后台调度任务（如 APScheduler）周期性调用。

    Args:
        key_manager (APIKeyManager): 需要更新其内部缓存分数的 APIKeyManager 实例。
    """
    logger.debug("开始执行周期性 Key 分数缓存刷新任务...")  # 记录开始日志
    # 从应用配置中获取所有定义了限制的模型名称列表
    models_to_update = list(config.MODEL_LIMITS.keys())  # 获取模型列表
    if not models_to_update:  # 如果配置中没有模型限制
        logger.debug(
            "在 config.MODEL_LIMITS 中未找到任何模型限制，无法刷新 Key 分数缓存。"
        )  # 记录警告改为 debug
        return  # 直接返回

    updated_count = 0  # 初始化成功更新的模型计数器
    # 遍历所有需要更新的模型
    # 注意：key_manager._async_update_key_scores 方法内部会处理所需的锁
    for model_name in models_to_update:
        try:
            # 调用 Key 管理器的内部方法来异步更新该模型的分数缓存
            await key_manager._async_update_key_scores(model_name, config.MODEL_LIMITS)
            updated_count += 1  # 更新成功，计数器加一
        except Exception as e:  # 捕获更新过程中可能发生的任何异常
            logger.error(
                f"刷新模型 '{model_name}' 的 Key 分数缓存时发生错误: {e}", exc_info=True
            )  # 记录错误日志

    # 记录刷新任务完成的日志，包含成功处理的模型数量
    logger.debug(
        f"Key 分数缓存刷新任务完成，共成功处理 {updated_count}/{len(models_to_update)} 个模型。"
    )
