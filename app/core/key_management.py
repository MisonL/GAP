import asyncio # 导入 asyncio 模块 (Import asyncio module)
import logging # 导入 logging 模块 (Import logging module)
from typing import List, Tuple, TYPE_CHECKING # 导入类型提示 (Import type hints)
from typing import Dict, Any
import os
import re
from . import db_utils

# 从其他模块导入必要的组件
# Import necessary components from other modules
# 注意：根据实际项目结构调整导入路径
# Note: Adjust import paths based on the actual project structure
from .utils import APIKeyManager, test_api_key # 假设 APIKeyManager 和 test_api_key 在同级的 utils 模块中 (Assume APIKeyManager and test_api_key are in the sibling utils module)
from ..handlers.log_config import format_log_message # 假设 format_log_message 在上级目录的 handlers.log_config 模块中 (Assume format_log_message is in the handlers.log_config module in the parent directory)
# 导入 config 模块以访问 MODEL_LIMITS
# Import config module to access MODEL_LIMITS
from .. import config # 导入 config 模块 (Import config module)

# 条件导入用于类型提示，以避免循环依赖（如果 APIKeyManager 稍后需要此处的类型）
# Conditional import for type hinting to avoid circular dependencies (if APIKeyManager needs types from here later)
if TYPE_CHECKING: # 仅在类型检查时导入，避免循环依赖 (Import only during type checking to avoid circular dependencies)
    pass # 目前不需要从 main 或其他模块导入特定类型进行提示 (Currently no need to import specific types from main or other modules for hinting)

logger = logging.getLogger('my_logger') # 使用与 main.py 中相同的日志记录器实例名称，确保日志一致性 (Use the same logger instance name as in main.py to ensure consistent logging)

# 用于存储启动时密钥检查结果的全局变量（由 check_keys 函数更新）
# Global variables to store key check results at startup (updated by the check_keys function)
INITIAL_KEY_COUNT: int = 0 # 初始配置的 Key 总数 (Total number of initially configured keys)
INVALID_KEYS: List[str] = [] # 存储检测到的无效 Key 列表 (List to store detected invalid keys)
INVALID_KEY_COUNT_AT_STARTUP: int = 0 # 存储启动时发现的无效 Key 数量 (Number of invalid keys found at startup)

async def check_keys(key_manager: APIKeyManager) -> Tuple[int, List[str], List[str]]:
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

    if db_utils.IS_MEMORY_DB:
        # 内存模式：从环境变量加载 Key，使用默认配置
        raw_keys = os.environ.get('GEMINI_API_KEYS', "")
        env_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", raw_keys)
        initial_key_count_local = len(env_keys)
        logger.info(f"内存模式：开始检查 {initial_key_count_local} 个配置的 API 密钥...")

        for key in env_keys:
            keys_to_check_with_config[key] = {'enable_context_completion': True} # 内存模式默认启用上下文补全

    else:
        # 文件模式：从数据库加载 Key 及其配置
        logger.info("文件模式：从数据库加载代理 Key 及其配置...")
        try:
            db_keys_data = await db_utils.get_all_proxy_keys()
            initial_key_count_local = len(db_keys_data)
            logger.info(f"从数据库加载了 {initial_key_count_local} 个代理 Key。开始检查有效性...")

            for key_info in db_keys_data:
                key_str = key_info['key']
                # 从数据库加载配置
                config_data = {
                    'description': key_info.get('description'),
                    'is_active': key_info.get('is_active', True), # 默认 True
                    'expires_at': key_info.get('expires_at'),
                    'enable_context_completion': key_info.get('enable_context_completion', True) # 默认 True
                }
                keys_to_check_with_config[key_str] = config_data

        except Exception as e:
            logger.error(f"从数据库加载代理 Key 失败: {e}", exc_info=True)
            # 如果从数据库加载失败，回退到环境变量加载（但会丢失配置）
            logger.warning("从数据库加载 Key 失败，回退到从环境变量加载（将丢失数据库中的配置）。")
            raw_keys = os.environ.get('GEMINI_API_KEYS', "")
            env_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", raw_keys)
            initial_key_count_local = len(env_keys)
            for key in env_keys:
                 keys_to_check_with_config[key] = {'enable_context_completion': True} # 回退时使用默认配置


    # 检查 Key 的有效性 (Google API) 并更新管理器
    valid_keys_with_config: Dict[str, Dict[str, Any]] = {}
    for key, config_data in keys_to_check_with_config.items():
        # 在文件模式下，先检查数据库层面的有效性 (is_active, expires_at)
        is_db_valid = True
        if not db_utils.IS_MEMORY_DB:
             # is_valid_proxy_key 已经检查了 is_active 和 expires_at
             is_db_valid = await db_utils.is_valid_proxy_key(key)

        if is_db_valid:
            is_api_valid = await test_api_key(key)
            status_msg = "有效" if is_api_valid else "无效 (API 测试失败)"
            log_msg = format_log_message('INFO', f"  - API Key {key[:10]}... {status_msg}.")
            logger.info(log_msg)

            if is_api_valid:
                available_keys_local.append(key)
                valid_keys_with_config[key] = config_data # 保留从数据库或默认加载的配置
            else:
                invalid_keys_local.append(key)
        else:
            # 数据库层面无效 (不活动或过期)
            status_msg = "无效 (数据库状态或已过期)"
            log_msg = format_log_message('INFO', f"  - API Key {key[:10]}... {status_msg}.")
            logger.info(log_msg)
            invalid_keys_local.append(key)


    # 检查完所有密钥后报告无效密钥
    if invalid_keys_local:
        logger.warning(f"检测到 {len(invalid_keys_local)} 个无效的 API 密钥:")
        for invalid_key in invalid_keys_local:
            logger.warning(f"  - {invalid_key[:10]}...")

    if not available_keys_local:
        logger.error("严重错误：没有找到任何有效的 API 密钥！应用程序可能无法正常处理请求。", extra={'key': 'N/A', 'request_type': 'startup'})

    # 更新 key_manager 的列表和配置
    with key_manager.keys_lock:
        key_manager.api_keys = available_keys_local
        key_manager.key_configs = valid_keys_with_config # 更新配置字典

    logger.info("API 密钥检查和管理器更新完成。")

    # 更新模块级别的全局变量
    INITIAL_KEY_COUNT = initial_key_count_local
    INVALID_KEYS = invalid_keys_local
    INVALID_KEY_COUNT_AT_STARTUP = len(invalid_keys_local)

    return initial_key_count_local, available_keys_local, invalid_keys_local


