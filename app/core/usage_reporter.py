# -*- coding: utf-8 -*-
"""
包含生成周期性使用情况报告的函数。
This module contains functions for generating periodic usage reports.
"""
import time
import logging
import pytz
import copy
from datetime import datetime, timedelta, date, timezone
from collections import Counter, defaultdict
from typing import List, Tuple, Dict, Any, TYPE_CHECKING

# 从其他模块导入必要的组件
# Import necessary components from other modules
from .tracking import ( # 同级目录导入 (Import from sibling directory)
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS,
    daily_rpd_totals, daily_totals_lock,
    key_scores_cache, cache_lock,
    # ip_daily_counts, ip_counts_lock, # 移除 tracking 中的 IP 请求计数 (Removed IP request counts from tracking)
    ip_daily_input_token_counts, ip_input_token_counts_lock # IP 输入 token 计数和锁 (IP input token counts and lock)
)
# 从 utils 导入实际使用的 IP 请求计数变量和锁
# Import the actual IP request count variable and lock from utils
from .utils import ip_daily_request_counts, ip_rate_limit_lock
from .. import config # 导入 config 模块 (Import config module)
from ..config import REPORT_LOG_LEVEL_INT # 导入日志级别配置 (Import report log level configuration)
from .key_management import INITIAL_KEY_COUNT, INVALID_KEY_COUNT_AT_STARTUP # 同级目录导入 (Import from sibling directory)

# 条件导入用于类型提示
# Conditional import for type hinting
if TYPE_CHECKING:
    from .utils import APIKeyManager # 同级目录导入 (Import from sibling directory)

logger = logging.getLogger('my_logger')

# --- 辅助函数：获取 Top IPs ---
# --- Helper Function: Get Top IPs ---
def get_top_ips(data_dict: Dict[str, Dict[str, int]], start_date: date, end_date: date, top_n=5) -> List[Tuple[str, int]]:
    """
    获取指定日期范围内 Top N IP 地址及其计数。
    Retrieves the top N IP addresses and their counts within a specified date range.

    Args:
        data_dict: 包含日期 -> IP -> 计数 的字典。A dictionary containing date -> IP -> count.
        start_date: 统计的开始日期。The start date for the statistics.
        end_date: 统计的结束日期。The end date for the statistics.
        top_n: 要获取的 Top IP 数量。The number of top IPs to retrieve.

    Returns:
        一个包含 (IP 地址, 计数) 元组的列表。A list of (IP address, count) tuples.
    """
    aggregated_counts = Counter()
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        if date_str in data_dict:
            # 使用 .get() 方法安全地访问嵌套字典，避免 KeyError
            # Use .get() method to safely access nested dictionaries and avoid KeyError
            for ip, count in data_dict.get(date_str, {}).items():
                aggregated_counts[ip] += count
        current_date += timedelta(days=1)
    return aggregated_counts.most_common(top_n)

