# -*- coding: utf-8 -*-
"""
包含每日重置相关任务的函数。
Contains functions related to daily reset tasks.
"""
import logging # 导入 logging 模块 (Import logging module)
import pytz # 导入 pytz 模块 (Import pytz module)
from datetime import datetime, timedelta # 导入日期和时间相关 (Import date and time related)

# 从其他模块导入必要的组件
# Import necessary components from other modules
from .tracking import ( # 从同级 tracking 模块导入 (Import from sibling tracking module)
    usage_data, usage_lock,             # 实时使用数据和锁 (Real-time usage data and lock)
    daily_rpd_totals, daily_totals_lock # 每日 RPD 总量和锁 (Daily RPD totals and lock)
)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# --- 每日重置函数 ---
# --- Daily Reset Function ---
def reset_daily_counts():
    """
    在太平洋时间午夜运行，重置所有 Key 的 RPD 和 TPD_Input 计数，
    并记录前一天的总 RPD。
    Runs at Pacific Time midnight to reset RPD and TPD_Input counts for all keys,
    and records the total RPD for the previous day.
    """
    pt_timezone = pytz.timezone('America/Los_Angeles') # 设置太平洋时间区 (Set Pacific Timezone)
    yesterday_pt = datetime.now(pt_timezone) - timedelta(days=1) # 计算昨天的太平洋时间 (Calculate yesterday's Pacific Time)
    yesterday_date_str = yesterday_pt.strftime('%Y-%m-%d') # 格式化昨天的日期字符串 (Format yesterday's date string)
    total_rpd_yesterday = 0 # 初始化昨天的总 RPD (Initialize yesterday's total RPD)

    logger.info(f"开始执行每日 RPD 和 TPD_Input 重置任务 (针对 PT 日期: {yesterday_date_str})...") # Log the start of the daily reset task

    with usage_lock: # 获取使用数据锁 (Acquire usage data lock)
        keys_to_reset = list(usage_data.keys()) # 获取所有需要重置的 Key 列表 (Get list of all keys to reset)
        for key in keys_to_reset: # 遍历每个 Key (Iterate through each key)
            models_to_reset = list(usage_data[key].keys()) # 获取该 Key 下所有需要重置的模型列表 (Get list of all models to reset for this key)
            for model in models_to_reset: # 遍历每个模型 (Iterate through each model)
                # 1. 重置 RPD (每日请求数) 计数
                # 1. Reset RPD (Requests Per Day) count
                if "rpd_count" in usage_data[key][model]: # 检查是否存在 RPD 计数 (Check if RPD count exists)
                    rpd_value = usage_data[key][model].get("rpd_count", 0) # 获取当前的 RPD 计数 (Get the current RPD count)
                    if rpd_value > 0:
                        total_rpd_yesterday += rpd_value # 累加到昨天的总 RPD (Accumulate to yesterday's total RPD)
                        logger.debug(f"重置 RPD 计数: Key={key[:8]}, Model={model}, RPD={rpd_value} -> 0") # Log RPD reset (DEBUG level)
                    usage_data[key][model]["rpd_count"] = 0 # 将 RPD 计数重置为 0 (Reset RPD count to 0)
                # 2. 重置 TPD_Input (每日输入 Token 数) 计数
                # 2. Reset TPD_Input (Tokens Per Day Input) count
                if "tpd_input_count" in usage_data[key][model]: # 检查是否存在 TPD_Input 计数 (Check if TPD_Input count exists)
                     usage_data[key][model]["tpd_input_count"] = 0 # 将 TPD_Input 计数重置为 0 (Reset TPD_Input count to 0)

    logger.info(f"所有 Key 的 RPD 和 TPD_Input 计数已重置。") # Log that counts have been reset

    if total_rpd_yesterday > 0: # 如果昨天有 RPD 使用记录 (If there were RPD usage records yesterday)
        with daily_totals_lock: # 获取每日总量锁 (Acquire daily totals lock)
            daily_rpd_totals[yesterday_date_str] = total_rpd_yesterday # 存储昨天的总 RPD (Store yesterday's total RPD)
            logger.info(f"记录 PT 日期 {yesterday_date_str} 的总 RPD: {total_rpd_yesterday}") # Log yesterday's total RPD
            # 可选：清理超过 30 天的旧每日总量数据，防止内存无限增长
            # Optional: Clean up old daily total data older than 30 days to prevent infinite memory growth
            cutoff_date = (datetime.now(pt_timezone) - timedelta(days=30)).strftime('%Y-%m-%d') # 计算 30 天前的日期 (Calculate the date 30 days ago)
            keys_to_delete = [d for d in daily_rpd_totals if d < cutoff_date] # 找出所有早于截止日期的记录键 (Find all record keys earlier than the cutoff date)
            for d in keys_to_delete:
                del daily_rpd_totals[d] # 删除旧记录 (Delete old records)
            if keys_to_delete:
                logger.info(f"已清理 {len(keys_to_delete)} 条旧的每日 RPD 总量记录。") # Log the number of old records cleaned
    else:
        logger.info(f"PT 日期 {yesterday_date_str} 没有 RPD 使用记录。") # Log if no RPD usage records for yesterday
