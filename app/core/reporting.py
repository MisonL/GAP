# app/core/reporting.py
import time
import json
import logging
import pytz
import copy # 导入 copy 模块
from datetime import datetime, timedelta, date
from collections import Counter, defaultdict
from typing import List, Tuple, Dict, Any, TYPE_CHECKING
from apscheduler.schedulers.background import BackgroundScheduler

# 从其他模块导入必要的组件
# 注意：调整导入路径
from .tracking import ( # 同级目录导入
    usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS,
    daily_rpd_totals, daily_totals_lock,
    key_scores_cache, cache_lock,
    ip_daily_counts, ip_counts_lock,
    ip_daily_input_token_counts, ip_input_token_counts_lock # 使用更新后的变量名
)
from .. import config # 导入 config 模块
from ..config import ( # 上一级目录导入
    USAGE_REPORT_INTERVAL_MINUTES,
    REPORT_LOG_LEVEL_INT,
    # MODEL_LIMITS # 不再直接导入
)
from .key_management import INITIAL_KEY_COUNT # 同级目录导入
from ..handlers.log_config import cleanup_old_logs # 导入日志清理任务

# 条件导入用于类型提示
if TYPE_CHECKING:
    from .utils import APIKeyManager # 同级目录导入

logger = logging.getLogger('my_logger') # 使用相同的日志记录器实例名称

# --- 调度器实例 ---
scheduler = BackgroundScheduler()

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