# --- 周期性报告函数 ---
# --- Periodic Reporting Function ---
def report_usage(key_manager: 'APIKeyManager'):
    """
    周期性地报告聚合的 API 密钥使用情况、总体统计、密钥数量建议以及 Top IP 统计。
    Periodically reports aggregated API key usage, overall statistics, key count suggestions, and Top IP statistics.

    Args:
        key_manager: APIKeyManager 实例，用于访问活跃密钥信息。An instance of APIKeyManager to access active key information.
    """
    logger.info("开始生成周期性使用情况报告...") # Log the start of report generation
    now = time.time()
    pt_timezone = pytz.timezone('America/Los_Angeles') # 设置太平洋时间区 (Set Pacific Timezone)
    today_pt = datetime.now(pt_timezone) # 获取太平洋时间区的当前时间 (Get current time in PT)
    today_date_str = today_pt.strftime('%Y-%m-%d') # 格式化今日日期字符串 (Format today's date string)
    start_of_week_pt = today_pt - timedelta(days=today_pt.weekday()) # 计算本周开始日期 (Calculate the start date of the week)
    start_of_month_pt = today_pt.replace(day=1) # 计算本月开始日期 (Calculate the start date of the month)

    # --- 安全地获取数据副本 ---
    # --- Safely Get Data Copies ---
    # 使用锁确保在复制数据时不会发生并发修改
    # Use locks to ensure no concurrent modifications happen while copying data
    with usage_lock:
        usage_data_copy = copy.deepcopy(usage_data) # 复制 Key 使用数据 (Copy key usage data)
    with daily_totals_lock:
        daily_rpd_totals_copy = daily_rpd_totals.copy() # 复制每日 RPD 总计 (Copy daily RPD totals)
    with cache_lock:
        key_scores_cache_copy = copy.deepcopy(key_scores_cache) # 复制 Key 分数缓存 (Copy key scores cache)

    # 复制并转换 IP 请求计数数据格式
    # Copy and convert IP request count data format
    ip_counts_copy = defaultdict(lambda: defaultdict(int)) # 初始化目标格式字典 (Initialize target format dictionary)
    with ip_rate_limit_lock: # 使用 utils 中的锁 (Use the lock from utils)
        ip_daily_request_counts_raw = copy.deepcopy(ip_daily_request_counts) # 复制原始数据 (Copy raw data)
        # 将原始格式 (date_str, ip): count 转换为 date_str: {ip: count}
        # Convert raw format (date_str, ip): count to date_str: {ip: count}
        for (date_str, ip), count in ip_daily_request_counts_raw.items():
            ip_counts_copy[date_str][ip] = count # 转换为 get_top_ips 所需格式 (Convert to format required by get_top_ips)

    with ip_input_token_counts_lock:
        ip_input_token_counts_copy = copy.deepcopy(ip_daily_input_token_counts) # 复制 IP 输入 token 计数 (Copy IP input token counts)
    with key_manager.keys_lock:
        active_keys = key_manager.api_keys[:] # 获取活跃 Key 列表 (Get list of active keys)
        active_keys_count = len(active_keys) # 计算活跃 Key 数量 (Count active keys)

    # Initialize summary dictionaries before usage processing
    key_status_summary = defaultdict(lambda: defaultdict(int)) # 初始化 Key 状态汇总字典 (Initialize key status summary dictionary)
    model_total_rpd = defaultdict(int) # 初始化模型总 RPD 字典 (Initialize model total RPD dictionary)
    model_total_tpd_input = defaultdict(int) # 初始化模型总 TPD 输入字典 (Initialize model total TPD input dictionary)

    # Use the correctly calculated invalid key count from key_management
    # invalid_keys_count = INITIAL_KEY_COUNT - active_keys_count # Removed incorrect calculation

    report_lines = [f"--- API 使用情况报告 ({today_pt.strftime('%Y-%m-%d %H:%M:%S %Z')}) ---"] # Moved initialization here

    # --- Key 使用情况聚合 ---
    # --- Key Usage Aggregation ---
    report_lines.append("\n[Key 使用情况聚合]")

    if not usage_data_copy:
        report_lines.append("  暂无 Key 使用数据。") # Report if no key usage data
    else:
        # 遍历每个 Key 的使用数据
        # Iterate through usage data for each key
        for key, models_usage in usage_data_copy.items():
            if not models_usage: continue # Skip if no usage for this key
            # 遍历每个模型的使用数据
            # Iterate through usage data for each model
            for model_name, usage in models_usage.items():
                limits = config.MODEL_LIMITS.get(model_name) # 获取模型的限制 (Get limits for the model)
                if not limits: continue # Skip if no limits defined for the model

                rpd_limit = limits.get("rpd") # 获取 RPD 限制 (Get RPD limit)
                rpm_limit = limits.get("rpm") # 获取 RPM 限制 (Get RPM limit)
                tpm_input_limit = limits.get("tpm_input") # 获取 TPM 输入限制 (Get TPM input limit)
                tpd_input_limit = limits.get("tpd_input") # 获取 TPD 输入限制 (Get TPD input limit)

                rpd_count = usage.get("rpd_count", 0) # 获取 RPD 计数 (Get RPD count)
                rpm_count = usage.get("rpm_count", 0) # 获取 RPM 计数 (Get RPM count)
                tpm_input_count = usage.get("tpm_input_count", 0) # 获取 TPM 输入计数 (Get TPM input count)
                tpd_input_count = usage.get("tpd_input_count", 0) # 获取 TPD 输入计数 (Get TPD input count)
                rpm_ts = usage.get("rpm_timestamp", 0) # 获取 RPM 时间戳 (Get RPM timestamp)
                tpm_input_ts = usage.get("tpm_input_timestamp", 0) # 获取 TPM 输入时间戳 (Get TPM input timestamp)

                model_total_rpd[model_name] += rpd_count # 累加模型的总 RPD (Accumulate total RPD for the model)
                model_total_tpd_input[model_name] += tpd_input_count # 累加模型的总 TPD 输入 (Accumulate total TPD input for the model)

                # RPM (每分钟请求数)
                # RPM (Requests Per Minute)
                rpm_in_window = 0
                rpm_remaining_pct = 1.0
                if rpm_limit is not None:
                    # 检查是否在 RPM 窗口期内
                    # Check if within the RPM window
                    if now - rpm_ts < RPM_WINDOW_SECONDS:
                        rpm_in_window = rpm_count # 获取窗口期内的 RPM 计数 (Get RPM count within the window)
                        # 计算剩余百分比
                        # Calculate remaining percentage
                        rpm_remaining_pct = max(0, (rpm_limit - rpm_in_window) / rpm_limit) if rpm_limit > 0 else 0

                # TPM Input (每分钟输入 Token 数)
                # TPM Input (Tokens Per Minute Input)
                tpm_input_in_window = 0
                tpm_input_remaining_pct = 1.0
                if tpm_input_limit is not None:
                    # 检查是否在 TPM 输入窗口期内
                    # Check if within the TPM input window
                    if now - tpm_input_ts < TPM_WINDOW_SECONDS:
                        tpm_input_in_window = tpm_input_count # 获取窗口期内的 TPM 输入计数 (Get TPM input count within the window)
                        # 计算剩余百分比
                        # Calculate remaining percentage
                        tpm_input_remaining_pct = max(0, (tpm_input_limit - tpm_input_in_window) / tpm_input_limit) if tpm_input_limit > 0 else 0

                # RPD (每日请求数)
                # RPD (Requests Per Day)
                # 计算剩余百分比
                # Calculate remaining percentage
                rpd_remaining_pct = max(0, (rpd_limit - rpd_count) / rpd_limit) if rpd_limit is not None and rpd_limit > 0 else 1.0

                # TPD Input (每日输入 Token 数)
                # TPD Input (Tokens Per Day Input)
                # 计算剩余百分比
                # Calculate remaining percentage
                tpd_input_remaining_pct = max(0, (tpd_input_limit - tpd_input_count) / tpd_input_limit) if tpd_input_limit is not None and tpd_input_limit > 0 else 1.0

                score = key_scores_cache_copy.get(key, {}).get(model_name, -1.0) # 获取 Key 分数 (Get key score)

                # 构建 Key 状态字符串
                # Build key status string
                status_parts = [
                    f"RPD={rpd_count}/{rpd_limit or 'N/A'} ({rpd_remaining_pct:.0%})",
                    f"RPM={rpm_in_window}/{rpm_limit or 'N/A'} ({rpm_remaining_pct:.0%})",
                    f"TPD_In={tpd_input_count:,}/{tpd_input_limit or 'N/A'} ({tpd_input_remaining_pct:.0%})",
                    f"TPM_In={tpm_input_in_window:,}/{tpm_input_limit or 'N/A'} ({tpm_input_remaining_pct:.0%})",
                    f"Score={score:.2f}"
                ]
                status_str = " | ".join(status_parts)
                key_status_summary[model_name][status_str] += 1 # 按模型和状态汇总 Key 数量 (Summarize key count by model and status)

        if not key_status_summary:
             report_lines.append("  暂无 Key 使用数据。") # Report if no key usage data after processing
        else:
            # 遍历并报告每个模型的 Key 使用情况
            # Iterate and report key usage for each model
            for model_name, statuses in sorted(key_status_summary.items()):
                total_keys_for_model = sum(statuses.values()) # 计算使用该模型的 Key 总数 (Calculate total keys using this model)
                report_lines.append(f"  模型: {model_name} (今日 RPD: {model_total_rpd[model_name]:,}, 今日 TPD_In: {model_total_tpd_input[model_name]:,}, 使用 Keys: {total_keys_for_model})")
                # 按数量降序排序状态并报告
                # Sort statuses by count in descending order and report
                for status, count in sorted(statuses.items(), key=lambda item: item[1], reverse=True):
                    report_lines.append(f"    - 数量: {count}, 状态: {status}")


    # --- 总体统计与预测 ---
    # --- Overall Statistics and Prediction ---
    report_lines.append("\n[总体统计与预测]")
    report_lines.append(f"  活跃 Key 数量: {active_keys_count}") # 报告活跃 Key 数量 (Report active key count)
    report_lines.append(f"  启动时无效 Key 数量: {INVALID_KEY_COUNT_AT_STARTUP}") # 报告启动时无效 Key 数量 (Report invalid key count at startup)

    # RPD 容量
    # RPD Capacity
    report_lines.append("  RPD 容量估算:") # Report RPD capacity estimation
    rpd_groups = defaultdict(list) # 按 RPD 限制分组模型 (Group models by RPD limit)
    model_rpd_usage_count = defaultdict(int) # 统计使用每个模型的 Key 数量 (Count keys using each model)
    for model, limits in config.MODEL_LIMITS.items():
        if limits and limits.get("rpd") is not None:
            rpd_groups[limits["rpd"]].append(model)
    for key, models_usage in usage_data_copy.items():
        for model_name in models_usage:
             if model_name in config.MODEL_LIMITS:
                 model_rpd_usage_count[model_name] += 1

    target_model = "gemini-2.5-pro-exp-03-25" # 目标模型名称 (Target model name)
    target_model_limits = config.MODEL_LIMITS.get(target_model, {}) # 获取目标模型的限制 (Get limits for the target model)
    target_model_rpd_limit = target_model_limits.get("rpd") # 获取目标模型的 RPD 限制 (Get RPD limit for the target model)
    target_model_tpd_input_limit = target_model_limits.get("tpd_input") # 获取目标模型的 TPD 输入限制 (Get TPD input limit for the target model)

    target_rpd_capacity = 0
    if target_model_rpd_limit:
        target_rpd_capacity = active_keys_count * target_model_rpd_limit # 计算目标模型的总 RPD 容量 (Calculate total RPD capacity for the target model)
        report_lines.append(f"    - 基于 {target_model} (RPD={target_model_rpd_limit}): {target_rpd_capacity:,}/天")
    else:
        logger.warning(f"目标模型 {target_model} 或其 RPD 限制未在 model_limits.json 中找到，无法估算 RPD 容量。") # Log warning if target model or its RPD limit is not found
        report_lines.append(f"    - 基于 {target_model}: RPD 限制未定义。") # Report if RPD limit is not defined

    # 报告其他 RPD 组的容量
    # Report capacity for other RPD groups
    for rpd_limit, models in sorted(rpd_groups.items()):
        if rpd_limit != target_model_rpd_limit:
             group_capacity = active_keys_count * rpd_limit # 计算该组的总容量 (Calculate total capacity for this group)
             used_models_in_group = [m for m in models if model_rpd_usage_count.get(m, 0) > 0] # 找出该组中实际使用的模型 (Find models in this group that are actually used)
             if used_models_in_group:
                 model_names_str = ', '.join(used_models_in_group)
                 report_lines.append(f"    - RPD={rpd_limit}: {model_names_str} (估算容量: {group_capacity:,}/天)")

    # TPD 输入容量
    # TPD Input Capacity
    report_lines.append("  TPD 输入容量估算:") # Report TPD input capacity estimation
    target_tpd_input_capacity = 0
    if target_model_tpd_input_limit:
        target_tpd_input_capacity = active_keys_count * target_model_tpd_input_limit # 计算目标模型的总 TPD 输入容量 (Calculate total TPD input capacity for the target model)
        report_lines.append(f"    - 基于 {target_model} (TPD_In={target_model_tpd_input_limit:,}): {target_tpd_input_capacity:,}/天")
    else:
        report_lines.append(f"    - 基于 {target_model}: TPD_Input 限制未定义。") # Report if TPD input limit is not defined

    # 今日用量与估算
    # Today's Usage and Estimation
    current_total_rpd = sum(model_total_rpd.values()) # 计算今日总 RPD (Calculate total RPD for today)
    current_total_tpd_input = sum(model_total_tpd_input.values()) # 计算今日总 TPD 输入 (Calculate total TPD input for today)
    report_lines.append(f"  今日已用 RPD (PT): {current_total_rpd:,}") # Report today's used RPD
    report_lines.append(f"  今日已用 TPD 输入 (PT): {current_total_tpd_input:,}") # Report today's used TPD input

    # 计算今天已经过去的时间占全天的比例
    # Calculate the fraction of the day that has passed
    seconds_since_pt_midnight = (today_pt - today_pt.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    fraction_of_day_passed = seconds_since_pt_midnight / (24 * 3600) if seconds_since_pt_midnight > 0 else 0
    estimated_total_rpd_today = 0
    estimated_total_tpd_input_today = 0

    # 如果一天已经过去了一小部分（大于 1%），则进行估算
    # Estimate if a small fraction of the day has passed (greater than 1%)
    if fraction_of_day_passed > 0.01:
        estimated_total_rpd_today = int(current_total_rpd / fraction_of_day_passed) # 估算今日总 RPD (Estimate total RPD for today)
        estimated_total_tpd_input_today = int(current_total_tpd_input / fraction_of_day_passed) # 估算今日总 TPD 输入 (Estimate total TPD input for today)
        report_lines.append(f"  预估今日 RPD (PT): {estimated_total_rpd_today:,} (基于 {fraction_of_day_passed:.1%} 时间)") # Report estimated RPD
        report_lines.append(f"  预估今日 TPD 输入 (PT): N/A (时间过早)") # Report N/A for TPD input if too early
        report_lines.append(f"  预估今日 TPD 输入 (PT): N/A (时间过早)") # Report N/A for TPD input if too early

    # 平均 RPD
    # Average RPD
    N = 7 # 统计过去 N 天 (Count last N days)
    last_n_days_rpd = [] # 存储过去 N 天的 RPD (Store RPD for last N days)
    # 遍历过去 N 天
    # Iterate through last N days
    for i in range(1, N + 1):
        day_str = (today_pt - timedelta(days=i)).strftime('%Y-%m-%d') # 获取日期字符串 (Get date string)
        rpd = daily_rpd_totals_copy.get(day_str) # 获取该日的 RPD (Get RPD for this day)
        if rpd is not None:
            last_n_days_rpd.append(rpd) # 如果存在则添加到列表 (Add to list if exists)

    avg_daily_rpd = 0
    if last_n_days_rpd:
        avg_daily_rpd = sum(last_n_days_rpd) / len(last_n_days_rpd) # 计算平均 RPD (Calculate average RPD)
        report_lines.append(f"  过去 {len(last_n_days_rpd)} 天平均日 RPD (PT): {avg_daily_rpd:,.0f}") # Report average daily RPD
    else:
        report_lines.append(f"  过去 {N} 天平均日 RPD (PT): N/A (无历史数据)") # Report N/A if no historical data

    # --- Key 数量建议 ---
    # --- Key Count Suggestion ---
    report_lines.append("\n[Key 数量建议]")
    suggestion = "保持当前 Key 数量。" # 默认建议 (Default suggestion)
    # 使用预估今日 RPD 和平均 RPD 中的较大值作为 RPD 使用指标
    # Use the larger of estimated today's RPD and average RPD as the RPD usage indicator
    rpd_usage_indicator = max(estimated_total_rpd_today, avg_daily_rpd)
    tpd_input_usage_indicator = estimated_total_tpd_input_today # TPD 输入使用指标 (TPD input usage indicator)

    rpd_usage_ratio = 0
    if target_rpd_capacity > 0:
        rpd_usage_ratio = rpd_usage_indicator / target_rpd_capacity # 计算 RPD 使用率 (Calculate RPD usage ratio)

    tpd_input_usage_ratio = 0
    if target_tpd_input_capacity > 0:
        tpd_input_usage_ratio = tpd_input_usage_indicator / target_tpd_input_capacity # 计算 TPD 输入使用率 (Calculate TPD input usage ratio)

    # 根据使用率提供 Key 数量建议
    # Provide key count suggestion based on usage ratio
    if active_keys_count == 0:
        suggestion = "错误: 未找到有效的 API Key！" # Error if no active keys
    elif target_rpd_capacity <= 0:
        suggestion = "无法生成建议 (目标模型 RPD 限制未定义)。" # Cannot suggest if target model RPD limit is not defined
    elif rpd_usage_ratio > 0.85:
        # 如果 RPD 使用率过高，建议增加 Key 数量
        # If RPD usage ratio is too high, suggest increasing key count
        needed_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.7)) # 计算建议的 Key 数量 (Calculate suggested key count)
        suggestion = f"警告: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 已达目标容量 ({target_rpd_capacity:,}) 的 {rpd_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。"
    elif target_tpd_input_capacity > 0 and tpd_input_usage_ratio > 0.85:
         # 如果 TPD 输入使用率过高，建议增加 Key 数量
         # If TPD input usage ratio is too high, suggest increasing key count
         needed_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.7)) # 计算建议的 Key 数量 (Calculate suggested key count)
         suggestion = f"警告: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 已达目标容量 ({target_tpd_input_capacity:,}) 的 {tpd_input_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。"
    elif rpd_usage_ratio < 0.3 and tpd_input_usage_ratio < 0.3 and active_keys_count > 1:
        # 如果 RPD 和 TPD 输入使用率都较低，且活跃 Key 数量大于 1，建议减少 Key 数量
        # If both RPD and TPD input usage ratios are low, and active key count is greater than 1, suggest decreasing key count
        if rpd_usage_ratio >= tpd_input_usage_ratio and target_model_rpd_limit:
             ideal_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.5)) + 1 # 计算理想的 Key 数量 (Calculate ideal key count)
             suggestion = f"提示: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 较低 ({rpd_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。"
        elif target_model_tpd_input_limit:
             ideal_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.5)) + 1 # 计算理想的 Key 数量 (Calculate ideal key count)
             suggestion = f"提示: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 较低 ({tpd_input_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。"
    report_lines.append(f"  {suggestion}") # 报告建议 (Report the suggestion)


    # --- Top 5 IP 地址统计 ---
    # --- Top 5 IP Address Statistics ---
    report_lines.append("\n[Top 5 IP 地址统计 (PT 时间)]") # Report Top 5 IP statistics

    # 今日 Top 5 请求
    # Top 5 Requests Today
    top_ips_today_req = get_top_ips(ip_counts_copy, today_pt.date(), today_pt.date()) # 获取今日 Top 5 请求 IP (Get Top 5 request IPs for today)
    report_lines.append("  今日请求次数 Top 5:") # Report Top 5 requests today
    if top_ips_today_req:
        for ip, count in top_ips_today_req: report_lines.append(f"    - {ip}: {count}") # Report each IP and count
    else: report_lines.append("    - 暂无记录") # Report if no records

    # 今日 Top 5 输入 Token
    # Top 5 Input Tokens Today
    top_ips_today_input_token = get_top_ips(ip_input_token_counts_copy, today_pt.date(), today_pt.date()) # 获取今日 Top 5 输入 Token IP (Get Top 5 input token IPs for today)
    report_lines.append("  今日输入 Token Top 5:") # Report Top 5 input tokens today
    if top_ips_today_input_token:
        for ip, tokens in top_ips_today_input_token: report_lines.append(f"    - {ip}: {tokens:,}") # Report each IP and token count
    else: report_lines.append("    - 暂无记录") # Report if no records

    # 本周 Top 5 请求
    # Top 5 Requests This Week
    top_ips_week_req = get_top_ips(ip_counts_copy, start_of_week_pt.date(), today_pt.date()) # 获取本周 Top 5 请求 IP (Get Top 5 request IPs for this week)
    report_lines.append("  本周请求次数 Top 5:") # Report Top 5 requests this week
    if top_ips_week_req:
        for ip, count in top_ips_week_req: report_lines.append(f"    - {ip}: {count}") # Report each IP and count
    else: report_lines.append("    - 暂无记录") # Report if no records

    # 本周 Top 5 输入 Token
    # Top 5 Input Tokens This Week
    top_ips_week_input_token = get_top_ips(ip_input_token_counts_copy, start_of_week_pt.date(), today_pt.date()) # 获取本周 Top 5 输入 Token IP (Get Top 5 input token IPs for this week)
    report_lines.append("  本周输入 Token Top 5:") # Report Top 5 input tokens this week
    if top_ips_week_input_token:
        for ip, tokens in top_ips_week_input_token: report_lines.append(f"    - {ip}: {tokens:,}") # Report each IP and token count
    else: report_lines.append("    - 暂无记录") # Report if no records

    # 本月 Top 5 请求
    # Top 5 Requests This Month
    top_ips_month_req = get_top_ips(ip_counts_copy, start_of_month_pt.date(), today_pt.date()) # 获取本月 Top 5 请求 IP (Get Top 5 request IPs for this month)
    report_lines.append("  本月请求次数 Top 5:") # Report Top 5 requests this month
    if top_ips_month_req:
        for ip, count in top_ips_month_req: report_lines.append(f"    - {ip}: {count}") # Report each IP and count
    else: report_lines.append("    - 暂无记录") # Report if no records

    # 本月 Top 5 输入 Token
    # Top 5 Input Tokens This Month
    top_ips_month_input_token = get_top_ips(ip_input_token_counts_copy, start_of_month_pt.date(), today_pt.date()) # 获取本月 Top 5 输入 Token IP (Get Top 5 input token IPs for this month)
    report_lines.append("  本月输入 Token Top 5:") # Report Top 5 input tokens this month
    if top_ips_month_input_token:
        for ip, tokens in top_ips_month_input_token: report_lines.append(f"    - {ip}: {tokens:,}") # Report each IP and token count
    else: report_lines.append("    - 暂无记录") # Report if no records


    report_lines.append("--- 报告结束 ---") # End of report marker
    full_report = "\n".join(report_lines) # Join all report lines into a single string

    # 使用配置的日志级别记录报告
    # Log the report using the configured log level
    logger.log(REPORT_LOG_LEVEL_INT, full_report)


