# -*- coding: utf-8 -*-
"""
包含生成周期性使用情况报告的函数。
This module contains functions for generating periodic usage reports.
"""
import time # 导入时间模块
import logging # 导入日志模块
import pytz # 导入时区库
import copy # 导入复制模块，用于深拷贝数据结构
from datetime import datetime, timedelta, date, timezone # 导入日期时间相关类
from collections import Counter, defaultdict # 导入计数器和默认字典
from typing import List, Tuple, Dict, Any, TYPE_CHECKING # 导入类型提示
import json # 导入 JSON 模块

# 从其他模块导入必要的组件
from app.core.tracking import ( # 从 tracking 模块导入共享数据和锁
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS, # Key 使用数据、锁、时间窗口常量
    daily_rpd_totals, daily_totals_lock, # 每日 RPD 总计和锁
    key_scores_cache, cache_lock, # Key 分数缓存和锁
    ip_daily_input_token_counts, ip_input_token_counts_lock, # IP 每日输入 Token 计数和锁
    cache_hit_count, cache_miss_count, total_tokens_saved, cache_tracking_lock # 缓存统计变量和锁
)
# 从 request_helpers 导入 IP 请求数据和锁 (注意别名)
from app.core.utils.request_helpers import ip_request_data, ip_daily_counts_lock as ip_rate_limit_lock # (新路径)
from app import config # 导入应用配置模块
from app.core.keys.checker import INITIAL_KEY_COUNT, INVALID_KEY_COUNT_AT_STARTUP # 从 checker 模块导入启动时 Key 统计信息 (新路径)

# 条件导入 APIKeyManager 用于类型提示，避免循环导入
if TYPE_CHECKING:
    from app.core.keys.manager import APIKeyManager # (新路径)

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 辅助函数：获取 Top IPs ---
def get_top_ips(data_dict: Dict[str, Dict[str, int]], start_date: date, end_date: date, top_n=5) -> List[Tuple[str, int]]:
    """
    (辅助函数) 从按日期组织的 IP 计数/Token 字典中，聚合指定日期范围内的 Top N IP 地址及其总数。

    Args:
        data_dict (Dict[str, Dict[str, int]]): 包含数据的字典，格式为 {'YYYY-MM-DD': {'ip_address': count}}。
        start_date (date): 统计范围的开始日期 (包含)。
        end_date (date): 统计范围的结束日期 (包含)。
        top_n (int): 返回 Top N 个结果。默认为 5。

    Returns:
        List[Tuple[str, int]]: 一个元组列表，每个元组包含 (IP 地址, 总计数/Token)，按总数降序排列。
    """
    aggregated_counts = Counter() # 使用 Counter 进行高效聚合
    current_date = start_date # 从开始日期迭代
    # 循环遍历指定日期范围内的每一天
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d') # 将日期格式化为字符串键
        # 检查当天是否有数据
        if date_str in data_dict:
            # 安全地获取当天的 IP 计数数据 (使用 .get 避免 KeyError)
            for ip, count in data_dict.get(date_str, {}).items():
                aggregated_counts[ip] += count # 累加每个 IP 的计数
        current_date += timedelta(days=1) # 移动到下一天
    # 返回计数最高的前 N 个 IP 及其计数
    return aggregated_counts.most_common(top_n)

# --- 辅助函数：格式化 Top IPs ---
def format_top_ips(raw_data: List[Tuple[str, int]], key_name: str) -> List[Dict[str, Any]]:
    """
    (辅助函数) 将 `get_top_ips` 返回的原始元组列表格式化为更易于 JSON 序列化的字典列表。

    Args:
        raw_data (List[Tuple[str, int]]): `get_top_ips` 返回的 (IP, count/tokens) 元组列表。
        key_name (str): 用于表示计数值的键名 (例如 'count' 或 'tokens')。

    Returns:
        List[Dict[str, Any]]: 一个字典列表，每个字典包含 'ip' 和指定的 `key_name`。
                               例如: [{'ip': '1.2.3.4', 'count': 100}, ...]
    """
    # 使用列表推导式进行格式转换
    return [{'ip': ip, key_name: value} for ip, value in raw_data]

