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
    for key, config_data in keys_to_check_with_config.items():
        is_db_valid = True
        # 延迟导入 db_utils
        from app.core import db_utils
        if not db_utils.IS_MEMORY_DB:
             is_db_valid = await db_utils.is_valid_proxy_key(key)

        if is_db_valid:
            is_api_valid = await test_api_key(key, http_client) # 传递 http_client
            status_msg = "有效" if is_api_valid else "无效 (API 测试失败)"
            log_msg = format_log_message('INFO', f"  - API Key {key[:10]}... {status_msg}.")
            logger.info(log_msg)

            if is_api_valid:
                available_keys_local.append(key)
                valid_keys_with_config[key] = config_data # 保留从数据库或默认加载的配置
            else:
                invalid_keys_local.append(key)
        else:
            status_msg = "无效 (数据库状态或已过期)"
            log_msg = format_log_message('INFO', f"  - API Key {key[:10]}... {status_msg}.")
            logger.info(log_msg)
            invalid_keys_local.append(key)


    if invalid_keys_local:
        logger.warning(f"检测到 {len(invalid_keys_local)} 个无效的 API 密钥:") # 检测到无效的 API 密钥
        for invalid_key in invalid_keys_local:
            logger.warning(f"  - {invalid_key[:10]}...") # 部分显示

    if not available_keys_local:
        logger.error("严重错误：没有找到任何有效的 API 密钥！应用程序可能无法正常处理请求。", extra={'key': 'N/A', 'request_type': 'startup'}) # 严重错误：没有找到任何有效的 API 密钥

    with key_manager.keys_lock:
        key_manager.api_keys = available_keys_local
        key_manager.key_configs = valid_keys_with_config # 更新配置字典

    logger.info("API 密钥检查和管理器更新完成。") # API 密钥检查和管理器更新完成

    INITIAL_KEY_COUNT = initial_key_count_local
    INVALID_KEYS = invalid_keys_local
    INVALID_KEY_COUNT_AT_STARTUP = len(invalid_keys_local)

    return initial_key_count_local, available_keys_local, invalid_keys_local


def _refresh_all_key_scores(key_manager: 'APIKeyManager'):
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
            key_manager._update_key_scores(model_name, config.MODEL_LIMITS)
            updated_count += 1 # 更新成功，计数器加一
        except Exception as e: # 捕获更新过程中可能发生的任何异常 (Catch any exception that might occur during the update process)
            logger.error(f"刷新模型 '{model_name}' 的 Key 分数缓存时发生错误: {e}", exc_info=True) # 刷新模型 的 Key 分数缓存时发生错误

    logger.debug(f"Key 分数缓存刷新任务完成，共成功处理 {updated_count}/{len(models_to_update)} 个模型。") # Key 分数缓存刷新任务完成
