from app.config import REPORT_LOG_LEVEL_INT
# app/core/reporting.py
"""
此模块负责设置和管理后台调度任务，例如日志清理、每日计数重置、
周期性使用情况报告和 Key 分数缓存刷新。
"""
import logging
import asyncio # 导入 asyncio
from typing import TYPE_CHECKING, List, Dict, Any # 导入类型提示
from apscheduler.schedulers.asyncio import AsyncIOScheduler # 导入 AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor # 导入 AsyncIOExecutor

# 从其他模块导入必要的组件
from app import config # 导入 config 模块
from app.config import ( # 上一级目录导入
    USAGE_REPORT_INTERVAL_MINUTES, # 使用情况报告间隔（分钟）
    MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS, # 内存上下文清理间隔（秒）
    CACHE_REFRESH_INTERVAL_SECONDS # 确保导入
)
# 导入上下文存储相关 (清理函数)
from app.core import context_store # 导入整个模块以便调用 async 函数
# 导入数据库工具 (数据库模式)
from app.core.db_utils import IS_MEMORY_DB # 导入是否为内存数据库的标志
# 导入日志清理任务
from app.handlers.log_config import cleanup_old_logs # 导入清理旧日志的函数
# 导入新拆分出的任务函数
from app.core.daily_reset import reset_daily_counts # 导入每日计数重置函数
from app.core.usage_reporter import report_usage # 导入使用情况报告函数
from app.core.key_management import _refresh_all_key_scores # Key 分数刷新函数已移至 key_management

# 条件导入用于类型提示
if TYPE_CHECKING:
    from .key_manager_class import APIKeyManager # 从 key_manager_class 导入 APIKeyManager

logger = logging.getLogger('my_logger')

# 定义 ANSI 转义码以增加颜色和样式
COLOR_TITLE = "\033[1;94m"  # 亮蓝色 (Bright Blue) - 用于主标题
COLOR_SEPARATOR = "\033[0;90m" # 亮黑色/深灰色 (Bright Black/Dark Gray) - 用于分隔符
COLOR_SECTION_HEADER = "\033[1;96m" # 亮青色 (Bright Cyan) - 用于区域标题
COLOR_POSITIVE = "\033[1;92m" # 亮绿色 (Bright Green) - 用于良好状态、数值、模型名
COLOR_WARNING = "\033[1;93m" # 亮黄色 (Bright Yellow) - 用于警告、次要建议
COLOR_ERROR = "\033[1;91m" # 亮红色 (Red) - 用于错误、主要警告、重要建议
COLOR_INFO = "\033[0;37m" # 白色 (White) - 用于普通标签 (可选，或直接用 RESET)
COLOR_RESET = "\033[0m"    # 重置颜色和样式
SEPARATOR_LINE = f"{COLOR_SEPARATOR}{'=' * 60}{COLOR_RESET}" # 定义分隔符行

# --- 调度器实例 ---
scheduler = AsyncIOScheduler(
    executors={
        'default': {'type': 'threadpool', 'max_workers': 20},
        'asyncio': {'type': 'asyncio'} # 添加 asyncio 执行器
    }
) # 创建 BackgroundScheduler 实例并配置执行器

# --- 同步包装器，用于从调度器调用异步函数 ---
def run_cleanup_memory_context(max_age_seconds: int):
    """
    同步包装器，用于运行异步的 cleanup_memory_context。
    """
    logger.debug(f"调度器触发 run_cleanup_memory_context (max_age={max_age_seconds})")
    try:
        # 使用 asyncio.run() 在新/当前事件循环中运行异步函数
        # 注意：如果主应用事件循环复杂，这可能不是最佳实践，
        # 但对于简单的后台任务通常足够。
        # 更好的方法可能是获取正在运行的循环并使用 run_coroutine_threadsafe。
        asyncio.run(context_store.cleanup_memory_context(max_age_seconds))
        logger.debug(f"run_cleanup_memory_context (max_age={max_age_seconds}) 完成")
    except Exception as e:
        logger.error(f"运行 cleanup_memory_context 时出错: {e}", exc_info=True) # Log error during cleanup

# --- 报告格式化辅助函数 ---

def _format_key_usage_summary(models_summary: List[Dict[str, Any]]) -> List[str]:
    """格式化 Key 使用情况聚合部分。"""
    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} Key 使用情况聚合 {COLOR_RESET}\n{SEPARATOR_LINE}"]
    if not models_summary:
        lines.append(f"  {COLOR_WARNING}暂无 Key 使用数据。{COLOR_RESET}")
    else:
        for model_summary in models_summary:
            lines.append(f"  {COLOR_POSITIVE}模型: {model_summary.get('model_name', 'N/A')} (Key 数量: {model_summary.get('key_count', 0)}){COLOR_RESET}")
            lines.append(f"    今日总 RPD: {model_summary.get('total_rpd_today', 0):,} | 今日总 TPD 输入: {model_summary.get('total_tpd_input_today', 0):,}")
            lines.append("    状态分布:")
            status_distribution = model_summary.get("status_distribution", [])
            if not status_distribution:
                 lines.append(f"      {COLOR_WARNING}无状态数据。{COLOR_RESET}")
            else:
                for status_info in status_distribution:
                    lines.append(f"      - 数量: {status_info.get('count', 0)}, 状态: {status_info.get('status', 'N/A')}")
    return lines