# --- 周期性报告生成函数 ---
def report_usage(key_manager: 'APIKeyManager') -> Dict[str, Any]: # 返回类型修改为 Dict
    """
    生成周期性的 API 使用情况报告。
    此函数聚合来自 `tracking` 模块的各种统计数据，
    包括 Key 使用情况、总体容量估算、Key 数量建议、Top IP 统计、Key 选择原因和缓存使用情况。
    通常由后台调度任务（如 APScheduler）定期调用。

    Args:
        key_manager (APIKeyManager): APIKeyManager 的实例，用于获取当前活跃 Key 的信息。

    Returns:
        Dict[str, Any]: 包含所有报告数据的字典，方便后续处理或 JSON 序列化。
    """
    logger.info("开始生成周期性使用情况报告...") # 记录报告开始日志
    report_data: Dict[str, Any] = {} # 初始化空的报告数据字典
    now = time.time() # 获取当前时间戳 (Unix timestamp)

    # --- 时间和日期设置 ---
    pt_timezone = pytz.timezone('America/Los_Angeles') # 定义太平洋时区
    today_pt = datetime.now(pt_timezone) # 获取太平洋时区的当前日期和时间
    today_date = today_pt.date() # 获取太平洋时区的当前日期
    today_date_str = today_date.strftime('%Y-%m-%d') # 格式化太平洋时区的日期字符串
    start_of_week_pt = today_date - timedelta(days=today_pt.weekday()) # 计算本周一的日期 (太平洋时区)
    start_of_month_pt = today_date.replace(day=1) # 计算本月第一天的日期 (太平洋时区)

    # --- 安全地获取共享数据的副本 ---
    # 使用各自的锁来确保在复制数据时不会发生并发修改，保证数据一致性
    with usage_lock: # Key 使用数据锁
        usage_data_copy = copy.deepcopy(usage_data)
    with daily_totals_lock: # 每日 RPD 总计锁
        daily_rpd_totals_copy = daily_rpd_totals.copy()
    with cache_lock: # Key 分数缓存锁
        key_scores_cache_copy = copy.deepcopy(key_scores_cache)

    # 复制并转换 IP 请求计数数据格式 (从 (date, ip): count 到 date: {ip: count})
    ip_counts_copy = defaultdict(lambda: defaultdict(int)) # 初始化目标格式字典
    with ip_rate_limit_lock: # IP 请求计数锁
        ip_daily_request_counts_raw = copy.deepcopy(ip_request_data) # 复制原始数据
        # 转换格式
        for date_str_key, ip_counts_for_date in ip_daily_request_counts_raw.items():
            for ip, count in ip_counts_for_date.items():
                ip_counts_copy[date_str_key][ip] = count

    with ip_input_token_counts_lock: # IP 输入 Token 计数锁
        ip_input_token_counts_copy = copy.deepcopy(ip_daily_input_token_counts)
    with key_manager.keys_lock: # Key 管理器锁
        active_keys = key_manager.api_keys[:] # 获取当前活动 Key 列表的副本
        active_keys_count = len(active_keys) # 计算活动 Key 数量
        # 安全地获取 Key 选择记录的副本 (使用 getattr 以防属性不存在)
        key_selection_records_copy = copy.deepcopy(getattr(key_manager, 'key_selection_records', []))

    # --- 初始化报告数据字典结构 ---
    # 定义报告的基本结构，并设置默认值
    report_data: Dict[str, Any] = {
        "overall_stats": { # 总体统计信息
            "active_keys_count": active_keys_count, # 当前活动 Key 数量
            "invalid_keys_at_startup": INVALID_KEY_COUNT_AT_STARTUP, # 启动时发现的无效 Key 数量
            "rpd_capacity_estimation": [], # RPD 容量估算列表
            "tpd_input_capacity_estimation": [], # TPD 输入容量估算列表
            "current_rpd_today": 0, # 今日当前总 RPD
            "current_tpd_input_today": 0, # 今日当前总 TPD 输入
            "estimated_rpd_today": "N/A", # 今日预估总 RPD
            "estimated_tpd_input_today": "N/A", # 今日预估总 TPD 输入
            "estimation_fraction_of_day": 0, # 今天已过去的时间比例
            "historical_average_usage": { # 历史平均使用情况
                "avg_daily_rpd": "N/A (无历史数据)", # 平均每日 RPD
                "days_included": 0 # 统计包含的天数
            }
        },
        "key_usage_summary": { # Key 使用情况摘要
            "models": [] # 按模型分类的摘要列表
        },
        "key_suggestion": "正在加载建议...", # Key 数量建议 (默认值)
        "top_ips": { # Top IP 统计
            "requests": { # 按请求数统计
                "today": [], "week": [], "month": []
            },
            "tokens": { # 按输入 Token 数统计
                "today": [], "week": [], "month": []
            }
        },
        "key_selection_stats": {}, # Key 选择原因统计
        "cache_stats": { # 缓存使用情况统计
            "hit_count": 0, # 命中次数
            "miss_count": 0, # 未命中次数
            "total_tokens_saved": 0, # 总节省 Token 数
            "hit_rate": "N/A" # 命中率
        },
        "timestamp": datetime.now(timezone.utc).isoformat() # 报告生成时间戳 (UTC ISO 格式)
    }

    # --- 获取并填充缓存使用情况统计 ---
    with cache_tracking_lock: # 获取缓存跟踪锁
        hit_count = cache_hit_count # 获取命中次数
        miss_count = cache_miss_count # 获取未命中次数
        tokens_saved = total_tokens_saved # 获取节省的 Token 数
        # 防御性检查，确保 report_data["cache_stats"] 是字典
        if "cache_stats" not in report_data or not isinstance(report_data["cache_stats"], dict):
            report_data["cache_stats"] = {}
        # 填充数据
        report_data["cache_stats"]["hit_count"] = hit_count
        report_data["cache_stats"]["miss_count"] = miss_count
        report_data["cache_stats"]["total_tokens_saved"] = tokens_saved
        # 计算缓存命中率
        total_cache_lookups = hit_count + miss_count # 总查找次数
        if total_cache_lookups > 0: # 避免除零错误
            hit_rate = hit_count / total_cache_lookups # 计算命中率
            report_data["cache_stats"]["hit_rate"] = f"{hit_rate:.1%}" # 格式化为百分比字符串
        else: # 如果没有缓存查找
            report_data["cache_stats"]["hit_rate"] = "N/A (无缓存查找)" # 设置为 N/A


    # --- Key 筛选原因统计 ---
    selection_reason_counts = Counter() # 初始化原因计数器
    key_reason_counts = defaultdict(Counter) # 初始化按 Key 分组的原因计数器

    # 获取并清空 KeyManager 中的筛选记录 (确保每次报告都是新的统计周期)
    key_selection_records = key_manager.get_and_clear_all_selection_records()

    # 遍历记录并统计
    for record in key_selection_records:
        # 获取 Key (可能已截断) 和原因
        key = record.get('key', '未知 Key') # 使用 get 提供默认值
        reason = record.get('reason', '未知原因') # 使用 get 提供默认值
        selection_reason_counts[reason] += 1 # 增加总原因计数
        key_reason_counts[key][reason] += 1 # 增加特定 Key 的原因计数

    # 将统计结果添加到报告数据中
    # 防御性检查
    if "key_selection_stats" not in report_data or not isinstance(report_data["key_selection_stats"], dict):
        report_data["key_selection_stats"] = {}
    # 存储按原因统计的总次数
    report_data["key_selection_stats"]["total_by_reason"] = dict(selection_reason_counts)
    # 存储按 Key 分组的详细原因统计 (将内部 Counter 转换为字典)
    report_data["key_selection_stats"]["details_by_key"] = {
        key: dict(reasons) for key, reasons in key_reason_counts.items()
    }

    # --- 初始化用于聚合的字典 ---
    key_status_summary = defaultdict(lambda: defaultdict(int)) # 按模型和状态字符串汇总 Key 数量
    model_total_rpd = defaultdict(int) # 按模型汇总今日总 RPD
    model_total_tpd_input = defaultdict(int) # 按模型汇总今日总 TPD 输入


    # --- 定义 ANSI 转义码用于彩色输出 (可选，主要用于日志) ---
    COLOR_TITLE = "\033[1;94m"  # 亮蓝色
    COLOR_SEPARATOR = "\033[0;90m" # 亮黑色/深灰色
    COLOR_SECTION_HEADER = "\033[1;96m" # 亮青色
    COLOR_POSITIVE = "\033[1;92m" # 亮绿色
    COLOR_WARNING = "\033[1;93m" # 亮黄色
    COLOR_ERROR = "\033[1;91m" # 亮红色
    COLOR_INFO = "\033[0;37m" # 白色
    COLOR_RESET = "\033[0m"    # 重置颜色

    # --- 构建报告文本行 (用于日志输出) ---
    report_lines = [f"{COLOR_TITLE}--- API 使用情况报告 ({today_pt.strftime('%Y-%m-%d %H:%M:%S %Z')}) ---{COLOR_RESET}"] # 报告标题
    separator = f"{COLOR_SEPARATOR}{'=' * 60}{COLOR_RESET}" # 定义分隔符

    # --- Key 使用情况聚合 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} Key 使用情况聚合 {COLOR_RESET}\n{separator}") # 添加章节标题

    # 防御性检查报告数据结构
    if "key_usage_summary" not in report_data or not isinstance(report_data["key_usage_summary"], dict):
        report_data["key_usage_summary"] = {"models": []}
    if "models" not in report_data["key_usage_summary"] or not isinstance(report_data["key_usage_summary"]["models"], list):
        report_data["key_usage_summary"]["models"] = []

    # 处理 usage_data_copy 中的数据
    if not usage_data_copy: # 如果没有使用数据
        report_lines.append(f"  {COLOR_WARNING}暂无 Key 使用数据。{COLOR_RESET}")
        report_data["key_usage_summary"]["models"] = [] # 确保 models 列表为空
    else:
        # 遍历每个 Key 的使用数据
        for key, models_usage in usage_data_copy.items():
            if not models_usage: continue # 跳过没有使用数据的 Key
            # 遍历该 Key 使用的每个模型
            for model_name, usage in models_usage.items():
                limits = config.MODEL_LIMITS.get(model_name) # 获取该模型的限制配置
                if not limits: continue # 如果没有限制配置，跳过该模型

                # 获取各种限制值和当前计数值
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

                # 累加模型的总 RPD 和 TPD 输入
                model_total_rpd[model_name] += rpd_count
                model_total_tpd_input[model_name] += tpd_input_count

                # --- 计算 RPM 和 TPM 的窗口内使用情况和剩余百分比 ---
                rpm_in_window = 0 # 初始化窗口内 RPM
                rpm_remaining_pct = 1.0 # 初始化 RPM 剩余百分比
                if rpm_limit is not None: # 如果有 RPM 限制
                    if now - rpm_ts < RPM_WINDOW_SECONDS: # 如果在窗口期内
                        rpm_in_window = rpm_count # 获取窗口内计数
                        # 计算剩余百分比，避免除零错误
                        rpm_remaining_pct = max(0, (rpm_limit - rpm_in_window) / rpm_limit) if rpm_limit > 0 else 0

                tpm_input_in_window = 0 # 初始化窗口内 TPM 输入
                tpm_input_remaining_pct = 1.0 # 初始化 TPM 输入剩余百分比
                if tpm_input_limit is not None: # 如果有 TPM 输入限制
                    if now - tpm_input_ts < TPM_WINDOW_SECONDS: # 如果在窗口期内
                        tpm_input_in_window = tpm_input_count # 获取窗口内计数
                        # 计算剩余百分比，避免除零错误
                        tpm_input_remaining_pct = max(0, (tpm_input_limit - tpm_input_in_window) / tpm_input_limit) if tpm_input_limit > 0 else 0

                # --- 计算 RPD 和 TPD 输入的剩余百分比 ---
                rpd_remaining_pct = max(0, (rpd_limit - rpd_count) / rpd_limit) if rpd_limit is not None and rpd_limit > 0 else 1.0
                tpd_input_remaining_pct = max(0, (tpd_input_limit - tpd_input_count) / tpd_input_limit) if tpd_input_limit is not None and tpd_input_limit > 0 else 1.0

                # 获取 Key 对该模型的分数 (如果存在)
                score = key_scores_cache_copy.get(key, {}).get(model_name, -1.0) # 默认 -1.0 表示无分数

                # --- 构建 Key 状态描述字符串 ---
                status_parts = [
                    f"RPD={rpd_count}/{rpd_limit or 'N/A'} ({rpd_remaining_pct:.0%})", # RPD 状态
                    f"RPM={rpm_in_window}/{rpm_limit or 'N/A'} ({rpm_remaining_pct:.0%})", # RPM 状态
                    f"TPD_In={tpd_input_count:,}/{tpd_input_limit or 'N/A'} ({tpd_input_remaining_pct:.0%})", # TPD 输入状态
                    f"TPM_In={tpm_input_in_window:,}/{tpm_input_limit or 'N/A'} ({tpm_input_remaining_pct:.0%})", # TPM 输入状态
                    f"Score={score:.2f}" # Key 分数
                ]
                status_str = " | ".join(status_parts) # 使用 | 分隔
                # 按模型和状态字符串汇总 Key 的数量
                key_status_summary[model_name][status_str] += 1

        # --- 生成 Key 使用情况摘要报告 ---
        if not key_status_summary: # 如果处理后仍然没有状态摘要
             report_lines.append(f"  {COLOR_WARNING}暂无 Key 使用数据。{COLOR_RESET}")
             report_data["key_usage_summary"]["models"] = [] # 确保 models 列表为空
        else:
            # 确保 models 列表已初始化
            report_data["key_usage_summary"]["models"] = []
            # 按模型名称排序遍历
            for model_name, statuses in sorted(key_status_summary.items()):
                total_keys_for_model = sum(statuses.values()) # 计算该模型的 Key 总数
                # 构建该模型的摘要数据
                model_summary = {
                    "model_name": model_name,
                    "total_rpd_today": model_total_rpd[model_name],
                    "total_tpd_input_today": model_total_tpd_input[model_name],
                    "key_count": total_keys_for_model,
                    "status_distribution": [] # 初始化状态分布列表
                }
                # 添加模型标题到报告文本行
                report_lines.append(f"\n  {COLOR_POSITIVE}{model_name}{COLOR_RESET} (今日总 RPD: {model_total_rpd[model_name]:,}, 今日总 TPD 输入: {model_total_tpd_input[model_name]:,}, Key 数量: {total_keys_for_model})")
                # 按 Key 数量降序遍历该模型下的状态
                for status, count in sorted(statuses.items(), key=lambda item: item[1], reverse=True):
                    # 添加状态详情到报告文本行
                    report_lines.append(f"    - {count} Key(s): {status}")
                    # 添加状态分布到模型摘要数据
                    model_summary["status_distribution"].append({
                        "count": count,
                        "status": status
                    })
                # 将该模型的摘要数据添加到报告总数据中
                report_data["key_usage_summary"]["models"].append(model_summary)


    # --- 总体统计与预测 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} 总体统计与预测 {COLOR_RESET}\n{separator}") # 添加章节标题
    # 防御性检查报告数据结构
    if "overall_stats" not in report_data or not isinstance(report_data["overall_stats"], dict):
        report_data["overall_stats"] = {}
    if "rpd_capacity_estimation" not in report_data["overall_stats"] or not isinstance(report_data["overall_stats"]["rpd_capacity_estimation"], list):
        report_data["overall_stats"]["rpd_capacity_estimation"] = []
    if "tpd_input_capacity_estimation" not in report_data["overall_stats"] or not isinstance(report_data["overall_stats"]["tpd_input_capacity_estimation"], list):
        report_data["overall_stats"]["tpd_input_capacity_estimation"] = []
    if "historical_average_usage" not in report_data["overall_stats"] or not isinstance(report_data["overall_stats"]["historical_average_usage"], dict):
        report_data["overall_stats"]["historical_average_usage"] = {"avg_daily_rpd": "N/A (无历史数据)", "days_included": 0}

    # --- RPD 容量估算 ---
    rpd_groups = defaultdict(list) # 按 RPD 限制对模型进行分组
    model_rpd_usage_count = defaultdict(int) # 统计每个模型被多少个 Key 使用过
    # 遍历模型限制配置
    for model, limits in config.MODEL_LIMITS.items():
        if limits and limits.get("rpd") is not None: # 如果模型有 RPD 限制
            rpd_groups[limits["rpd"]].append(model) # 按 RPD 限制值分组
    # 统计每个模型的使用 Key 数量
    for key, models_usage in usage_data_copy.items():
        for model_name in models_usage:
             if model_name in config.MODEL_LIMITS:
                  model_rpd_usage_count[model_name] += 1

    # 定义需要重点估算容量的目标模型列表
    target_models = [
        "gemini-1.5-pro-latest", # 修正为实际存在的模型或配置中的模型
        "gemini-1.5-flash-latest",
        "gemini-pro" # 假设这是另一个常用模型
    ]

    # 计算并报告目标模型的 RPD 容量
    reported_rpd_limits = set() # 用于记录已报告过的 RPD 限制值，避免重复报告
    target_rpd_capacity_total = 0 # 初始化目标模型的理论总 RPD 容量
    report_lines.append(f"\n  {COLOR_INFO}RPD 容量估算 (基于 {active_keys_count} 个活跃 Key):{COLOR_RESET}") # 添加子标题
    # 遍历目标模型
    for target_model in target_models:
        target_model_limits = config.MODEL_LIMITS.get(target_model, {}) # 获取目标模型的限制
        target_model_rpd_limit = target_model_limits.get("rpd") # 获取 RPD 限制值
        if target_model_rpd_limit is not None: # 如果存在 RPD 限制
            # 计算理论总容量 = 活动 Key 数 * 单 Key RPD 限制
            target_rpd_capacity = active_keys_count * target_model_rpd_limit
            # 添加到报告文本行
            report_lines.append(f"    - 基于 {COLOR_POSITIVE}{target_model}{COLOR_RESET} (RPD={target_model_rpd_limit}): {COLOR_POSITIVE}{target_rpd_capacity:,}{COLOR_RESET} 请求/天")
            # 添加到报告数据字典
            report_data["overall_stats"]["rpd_capacity_estimation"].append({
                "based_on": target_model,
                "limit": target_model_rpd_limit,
                "capacity": target_rpd_capacity
            })
            target_rpd_capacity_total += target_rpd_capacity # 累加总容量
            reported_rpd_limits.add(target_model_rpd_limit) # 标记此限制值已报告
        else: # 如果目标模型没有 RPD 限制
            logger.debug(f"目标模型 {target_model} 或其 RPD 限制未在 model_limits.json 中找到，无法估算 RPD 容量。") # 记录警告改为 debug
            report_lines.append(f"    - 基于 {COLOR_WARNING}{target_model}{COLOR_RESET}: {COLOR_WARNING}RPD 限制未定义{COLOR_RESET}") # 添加到报告文本行
            report_data["overall_stats"]["rpd_capacity_estimation"].append({
                "based_on": target_model,
                "message": "RPD 限制未定义。"
            })

    # 报告其他 RPD 限制组的容量 (排除已在目标模型中报告过的限制值)
    for rpd_limit, models in sorted(rpd_groups.items()): # 按 RPD 限制值排序遍历
        if rpd_limit not in reported_rpd_limits: # 如果此限制值未被报告过
             group_capacity = active_keys_count * rpd_limit # 计算该组的总容量
             # 找出该组中实际被使用过的模型
             used_models_in_group = [m for m in models if model_rpd_usage_count.get(m, 0) > 0]
             if used_models_in_group: # 如果该组有模型被使用过
                  # 添加到报告文本行
                  report_lines.append(f"    - 基于 {COLOR_POSITIVE}{', '.join(used_models_in_group)}{COLOR_RESET} (RPD={rpd_limit}): {COLOR_POSITIVE}{group_capacity:,}{COLOR_RESET} 请求/天")
                  # 添加到报告数据字典
                  report_data["overall_stats"]["rpd_capacity_estimation"].append({
                      "based_on": ', '.join(used_models_in_group),
                      "limit": rpd_limit,
                      "capacity": group_capacity
                  })

    # --- TPD 输入容量估算 ---
    target_tpd_input_capacity_total = 0 # 初始化目标模型的理论总 TPD 输入容量
    report_lines.append(f"\n  {COLOR_INFO}TPD 输入容量估算 (基于 {active_keys_count} 个活跃 Key):{COLOR_RESET}") # 添加子标题
    # 遍历目标模型
    for target_model in target_models:
        target_model_limits = config.MODEL_LIMITS.get(target_model, {}) # 获取目标模型的限制
        target_model_tpd_input_limit = target_model_limits.get("tpd_input") # 获取 TPD 输入限制值
        if target_model_tpd_input_limit is not None: # 如果存在 TPD 输入限制
            # 计算理论总容量 = 活动 Key 数 * 单 Key TPD 输入限制
            target_tpd_input_capacity = active_keys_count * target_model_tpd_input_limit
            # 添加到报告文本行
            report_lines.append(f"    - 基于 {COLOR_POSITIVE}{target_model}{COLOR_RESET} (TPD_In={target_model_tpd_input_limit:,}): {COLOR_POSITIVE}{target_tpd_input_capacity:,}{COLOR_RESET} Token/天")
            # 添加到报告数据字典
            report_data["overall_stats"]["tpd_input_capacity_estimation"].append({
                "based_on": target_model,
                "limit": target_model_tpd_input_limit,
                "capacity": target_tpd_input_capacity
            })
            target_tpd_input_capacity_total += target_tpd_input_capacity # 累加总容量
        else: # 如果目标模型没有 TPD 输入限制
            report_lines.append(f"    - 基于 {COLOR_WARNING}{target_model}{COLOR_RESET}: {COLOR_WARNING}TPD 输入限制未定义{COLOR_RESET}") # 添加到报告文本行
            report_data["overall_stats"]["tpd_input_capacity_estimation"].append({
                "based_on": target_model,
                "message": "TPD 输入限制未定义。"
            })

    # --- 今日用量与全天预估 ---
    current_total_rpd = sum(model_total_rpd.values()) # 计算今日所有模型的总 RPD
    current_total_tpd_input = sum(model_total_tpd_input.values()) # 计算今日所有模型的总 TPD 输入
    # 更新报告数据
    report_data["overall_stats"]["current_rpd_today"] = current_total_rpd
    report_data["overall_stats"]["current_tpd_input_today"] = current_total_tpd_input
    # 添加到报告文本行
    report_lines.append(f"\n  {COLOR_INFO}今日 ({today_date_str}) 已用量:{COLOR_RESET}")
    report_lines.append(f"    - 总 RPD: {COLOR_POSITIVE}{current_total_rpd:,}{COLOR_RESET}")
    report_lines.append(f"    - 总 TPD 输入: {COLOR_POSITIVE}{current_total_tpd_input:,}{COLOR_RESET}")

    # 计算今天已经过去的时间占全天的比例 (太平洋时区)
    seconds_since_pt_midnight = (today_pt - today_pt.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    fraction_of_day_passed = seconds_since_pt_midnight / (24 * 3600) if seconds_since_pt_midnight > 0 else 0
    estimated_total_rpd_today = 0 # 初始化预估 RPD
    estimated_total_tpd_input_today = 0 # 初始化预估 TPD 输入

    report_lines.append(f"\n  {COLOR_INFO}今日 ({today_date_str}) 预估全天用量 (基于已过去 {fraction_of_day_passed:.1%}):{COLOR_RESET}") # 添加子标题
    # 只有当一天过去超过 1% 时才进行估算，避免早期估算误差过大
    if fraction_of_day_passed > 0.01:
        # 估算全天用量 = 当前用量 / 已过去时间比例
        estimated_total_rpd_today = int(current_total_rpd / fraction_of_day_passed)
        estimated_total_tpd_input_today = int(current_total_tpd_input / fraction_of_day_passed)
        # 更新报告数据
        report_data["overall_stats"]["estimated_rpd_today"] = estimated_total_rpd_today
        report_data["overall_stats"]["estimation_fraction_of_day"] = round(fraction_of_day_passed, 3)
        # 添加到报告文本行
        report_lines.append(f"    - 预估总 RPD: {COLOR_POSITIVE}{estimated_total_rpd_today:,}{COLOR_RESET}")
        # 对 TPD 输入估算设置更高的时间阈值 (例如 10%)，因为 Token 量波动可能更大
        if fraction_of_day_passed > 0.1:
            report_data["overall_stats"]["estimated_tpd_input_today"] = estimated_total_tpd_input_today
            report_lines.append(f"    - 预估总 TPD 输入: {COLOR_POSITIVE}{estimated_total_tpd_input_today:,}{COLOR_RESET}")
        else: # 时间过早，不显示 TPD 估算
            report_data["overall_stats"]["estimated_tpd_input_today"] = "N/A (时间过早)"
            report_lines.append(f"    - 预估总 TPD 输入: {COLOR_WARNING}N/A (时间过早，估算不准确){COLOR_RESET}")
    else: # 时间过早，不进行估算
         report_data["overall_stats"]["estimated_rpd_today"] = "N/A (时间过早)"
         report_data["overall_stats"]["estimated_tpd_input_today"] = "N/A (时间过早)"
         report_data["overall_stats"]["estimation_fraction_of_day"] = 0
         report_lines.append(f"    - 预估总 RPD: {COLOR_WARNING}N/A (时间过早，估算不准确){COLOR_RESET}")
         report_lines.append(f"    - 预估总 TPD 输入: {COLOR_WARNING}N/A (时间过早，估算不准确){COLOR_RESET}")

    # --- 历史平均 RPD 计算 ---
    N = 7 # 定义统计过去 N 天
    last_n_days_rpd = [] # 存储过去 N 天的 RPD 数据
    # 循环获取过去 N 天的 RPD 总计
    for i in range(1, N + 1):
        day_str_loop = (today_date - timedelta(days=i)).strftime('%Y-%m-%d') # 计算日期字符串
        rpd = daily_rpd_totals_copy.get(day_str_loop) # 从复制的数据中获取 RPD
        if rpd is not None: # 如果当天有数据
            last_n_days_rpd.append(rpd) # 添加到列表

    avg_daily_rpd = 0 # 初始化平均 RPD
    if last_n_days_rpd: # 如果有历史数据
        avg_daily_rpd = sum(last_n_days_rpd) / len(last_n_days_rpd) # 计算平均值
        # 更新报告数据
        report_data["overall_stats"]["historical_average_usage"]["avg_daily_rpd"] = round(avg_daily_rpd, 0)
        report_data["overall_stats"]["historical_average_usage"]["days_included"] = len(last_n_days_rpd)
        # 添加到报告文本行
        report_lines.append(f"\n  {COLOR_INFO}过去 {len(last_n_days_rpd)} 天平均每日 RPD: {COLOR_POSITIVE}{avg_daily_rpd:,.0f}{COLOR_RESET}")
    else: # 如果没有历史数据
        # 保持报告数据中的默认值
        report_data["overall_stats"]["historical_average_usage"]["avg_daily_rpd"] = "N/A (无历史数据)"
        report_data["overall_stats"]["historical_average_usage"]["days_included"] = 0
        # 添加到报告文本行
        report_lines.append(f"\n  {COLOR_INFO}过去 {N} 天平均每日 RPD: {COLOR_WARNING}N/A (无历史数据){COLOR_RESET}")


    # --- Key 数量建议 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} Key 数量建议 {COLOR_RESET}\n{separator}") # 添加章节标题
    suggestion = f"保持当前 Key 数量 ({active_keys_count} 个)。" # 初始化默认建议
    suggestion_color = COLOR_POSITIVE # 初始化默认颜色

    # --- 计算使用率指标 ---
    # 使用 RPD 指标：取今日预估 RPD 和历史平均 RPD 中的较大值
    rpd_usage_indicator = max(estimated_total_rpd_today if isinstance(estimated_total_rpd_today, (int, float)) else 0, avg_daily_rpd if isinstance(avg_daily_rpd, (int, float)) else 0)
    # 使用 TPD 输入指标：取今日预估 TPD 输入
    tpd_input_usage_indicator = estimated_total_tpd_input_today if isinstance(estimated_total_tpd_input_today, (int, float)) else 0

    # 计算 RPD 使用率 (相对于目标模型的总容量)
    rpd_usage_ratio = 0
    if target_rpd_capacity_total > 0: # 避免除零错误
        rpd_usage_ratio = rpd_usage_indicator / target_rpd_capacity_total

    # 计算 TPD 输入使用率 (相对于目标模型的总容量)
    tpd_input_usage_ratio = 0
    if target_tpd_input_capacity_total > 0: # 避免除零错误
        tpd_input_usage_ratio = tpd_input_usage_indicator / target_tpd_input_capacity_total

    # 获取第一个目标模型的限制，用于估算所需 Key 数量
    first_target_model_rpd_limit = 0
    first_target_model_tpd_input_limit = 0
    for target_model in target_models:
        target_model_limits = config.MODEL_LIMITS.get(target_model, {})
        if target_model_limits:
            first_target_model_rpd_limit = target_model_limits.get("rpd", 0)
            first_target_model_tpd_input_limit = target_model_limits.get("tpd_input", 0)
            break # 找到第一个目标模型的限制后即退出

    # --- 生成建议逻辑 ---
    suggested_key_count = active_keys_count # 默认建议保持当前数量

    # 定义使用率阈值
    RPD_HIGH_USAGE_THRESHOLD = 0.8 # RPD 高使用率阈值
    TPD_INPUT_HIGH_USAGE_THRESHOLD = 0.8 # TPD 输入高使用率阈值
    RPD_CRITICAL_USAGE_THRESHOLD = 0.95 # RPD 关键使用率阈值
    TPD_INPUT_CRITICAL_USAGE_THRESHOLD = 0.95 # TPD 输入关键使用率阈值
    RPD_LOW_USAGE_THRESHOLD = 0.3 # RPD 低使用率阈值
    TPD_INPUT_LOW_USAGE_THRESHOLD = 0.3 # TPD 输入低使用率阈值

    # 检查是否需要增加 Key (关键阈值)
    if rpd_usage_ratio > RPD_CRITICAL_USAGE_THRESHOLD or tpd_input_usage_ratio > TPD_INPUT_CRITICAL_USAGE_THRESHOLD:
        # 估算满足当前用量 + 20% 缓冲所需的 Key 数量
        needed_keys_rpd = (rpd_usage_indicator / first_target_model_rpd_limit) * 1.2 if first_target_model_rpd_limit > 0 else active_keys_count * 2 # 如果限制为0，则建议翻倍
        needed_keys_tpd_input = (tpd_input_usage_indicator / first_target_model_tpd_input_limit) * 1.2 if first_target_model_tpd_input_limit > 0 else active_keys_count * 2
        # 取两者所需的最大值，并确保至少增加 1 个
        suggested_key_count = max(active_keys_count + 1, int(max(needed_keys_rpd, needed_keys_tpd_input)))
        suggestion = f"用量接近或达到上限 ({rpd_usage_ratio:.1%} RPD 或 {tpd_input_usage_ratio:.1%} TPD_In)，强烈建议增加 Key 数量至 {suggested_key_count} 个，以确保服务稳定性！"
        suggestion_color = COLOR_ERROR # 使用错误颜色表示紧急
    # 检查是否需要增加 Key (高阈值)
    elif rpd_usage_ratio > RPD_HIGH_USAGE_THRESHOLD or tpd_input_usage_ratio > TPD_INPUT_HIGH_USAGE_THRESHOLD:
        # 建议适度增加 Key (例如增加 20%，且至少增加 1 个)
        suggested_key_count = max(active_keys_count + 1, int(active_keys_count * 1.2))
        suggestion = f"用量较高 ({rpd_usage_ratio:.1%} RPD 或 {tpd_input_usage_ratio:.1%} TPD_In)，建议增加 Key 数量至 {suggested_key_count} 个，提前应对潜在的用量增长。"
        suggestion_color = COLOR_WARNING # 使用警告颜色
    # 检查是否可以减少 Key (低阈值，且当前 Key 数大于启动时的数量)
    elif rpd_usage_ratio < RPD_LOW_USAGE_THRESHOLD and tpd_input_usage_ratio < TPD_INPUT_LOW_USAGE_THRESHOLD and active_keys_count > INITIAL_KEY_COUNT:
        # 建议减少 Key (例如减少 20%，但不少于启动时的数量)
        suggested_key_count = max(INITIAL_KEY_COUNT, int(active_keys_count * 0.8))
        suggestion = f"用量较低 ({rpd_usage_ratio:.1%} RPD 且 {tpd_input_usage_ratio:.1%} TPD_In)，可以考虑减少 Key 数量至 {suggested_key_count} 个，以优化成本。"
        suggestion_color = COLOR_INFO # 使用信息颜色表示非紧急建议
    else: # 其他情况，保持默认建议
        suggestion = f"当前用量 ({rpd_usage_ratio:.1%} RPD, {tpd_input_usage_ratio:.1%} TPD_In) 在合理范围，建议保持当前 Key 数量 ({active_keys_count} 个)。"
        suggestion_color = COLOR_POSITIVE

    # 更新报告数据并添加到报告文本行
    report_data["key_suggestion"] = suggestion
    report_lines.append(f"  {suggestion_color}{suggestion}{COLOR_RESET}")

    # --- Top IP 统计 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} Top IP 统计 {COLOR_RESET}\n{separator}") # 添加章节标题
    # 防御性检查报告数据结构
    if "top_ips" not in report_data or not isinstance(report_data["top_ips"], dict):
        report_data["top_ips"] = {"requests": {"today": [], "week": [], "month": []}, "tokens": {"today": [], "week": [], "month": []}}

    # --- Top 请求 IP ---
    report_lines.append(f"\n  {COLOR_INFO}Top 请求 IP:{COLOR_RESET}") # 添加子标题
    # 今日 Top IP (请求数)
    top_ips_today_req = get_top_ips(ip_counts_copy, today_date, today_date)
    report_data["top_ips"]["requests"]["today"] = format_top_ips(top_ips_today_req, 'count') # 格式化并存入报告数据
    report_lines.append(f"    - 今日 ({today_date_str}): {top_ips_today_req if top_ips_today_req else 'N/A'}") # 添加到报告文本行
    # 本周 Top IP (请求数)
    top_ips_week_req = get_top_ips(ip_counts_copy, start_of_week_pt, today_date)
    report_data["top_ips"]["requests"]["week"] = format_top_ips(top_ips_week_req, 'count')
    report_lines.append(f"    - 本周 ({start_of_week_pt.strftime('%Y-%m-%d')} - {today_date_str}): {top_ips_week_req if top_ips_week_req else 'N/A'}")
    # 本月 Top IP (请求数)
    top_ips_month_req = get_top_ips(ip_counts_copy, start_of_month_pt, today_date)
    report_data["top_ips"]["requests"]["month"] = format_top_ips(top_ips_month_req, 'count')
    report_lines.append(f"    - 本月 ({start_of_month_pt.strftime('%Y-%m-%d')} - {today_date_str}): {top_ips_month_req if top_ips_month_req else 'N/A'}")

    # --- Top Token IP (输入) ---
    report_lines.append(f"\n  {COLOR_INFO}Top Token IP (输入):{COLOR_RESET}") # 添加子标题
    # 今日 Top IP (Token 数)
    top_ips_today_token = get_top_ips(ip_input_token_counts_copy, today_date, today_date)
    report_data["top_ips"]["tokens"]["today"] = format_top_ips(top_ips_today_token, 'tokens')
    report_lines.append(f"    - 今日 ({today_date_str}): {top_ips_today_token if top_ips_today_token else 'N/A'}")
    # 本周 Top IP (Token 数)
    top_ips_week_token = get_top_ips(ip_input_token_counts_copy, start_of_week_pt, today_date)
    report_data["top_ips"]["tokens"]["week"] = format_top_ips(top_ips_week_token, 'tokens')
    report_lines.append(f"    - 本周 ({start_of_week_pt.strftime('%Y-%m-%d')} - {today_date_str}): {top_ips_week_token if top_ips_week_token else 'N/A'}")
    # 本月 Top IP (Token 数)
    top_ips_month_token = get_top_ips(ip_input_token_counts_copy, start_of_month_pt, today_date)
    report_data["top_ips"]["tokens"]["month"] = format_top_ips(top_ips_month_token, 'tokens')
    report_lines.append(f"    - 本月 ({start_of_month_pt.strftime('%Y-%m-%d')} - {today_date_str}): {top_ips_month_token if top_ips_month_token else 'N/A'}")


    # --- Key 筛选原因统计报告 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} Key 筛选原因统计 {COLOR_RESET}\n{separator}") # 添加章节标题
    if selection_reason_counts: # 如果有筛选记录
        report_lines.append(f"\n  {COLOR_INFO}总计 (按原因):{COLOR_RESET}") # 添加子标题
        # 按次数降序遍历原因统计
        for reason, count in sorted(selection_reason_counts.items(), key=lambda item: item[1], reverse=True):
            report_lines.append(f"    - {reason}: {count} 次") # 添加到报告文本行

        report_lines.append(f"\n  {COLOR_INFO}详情 (按 Key 和原因):{COLOR_RESET}") # 添加子标题
        # 按 Key 排序遍历详细统计
        for key, reasons in sorted(key_reason_counts.items()):
            report_lines.append(f"    - Key '{key}':") # 添加 Key 标题
            # 按次数降序遍历该 Key 的原因
            for reason, count in sorted(reasons.items(), key=lambda item: item[1], reverse=True):
                report_lines.append(f"      - {reason}: {count} 次") # 添加原因详情
    else: # 如果没有筛选记录
        report_lines.append(f"  {COLOR_WARNING}暂无 Key 筛选记录。{COLOR_RESET}") # 添加提示信息


    # --- 缓存使用情况报告 ---
    report_lines.append(f"\n{separator}\n{COLOR_SECTION_HEADER} 缓存使用情况 {COLOR_RESET}\n{separator}") # 添加章节标题
    # 添加缓存统计信息到报告文本行
    report_lines.append(f"  {COLOR_INFO}缓存命中次数: {COLOR_POSITIVE}{report_data['cache_stats']['hit_count']:,}{COLOR_RESET}")
    report_lines.append(f"  {COLOR_INFO}缓存未命中次数: {COLOR_WARNING}{report_data['cache_stats']['miss_count']:,}{COLOR_RESET}")
    report_lines.append(f"  {COLOR_INFO}总共节省 Token 数: {COLOR_POSITIVE}{report_data['cache_stats']['total_tokens_saved']:,}{COLOR_RESET}")
    report_lines.append(f"  {COLOR_INFO}缓存命中率: {COLOR_POSITIVE}{report_data['cache_stats']['hit_rate']}{COLOR_RESET}")


    # --- 报告生成时间戳 ---
    report_lines.append(f"\n{separator}\n{COLOR_INFO} 报告生成时间: {report_data['timestamp']}{COLOR_RESET}\n{separator}") # 添加时间戳和分隔符

    # --- (可选) 打印或保存报告 ---
    # 将报告数据转换为格式化的 JSON 字符串 (用于调试或传输)
    # report_json_data = json.dumps(report_data, indent=4, ensure_ascii=False)
    # 打印文本报告到日志
    logger.info("周期性使用情况报告:\n" + "\n".join(report_lines)) # 取消注释以打印文本报告
    # 打印 JSON 报告到日志 (DEBUG 级别)
    # logger.debug("周期性使用情况报告 (JSON):\n" + report_json_data)

    # 返回包含所有报告数据的字典
    return report_data
