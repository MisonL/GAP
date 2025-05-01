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
from app.core.tracking import ( # 同级目录导入
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS,
    daily_rpd_totals, daily_totals_lock,
    key_scores_cache, cache_lock,
    # ip_daily_counts, ip_counts_lock, # 移除 tracking 中的 IP 请求计数
    ip_daily_input_token_counts, ip_input_token_counts_lock # IP 输入 token 计数和锁
)
# 从 utils 导入实际使用的 IP 请求计数变量和锁
from app.core.request_helpers import ip_daily_request_counts, ip_daily_counts_lock as ip_rate_limit_lock # 从 request_helpers 导入 IP 计数和锁
from app import config # 导入 config 模块
from app.config import REPORT_LOG_LEVEL_INT # 导入日志级别配置
from app.core.key_management import INITIAL_KEY_COUNT, INVALID_KEY_COUNT_AT_STARTUP # 同级目录导入

# 条件导入用于类型提示
if TYPE_CHECKING:
    from app.core.key_manager_class import APIKeyManager # 导入密钥管理器类

logger = logging.getLogger('my_logger')

# --- 辅助函数：获取 Top IPs ---
def get_top_ips(data_dict: Dict[str, Dict[str, int]], start_date: date, end_date: date, top_n=5) -> List[Tuple[str, int]]:
    """
    获取指定日期范围内 Top N IP 地址及其计数。

    Args:
        data_dict: 包含日期 -> IP -> 计数 的字典。
        start_date: 统计的开始日期。
        end_date: 统计的结束日期。
        top_n: 要获取的 Top IP 数量。

    Returns:
        一个包含 (IP 地址, 计数) 元组的列表。
    """
    aggregated_counts = Counter()
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        if date_str in data_dict:
            # 使用 .get() 方法安全地访问嵌套字典，避免 KeyError
            for ip, count in data_dict.get(date_str, {}).items():
                aggregated_counts[ip] += count
        current_date += timedelta(days=1)
    return aggregated_counts.most_common(top_n)