# --- Key 分数缓存刷新辅助函数 (此函数之前可能位于 reporting.py，现移至此处以便与 Key 管理逻辑聚合) ---
# --- Key Score Cache Refresh Helper Function (This function might have been in reporting.py before, now moved here to aggregate with key management logic) ---
def _refresh_all_key_scores(key_manager: 'APIKeyManager'):
    """
    辅助函数，用于迭代并更新所有已知模型的 Key 健康度分数缓存。
    此函数通常由后台调度任务（如 APScheduler）周期性调用。
    Helper function to iterate and update the key health score cache for all known models.
    This function is typically called periodically by a background scheduled task (e.g., APScheduler).

    Args:
        key_manager (APIKeyManager): 需要更新其内部缓存分数的 APIKeyManager 实例。The APIKeyManager instance whose internal cache scores need to be updated.
    """
    logger.debug("开始执行周期性 Key 分数缓存刷新任务...") # 将日志级别设为 DEBUG，因为此任务会频繁运行 (Set log level to DEBUG as this task runs frequently)
    # 从配置中获取所有定义了限制的模型名称列表
    # Get the list of all model names from the configuration that have limits defined
    models_to_update = list(config.MODEL_LIMITS.keys()) # 获取模型限制字典的键列表 (Get list of keys from the model limits dictionary)
    if not models_to_update: # 如果没有配置模型限制 (If no model limits are configured)
        logger.warning("在 config.MODEL_LIMITS 中未找到任何模型限制，无法刷新 Key 分数缓存。") # Log warning if no model limits are found
        return # 直接返回 (Return directly)

    updated_count = 0 # 初始化成功更新的模型计数器 (Initialize counter for successfully updated models)
    # 注意：key_manager._update_key_scores 方法内部会处理所需的锁（cache_lock 和 keys_lock），
    # Note: The key_manager._update_key_scores method handles the necessary locks (cache_lock and keys_lock) internally,
    # 因此在这里迭代时不需要额外的锁。
    # so no additional locks are needed when iterating here.
    for model_name in models_to_update: # 遍历所有需要更新分数的模型 (Iterate through all models whose scores need to be updated)
        try:
            # 调用 key_manager 实例的内部方法来更新该模型对应的 Key 分数
            # Call the internal method of the key_manager instance to update the key scores for the corresponding model
            # 传递模型名称和从配置加载的完整模型限制字典
            # Pass the model name and the complete model limits dictionary loaded from the configuration
            key_manager._update_key_scores(model_name, config.MODEL_LIMITS) # 调用内部更新分数方法 (Call internal update scores method)
            updated_count += 1 # 更新成功，计数器加一 (Increment counter on successful update)
        except Exception as e: # 捕获更新过程中可能发生的任何异常 (Catch any exception that might occur during the update process)
            # 记录错误，但继续处理下一个模型
            # Log the error, but continue processing the next model
            logger.error(f"刷新模型 '{model_name}' 的 Key 分数缓存时发生错误: {e}", exc_info=True) # Log error during cache refresh

    # 刷新任务完成后记录总结信息
    # Log summary information after the refresh task is complete
    logger.debug(f"Key 分数缓存刷新任务完成，共成功处理 {updated_count}/{len(models_to_update)} 个模型。") # 将日志级别设为 DEBUG (Set log level to DEBUG)