# --- 新增：获取结构化报告数据的函数 ---
# --- New: Function to Get Structured Report Data ---
async def get_structured_report_data(key_manager: 'APIKeyManager') -> Dict[str, Any]:
    """
    获取用于 API 的结构化使用情况报告数据。
    Gets structured usage report data for API use.

    Args:
        key_manager: APIKeyManager 实例。An instance of APIKeyManager.

    Returns:
        包含报告数据的字典。A dictionary containing the report data.
    """
    logger.debug("开始获取结构化报告数据...") # Log start of structured data retrieval
    now = time.time()
    utc_now = datetime.now(timezone.utc) # 获取 UTC 当前时间 (Get current UTC time)
    pt_timezone = pytz.timezone('America/Los_Angeles') # 设置太平洋时间区 (Set Pacific Timezone)
    today_pt = datetime.now(pt_timezone) # 获取太平洋时间区的当前时间 (Get current time in PT)
    today_date_str = today_pt.strftime('%Y-%m-%d') # 格式化今日日期字符串 (Format today's date string)
    start_of_week_pt = today_pt - timedelta(days=today_pt.weekday()) # 计算本周开始日期 (Calculate the start date of the week)
    start_of_month_pt = today_pt.replace(day=1) # 计算本月开始日期 (Calculate the start date of the month)

    # --- 安全地获取数据副本 ---
    # --- Safely Get Data Copies ---
    with usage_lock:
        usage_data_copy = copy.deepcopy(usage_data)
    with daily_totals_lock:
        daily_rpd_totals_copy = daily_rpd_totals.copy()
    with cache_lock:
        key_scores_cache_copy = copy.deepcopy(key_scores_cache)
    ip_counts_copy = defaultdict(lambda: defaultdict(int))
    with ip_rate_limit_lock:
        ip_daily_request_counts_raw = copy.deepcopy(ip_daily_request_counts)
        for (date_str, ip), count in ip_daily_request_counts_raw.items():
            ip_counts_copy[date_str][ip] = count
    with ip_input_token_counts_lock:
        ip_input_token_counts_copy = copy.deepcopy(ip_daily_input_token_counts)
    with key_manager.keys_lock:
        active_keys = key_manager.api_keys[:]
        active_keys_count = len(active_keys)

    # --- 初始化结果字典 ---
    # --- Initialize Result Dictionary ---
    report_data = {
        "report_time_utc": utc_now.isoformat(), # 报告时间 (Report time)
        "key_status_summary": {}, # Key 状态汇总 (Key status summary)
        "overall_stats": { # 总体统计 (Overall stats)
            "active_keys_count": active_keys_count, # 活跃 Key 数量 (Active key count)
            "invalid_keys_startup": INVALID_KEY_COUNT_AT_STARTUP, # 启动时无效 Key 数量 (Invalid keys at startup)
            "rpd": { # RPD 相关统计 (RPD related stats)
                "capacity_target_model": None, # 目标模型容量信息 (Target model capacity info)
                "capacity_other_models": [], # 其他模型容量信息 (Other models capacity info)
                "used_today": 0, # 今日已用 RPD (RPD used today)
                "estimated_today": None, # 今日预估 RPD (Estimated RPD today)
            },
            "tpd_input": { # TPD 输入相关统计 (TPD input related stats)
                 "capacity_target_model": None, # 目标模型容量信息 (Target model capacity info)
                 "used_today": 0, # 今日已用 TPD 输入 (TPD input used today)
                 "estimated_today": None, # 今日预估 TPD 输入 (Estimated TPD input today)
            },
            "avg_daily_rpd_past_7_days": None, # 过去7天平均日 RPD (Average daily RPD past 7 days)
        },
        "key_suggestion": "无法生成建议。", # Key 数量建议 (Key count suggestion)
        "top_ips": { # Top IP 统计 (Top IP stats)
            "requests": {"today": [], "week": [], "month": []}, # 请求次数 (Request counts)
            "tokens": {"today": [], "week": [], "month": []} # 输入 Token 数 (Input token counts)
        }
    }

    # --- Key 使用情况聚合 ---
    # --- Key Usage Aggregation ---
    key_status_summary_internal = defaultdict(lambda: defaultdict(int)) # 内部汇总 (Internal summary)
    model_total_rpd = defaultdict(int) # 模型总 RPD (Model total RPD)
    model_total_tpd_input = defaultdict(int) # 模型总 TPD 输入 (Model total TPD input)

    if usage_data_copy:
        for key, models_usage in usage_data_copy.items():
            if not models_usage: continue
            for model_name, usage in models_usage.items():
                limits = config.MODEL_LIMITS.get(model_name)
                if not limits: continue

                rpd_limit = limits.get("rpd")
                rpm_limit = limits.get("rpm")
                tpm_input_limit = limits.get("tpm_input")
                tpd_input_limit = limits.get("tpd_input")

                rpd_count = usage.get("rpd_count", 0)
                rpm_count = usage.get("rpm_count", 0)
                tpm_input_count = usage.get("tpm_input_count", 0)
                tpd_input_count = usage.get("tpd_input_count", 0)
                rpm_ts = usage.get("rpm_timestamp", 0)
                tpm_input_ts = usage.get("tpm_input_timestamp", 0)

                model_total_rpd[model_name] += rpd_count
                model_total_tpd_input[model_name] += tpd_input_count

                rpm_in_window = 0
                rpm_remaining_pct = 1.0
                if rpm_limit is not None:
                    if now - rpm_ts < RPM_WINDOW_SECONDS:
                        rpm_in_window = rpm_count
                        rpm_remaining_pct = max(0, (rpm_limit - rpm_in_window) / rpm_limit) if rpm_limit > 0 else 0

                tpm_input_in_window = 0
                tpm_input_remaining_pct = 1.0
                if tpm_input_limit is not None:
                    if now - tpm_input_ts < TPM_WINDOW_SECONDS:
                        tpm_input_in_window = tpm_input_count
                        tpm_input_remaining_pct = max(0, (tpm_input_limit - tpm_input_in_window) / tpm_input_limit) if tpm_input_limit > 0 else 0

                rpd_remaining_pct = max(0, (rpd_limit - rpd_count) / rpd_limit) if rpd_limit is not None and rpd_limit > 0 else 1.0
                tpd_input_remaining_pct = max(0, (tpd_input_limit - tpd_input_count) / tpd_input_limit) if tpd_input_limit is not None and tpd_input_limit > 0 else 1.0
                score = key_scores_cache_copy.get(key, {}).get(model_name, -1.0)

                status_parts = [
                    f"RPD={rpd_count}/{rpd_limit or 'N/A'} ({rpd_remaining_pct:.0%})",
                    f"RPM={rpm_in_window}/{rpm_limit or 'N/A'} ({rpm_remaining_pct:.0%})",
                    f"TPD_In={tpd_input_count:,}/{tpd_input_limit or 'N/A'} ({tpd_input_remaining_pct:.0%})",
                    f"TPM_In={tpm_input_in_window:,}/{tpm_input_limit or 'N/A'} ({tpm_input_remaining_pct:.0%})",
                    f"Score={score:.2f}"
                ]
                status_str = " | ".join(status_parts)
                key_status_summary_internal[model_name][status_str] += 1

        # 格式化 Key 状态汇总结果
        # Format key status summary result
        for model_name, statuses in sorted(key_status_summary_internal.items()):
            total_keys_for_model = sum(statuses.values())
            report_data["key_status_summary"][model_name] = {
                "total_keys": total_keys_for_model,
                "statuses": dict(sorted(statuses.items(), key=lambda item: item[1], reverse=True)) # 按数量排序 (Sort by count)
            }

    # --- 总体统计与预测 ---
    # --- Overall Statistics and Prediction ---
    rpd_groups = defaultdict(list)
    model_rpd_usage_count = defaultdict(int)
    for model, limits in config.MODEL_LIMITS.items():
        if limits and limits.get("rpd") is not None:
            rpd_groups[limits["rpd"]].append(model)
    for key, models_usage in usage_data_copy.items():
        for model_name in models_usage:
             if model_name in config.MODEL_LIMITS:
                 model_rpd_usage_count[model_name] += 1

    target_model = "gemini-2.5-pro-exp-03-25"
    target_model_limits = config.MODEL_LIMITS.get(target_model, {})
    target_model_rpd_limit = target_model_limits.get("rpd")
    target_model_tpd_input_limit = target_model_limits.get("tpd_input")

    target_rpd_capacity = 0
    if target_model_rpd_limit:
        target_rpd_capacity = active_keys_count * target_model_rpd_limit
        report_data["overall_stats"]["rpd"]["capacity_target_model"] = {
            "limit": target_model_rpd_limit,
            "capacity": target_rpd_capacity,
            "model": target_model
        }

    for rpd_limit, models in sorted(rpd_groups.items()):
        if rpd_limit != target_model_rpd_limit:
             group_capacity = active_keys_count * rpd_limit
             used_models_in_group = [m for m in models if model_rpd_usage_count.get(m, 0) > 0]
             if used_models_in_group:
                 report_data["overall_stats"]["rpd"]["capacity_other_models"].append({
                     "limit": rpd_limit,
                     "capacity": group_capacity,
                     "models": used_models_in_group
                 })

    target_tpd_input_capacity = 0
    if target_model_tpd_input_limit:
        target_tpd_input_capacity = active_keys_count * target_model_tpd_input_limit
        report_data["overall_stats"]["tpd_input"]["capacity_target_model"] = {
            "limit": target_model_tpd_input_limit,
            "capacity": target_tpd_input_capacity,
            "model": target_model
        }

    current_total_rpd = sum(model_total_rpd.values())
    current_total_tpd_input = sum(model_total_tpd_input.values())
    report_data["overall_stats"]["rpd"]["used_today"] = current_total_rpd
    report_data["overall_stats"]["tpd_input"]["used_today"] = current_total_tpd_input

    seconds_since_pt_midnight = (today_pt - today_pt.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    fraction_of_day_passed = seconds_since_pt_midnight / (24 * 3600) if seconds_since_pt_midnight > 0 else 0
    estimated_total_rpd_today = 0
    estimated_total_tpd_input_today = 0

    if fraction_of_day_passed > 0.01:
        estimated_total_rpd_today = int(current_total_rpd / fraction_of_day_passed)
        estimated_total_tpd_input_today = int(current_total_tpd_input / fraction_of_day_passed) # 虽然报告为 N/A，但计算出来 (Although reported as N/A, calculate it)
        report_data["overall_stats"]["rpd"]["estimated_today"] = estimated_total_rpd_today
        # TPD 输入预估通常意义不大，保持 None 或标记为 N/A
        # TPD input estimation is usually not meaningful, keep as None or mark as N/A
        report_data["overall_stats"]["tpd_input"]["estimated_today"] = None # 或者 "N/A" (or "N/A")

    N = 7
    last_n_days_rpd = []
    for i in range(1, N + 1):
        day_str = (today_pt - timedelta(days=i)).strftime('%Y-%m-%d')
        rpd = daily_rpd_totals_copy.get(day_str)
        if rpd is not None:
            last_n_days_rpd.append(rpd)

    avg_daily_rpd = 0
    if last_n_days_rpd:
        avg_daily_rpd = sum(last_n_days_rpd) / len(last_n_days_rpd)
        report_data["overall_stats"]["avg_daily_rpd_past_7_days"] = round(avg_daily_rpd, 2)

    # --- Key 数量建议 ---
    # --- Key Count Suggestion ---
    suggestion = "保持当前 Key 数量。"
    rpd_usage_indicator = max(estimated_total_rpd_today, avg_daily_rpd)
    tpd_input_usage_indicator = estimated_total_tpd_input_today # 使用计算值 (Use calculated value)

    rpd_usage_ratio = 0
    if target_rpd_capacity > 0:
        rpd_usage_ratio = rpd_usage_indicator / target_rpd_capacity

    tpd_input_usage_ratio = 0
    if target_tpd_input_capacity > 0 and tpd_input_usage_indicator > 0: # 仅当有 TPD 输入时计算比率 (Calculate ratio only if there is TPD input)
        tpd_input_usage_ratio = tpd_input_usage_indicator / target_tpd_input_capacity

    if active_keys_count == 0:
        suggestion = "错误: 未找到有效的 API Key！"
    elif target_rpd_capacity <= 0:
        suggestion = "无法生成建议 (目标模型 RPD 限制未定义)。"
    elif rpd_usage_ratio > 0.85:
        needed_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.7))
        suggestion = f"警告: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 已达目标容量 ({target_rpd_capacity:,}) 的 {rpd_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。"
    elif target_tpd_input_capacity > 0 and tpd_input_usage_ratio > 0.85:
         needed_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.7))
         suggestion = f"警告: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 已达目标容量 ({target_tpd_input_capacity:,}) 的 {tpd_input_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。"
    elif rpd_usage_ratio < 0.3 and tpd_input_usage_ratio < 0.3 and active_keys_count > 1:
        if rpd_usage_ratio >= tpd_input_usage_ratio and target_model_rpd_limit:
             ideal_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.5)) + 1
             suggestion = f"提示: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 较低 ({rpd_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。"
        elif target_model_tpd_input_limit:
             ideal_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.5)) + 1
             suggestion = f"提示: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 较低 ({tpd_input_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。"
    report_data["key_suggestion"] = suggestion

    # --- Top 5 IP 地址统计 ---
    # --- Top 5 IP Address Statistics ---
    def format_top_ips(raw_data: List[Tuple[str, int]], key_name: str) -> List[Dict[str, Any]]:
        """将 get_top_ips 返回的元组列表格式化为字典列表。"""
        """Formats the list of tuples returned by get_top_ips into a list of dictionaries."""
        return [{"ip": ip, key_name: count} for ip, count in raw_data]

    report_data["top_ips"]["requests"]["today"] = format_top_ips(get_top_ips(ip_counts_copy, today_pt.date(), today_pt.date()), "count")
    report_data["top_ips"]["tokens"]["today"] = format_top_ips(get_top_ips(ip_input_token_counts_copy, today_pt.date(), today_pt.date()), "tokens")
    report_data["top_ips"]["requests"]["week"] = format_top_ips(get_top_ips(ip_counts_copy, start_of_week_pt.date(), today_pt.date()), "count")
    report_data["top_ips"]["tokens"]["week"] = format_top_ips(get_top_ips(ip_input_token_counts_copy, start_of_week_pt.date(), today_pt.date()), "tokens")
    report_data["top_ips"]["requests"]["month"] = format_top_ips(get_top_ips(ip_counts_copy, start_of_month_pt.date(), today_pt.date()), "count")
    report_data["top_ips"]["tokens"]["month"] = format_top_ips(get_top_ips(ip_input_token_counts_copy, start_of_month_pt.date(), today_pt.date()), "tokens")

    logger.debug("结构化报告数据获取完成。") # Log completion of structured data retrieval
    return report_data
