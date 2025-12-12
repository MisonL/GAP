# -*- coding: utf-8 -*-
"""
包含每日计数重置相关任务的函数。
此模块主要用于 APScheduler 定时任务，在每天特定时间（通常是午夜）执行。
"""
import logging  # 导入日志模块
from datetime import datetime, timedelta  # 导入日期和时间处理类

import pytz  # 导入时区库，用于处理太平洋时间
from fastapi import Depends  # 导入 FastAPI 的 Depends，用于依赖注入

from gap.core.dependencies import get_key_manager  # 导入获取 Key 管理器的依赖函数
from gap.core.keys.manager import APIKeyManager  # 导入 APIKeyManager 类型提示 (新路径)
from gap.core.tracking import daily_totals_lock  # 存储每日总 RPD 的字典和对应的锁
from gap.core.tracking import usage_lock  # Key 的实时使用数据和对应的锁
from gap.core.tracking import (  # 从 tracking 模块导入共享数据和锁
    daily_rpd_totals,
    usage_data,
)

logger = logging.getLogger("my_logger")  # 获取日志记录器实例

# --- 每日重置函数 ---


def _reset_key_model_counts(key: str, model: str) -> int:
    """
    (内部辅助函数) 重置指定 API Key 和模型的每日计数器 (RPD 和 TPD_Input)。
    此函数应在持有 `usage_lock` 的情况下调用。

    Args:
        key (str): 要重置计数的 API Key 字符串。
        model (str): 要重置计数的模型名称。

    Returns:
        int: 重置前的 RPD (每日请求数) 值，用于累加计算前一天的总 RPD。
    """
    rpd_value = 0  # 初始化 RPD 值为 0
    # 检查 usage_data 中是否存在该 Key 和模型的条目
    if key in usage_data and model in usage_data[key]:
        # 1. 重置 RPD (每日请求数) 计数
        if "rpd_count" in usage_data[key][model]:  # 检查是否存在 RPD 计数器
            rpd_value = usage_data[key][model].get(
                "rpd_count", 0
            )  # 获取当前的 RPD 计数
            if rpd_value > 0:  # 如果 RPD 大于 0，记录重置日志
                logger.debug(
                    f"重置 RPD 计数: Key={key[:8]}, Model={model}, RPD={rpd_value} -> 0"
                )
            usage_data[key][model]["rpd_count"] = 0  # 将 RPD 计数重置为 0
        # 2. 重置 TPD_Input (每日输入 Token 数) 计数
        if "tpd_input_count" in usage_data[key][model]:  # 检查是否存在 TPD_Input 计数器
            # TPD 输入计数也需要每日重置
            if usage_data[key][model].get("tpd_input_count", 0) > 0:
                logger.debug(
                    f"重置 TPD_Input 计数: Key={key[:8]}, Model={model}, TPD_In={usage_data[key][model].get('tpd_input_count', 0)} -> 0"
                )
            usage_data[key][model]["tpd_input_count"] = 0  # 将 TPD_Input 计数重置为 0
    return rpd_value  # 返回重置前的 RPD 值


def _cleanup_daily_totals(pt_timezone: pytz.BaseTzInfo):
    """
    (内部辅助函数) 清理 `daily_rpd_totals` 字典中超过 30 天的旧每日 RPD 总量记录。
    此函数应在持有 `daily_totals_lock` 的情况下调用。

    Args:
        pt_timezone (pytz.BaseTzInfo): 太平洋时区对象，用于计算截止日期。
    """
    with daily_totals_lock:  # 确保持有锁
        # 计算 30 天前的日期作为截止日期
        cutoff_date = (datetime.now(pt_timezone) - timedelta(days=30)).strftime(
            "%Y-%m-%d"
        )
        # 找出所有日期键早于截止日期的条目
        keys_to_delete = [d for d in daily_rpd_totals if d < cutoff_date]
        # 删除这些旧条目
        for d in keys_to_delete:
            del daily_rpd_totals[d]
        # 如果删除了条目，记录日志
        if keys_to_delete:
            logger.info(
                f"已清理 {len(keys_to_delete)} 条旧的每日 RPD 总量记录 (早于 {cutoff_date})。"
            )


async def reset_daily_counts(key_manager: APIKeyManager):
    """
    每日执行的异步任务，用于重置所有 API Key 的每日使用计数 (RPD 和 TPD_Input)。
    此任务通常在太平洋时间 (PT) 的午夜运行。
    它还会记录前一天的总 RPD，并清理过旧的每日 RPD 记录。
    同时调用 Key 管理器的方法来重置 Key 的每日配额耗尽状态。

    Args:
        key_manager (APIKeyManager): APIKeyManager 实例。
    """
    # 定义太平洋时区
    pt_timezone = pytz.timezone("America/Los_Angeles")
    # 获取昨天的日期 (太平洋时区)
    yesterday_pt = datetime.now(pt_timezone) - timedelta(days=1)
    # 将昨天的日期格式化为字符串 (YYYY-MM-DD)
    yesterday_date_str = yesterday_pt.strftime("%Y-%m-%d")
    # 初始化昨天的总 RPD 计数器
    total_rpd_yesterday = 0

    logger.info(
        f"开始执行每日 RPD 和 TPD_Input 重置任务 (针对 PT 日期: {yesterday_date_str})..."
    )  # 记录任务开始日志

    # --- 重置 Key 的使用计数 ---
    with usage_lock:  # 获取 usage_data 的锁
        # 获取当前所有存在使用记录的 Key 列表 (创建副本以安全迭代)
        keys_to_reset = list(usage_data.keys())
        # 遍历每个 Key
        for key in keys_to_reset:
            # 获取该 Key 下所有存在使用记录的模型列表 (创建副本)
            models_to_reset = list(
                usage_data.get(key, {}).keys()
            )  # 使用 get 增加健壮性
            # 遍历每个模型
            for model in models_to_reset:
                # 调用内部辅助函数重置该 Key 和模型的计数，并累加返回的 RPD 值
                total_rpd_yesterday += _reset_key_model_counts(key, model)

    # --- 重置 Key Manager 中的每日配额耗尽标记 ---
    # 调用 Key Manager 实例的方法来清除所有 Key 的每日耗尽状态
    # 注意：key_manager.reset_daily_exhausted_keys() 需要是同步或异步方法，取决于其实现
    # 假设它是同步方法
    try:
        key_manager.reset_daily_exhausted_keys()  # 调用重置方法
        logger.info("Key Manager 中的每日配额耗尽标记已重置。")  # 记录日志
    except Exception as km_reset_err:
        logger.error(
            f"重置 Key Manager 每日配额耗尽标记时出错: {km_reset_err}", exc_info=True
        )  # 记录错误

    logger.info("所有 Key 的 RPD 和 TPD_Input 计数已重置。")  # 记录计数重置完成日志

    # --- 记录前一天的总 RPD 并清理旧记录 ---
    if total_rpd_yesterday > 0:  # 如果昨天有 RPD 记录
        with daily_totals_lock:  # 获取每日 RPD 总计的锁
            # 将昨天的总 RPD 存储到 daily_rpd_totals 字典中
            daily_rpd_totals[yesterday_date_str] = total_rpd_yesterday
            logger.info(
                f"记录 PT 日期 {yesterday_date_str} 的总 RPD: {total_rpd_yesterday}"
            )  # 记录日志

        # 调用辅助函数清理超过 30 天的旧 RPD 记录
        _cleanup_daily_totals(pt_timezone)

    else:  # 如果昨天没有 RPD 记录
        logger.info(f"PT 日期 {yesterday_date_str} 没有 RPD 使用记录。")  # 记录日志