# --- 周期性报告函数 ---
def report_usage(key_manager: 'APIKeyManager'):
    """周期性地报告聚合的 API 密钥使用情况、总体统计、密钥数量建议以及 Top IP 统计。"""
    logger.info("开始生成周期性使用情况报告...")
    now = time.time()
    pt_timezone = pytz.timezone('America/Los_Angeles')
    today_pt = datetime.now(pt_timezone)
    today_date_str = today_pt.strftime('%Y-%m-%d')
    start_of_week_pt = today_pt - timedelta(days=today_pt.weekday())
    start_of_month_pt = today_pt.replace(day=1)

    # --- 安全地获取数据副本 ---
    with usage_lock:
        usage_data_copy = copy.deepcopy(usage_data)
    with daily_totals_lock:
        daily_rpd_totals_copy = daily_rpd_totals.copy()
    with cache_lock:
        key_scores_cache_copy = copy.deepcopy(key_scores_cache)
    with ip_counts_lock:
        ip_counts_copy = copy.deepcopy(ip_daily_counts)
    with ip_input_token_counts_lock: # 使用更新后的锁名
        ip_input_token_counts_copy = copy.deepcopy(ip_daily_input_token_counts) # 使用更新后的变量名
    with key_manager.keys_lock:
        active_keys = key_manager.api_keys[:]
        active_keys_count = len(active_keys)

    # 使用从 key_management 导入的 INITIAL_KEY_COUNT
    invalid_keys_count = INITIAL_KEY_COUNT - active_keys_count

    report_lines = [f"--- API 使用情况报告 ({today_pt.strftime('%Y-%m-%d %H:%M:%S %Z')}) ---"]
    current_total_rpd = 0
    current_total_tpd_input = 0 # 新增

    # --- Key 使用情况聚合 ---
    report_lines.append("\n[Key 使用情况聚合]")
    key_status_summary = defaultdict(lambda: defaultdict(int))
    model_total_rpd = defaultdict(int)
    model_total_tpd_input = defaultdict(int) # 新增

    if not usage_data_copy:
        report_lines.append("  暂无 Key 使用数据。")
    else:
        for key, models_usage in usage_data_copy.items():
            if not models_usage: continue
            for model_name, usage in models_usage.items():
                limits = config.MODEL_LIMITS.get(model_name) # 通过 config 模块访问
                if not limits: continue

                rpd_limit = limits.get("rpd")
                rpm_limit = limits.get("rpm")
                tpm_input_limit = limits.get("tpm_input") # 使用 tpm_input
                tpd_input_limit = limits.get("tpd_input") # 使用 tpd_input

                rpd_count = usage.get("rpd_count", 0)
                rpm_count = usage.get("rpm_count", 0)
                tpm_input_count = usage.get("tpm_input_count", 0) # 使用 tpm_input
                tpd_input_count = usage.get("tpd_input_count", 0) # 使用 tpd_input
                rpm_ts = usage.get("rpm_timestamp", 0)
                tpm_input_ts = usage.get("tpm_input_timestamp", 0) # 使用 tpm_input

                model_total_rpd[model_name] += rpd_count
                model_total_tpd_input[model_name] += tpd_input_count # 累加 TPD Input

                # RPM
                rpm_in_window = 0
                rpm_remaining_pct = 1.0
                if rpm_limit is not None:
                    if now - rpm_ts < RPM_WINDOW_SECONDS:
                        rpm_in_window = rpm_count
                        rpm_remaining_pct = max(0, (rpm_limit - rpm_in_window) / rpm_limit) if rpm_limit > 0 else 0

                # TPM Input
                tpm_input_in_window = 0
                tpm_input_remaining_pct = 1.0
                if tpm_input_limit is not None:
                    if now - tpm_input_ts < TPM_WINDOW_SECONDS:
                        tpm_input_in_window = tpm_input_count
                        tpm_input_remaining_pct = max(0, (tpm_input_limit - tpm_input_in_window) / tpm_input_limit) if tpm_input_limit > 0 else 0

                # RPD
                rpd_remaining_pct = max(0, (rpd_limit - rpd_count) / rpd_limit) if rpd_limit is not None and rpd_limit > 0 else 1.0

                # TPD Input
                tpd_input_remaining_pct = max(0, (tpd_input_limit - tpd_input_count) / tpd_input_limit) if tpd_input_limit is not None and tpd_input_limit > 0 else 1.0

                score = key_scores_cache_copy.get(key, {}).get(model_name, -1.0)

                # 更新状态字符串以包含新指标
                status_parts = [
                    f"RPD={rpd_count}/{rpd_limit or 'N/A'} ({rpd_remaining_pct:.0%})",
                    f"RPM={rpm_in_window}/{rpm_limit or 'N/A'} ({rpm_remaining_pct:.0%})",
                    f"TPD_In={tpd_input_count:,}/{tpd_input_limit or 'N/A'} ({tpd_input_remaining_pct:.0%})", # TPD 输入
                    f"TPM_In={tpm_input_in_window:,}/{tpm_input_limit or 'N/A'} ({tpm_input_remaining_pct:.0%})", # TPM 输入
                    f"Score={score:.2f}" # 得分
                ]
                status_str = " | ".join(status_parts)
                key_status_summary[model_name][status_str] += 1

        if not key_status_summary:
             report_lines.append("  暂无 Key 使用数据。")
        else:
            for model_name, statuses in sorted(key_status_summary.items()):
                total_keys_for_model = sum(statuses.values())
                # 在模型报告中添加 TPD_Input
                report_lines.append(f"  模型: {model_name} (今日 RPD: {model_total_rpd[model_name]:,}, 今日 TPD_In: {model_total_tpd_input[model_name]:,}, 使用 Keys: {total_keys_for_model})")
                for status, count in sorted(statuses.items(), key=lambda item: item[1], reverse=True):
                    report_lines.append(f"    - 数量: {count}, 状态: {status}")


    # --- 总体统计与预测 ---
    report_lines.append("\n[总体统计与预测]")
    report_lines.append(f"  活跃 Key 数量: {active_keys_count}")
    report_lines.append(f"  启动时无效 Key 数量: {invalid_keys_count}")

    # RPD 容量
    report_lines.append("  RPD 容量估算:")
    rpd_groups = defaultdict(list)
    model_rpd_usage_count = defaultdict(int)
    for model, limits in config.MODEL_LIMITS.items(): # 通过 config 模块访问
        if limits and limits.get("rpd") is not None:
            rpd_groups[limits["rpd"]].append(model)
    for key, models_usage in usage_data_copy.items():
        for model_name in models_usage:
             if model_name in config.MODEL_LIMITS: # 通过 config 模块访问
                 model_rpd_usage_count[model_name] += 1 # type: ignore

    target_model = "gemini-2.5-pro-exp-03-25" # 考虑使其可配置
    target_model_limits = config.MODEL_LIMITS.get(target_model, {}) # 通过 config 模块访问
    target_model_rpd_limit = target_model_limits.get("rpd")
    target_model_tpd_input_limit = target_model_limits.get("tpd_input") # 获取 TPD 输入限制

    target_rpd_capacity = 0
    if target_model_rpd_limit:
        target_rpd_capacity = active_keys_count * target_model_rpd_limit
        report_lines.append(f"    - 基于 {target_model} (RPD={target_model_rpd_limit}): {target_rpd_capacity:,}/天")
    else:
        logger.warning(f"目标模型 {target_model} 或其 RPD 限制未在 model_limits.json 中找到，无法估算 RPD 容量。")
        report_lines.append(f"    - 基于 {target_model}: RPD 限制未定义。")

    for rpd_limit, models in sorted(rpd_groups.items()):
        if rpd_limit != target_model_rpd_limit:
             group_capacity = active_keys_count * rpd_limit
             used_models_in_group = [m for m in models if model_rpd_usage_count.get(m, 0) > 0]
             if used_models_in_group:
                 model_names_str = ', '.join(used_models_in_group)
                 report_lines.append(f"    - RPD={rpd_limit}: {model_names_str} (估算容量: {group_capacity:,}/天)")

    # TPD 输入容量 (新部分)
    report_lines.append("  TPD 输入容量估算:")
    target_tpd_input_capacity = 0
    if target_model_tpd_input_limit:
        target_tpd_input_capacity = active_keys_count * target_model_tpd_input_limit
        report_lines.append(f"    - 基于 {target_model} (TPD_In={target_model_tpd_input_limit:,}): {target_tpd_input_capacity:,}/天")
    else:
        report_lines.append(f"    - 基于 {target_model}: TPD_Input 限制未定义。")

    # 今日用量与估算
    current_total_rpd = sum(model_total_rpd.values())
    current_total_tpd_input = sum(model_total_tpd_input.values()) # 计算当前 TPD 输入
    report_lines.append(f"  今日已用 RPD (PT): {current_total_rpd:,}")
    report_lines.append(f"  今日已用 TPD 输入 (PT): {current_total_tpd_input:,}") # 报告 TPD 输入

    seconds_since_pt_midnight = (today_pt - today_pt.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    fraction_of_day_passed = seconds_since_pt_midnight / (24 * 3600) if seconds_since_pt_midnight > 0 else 0
    estimated_total_rpd_today = 0
    estimated_total_tpd_input_today = 0 # 新增

    if fraction_of_day_passed > 0.01:
        estimated_total_rpd_today = int(current_total_rpd / fraction_of_day_passed)
        estimated_total_tpd_input_today = int(current_total_tpd_input / fraction_of_day_passed) # 估算 TPD 输入
        report_lines.append(f"  预估今日 RPD (PT): {estimated_total_rpd_today:,} (基于 {fraction_of_day_passed:.1%} 时间)")
        report_lines.append(f"  预估今日 TPD 输入 (PT): {estimated_total_tpd_input_today:,} (基于 {fraction_of_day_passed:.1%} 时间)")
    else:
        report_lines.append(f"  预估今日 RPD (PT): N/A (时间过早)")
        report_lines.append(f"  预估今日 TPD 输入 (PT): N/A (时间过早)")

    # 平均 RPD
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
        report_lines.append(f"  过去 {len(last_n_days_rpd)} 天平均日 RPD (PT): {avg_daily_rpd:,.0f}")
    else:
        report_lines.append(f"  过去 {N} 天平均日 RPD (PT): N/A (无历史数据)")

    # --- Key 数量建议 (调整后逻辑) ---
    report_lines.append("\n[Key 数量建议]")
    suggestion = "保持当前 Key 数量。"
    rpd_usage_indicator = max(estimated_total_rpd_today, avg_daily_rpd)
    tpd_input_usage_indicator = estimated_total_tpd_input_today # 使用预估 TPD 输入

    rpd_usage_ratio = 0
    if target_rpd_capacity > 0:
        rpd_usage_ratio = rpd_usage_indicator / target_rpd_capacity

    tpd_input_usage_ratio = 0
    if target_tpd_input_capacity > 0:
        tpd_input_usage_ratio = tpd_input_usage_indicator / target_tpd_input_capacity

    if active_keys_count == 0:
        suggestion = "错误: 未找到有效的 API Key！"
    elif target_rpd_capacity <= 0: # 如果 RPD 限制未知则无法生成建议
        suggestion = "无法生成建议 (目标模型 RPD 限制未定义)。"
    elif rpd_usage_ratio > 0.85: # 优先考虑 RPD 限制
        needed_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.7))
        suggestion = f"警告: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 已达目标容量 ({target_rpd_capacity:,}) 的 {rpd_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。"
    elif target_tpd_input_capacity > 0 and tpd_input_usage_ratio > 0.85: # 然后检查 TPD 输入
         needed_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.7))
         suggestion = f"警告: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 已达目标容量 ({target_tpd_input_capacity:,}) 的 {tpd_input_usage_ratio:.1%}。建议增加 Key 数量至约 {max(needed_keys, active_keys_count + 1)} 个。"
    elif rpd_usage_ratio < 0.3 and tpd_input_usage_ratio < 0.3 and active_keys_count > 1: # 仅在两者都低时建议减少
        # 根据 RPD 和 TPD_Input 中较高的使用率提出建议
        if rpd_usage_ratio >= tpd_input_usage_ratio and target_model_rpd_limit:
             ideal_keys = int(rpd_usage_indicator / (target_model_rpd_limit * 0.5)) + 1
             suggestion = f"提示: 预估/平均 RPD ({rpd_usage_indicator:,.0f}) 较低 ({rpd_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。"
        elif target_model_tpd_input_limit:
             ideal_keys = int(tpd_input_usage_indicator / (target_model_tpd_input_limit * 0.5)) + 1
             suggestion = f"提示: 预估 TPD 输入 ({tpd_input_usage_indicator:,.0f}) 较低 ({tpd_input_usage_ratio:.1%})。可考虑减少 Key 数量至约 {max(1, ideal_keys)} 个。"
    report_lines.append(f"  {suggestion}")


    # --- Top 5 IP 地址统计 ---
    report_lines.append("\n[Top 5 IP 地址统计 (PT 时间)]")

    def get_top_ips(data_dict: Dict[str, Dict[str, int]], start_date: date, end_date: date, top_n=5) -> List[Tuple[str, int]]:
        """获取指定日期范围内 Top N IP 地址及其计数"""
        aggregated_counts = Counter()
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            if date_str in data_dict:
                for ip, count in data_dict.get(date_str, {}).items():
                    aggregated_counts[ip] += count
            current_date += timedelta(days=1)
        return aggregated_counts.most_common(top_n)

    # 今日 Top 5 请求
    top_ips_today_req = get_top_ips(ip_counts_copy, today_pt.date(), today_pt.date())
    report_lines.append("  今日请求次数 Top 5:")
    if top_ips_today_req:
        for ip, count in top_ips_today_req: report_lines.append(f"    - {ip}: {count}")
    else: report_lines.append("    - 暂无记录")

    # 今日 Top 5 输入 Token
    top_ips_today_input_token = get_top_ips(ip_input_token_counts_copy, today_pt.date(), today_pt.date()) # 使用输入 Token 副本
    report_lines.append("  今日输入 Token Top 5:") # 修改标题
    if top_ips_today_input_token:
        for ip, tokens in top_ips_today_input_token: report_lines.append(f"    - {ip}: {tokens:,}")
    else: report_lines.append("    - 暂无记录")

    # 本周 Top 5 请求
    top_ips_week_req = get_top_ips(ip_counts_copy, start_of_week_pt.date(), today_pt.date())
    report_lines.append("  本周请求次数 Top 5:")
    if top_ips_week_req:
        for ip, count in top_ips_week_req: report_lines.append(f"    - {ip}: {count}")
    else: report_lines.append("    - 暂无记录")

    # 本周 Top 5 输入 Token
    top_ips_week_input_token = get_top_ips(ip_input_token_counts_copy, start_of_week_pt.date(), today_pt.date()) # 使用输入 Token 副本
    report_lines.append("  本周输入 Token Top 5:") # 修改标题
    if top_ips_week_input_token:
        for ip, tokens in top_ips_week_input_token: report_lines.append(f"    - {ip}: {tokens:,}")
    else: report_lines.append("    - 暂无记录")

    # 本月 Top 5 请求
    top_ips_month_req = get_top_ips(ip_counts_copy, start_of_month_pt.date(), today_pt.date())
    report_lines.append("  本月请求次数 Top 5:")
    if top_ips_month_req:
        for ip, count in top_ips_month_req: report_lines.append(f"    - {ip}: {count}")
    else: report_lines.append("    - 暂无记录")

    # 本月 Top 5 输入 Token
    top_ips_month_input_token = get_top_ips(ip_input_token_counts_copy, start_of_month_pt.date(), today_pt.date()) # 使用输入 Token 副本
    report_lines.append("  本月输入 Token Top 5:") # 修改标题
    if top_ips_month_input_token:
        for ip, tokens in top_ips_month_input_token: report_lines.append(f"    - {ip}: {tokens:,}")
    else: report_lines.append("    - 暂无记录")


    report_lines.append("--- 报告结束 ---")
    full_report = "\n".join(report_lines)

    # 使用配置的日志级别记录报告
    logger.log(REPORT_LOG_LEVEL_INT, full_report)


