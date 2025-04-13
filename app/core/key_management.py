import asyncio
import logging
from typing import List, Tuple, TYPE_CHECKING

# 从其他模块导入必要的组件
# 注意：调整导入路径
from .utils import APIKeyManager, test_api_key # 假设 APIKeyManager 和 test_api_key 在同级 utils 中
from ..handlers.log_config import format_log_message # 假设 format_log_message 在 handlers.log_config 中

# 条件导入用于类型提示，以避免循环依赖（如果 APIKeyManager 稍后需要此处的类型）
if TYPE_CHECKING:
    pass # 目前不需要从 main 导入特定类型

logger = logging.getLogger('my_logger') # 使用与 main.py 中相同的日志记录器实例名称

# 用于存储启动时密钥状态的全局变量 (由 check_keys 管理)
INITIAL_KEY_COUNT: int = 0
INVALID_KEYS: List[str] = []

async def check_keys(key_manager: APIKeyManager) -> Tuple[int, List[str], List[str]]:
    """
    在应用启动时检查所有已配置 API 密钥的有效性。
    使用有效的密钥更新 key_manager。

    Args:
        key_manager (APIKeyManager): 包含密钥的 APIKeyManager 实例。

    Returns:
        Tuple[int, List[str], List[str]]: 一个包含以下内容的元组：
            - initial_key_count: 初始配置的密钥总数。
            - available_keys: 有效 API 密钥的列表。
            - invalid_keys_list: 找到的无效 API 密钥列表。
    """
    global INITIAL_KEY_COUNT, INVALID_KEYS # 声明将修改全局变量
    initial_key_count_local = 0
    available_keys_local = []
    invalid_keys_local = [] # 用于无效密钥的本地列表
    keys_to_check = []

    with key_manager.keys_lock: # 安全地访问密钥
        keys_to_check = key_manager.api_keys[:]
        initial_key_count_local = len(keys_to_check) # 记录初始数量

    logger.info(f"开始检查 {initial_key_count_local} 个配置的 API 密钥...")
    for key in keys_to_check:
        is_valid = await test_api_key(key) # 假设 test_api_key 是异步的
        status_msg = "有效" if is_valid else "无效"
        log_msg = format_log_message('INFO', f"  - API Key {key[:10]}... {status_msg}.")
        logger.info(log_msg)
        if is_valid:
            available_keys_local.append(key)
        else:
            invalid_keys_local.append(key) # 将无效密钥添加到本地列表

    # 检查完所有密钥后报告无效密钥
    if invalid_keys_local:
        logger.warning(f"检测到 {len(invalid_keys_local)} 个无效的 API 密钥:")
        for invalid_key in invalid_keys_local:
            logger.warning(f"  - {invalid_key[:10]}...")

    if not available_keys_local:
        logger.error("错误：没有找到任何有效的 API 密钥！应用可能无法正常处理请求。", extra={'key': 'N/A', 'request_type': 'startup'})

    # 更新 key_manager 的列表，使其仅包含有效密钥
    with key_manager.keys_lock:
        key_manager.api_keys = available_keys_local

    logger.info("API 密钥检查完成。")

    # 更新全局变量
    INITIAL_KEY_COUNT = initial_key_count_local
    INVALID_KEYS = invalid_keys_local

    # 返回初始数量、有效列表和无效列表
    return initial_key_count_local, available_keys_local, invalid_keys_local