def _format_overall_stats(overall_stats: Dict[str, Any]) -> List[str]:
    """格式化总体统计与预测部分。"""
    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} 总体统计与预测 {COLOR_RESET}\n{SEPARATOR_LINE}"]
    lines.append(f"  活跃 Key 数量: {overall_stats.get('active_keys_count', 0)}")
    lines.append(f"  启动时无效 Key 数量: {overall_stats.get('invalid_keys_at_startup', 0)}")
    lines.append("  RPD 容量估算:")
    rpd_capacity_estimations = overall_stats.get("rpd_capacity_estimation", [])
    if not rpd_capacity_estimations:
         lines.append(f"    {COLOR_WARNING}无 RPD 容量估算数据。{COLOR_RESET}")
    else:
        for estimation in rpd_capacity_estimations:
            if "capacity" in estimation:
                lines.append(f"    - 基于模型 {estimation.get('based_on', 'N/A')}: 限制 {estimation.get('limit', 'N/A')}, 容量 {estimation.get('capacity', 0):,}")
            else:
                lines.append(f"    - 基于模型 {estimation.get('based_on', 'N/A')}: {estimation.get('message', 'N/A')}")

    lines.append("  TPD 输入容量估算:")
    tpd_input_capacity_estimations = overall_stats.get("tpd_input_capacity_estimation", [])
    if not tpd_input_capacity_estimations:
         lines.append(f"    {COLOR_WARNING}无 TPD 输入容量估算数据。{COLOR_RESET}")
    else:
        for estimation in tpd_input_capacity_estimations:
             if "capacity" in estimation:
                lines.append(f"    - 基于模型 {estimation.get('based_on', 'N/A')}: 限制 {estimation.get('limit', 'N/A')}, 容量 {estimation.get('capacity', 0):,}")
             else:
                lines.append(f"    - 基于模型 {estimation.get('based_on', 'N/A')}: {estimation.get('message', 'N/A')}")

    lines.append(f"  今日已用 RPD: {overall_stats.get('current_rpd_today', 0):,}")
    lines.append(f"  今日已用 TPD 输入: {overall_stats.get('current_tpd_input_today', 0):,}")
    lines.append(f"  预估今日总 RPD: {overall_stats.get('estimated_rpd_today', 'N/A')} (基于已过去 {overall_stats.get('estimation_fraction_of_day', 0):.1%} 时间)")
    lines.append(f"  预估今日总 TPD 输入: {overall_stats.get('estimated_tpd_input_today', 'N/A')} (基于已过去 {overall_stats.get('estimation_fraction_of_day', 0):.1%} 时间)")

    historical_average_usage = overall_stats.get("historical_average_usage", {})
    lines.append(f"  历史平均每日 RPD ({historical_average_usage.get('days_included', 0)} 天): {historical_average_usage.get('avg_daily_rpd', 'N/A')}")

    return lines

def _format_key_suggestion(suggestion: str) -> List[str]:
    """格式化 Key 数量建议部分。"""
    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} Key 数量建议 {COLOR_RESET}\n{SEPARATOR_LINE}"]
    if "警告" in suggestion or "错误" in suggestion:
        lines.append(f"  {COLOR_ERROR}{suggestion}{COLOR_RESET}")
    elif "提示" in suggestion:
        lines.append(f"  {COLOR_WARNING}{suggestion}{COLOR_RESET}")
    else:
        lines.append(f"  {COLOR_POSITIVE}{suggestion}{COLOR_RESET}")
    return lines

def _format_top_ips(top_ips: Dict[str, Any]) -> List[str]:
    """格式化 Top 5 IP 地址统计部分。"""
    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} Top 5 IP 地址统计 {COLOR_RESET}\n{SEPARATOR_LINE}"]

    lines.append("  请求数:")
    for period in ["today", "week", "month"]:
        lines.append(f"    {period.capitalize()}:")
        ip_list = top_ips.get("requests", {}).get(period, [])
        if not ip_list:
             lines.append(f"      {COLOR_WARNING}无数据。{COLOR_RESET}")
        else:
            for ip_info in ip_list:
                lines.append(f"      - {ip_info.get('ip', 'N/A')}: {ip_info.get('count', 0):,} 次请求")

    lines.append("  输入 Token 数:")
    for period in ["today", "week", "month"]:
        lines.append(f"    {period.capitalize()}:")
        ip_list = top_ips.get("tokens", {}).get(period, [])
        if not ip_list:
             lines.append(f"      {COLOR_WARNING}无数据。{COLOR_RESET}")
        else:
            for ip_info in ip_list:
                lines.append(f"      - {ip_info.get('ip', 'N/A')}: {ip_info.get('tokens', 0):,} Tokens")
    return lines


