# -*- coding: utf-8 -*-
"""
包含每日重置相关任务的函数。
"""
import logging
import pytz
from datetime import datetime, timedelta

# 从其他模块导入必要的组件
from .tracking import ( # 同级目录导入
    usage_data, usage_lock,
    daily_rpd_totals, daily_totals_lock
)

logger = logging.getLogger('my_logger')

# --- 每日重置函数 ---
def reset_daily_counts():
    """
    在太平洋时间午夜运行，重置所有 Key 的 RPD 和 TPD_Input 计数，
    并记录前一天的总 RPD。
    """
    pt_timezone = pytz.timezone('America/Los_Angeles')
    yesterday_pt = datetime.now(pt_timezone) - timedelta(days=1)
    yesterday_date_str = yesterday_pt.strftime('%Y-%m-%d')
    total_rpd_yesterday = 0

    logger.info(f"开始执行每日 RPD 和 TPD_Input 重置任务 (针对 PT 日期: {yesterday_date_str})...")

    with usage_lock:
        keys_to_reset = list(usage_data.keys())
        for key in keys_to_reset:
            models_to_reset = list(usage_data[key].keys())
            for model in models_to_reset:
                # 重置 RPD
                if "rpd_count" in usage_data[key][model]:
                    rpd_value = usage_data[key][model].get("rpd_count", 0)
                    if rpd_value > 0:
                        total_rpd_yesterday += rpd_value
                        logger.debug(f"重置 RPD 计数: Key={key[:8]}, Model={model}, RPD={rpd_value} -> 0")
                    usage_data[key][model]["rpd_count"] = 0
                # 重置 TPD_Input
                if "tpd_input_count" in usage_data[key][model]:
                     usage_data[key][model]["tpd_input_count"] = 0

    logger.info(f"所有 Key 的 RPD 和 TPD_Input 计数已重置。")

    if total_rpd_yesterday > 0:
        with daily_totals_lock:
            daily_rpd_totals[yesterday_date_str] = total_rpd_yesterday
            logger.info(f"记录 PT 日期 {yesterday_date_str} 的总 RPD: {total_rpd_yesterday}")
            # 可选：清理旧的每日总量数据
            cutoff_date = (datetime.now(pt_timezone) - timedelta(days=30)).strftime('%Y-%m-%d')
            keys_to_delete = [d for d in daily_rpd_totals if d < cutoff_date]
            for d in keys_to_delete:
                del daily_rpd_totals[d]
            if keys_to_delete:
                logger.info(f"已清理 {len(keys_to_delete)} 条旧的每日 RPD 总量记录。")
    else:
        logger.info(f"PT 日期 {yesterday_date_str} 没有 RPD 使用记录。")