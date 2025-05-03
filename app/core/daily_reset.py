# -*- coding: utf-8 -*-
"""
包含每日重置相关任务的函数。
"""
import logging # 导入 logging 模块
import pytz # 导入 pytz 模块
from datetime import datetime, timedelta # 导入日期和时间相关
from app.core.key_manager_class import key_manager_instance # 导入 Key Manager 实例
from app.core.tracking import ( # 从同级 tracking 模块导入
    usage_data, usage_lock,             # 实时使用数据和锁
    daily_rpd_totals, daily_totals_lock # 每日 RPD 总量和锁
)

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 每日重置函数 ---
def reset_daily_counts():
    """
    在太平洋时间午夜运行，重置所有 Key 的 RPD 和 TPD_Input 计数，
    并记录前一天的总 RPD。
    """
    pt_timezone = pytz.timezone('America/Los_Angeles')
    yesterday_pt = datetime.now(pt_timezone) - timedelta(days=1) # 计算昨天的太平洋时间
    yesterday_date_str = yesterday_pt.strftime('%Y-%m-%d') # 格式化昨天的日期字符串
    total_rpd_yesterday = 0 # 初始化昨天的总 RPD

    logger.info(f"开始执行每日 RPD 和 TPD_Input 重置任务 (针对 PT 日期: {yesterday_date_str})...") # 开始执行每日 RPD 和 TPD_Input 重置任务

    with usage_lock: # 获取使用数据锁
        keys_to_reset = list(usage_data.keys()) # 获取所有需要重置的 Key 列表
        for key in keys_to_reset: # 遍历每个 Key
            models_to_reset = list(usage_data[key].keys()) # 获取该 Key 下所有需要重置的模型列表
            for model in models_to_reset: # 遍历每个模型
                # 1. 重置 RPD (每日请求数) 计数
                if "rpd_count" in usage_data[key][model]: # 检查是否存在 RPD 计数
                    rpd_value = usage_data[key][model].get("rpd_count", 0) # 获取当前的 RPD 计数
                    if rpd_value > 0:
                        total_rpd_yesterday += rpd_value # 累加到昨天的总 RPD
                        logger.debug(f"重置 RPD 计数: Key={key[:8]}, Model={model}, RPD={rpd_value} -> 0") # 重置 RPD 计数
                    usage_data[key][model]["rpd_count"] = 0 # 将 RPD 计数重置为 0
                # 2. 重置 TPD_Input (每日输入 Token 数) 计数
                if "tpd_input_count" in usage_data[key][model]: # 检查是否存在 TPD_Input 计数
                     usage_data[key][model]["tpd_input_count"] = 0 # 将 TPD_Input 计数重置为 0

    # 重置 Key Manager 中的每日配额耗尽标记
    key_manager_instance.reset_daily_exhausted_keys() # 调用 Key Manager 的重置方法

    logger.info(f"所有 Key 的 RPD 和 TPD_Input 计数已重置。") # 所有 Key 的 RPD 和 TPD_Input 计数已重置

    if total_rpd_yesterday > 0: # 如果昨天有 RPD 使用记录
        with daily_totals_lock: # 获取每日总量锁
            daily_rpd_totals[yesterday_date_str] = total_rpd_yesterday # 存储昨天的总 RPD
            logger.info(f"记录 PT 日期 {yesterday_date_str} 的总 RPD: {total_rpd_yesterday}") # 记录昨天的总 RPD
            cutoff_date = (datetime.now(pt_timezone) - timedelta(days=30)).strftime('%Y-%m-%d') # 计算 30 天前的日期
            keys_to_delete = [d for d in daily_rpd_totals if d < cutoff_date] # 找出所有早于截止日期的记录键
            for d in keys_to_delete:
                del daily_rpd_totals[d] # 删除旧记录
            if keys_to_delete:
                logger.info(f"已清理 {len(keys_to_delete)} 条旧的每日 RPD 总量记录。") # 已清理旧的每日 RPD 总量记录
    else:
        logger.info(f"PT 日期 {yesterday_date_str} 没有 RPD 使用记录。") # 没有 RPD 使用记录
