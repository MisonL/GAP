import httpx
import asyncio # 导入 asyncio 模块
import logging # 导入 logging 模块
from typing import List, Tuple, TYPE_CHECKING # 导入类型提示
from typing import Dict, Any
import os
import re

# 注意：根据实际项目结构调整导入路径
# 延迟导入 db_utils 以避免循环依赖
# from app.core import db_utils
from app.core.key_manager_class import APIKeyManager # APIKeyManager 已移至 key_manager_class.py
from app.core.key_utils import test_api_key # test_api_key 已移至 key_utils.py
from app.handlers.log_config import format_log_message # 假设 format_log_message 在上级目录的 handlers.log_config 模块中
# 导入 config 模块以访问 MODEL_LIMITS
from app import config # 导入 config 模块

# 条件导入用于类型提示，以避免循环依赖（如果 APIKeyManager 稍后需要此处的类型）
if TYPE_CHECKING:
    pass

logger = logging.getLogger('my_logger') # 使用与 main.py 中相同的日志记录器实例名称，确保日志一致性

# 用于存储启动时密钥检查结果的全局变量（由 check_keys 函数更新）
INITIAL_KEY_COUNT: int = 0 # 初始配置的 Key 总数
INVALID_KEYS: List[str] = [] # 存储检测到的无效 Key 列表
INVALID_KEY_COUNT_AT_STARTUP: int = 0 # 存储启动时发现的无效 Key 数量

async def check_keys(key_manager: APIKeyManager, http_client: httpx.AsyncClient) -> Tuple[int, List[str], List[str]]: # 添加 http_client 参数
    """
    在应用启动时检查所有已配置 API 密钥的有效性。
    使用有效的密钥更新 key_manager。
    在文件模式下，从数据库加载 Key 及其配置。
    """
    global INITIAL_KEY_COUNT, INVALID_KEYS, INVALID_KEY_COUNT_AT_STARTUP
    initial_key_count_local = 0
    available_keys_local = []
    invalid_keys_local = []
    keys_to_check_with_config: Dict[str, Dict[str, Any]] = {} # 用于存储待检查的 Key 及其配置

    # 延迟导入 db_utils
    from app.core import db_utils
    if db_utils.IS_MEMORY_DB:
        raw_keys = os.environ.get('GEMINI_API_KEYS', "")
        env_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", raw_keys)
        initial_key_count_local = len(env_keys)
        logger.info(f"内存模式：开始检查 {initial_key_count_local} 个配置的 API 密钥...") # 内存模式：开始检查配置的 API 密钥

        for key in env_keys:
            keys_to_check_with_config[key] = {'enable_context_completion': True} # 内存模式默认启用上下文补全

    else:
        logger.info("文件模式：从数据库加载代理 Key 及其配置...") # 文件模式：从数据库加载代理 Key 及其配置
        try:
            db_keys_data = await db_utils.get_all_proxy_keys()
            initial_key_count_local = len(db_keys_data)
            logger.info(f"从数据库加载了 {initial_key_count_local} 个代理 Key。开始检查有效性...") # 从数据库加载了代理 Key，开始检查有效性

            for key_info in db_keys_data:
                key_str = key_info['key']
                config_data = {
                    'description': key_info.get('description'),
                    'is_active': key_info.get('is_active', True), # 默认 True
                    'expires_at': key_info.get('expires_at'),
                    'enable_context_completion': key_info.get('enable_context_completion', True) # 默认 True
                }
                keys_to_check_with_config[key_str] = config_data

        except Exception as e:
            logger.error(f"从数据库加载代理 Key 失败: {e}", exc_info=True) # 从数据库加载代理 Key 失败
            # 如果从数据库加载失败，回退到环境变量加载（但会丢失配置）
            logger.warning("从数据库加载 Key 失败，回退到从环境变量加载（将丢失数据库中的配置）。") # 从数据库加载 Key 失败，回退到从环境变量加载
            raw_keys = os.environ.get('GEMINI_API_KEYS', "")
            env_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", raw_keys)
            initial_key_count_local = len(env_keys)
            for key in env_keys:
                 keys_to_check_with_config[key] = {'enable_context_completion': True} # 回退时使用默认配置


    valid_keys_with_config: Dict[str, Dict[str, Any]] = {}
    tasks = []
    key_order = list(keys_to_check_with_config.keys()) # 保持原始顺序以便匹配结果

    logger.info(f"开始并发检查 {len(key_order)} 个 Key 的有效性...") # 开始并发检查 Key 的有效性

    # 准备并发任务
    for key in key_order:
        config_data = keys_to_check_with_config[key]
        tasks.append(_check_single_key(key, config_data, http_client)) # 使用辅助函数创建任务

    # 并发执行检查
    # return_exceptions=True 使得即使某个检查失败，其他检查也能继续
    results = await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("并发 Key 检查完成，开始处理结果...") # 并发 Key 检查完成，开始处理结果

    # 处理并发结果
    for i, result in enumerate(results):
        key = key_order[i]
        config_data = keys_to_check_with_config[key]

        if isinstance(result, Exception):
            # 如果检查过程中发生异常
            logger.error(f"检查 Key {key[:10]}... 时发生异常: {result}", exc_info=result)
            invalid_keys_local.append(key)
            status_msg = f"无效 (检查时发生错误: {result})"
        elif isinstance(result, tuple) and len(result) == 2:
            # 正常返回结果 (is_valid, status_msg)
            is_valid, status_msg = result
            if is_valid:
                available_keys_local.append(key)
                valid_keys_with_config[key] = config_data # 保留配置
            else:
                invalid_keys_local.append(key)
        else:
             # 未知结果类型
            logger.error(f"检查 Key {key[:10]}... 返回了未知类型的结果: {result}")
            invalid_keys_local.append(key)
            status_msg = "无效 (检查返回未知结果)"

        # 记录每个 Key 的最终状态
        log_msg = format_log_message('INFO', f"  - API Key {key[:10]}... {status_msg}.")
        logger.info(log_msg)


    if invalid_keys_local:
        logger.warning(f"检测到 {len(invalid_keys_local)} 个无效或检查失败的 API 密钥:") # 检测到无效或检查失败的 API 密钥
        # (日志已在上面循环中记录，这里不再重复)
        # for invalid_key in invalid_keys_local:
        #     logger.warning(f"  - {invalid_key[:10]}...")

    if not available_keys_local:
        logger.error("严重错误：没有找到任何有效的 API 密钥！应用程序可能无法正常处理请求。", extra={'key': 'N/A', 'request_type': 'startup'}) # 严重错误：没有找到任何有效的 API 密钥

    logger.info("准备使用锁更新 Key 管理器状态...") # 准备使用锁更新 Key 管理器状态
    with key_manager.keys_lock:
        logger.debug("已获取 key_manager.keys_lock") # 已获取 key_manager.keys_lock
        key_manager.api_keys = available_keys_local
        key_manager.key_configs = valid_keys_with_config # 更新配置字典
        logger.debug(f"Key 管理器状态更新完成：有效 Key 数量 {len(available_keys_local)}") # Key 管理器状态更新完成

    logger.info("API 密钥检查和管理器更新完成。") # API 密钥检查和管理器更新完成

    INITIAL_KEY_COUNT = initial_key_count_local
    INVALID_KEYS = invalid_keys_local
    INVALID_KEY_COUNT_AT_STARTUP = len(invalid_keys_local)

    return initial_key_count_local, available_keys_local, invalid_keys_local