# --- 周期性报告函数 ---
def report_usage(key_manager: 'APIKeyManager'):
    """
    周期性地报告聚合的 API 密钥使用情况、总体统计、密钥数量建议以及 Top IP 统计。

    Args:
        key_manager: APIKeyManager 实例，用于访问活跃密钥信息。
    """
    logger.info("开始生成周期性使用情况报告...")
    now = time.time()
    pt_timezone = pytz.timezone('America/Los_Angeles') # 设置太平洋时间区
    today_pt = datetime.now(pt_timezone) # 获取太平洋时间区的当前时间
    today_date_str = today_pt.strftime('%Y-%m-%d') # 格式化今日日期字符串
    start_of_week_pt = today_pt - timedelta(days=today_pt.weekday()) # 计算本周开始日期
    start_of_month_pt = today_pt.replace(day=1) # 计算本月开始日期

    # --- 安全地获取数据副本 ---
    # 使用锁确保在复制数据时不会发生并发修改
    with usage_lock:
        usage_data_copy = copy.deepcopy(usage_data) # 复制 Key 使用数据
    with daily_totals_lock:
        daily_rpd_totals_copy = daily_rpd_totals.copy() # 复制每日 RPD 总计
    with cache_lock:
        key_scores_cache_copy = copy.deepcopy(key_scores_cache) # 复制 Key 分数缓存

    # 复制并转换 IP 请求计数数据格式
    ip_counts_copy = defaultdict(lambda: defaultdict(int)) # 初始化目标格式字典
    with ip_rate_limit_lock: # 使用 utils 中的锁
        ip_daily_request_counts_raw = copy.deepcopy(ip_daily_request_counts) # 复制原始数据
        # 将原始格式 (date_str, ip): count 转换为 date_str: {ip: count}
        for (date_str, ip), count in ip_daily_request_counts_raw.items():
            ip_counts_copy[date_str][ip] = count # 转换为 get_top_ips 所需格式

    with ip_input_token_counts_lock:
        ip_input_token_counts_copy = copy.deepcopy(ip_daily_input_token_counts) # 复制 IP 输入 token 计数
    with key_manager.keys_lock:
        active_keys = key_manager.api_keys[:] # 获取活跃 Key 列表
        active_keys_count = len(active_keys) # 计算活跃 Key 数量

    # Initialize summary dictionaries before usage processing
    key_status_summary = defaultdict(lambda: defaultdict(int)) # 初始化 Key 状态汇总字典
    model_total_rpd = defaultdict(int) # 初始化模型总 RPD 字典
    model_total_tpd_input = defaultdict(int) # 初始化模型总 TPD 输入字典

    # Use the correctly calculated invalid key count from key_management
    # invalid_keys_count = INITIAL_KEY_COUNT - active_keys_count

    # 添加 ANSI 转义码以增加颜色和样式
    # 新配色方案 New Color Scheme
    COLOR_TITLE = "\033[1;94m"  # 亮蓝色 (Bright Blue) - 用于主标题
    COLOR_SEPARATOR = "\033[0;90m" # 亮黑色/深灰色 (Bright Black/Dark Gray) - 用于分隔符
    COLOR_SECTION_HEADER = "\033[1;96m" # 亮青色 (Bright Cyan) - 用于区域标题
    COLOR_POSITIVE = "\033[1;92m" # 亮绿色 (Bright Green) - 用于良好状态、数值、模型名
    COLOR_WARNING = "\033[1;93m" # 亮黄色 (Bright Yellow) - 用于警告、次要建议
    COLOR_ERROR = "\033[1;91m" # 亮红色 (Bright Red) - 用于错误、主要警告、重要建议
    COLOR_INFO = "\033[0;37m" # 白色 (White) - 用于普通标签 (可选，或直接用 RESET)
    COLOR_RESET = "\033[0m"    # 重置颜色和样式

    report_lines = [f"{COLOR_TITLE}--- API 使用情况报告 ({today_pt.strftime('%Y-%m-%d %H:%M:%S %Z')}) ---{COLOR_RESET}"] # 报告标题
    separator = f"{COLOR_SEPARATOR}{'=' * 60}{COLOR_RESET}" # 定义分隔符，使用新颜色并加长

    # --- Key 使用情况聚合 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} Key 使用情况聚合 {COLOR_RESET}\n{separator}") # 添加分隔符和标题，使用新颜色

    if not usage_data_copy:
        report_lines.append(f"  {COLOR_WARNING}暂无 Key 使用数据。{COLOR_RESET}") # 如果没有 Key 使用数据则报告，使用警告色
    else:
        # 遍历每个 Key 的使用数据
        for key, models_usage in usage_data_copy.items():
            if not models_usage: continue # Skip if no usage for this key
            # 遍历每个模型的使用数据
            for model_name, usage in models_usage.items():
                limits = config.MODEL_LIMITS.get(model_name) # 获取模型的限制
                if not limits: continue # Skip if no limits defined for the model

                rpd_limit = limits.get("rpd") # 获取 RPD 限制
                rpm_limit = limits.get("rpm") # 获取 RPM 限制
                tpm_input_limit = limits.get("tpm_input") # 获取 TPM 输入限制
                tpd_input_limit = limits.get("tpd_input") # 获取 TPD 输入限制

                rpd_count = usage.get("rpd_count", 0) # 获取 RPD 计数
                rpm_count = usage.get("rpm_count", 0) # 获取 RPM 计数
                tpm_input_count = usage.get("tpm_input_count", 0) # 获取 TPM 输入计数
                tpd_input_count = usage.get("tpd_input_count", 0) # 获取 TPD 输入计数
                rpm_ts = usage.get("rpm_timestamp", 0) # 获取 RPM 时间戳
                tpm_input_ts = usage.get("tpm_input_timestamp", 0) # 获取 TPM 输入时间戳

                model_total_rpd[model_name] += rpd_count # 累加模型的总 RPD
                model_total_tpd_input[model_name] += tpd_input_count # 累加模型的总 TPD 输入

                # RPM (每分钟请求数)
                rpm_in_window = 0
                rpm_remaining_pct = 1.0
                if rpm_limit is not None:
                    # 检查是否在 RPM 窗口期内
                    if now - rpm_ts < RPM_WINDOW_SECONDS:
                        rpm_in_window = rpm_count # 获取窗口期内的 RPM 计数
                        # 计算剩余百分比
                        rpm_remaining_pct = max(0, (rpm_limit - rpm_in_window) / rpm_limit) if rpm_limit > 0 else 0

                # TPM Input (每分钟输入 Token 数)
                tpm_input_in_window = 0
                tpm_input_remaining_pct = 1.0
                if tpm_input_limit is not None:
                    # 检查是否在 TPM 输入窗口期内
                    if now - tpm_input_ts < TPM_WINDOW_SECONDS:
                        tpm_input_in_window = tpm_input_count # 获取窗口期内的 TPM 输入计数
                        # 计算剩余百分比
                        tpm_input_remaining_pct = max(0, (tpm_input_limit - tpm_input_in_window) / tpm_input_limit) if tpm_input_limit > 0 else 0

                # RPD (每日请求数)
                # 计算剩余百分比
                rpd_remaining_pct = max(0, (rpd_limit - rpd_count) / rpd_limit) if rpd_limit is not None and rpd_limit > 0 else 1.0

                # TPD Input (每日输入 Token 数)
                # 计算剩余百分比
                tpd_input_remaining_pct = max(0, (tpd_input_limit - tpd_input_count) / tpd_input_limit) if tpd_input_limit is not None and tpd_input_limit > 0 else 1.0

                score = key_scores_cache_copy.get(key, {}).get(model_name, -1.0) # 获取 Key 分数

                # 构建 Key 状态字符串
                status_parts = [
                    f"RPD={rpd_count}/{rpd_limit or 'N/A'} ({rpd_remaining_pct:.0%})",
                    f"RPM={rpm_in_window}/{rpm_limit or 'N/A'} ({rpm_remaining_pct:.0%})",
                    f"TPD_In={tpd_input_count:,}/{tpd_input_limit or 'N/A'} ({tpd_input_remaining_pct:.0%})",
                    f"TPM_In={tpm_input_in_window:,}/{tpm_input_limit or 'N/A'} ({tpm_input_remaining_pct:.0%})",
                    f"Score={score:.2f}"
                ]
                status_str = " | ".join(status_parts)
                key_status_summary[model_name][status_str] += 1 # 按模型和状态汇总 Key 数量

        if not key_status_summary:
             report_lines.append(f"  {COLOR_WARNING}暂无 Key 使用数据。{COLOR_RESET}") # Report if no key usage data after processing, use warning color
        else:
            # 遍历并报告每个模型的 Key 使用情况
            for model_name, statuses in sorted(key_status_summary.items()):
                total_keys_for_model = sum(statuses.values()) # 计算使用该模型的 Key 总数
                report_lines.append(f"\n  {COLOR_POSITIVE}模型: {model_name}{COLOR_RESET}") # 报告模型名称，使用新颜色
                report_lines.append(f"    今日总 RPD: {COLOR_POSITIVE}{model_total_rpd[model_name]:,}{COLOR_RESET}") # 报告模型今日总 RPD，使用新颜色
                report_lines.append(f"    今日总 TPD_In: {COLOR_POSITIVE}{model_total_tpd_input[model_name]:,}{COLOR_RESET}") # 报告模型今日总 TPD 输入，使用新颜色
                report_lines.append(f"    使用此模型的 Key 数量: {COLOR_POSITIVE}{total_keys_for_model}{COLOR_RESET}") # 报告使用此模型的 Key 数量，使用新颜色
                report_lines.append(f"    {COLOR_SECTION_HEADER}状态分布:{COLOR_RESET}") # 报告状态分布标题，使用新颜色
                # 按数量降序排序状态并报告
                for status, count in sorted(statuses.items(), key=lambda item: item[1], reverse=True):
                    report_lines.append(f"      - 数量: {COLOR_POSITIVE}{count}{COLOR_RESET}") # 报告数量，使用新颜色
                    # 解析状态字符串并格式化输出
                    parts = status.split(' | ')
                    for part in parts:
                        # 使用 f-string 进行左对齐，分配足够宽度
                        report_lines.append(f"        {part:<45}") # 左对齐，宽度 45


    # --- 总体统计与预测 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} 总体统计与预测 {COLOR_RESET}\n{separator}") # 添加分隔符和标题，使用新颜色
    report_lines.append(f"  活跃 Key 数量: {COLOR_POSITIVE}{active_keys_count}{COLOR_RESET}") # 报告活跃 Key 数量，使用新颜色
    report_lines.append(f"  启动时无效 Key 数量: {COLOR_WARNING}{INVALID_KEY_COUNT_AT_STARTUP}{COLOR_RESET}") # 报告启动时无效 Key 数量，使用警告色

    # RPD 容量
    report_lines.append(f"\n  {COLOR_SECTION_HEADER}RPD 容量估算:{COLOR_RESET}") # 报告 RPD 容量估算标题，使用新颜色
    rpd_groups = defaultdict(list) # 按 RPD 限制分组模型
    model_rpd_usage_count = defaultdict(int) # 统计使用每个模型的 Key 数量
    for model, limits in config.MODEL_LIMITS.items():
        if limits and limits.get("rpd") is not None:
            rpd_groups[limits["rpd"]].append(model)
    for key, models_usage in usage_data_copy.items():
        for model_name in models_usage:
             if model_name in config.MODEL_LIMITS:
                  model_rpd_usage_count[model_name] += 1

    # 定义需要估算的三个目标模型
    target_models = [
        "Gemini-2.5-pro-exp-03-25",
        "gemini-2.5-flash-preview-04-17",
        "gemini-2.0-flash-thinking-exp-01-21"
    ]

    # 遍历目标模型进行容量估算
    reported_rpd_limits = set() # 记录已报告的 RPD 限制，避免重复
    for target_model in target_models:
        target_model_limits = config.MODEL_LIMITS.get(target_model, {})
        target_model_rpd_limit = target_model_limits.get("rpd")

        if target_model_rpd_limit is not None:
            target_rpd_capacity = active_keys_count * target_model_rpd_limit
            report_lines.append(f"    - 基于 {target_model} (RPD={target_model_rpd_limit}): {COLOR_POSITIVE}{target_rpd_capacity:,}/天{COLOR_RESET}")
            reported_rpd_limits.add(target_model_rpd_limit) # 记录已报告的 RPD 限制
        else:
            logger.warning(f"目标模型 {target_model} 或其 RPD 限制未在 model_limits.json 中找到，无法估算 RPD 容量。")
            report_lines.append(f"    - 基于 {target_model}: {COLOR_ERROR}RPD 限制未定义。{COLOR_RESET}")

    # 报告其他 RPD 组的容量 (排除已在目标模型中报告的 RPD 限制)
    for rpd_limit, models in sorted(rpd_groups.items()):
        if rpd_limit not in reported_rpd_limits: # 检查是否已报告
             group_capacity = active_keys_count * rpd_limit
             used_models_in_group = [m for m in models if model_rpd_usage_count.get(m, 0) > 0]
             if used_models_in_group:
                  model_names_str = ', '.join(used_models_in_group)
                  report_lines.append(f"    - RPD={rpd_limit}: {model_names_str} (估算容量: {COLOR_POSITIVE}{group_capacity:,}/天{COLOR_RESET})")

    # TPD 输入容量
    report_lines.append(f"\n  {COLOR_SECTION_HEADER}TPD 输入容量估算:{COLOR_RESET}") # 报告 TPD 输入容量估算标题，使用新颜色

    # 遍历目标模型进行 TPD 输入容量估算
    for target_model in target_models:
        target_model_limits = config.MODEL_LIMITS.get(target_model, {})
        target_model_tpd_input_limit = target_model_limits.get("tpd_input")

        if target_model_tpd_input_limit is not None:
            target_tpd_input_capacity = active_keys_count * target_model_tpd_input_limit
            report_lines.append(f"    - 基于 {target_model} (TPD_In={target_model_tpd_input_limit:,}): {COLOR_POSITIVE}{target_tpd_input_capacity:,}/天{COLOR_RESET}")
        else:
            report_lines.append(f"    - 基于 {target_model}: {COLOR_ERROR}TPD_Input 限制未定义。{COLOR_RESET}")

    # 今日用量与估算
    report_lines.append(f"\n  {COLOR_SECTION_HEADER}今日用量与估算 (PT 时间):{COLOR_RESET}") # 报告今日用量与估算标题，使用新颜色
    current_total_rpd = sum(model_total_rpd.values()) # 计算今日总 RPD
    current_total_tpd_input = sum(model_total_tpd_input.values()) # 计算今日总 TPD 输入
    report_lines.append(f"    - 今日已用 RPD: {COLOR_POSITIVE}{current_total_rpd:,}{COLOR_RESET}") # 报告今日已用 RPD，使用新颜色
    report_lines.append(f"    - 今日已用 TPD 输入: {COLOR_POSITIVE}{current_total_tpd_input:,}{COLOR_RESET}") # 报告今日已用 TPD 输入，使用新颜色

    # 计算今天已经过去的时间占全天的比例
    seconds_since_pt_midnight = (today_pt - today_pt.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    fraction_of_day_passed = seconds_since_pt_midnight / (24 * 3600) if seconds_since_pt_midnight > 0 else 0
    estimated_total_rpd_today = 0
    estimated_total_tpd_input_today = 0

    # 如果一天已经过去了一小部分（大于 1%），则进行估算
    if fraction_of_day_passed > 0.01:
        estimated_total_rpd_today = int(current_total_rpd / fraction_of_day_passed) # 估算今日总 RPD
        estimated_total_tpd_input_today = int(current_total_tpd_input / fraction_of_day_passed) # 估算今日总 TPD 输入
        report_lines.append(f"  预估今日 RPD (PT): {COLOR_POSITIVE}{estimated_total_rpd_today:,}{COLOR_RESET} (基于 {fraction_of_day_passed:.1%} 时间)") # Report estimated RPD, use new color
        # 根据时间早晚决定是否显示 TPD 输入估算
        if fraction_of_day_passed > 0.1: # 例如，如果超过 10% 的时间过去了
            report_lines.append(f"  预估今日 TPD 输入 (PT): {COLOR_POSITIVE}{estimated_total_tpd_input_today:,}{COLOR_RESET} (基于 {fraction_of_day_passed:.1%} 时间)") # Report estimated TPD input, use new color
        else:
            report_lines.append(f"  预估今日 TPD 输入 (PT): {COLOR_WARNING}N/A (时间过早){COLOR_RESET}") # Report N/A for TPD input if too early, use warning color

    # 平均 RPD
    report_lines.append(f"\n  {COLOR_SECTION_HEADER}历史平均用量:{COLOR_RESET}") # 报告历史平均用量标题，使用新颜色
    N = 7 # 统计过去 N 天
    last_n_days_rpd = [] # 存储过去 N 天的 RPD
    # 遍历过去 N 天
    for i in range(1, N + 1):
        day_str = (today_pt - timedelta(days=i)).strftime('%Y-%m-%d') # 获取日期字符串
        rpd = daily_rpd_totals_copy.get(day_str) # 获取该日的 RPD
        if rpd is not None:
            last_n_days_rpd.append(rpd) # 如果存在则添加到列表

    avg_daily_rpd = 0
    if last_n_days_rpd:
        avg_daily_rpd = sum(last_n_days_rpd) / len(last_n_days_rpd) # 计算平均 RPD
        report_lines.append(f"  过去 {len(last_n_days_rpd)} 天平均日 RPD (PT): {COLOR_POSITIVE}{avg_daily_rpd:,.0f}{COLOR_RESET}") # Report average daily RPD, use new color
    else:
        report_lines.append(f"  过去 {N} 天平均日 RPD (PT): {COLOR_WARNING}N/A (无历史数据){COLOR_RESET}") # Report N/A if no historical data, use warning color

    # --- Key 数量建议 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} Key 数量建议 {COLOR_RESET}\n{separator}") # 添加分隔符和标题，使用新颜色
    suggestion = f"{COLOR_POSITIVE}保持当前 Key 数量。{COLOR_RESET}" # 默认建议，使用新颜色
    # 使用预估今日 RPD 和平均 RPD 中的较大值作为 RPD 使用指标
    rpd_usage_indicator = max(estimated_total_rpd_today, avg_daily_rpd)
    tpd_input_usage_indicator = estimated_total_tpd_input_today # TPD 输入使用指标

    rpd_usage_ratio = 0
    if target_rpd_capacity > 0:
        rpd_usage_ratio = rpd_usage_indicator / target_rpd_capacity # 计算 RPD 使用率

    tpd_input_usage_ratio = 0
    if target_tpd_input_capacity > 0:
        tpd_input_usage_ratio = tpd_input_usage_indicator / target_tpd_input_capacity # 计算 TPD 输入使用率

    # 根据使用率提供 Key 数量建议
    if active_keys_count == 0:
        suggestion = f"{COLOR_ERROR}错误: 未找到有效的 API Key！{COLOR_RESET}" # 使用错误色
    elif target_rpd_capacity <= 0:
        suggestion = f"{COLOR_ERROR}无法生成建议 (目标模型 RPD 限制未定义)。{COLOR_RESET}" # 使用错误色
    elif rpd_usage_ratio > 0.85:
        # 如果 RPD 使用率过高，建议增加 Key 数量
        needed_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.7)) # 计算建议的 Key 数量
        suggestion = f"{COLOR_ERROR}警告: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 已达目标容量 ({target_rpd_capacity:,}) 的 {rpd_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。{COLOR_RESET}" # 使用错误色
    elif target_tpd_input_capacity > 0 and tpd_input_usage_ratio > 0.85:
         # 如果 TPD 输入使用率过高，建议增加 Key 数量
         needed_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.7)) # 计算建议的 Key 数量
         suggestion = f"{COLOR_ERROR}警告: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 已达目标容量 ({target_tpd_input_capacity:,}) 的 {tpd_input_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。{COLOR_RESET}" # 使用错误色
    elif rpd_usage_ratio < 0.3 and tpd_input_usage_ratio < 0.3 and active_keys_count > 1:
        # 如果 RPD 和 TPD 输入使用率都较低，且活跃 Key 数量大于 1，建议减少 Key 数量
        if rpd_usage_ratio >= tpd_input_usage_ratio and target_model_rpd_limit:
             ideal_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.5)) + 1 # 计算理想的 Key 数量
             suggestion = f"{COLOR_WARNING}提示: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 较低 ({rpd_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。{COLOR_RESET}" # 使用警告色
        elif target_model_tpd_input_limit:
             ideal_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.5)) + 1 # 计算理想的 Key 数量
             suggestion = f"{COLOR_WARNING}提示: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 较低 ({tpd_input_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。{COLOR_RESET}" # 使用警告色
    report_lines.append(f"  {suggestion}") # 报告建议


    # --- Top 5 IP 地址统计 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} Top 5 IP 地址统计 (PT 时间) {COLOR_RESET}\n{separator}") # 添加分隔符和标题，使用新颜色

    # 今日 Top 5 请求
    top_ips_today_req = get_top_ips(ip_counts_copy, today_pt.date(), today_pt.date()) # 获取今日 Top 5 请求 IP
    report_lines.append(f"\n  {COLOR_SECTION_HEADER}今日请求次数 Top 5:{COLOR_RESET}") # 报告今日 Top 5 请求标题，使用新颜色
    if top_ips_today_req:
        for ip, count in top_ips_today_req: report_lines.append(f"    - {ip}: {COLOR_POSITIVE}{count}{COLOR_RESET}") # 报告每个 IP 和计数，使用新颜色
    else: report_lines.append(f"    - {COLOR_WARNING}暂无记录{COLOR_RESET}") # 如果没有记录则报告，使用警告色

    # 今日 Top 5 输入 Token
    top_ips_today_input_token = get_top_ips(ip_input_token_counts_copy, today_pt.date(), today_pt.date()) # 获取今日 Top 5 输入 Token IP
    report_lines.append(f"  {COLOR_SECTION_HEADER}今日输入 Token Top 5:{COLOR_RESET}") # 报告今日 Top 5 输入 Token 标题，使用新颜色
    if top_ips_today_input_token:
        for ip, tokens in top_ips_today_input_token: report_lines.append(f"    - {ip}: {COLOR_POSITIVE}{tokens:,}{COLOR_RESET}") # 报告每个 IP 和 Token 计数，使用新颜色
    else: report_lines.append(f"    - {COLOR_WARNING}暂无记录{COLOR_RESET}") # 如果没有记录则报告，使用警告色

    # 本周 Top 5 请求
    top_ips_week_req = get_top_ips(ip_counts_copy, start_of_week_pt.date(), today_pt.date()) # 获取本周 Top 5 请求 IP
    report_lines.append(f"\n  {COLOR_SECTION_HEADER}本周请求次数 Top 5:{COLOR_RESET}") # 报告本周 Top 5 请求标题，使用新颜色
    if top_ips_week_req:
        for ip, count in top_ips_week_req: report_lines.append(f"    - {ip}: {COLOR_POSITIVE}{count}{COLOR_RESET}") # 报告每个 IP 和计数，使用新颜色
    else: report_lines.append(f"    - {COLOR_WARNING}暂无记录{COLOR_RESET}") # 如果没有记录则报告，使用警告色

    # 本周 Top 5 输入 Token
    top_ips_week_input_token = get_top_ips(ip_input_token_counts_copy, start_of_week_pt.date(), today_pt.date()) # 获取本周 Top 5 输入 Token IP
    report_lines.append(f"  {COLOR_SECTION_HEADER}本周输入 Token Top 5:{COLOR_RESET}") # 报告本周 Top 5 输入 Token 标题，使用新颜色
    if top_ips_week_input_token:
        for ip, tokens in top_ips_week_input_token: report_lines.append(f"    - {ip}: {COLOR_POSITIVE}{tokens:,}{COLOR_RESET}") # 报告每个 IP 和 Token 计数，使用新颜色
    else: report_lines.append(f"    - {COLOR_WARNING}暂无记录{COLOR_RESET}") # 如果没有记录则报告，使用警告色

    # 本月 Top 5 请求
    top_ips_month_req = get_top_ips(ip_counts_copy, start_of_month_pt.date(), today_pt.date()) # 获取本月 Top 5 请求 IP
    report_lines.append(f"\n  {COLOR_SECTION_HEADER}本月请求次数 Top 5:{COLOR_RESET}") # 报告本月 Top 5 请求标题，使用新颜色
    if top_ips_month_req:
        for ip, count in top_ips_month_req: report_lines.append(f"    - {ip}: {COLOR_POSITIVE}{count}{COLOR_RESET}") # 报告每个 IP 和计数，使用新颜色
    else: report_lines.append(f"    - {COLOR_WARNING}暂无记录{COLOR_RESET}") # 如果没有记录则报告，使用警告色

    # 本月 Top 5 输入 Token
    # Top 5 Input Tokens This Month
    top_ips_month_input_token = get_top_ips(ip_input_token_counts_copy, start_of_month_pt.date(), today_pt.date()) # 获取本月 Top 5 输入 Token IP (Get Top 5 input token IPs for this month)
    report_lines.append(f"  {COLOR_SECTION_HEADER}本月输入 Token Top 5:{COLOR_RESET}") # 报告本月 Top 5 输入 Token 标题 (Report Top 5 input tokens this month title), use new color
    if top_ips_month_input_token:
        for ip, tokens in top_ips_month_input_token: report_lines.append(f"    - {ip}: {COLOR_POSITIVE}{tokens:,}{COLOR_RESET}") # 报告每个 IP 和 Token 计数 (Report each IP and token count), use new color
    else: report_lines.append(f"    - {COLOR_WARNING}暂无记录{COLOR_RESET}") # 如果没有记录则报告 (Report if no records), use warning color


    report_lines.append(f"\n{separator}\n{COLOR_TITLE} 报告结束 {COLOR_RESET}\n{separator}") # 添加结束分隔符，使用新颜色
    full_report = "\n".join(report_lines) # 将所有报告行连接成单个字符串

    # 使用配置的日志级别记录报告
    logger.log(REPORT_LOG_LEVEL_INT, full_report)


