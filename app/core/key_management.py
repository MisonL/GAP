import asyncio
import logging
from typing import List, Tuple, TYPE_CHECKING

# 从其他模块导入必要的组件
# 注意：根据实际项目结构调整导入路径
from .utils import APIKeyManager, test_api_key # 假设 APIKeyManager 和 test_api_key 在同级的 utils 模块中
from ..handlers.log_config import format_log_message # 假设 format_log_message 在上级目录的 handlers.log_config 模块中
# 导入 config 模块以访问 MODEL_LIMITS
from .. import config

# 条件导入用于类型提示，以避免循环依赖（如果 APIKeyManager 稍后需要此处的类型）
if TYPE_CHECKING: # 仅在类型检查时导入，避免循环依赖
    pass # 目前不需要从 main 或其他模块导入特定类型进行提示

logger = logging.getLogger('my_logger') # 使用与 main.py 中相同的日志记录器实例名称，确保日志一致性

# 用于存储启动时密钥检查结果的全局变量（由 check_keys 函数更新）
INITIAL_KEY_COUNT: int = 0 # 初始配置的 Key 总数
INVALID_KEYS: List[str] = [] # 存储检测到的无效 Key 列表
INVALID_KEY_COUNT_AT_STARTUP: int = 0 # 存储启动时发现的无效 Key 数量

async def check_keys(key_manager: APIKeyManager) -> Tuple[int, List[str], List[str]]:
    """
    在应用启动时检查所有已配置 API 密钥的有效性。
    使用有效的密钥更新 key_manager。

    Args:
        key_manager (APIKeyManager): 包含待检查密钥的 APIKeyManager 实例。

    Returns:
        Tuple[int, List[str], List[str]]: 一个包含以下内容的元组：
            - initial_key_count (int): 初始配置的密钥总数。
            - available_keys (List[str]): 检测到的有效 API 密钥列表。
            - invalid_keys_list (List[str]): 检测到的无效 API 密钥列表。
    """
    global INITIAL_KEY_COUNT, INVALID_KEYS, INVALID_KEY_COUNT_AT_STARTUP # 声明将要修改模块级别的全局变量
    initial_key_count_local = 0 # 本地变量：初始 Key 数量
    available_keys_local = [] # 本地变量：有效 Key 列表
    invalid_keys_local = [] # 本地变量：无效 Key 列表
    keys_to_check = [] # 本地变量：待检查的 Key 列表

    with key_manager.keys_lock: # 获取锁以安全地访问 key_manager 中的密钥列表
        keys_to_check = key_manager.api_keys[:] # 创建密钥列表的副本以供迭代
        initial_key_count_local = len(keys_to_check) # 记录初始配置的密钥数量

    logger.info(f"开始检查 {initial_key_count_local} 个配置的 API 密钥...")
    for key in keys_to_check:
        is_valid = await test_api_key(key) # 调用异步函数测试单个 Key 的有效性
        status_msg = "有效" if is_valid else "无效" # 根据测试结果设置状态消息
        # 使用格式化函数生成日志消息
        log_msg = format_log_message('INFO', f"  - API Key {key[:10]}... {status_msg}.")
        logger.info(log_msg) # 记录每个 Key 的检查结果
        if is_valid:
            available_keys_local.append(key) # 如果有效，添加到有效 Key 列表
        else:
            invalid_keys_local.append(key) # 如果无效，添加到无效 Key 列表

    # 检查完所有密钥后报告无效密钥
    # 如果在检查过程中发现了无效密钥
    if invalid_keys_local:
        logger.warning(f"检测到 {len(invalid_keys_local)} 个无效的 API 密钥:") # 记录警告信息
        for invalid_key in invalid_keys_local: # 遍历并记录每个无效 Key（部分显示）
            logger.warning(f"  - {invalid_key[:10]}...")

    if not available_keys_local:
        # 如果检查后发现没有任何有效的 Key
        logger.error("严重错误：没有找到任何有效的 API 密钥！应用程序可能无法正常处理请求。", extra={'key': 'N/A', 'request_type': 'startup'})

    # 更新 key_manager 的列表，使其仅包含有效密钥
    # 更新 key_manager 实例中的密钥列表，使其只包含检查后有效的密钥
    with key_manager.keys_lock: # 获取锁以安全地修改列表
        key_manager.api_keys = available_keys_local

    logger.info("API 密钥检查完成。")

    # 更新模块级别的全局变量以供其他模块（如报告）使用
    INITIAL_KEY_COUNT = initial_key_count_local # 更新初始总数
    INVALID_KEYS = invalid_keys_local # 更新无效 Key 列表
    INVALID_KEY_COUNT_AT_STARTUP = len(invalid_keys_local) # 更新启动时无效 Key 的数量
    
    # 返回初始数量、有效列表和无效列表
    return initial_key_count_local, available_keys_local, invalid_keys_local


# --- Key 分数缓存刷新辅助函数 (此函数之前可能位于 reporting.py，现移至此处以便与 Key 管理逻辑聚合) ---
def _refresh_all_key_scores(key_manager: 'APIKeyManager'):
    """
    辅助函数，用于迭代并更新所有已知模型的 Key 健康度分数缓存。
    此函数通常由后台调度任务（如 APScheduler）周期性调用。

    Args:
        key_manager (APIKeyManager): 需要更新其内部缓存分数的 APIKeyManager 实例。
    """
    logger.debug("开始执行周期性 Key 分数缓存刷新任务...") # 将日志级别设为 DEBUG，因为此任务会频繁运行
    # 从配置中获取所有定义了限制的模型名称列表
    models_to_update = list(config.MODEL_LIMITS.keys())
    if not models_to_update: # 如果没有配置模型限制
        logger.warning("在 config.MODEL_LIMITS 中未找到任何模型限制，无法刷新 Key 分数缓存。")
        return # 直接返回

    updated_count = 0 # 初始化成功更新的模型计数器
    # 注意：key_manager._update_key_scores 方法内部会处理所需的锁（cache_lock 和 keys_lock），
    # 因此在这里迭代时不需要额外的锁。
    for model_name in models_to_update: # 遍历所有需要更新分数的模型
        try:
            # 调用 key_manager 实例的内部方法来更新该模型对应的 Key 分数
            # 传递模型名称和从配置加载的完整模型限制字典
            key_manager._update_key_scores(model_name, config.MODEL_LIMITS)
            updated_count += 1 # 更新成功，计数器加一
        except Exception as e: # 捕获更新过程中可能发生的任何异常
            # 记录错误，但继续处理下一个模型
            logger.error(f"刷新模型 '{model_name}' 的 Key 分数缓存时发生错误: {e}", exc_info=True)

    # 刷新任务完成后记录总结信息
    logger.debug(f"Key 分数缓存刷新任务完成，共成功处理 {updated_count}/{len(models_to_update)} 个模型。") # 将日志级别设为 DEBUG