# --- 新增辅助函数 ---
async def _check_single_key(key: str, config_data: Dict[str, Any], http_client: httpx.AsyncClient) -> Tuple[bool, str]:
    """
    异步检查单个 API Key 的有效性（包括数据库和 API 测试）。

    Args:
        key: 要检查的 API Key。
        config_data: 与 Key 关联的配置数据。
        http_client: 用于 API 请求的 httpx.AsyncClient 实例。

    Returns:
        一个元组 (is_valid, status_message)，其中 is_valid 是布尔值，status_message 是描述状态的字符串。
    """
    # 延迟导入 db_utils 以避免循环依赖和潜在的启动问题
    from app.core import db_utils

    # 1. 检查数据库状态（如果不是内存数据库）
    is_db_valid = True
    db_status_msg = "有效 (内存模式或数据库检查通过)"
    if not db_utils.IS_MEMORY_DB:
        try:
            is_db_valid = await db_utils.is_valid_proxy_key(key)
            if not is_db_valid:
                db_status_msg = "无效 (数据库状态或已过期)"
        except Exception as db_exc:
            logger.error(f"检查 Key {key[:10]}... 数据库状态时出错: {db_exc}", exc_info=True)
            return False, f"无效 (数据库检查异常: {db_exc})" # 数据库检查异常，直接返回无效

    if not is_db_valid:
        return False, db_status_msg # 数据库检查未通过

    # 2. 数据库有效，进行 API 测试
    try:
        is_api_valid = await test_api_key(key, http_client)
        if is_api_valid:
            return True, "有效"
        else:
            return False, "无效 (API 测试失败)"
    except httpx.RequestError as req_err:
        logger.warning(f"测试 Key {key[:10]}... 时发生网络请求错误: {req_err}")
        return False, f"无效 (API 测试网络错误: {req_err})"
    except Exception as api_exc:
        logger.error(f"测试 Key {key[:10]}... 时发生未知 API 错误: {api_exc}", exc_info=True)
        return False, f"无效 (API 测试未知错误: {api_exc})"


async def _refresh_all_key_scores(key_manager: 'APIKeyManager'):
    """
    辅助函数，用于迭代并更新所有已知模型的 Key 健康度分数缓存。
    此函数通常由后台调度任务（如 APScheduler）周期性调用。

    Args:
        key_manager (APIKeyManager): 需要更新其内部缓存分数的 APIKeyManager 实例。
    """
    logger.debug("开始执行周期性 Key 分数缓存刷新任务...")
    # 从配置中获取所有定义了限制的模型名称列表
    models_to_update = list(config.MODEL_LIMITS.keys()) # 获取模型限制字典的键列表
    if not models_to_update: # 如果没有配置模型限制
        logger.warning("在 config.MODEL_LIMITS 中未找到任何模型限制，无法刷新 Key 分数缓存。") # 在 config.MODEL_LIMITS 中未找到任何模型限制，无法刷新 Key 分数缓存
        return # 直接返回

    updated_count = 0 # 初始化成功更新的模型计数器
    # 注意：key_manager._update_key_scores 方法内部会处理所需的锁（cache_lock 和 keys_lock），
    # 因此在这里迭代时不需要额外的锁。
    for model_name in models_to_update:
        try:
            await key_manager._async_update_key_scores(model_name, config.MODEL_LIMITS)
            updated_count += 1 # 更新成功，计数器加一
        except Exception as e: # 捕获更新过程中可能发生的任何异常 (Catch any exception that might occur during the update process)
            logger.error(f"刷新模型 '{model_name}' 的 Key 分数缓存时发生错误: {e}", exc_info=True) # 刷新模型 的 Key 分数缓存时发生错误

    logger.debug(f"Key 分数缓存刷新任务完成，共成功处理 {updated_count}/{len(models_to_update)} 个模型。") # Key 分数缓存刷新任务完成