# --- 新增：获取结构化报告数据的函数 ---
async def get_structured_report_data(key_manager: 'APIKeyManager') -> Dict[str, Any]:
    """
    获取用于 API 的结构化使用情况报告数据。

    Args:
        key_manager: APIKeyManager 实例。

    Returns:
        包含报告数据的字典。
    """
    logger.debug("开始获取结构化报告数据...")
    now = time.time()
    utc_now = datetime.now(timezone.utc) # 获取 UTC 当前时间
    pt_timezone = pytz.timezone('America/Los_Angeles') # 设置太平洋时间区
    today_pt = datetime.now(pt_timezone) # 获取太平洋时间区的当前时间
    today_date_str = today_pt.strftime('%Y-%m-%d') # 格式化今日日期字符串
    start_of_week_pt = today_pt - timedelta(days=today_pt.weekday()) # 计算本周开始日期
    start_of_month_pt = today_pt.replace(day=1) # 计算本月开始日期

    # --- 安全地获取数据副本 ---
    with key_manager.keys_lock:
        active_keys = key_manager.api_keys[:]
        active_keys_count = len(active_keys)

    # 如果没有活跃 Key，返回友好提示和空数据
    if active_keys_count == 0:
        logger.debug("没有找到活跃 Key，返回无数据报告。")
        return {
            "report_time_utc": utc_now.isoformat(), # 报告时间
            "key_status_summary": {}, # Key 状态汇总
            "overall_stats": { # 总体统计
                "active_keys_count": 0, # 活跃 Key 数量
                "invalid_keys_startup": INVALID_KEY_COUNT_AT_STARTUP, # 启动时无效 Key 数量
                "rpd": { # RPD 相关统计
                    "capacity_target_model": None, # 目标模型容量信息
                    "capacity_other_models": [], # 其他模型容量信息
                    "used_today": 0, # 今日已用 RPD
                    "estimated_today": None, # 今日预估 RPD
                },
                "tpd_input": { # TPD 输入相关统计
                     "capacity_target_model": None, # 目标模型容量信息
                     "used_today": 0, # 今日已用 TPD 输入
                     "estimated_today": None, # 今日预估 TPD 输入
                },
                "avg_daily_rpd_past_7_days": None, # 过去7天平均日 RPD
            },
            "key_suggestion": "未找到有效的 API Key，请在管理页面配置。", # Key 数量建议的友好提示
            "top_ips": { # Top IP 统计
                "requests": {"today": [], "week": [], "month": []}, # 请求次数
                "tokens": {"today": [], "week": [], "month": []} # 输入 Token 数
            }
        }

    # --- 安全地获取数据副本 (仅在有活跃 Key 时) ---
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


    # --- 初始化结果字典 (在有活跃 Key 时填充) ---
    report_data = {
        "report_time_utc": utc_now.isoformat(), # 报告时间
        "key_status_summary": {}, # Key 状态汇总
        "overall_stats": { # 总体统计
            "active_keys_count": active_keys_count, # 活跃 Key 数量
            "invalid_keys_startup": INVALID_KEY_COUNT_AT_STARTUP, # 启动时无效 Key 数量
            "rpd": { # RPD 相关统计
                "capacity_target_model": None, # 目标模型容量信息
                "capacity_other_models": [], # 其他模型容量信息
                "used_today": 0, # 今日已用 RPD
                "estimated_today": None, # 今日预估 RPD
            },
            "tpd_input": { # TPD 输入相关统计
                 "capacity_target_model": None, # 目标模型容量信息
                 "used_today": 0, # 今日已用 TPD 输入
                 "estimated_today": None, # 今日预估 TPD 输入
            },
            "avg_daily_rpd_past_7_days": None, # 过去7天平均日 RPD
        },
        "key_suggestion": "无法生成建议。", # Key 数量建议
        "top_ips": { # Top IP 统计
            "requests": {"today": [], "week": [], "month": []}, # 请求次数
            "tokens": {"today": [], "week": [], "month": []} # 输入 Token 数
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

    # 定义需要估算的三个目标模型
    target_models = [
        "Gemini-2.5-pro-exp-03-25",
        "gemini-2.5-flash-preview-04-17",
        "gemini-2.0-flash-thinking-exp-01-21"
    ]

    # 遍历目标模型进行 RPD 容量估算
    report_data["overall_stats"]["rpd"]["capacity_target_models"] = [] # 修改键名并初始化为列表
    reported_rpd_limits = set() # 记录已报告的 RPD 限制，避免重复
    for target_model in target_models:
        target_model_limits = config.MODEL_LIMITS.get(target_model, {})
        target_model_rpd_limit = target_model_limits.get("rpd")

        if target_model_rpd_limit is not None:
            target_rpd_capacity = active_keys_count * target_model_rpd_limit
            report_data["overall_stats"]["rpd"]["capacity_target_models"].append({
                "limit": target_model_rpd_limit,
                "capacity": target_rpd_capacity,
                "model": target_model
            })
            reported_rpd_limits.add(target_model_rpd_limit) # 记录已报告的 RPD 限制

    # 报告其他 RPD 组的容量 (排除已在目标模型中报告的 RPD 限制)
    for rpd_limit, models in sorted(rpd_groups.items()):
        if rpd_limit not in reported_rpd_limits: # 检查是否已报告
             group_capacity = active_keys_count * rpd_limit
             used_models_in_group = [m for m in models if model_rpd_usage_count.get(m, 0) > 0]
             if used_models_in_group:
                  report_data["overall_stats"]["rpd"]["capacity_other_models"].append({
                      "limit": rpd_limit,
                      "capacity": group_capacity,
                      "models": used_models_in_group
                  })

    # TPD 输入容量
    report_data["overall_stats"]["tpd_input"]["capacity_target_models"] = [] # 修改键名并初始化为列表

    # 遍历目标模型进行 TPD 输入容量估算
    for target_model in target_models:
        target_model_limits = config.MODEL_LIMITS.get(target_model, {})
        target_model_tpd_input_limit = target_model_limits.get("tpd_input")

        if target_model_tpd_input_limit is not None:
            target_tpd_input_capacity = active_keys_count * target_model_tpd_input_limit
            report_data["overall_stats"]["tpd_input"]["capacity_target_models"].append({
                "limit": target_model_tpd_input_limit, # 修复：使用正确的变量名
                "capacity": target_tpd_input_capacity,
                "model": target_model
            })

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

    # 这里的逻辑在函数开头 active_keys_count == 0 时已经处理，所以这里不再需要检查
    # if active_keys_count == 0:
    #     suggestion = "错误: 未找到有效的 API Key！"
    if target_rpd_capacity <= 0:
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