# --- 周期性报告日志记录函数 ---
def log_usage_report(key_manager: 'APIKeyManager'):
    """
    调用 report_usage 获取报告数据并记录到终端日志。
    """
    logger.info("正在记录周期性使用情况报告到终端...")
    try:
        report_data = report_usage(key_manager) # 调用 report_usage 获取数据

        report_lines = [f"{COLOR_TITLE}--- API 使用情况报告 ({report_data.get('timestamp', 'N/A')}) ---{COLOR_RESET}"] # 报告标题

        # 格式化并添加各个报告部分
        report_lines.extend(_format_key_usage_summary(report_data.get("key_usage_summary", {}).get("models", [])))
        report_lines.extend(_format_overall_stats(report_data.get("overall_stats", {})))
        report_lines.extend(_format_key_suggestion(report_data.get("key_suggestion", "无建议。")))
        report_lines.extend(_format_top_ips(report_data.get("top_ips", {})))


        # 将所有报告行合并并记录到日志
        full_report_string = "\n".join(report_lines)
        logger.log(REPORT_LOG_LEVEL_INT, full_report_string) # 使用配置的日志级别记录报告

        logger.info("周期性使用情况报告已记录到终端。")

    except Exception as e:
        logger.error(f"记录周期性使用情况报告到终端失败: {e}", exc_info=True)


# --- Scheduler Setup and Start ---

def _add_memory_context_cleanup_job():
    """
    添加内存数据库上下文清理任务到调度器。
    """
    if IS_MEMORY_DB:
        # 采用新配置项 MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS
        cleanup_interval = getattr(config, 'MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS', 3600) # 默认1小时
        # 决定使用 TTL 作为清理依据，但任务按较短间隔运行
        cleanup_run_interval = max(600, cleanup_interval // 6) # 每隔一段时间检查一次，最短10分钟
        # 传递给 cleanup_memory_context 的参数是 max_age_seconds，即记录的最大存活时间
        # 这里可以设置为一个较大的值（例如 TTL 天数对应的秒数），或者一个基于运行间隔的值
        # 考虑到 TTL 可以在运行时更改，直接传递一个基于间隔的值可能更简单
        cleanup_max_age = cleanup_interval * 2 # 清理掉超过2倍检查间隔未使用的记录

        scheduler.add_job(
            run_cleanup_memory_context, # 调用同步包装器
            'interval',
            seconds=cleanup_run_interval, # 按较短间隔运行检查
            args=[cleanup_max_age], # 传递最大保留时间（秒）
            id='memory_context_cleanup',
            name='内存上下文清理',
            replace_existing=True
        )
        logger.info(f"内存上下文清理任务已添加，运行间隔: {cleanup_run_interval} 秒。")
    else:
         logger.info("非内存数据库模式，跳过添加内存上下文清理任务。")


def setup_scheduler(key_manager: 'APIKeyManager'):
    """
    将任务添加到调度器。
    """

    logger.info("正在设置后台任务...")
    # 日志清理任务
    scheduler.add_job(cleanup_old_logs, 'cron', hour=3, minute=0, args=[30], id='log_cleanup', name='日志清理', replace_existing=True)
    # 每日 RPD/TPD_Input 重置任务 (PT 午夜) - 从 daily_reset 导入
    scheduler.add_job(reset_daily_counts, 'cron', hour=0, minute=0, timezone='America/Los_Angeles', id='daily_reset', name='每日限制重置', replace_existing=True)
    # 周期性使用报告任务 - 调用新的日志记录函数
    scheduler.add_job(log_usage_report, 'interval', minutes=USAGE_REPORT_INTERVAL_MINUTES, args=[key_manager], id='usage_report', name='使用报告', replace_existing=True)
    # Key 得分缓存更新任务 (每 10 秒) - 从 key_management 导入
    # (已确认 _refresh_all_key_scores 不再是 async)
    scheduler.add_job(_refresh_all_key_scores, 'interval', seconds=CACHE_REFRESH_INTERVAL_SECONDS, args=[key_manager], id='key_score_update', name='Key 得分更新', replace_existing=True, executor='asyncio') # 注意：_refresh_all_key_scores 现在只需要 key_manager 参数

    # 添加内存数据库上下文清理任务 - 委托给辅助函数
    _add_memory_context_cleanup_job()


    job_names = [job.name for job in scheduler.get_jobs()]
    logger.info(f"后台任务已调度: {', '.join(job_names)}")

def start_scheduler():
    """
    """
    try:
        if not scheduler.running:
            scheduler.start()
            logger.info("后台调度器已启动。")
        else:
            logger.info("后台调度器已在运行。")
    except Exception as e:
        logger.error(f"启动后台调度器失败: {e}", exc_info=True)

def shutdown_scheduler():
    """
    """
    if scheduler.running:
        logger.info("正在关闭后台调度器...")
        scheduler.shutdown()
        logger.info("后台调度器已关闭。")