# --- 调度器设置与启动 ---
def setup_scheduler(key_manager: 'APIKeyManager'):
    """将任务添加到调度器。"""
    logger.info("正在设置后台任务...")
    # 日志清理任务
    scheduler.add_job(cleanup_old_logs, 'cron', hour=3, minute=0, args=[30], id='log_cleanup', name='日志清理', replace_existing=True)
    # 每日 RPD/TPD_Input 重置任务 (PT 午夜)
    scheduler.add_job(reset_daily_counts, 'cron', hour=0, minute=0, timezone='America/Los_Angeles', id='daily_reset', name='每日限制重置', replace_existing=True) # 重命名任务
    # 周期性使用报告任务
    scheduler.add_job(report_usage, 'interval', minutes=USAGE_REPORT_INTERVAL_MINUTES, args=[key_manager], id='usage_report', name='使用报告', replace_existing=True) # 重命名任务
    # Key 得分缓存更新任务 (每 10 秒)
    scheduler.add_job(key_manager.update_key_scores_cache, 'interval', seconds=10, args=[config.MODEL_LIMITS], id='key_score_update', name='Key 得分更新', replace_existing=True) # 传递 config.MODEL_LIMITS
    job_names = [job.name for job in scheduler.get_jobs()]
    logger.info(f"后台任务已调度: {', '.join(job_names)}")

def start_scheduler():
    """如果后台调度器尚未运行，则启动它。"""
    try:
        if not scheduler.running:
            scheduler.start()
            logger.info("后台调度器已启动。")
        else:
            logger.info("后台调度器已在运行。")
    except Exception as e:
        logger.error(f"启动后台调度器失败: {e}", exc_info=True)

def shutdown_scheduler():
    """关闭调度器。"""
    if scheduler.running:
        logger.info("正在关闭后台调度器...")
        scheduler.shutdown()
        logger.info("后台调度器已关闭。")