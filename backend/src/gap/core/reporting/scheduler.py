# -*- coding: utf-8 -*-
"""
后台任务调度器模块。
使用 APScheduler 设置和管理周期性任务，例如：
- 清理旧日志文件。
- 每日重置 API Key 的使用计数 (RPD, TPD)。
- 定期生成并记录使用情况报告。
- 定期刷新 Key 分数缓存。
- 定期清理内存数据库中的旧上下文记录 (如果使用内存数据库)。
"""
import logging # 导入日志模块
import asyncio # 导入 asyncio 库
from typing import TYPE_CHECKING, List, Dict, Any # 导入类型提示
from apscheduler.schedulers.asyncio import AsyncIOScheduler # 导入 APScheduler 的异步调度器
from apscheduler.executors.asyncio import AsyncIOExecutor # 导入 APScheduler 的异步执行器

# 从其他模块导入必要的组件
from gap import config # 导入应用配置模块
from gap.config import ( # 导入具体的配置项
    USAGE_REPORT_INTERVAL_MINUTES, # 使用情况报告的间隔时间（分钟）
    MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS, # 内存上下文清理任务的运行间隔（秒）
    CACHE_REFRESH_INTERVAL_SECONDS, # Key 分数缓存的刷新间隔（秒）
    REPORT_LOG_LEVEL_INT # 报告日志的级别 (整数形式)
)
# 导入 ContextStore 类用于类型提示
from gap.core.context.store import ContextStore
# 导入数据库工具模块中的内存数据库标志
from gap.core.database.utils import IS_MEMORY_DB # (新路径)
# 导入日志配置模块中的日志清理函数
from gap.utils.log_config import cleanup_old_logs # (路径修正)
# 导入报告模块中的任务函数
from gap.core.reporting.daily_reset import reset_daily_counts # 每日计数重置函数 (新路径)
from gap.core.reporting.reporter import report_usage # 使用情况报告生成函数 (新路径)
# 导入 Key 检查器模块中的分数刷新函数 (注意：下划线前缀表示内部使用)
from gap.core.keys.checker import _refresh_all_key_scores # (新路径)

# 条件导入 APIKeyManager 用于类型提示，避免循环导入
if TYPE_CHECKING:
    from gap.core.keys.manager import APIKeyManager # (新路径)

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- ANSI 转义码定义 (用于彩色日志输出) ---
COLOR_TITLE = "\033[1;94m"  # 亮蓝色
COLOR_SEPARATOR = "\033[0;90m" # 亮黑色/深灰色
COLOR_SECTION_HEADER = "\033[1;96m" # 亮青色
COLOR_POSITIVE = "\033[1;92m" # 亮绿色
COLOR_WARNING = "\033[1;93m" # 亮黄色
COLOR_ERROR = "\033[1;91m" # 亮红色
COLOR_INFO = "\033[0;37m" # 白色
COLOR_RESET = "\033[0m"    # 重置颜色和样式
SEPARATOR_LINE = f"{COLOR_SEPARATOR}{'=' * 60}{COLOR_RESET}" # 定义分隔符行样式

# --- 创建调度器实例 ---
# 使用 AsyncIOScheduler 适合在 asyncio 应用中使用
scheduler = AsyncIOScheduler(
    executors={
        'default': {'type': 'threadpool', 'max_workers': 20}, # 配置默认线程池执行器
        'asyncio': AsyncIOExecutor() # 添加 asyncio 执行器，用于运行异步任务
    }
)

# --- 同步包装器 (用于从调度器调用异步函数) ---
# run_cleanup_memory_context 同步包装器已不再需要，将直接调度异步方法。

# --- 报告格式化辅助函数 (用于 log_usage_report) ---
# 这些函数将 report_usage 返回的字典数据格式化为带颜色的文本行，以便在日志中清晰显示。

def _format_key_usage_summary(models_summary: List[Dict[str, Any]]) -> List[str]:
    """(内部辅助函数) 格式化报告中的 Key 使用情况聚合部分。"""
    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} Key 使用情况聚合 {COLOR_RESET}\n{SEPARATOR_LINE}"] # 添加章节标题和分隔符
    if not models_summary: # 如果没有模型数据
        lines.append(f"  {COLOR_WARNING}暂无 Key 使用数据。{COLOR_RESET}") # 添加提示信息
    else:
        # 遍历每个模型的摘要信息
        for model_summary in models_summary:
            # 添加模型名称、Key 数量、总 RPD、总 TPD 输入
            lines.append(f"  {COLOR_POSITIVE}模型: {model_summary.get('model_name', 'N/A')} (Key 数量: {model_summary.get('key_count', 0)}){COLOR_RESET}")
            lines.append(f"    今日总 RPD: {model_summary.get('total_rpd_today', 0):,} | 今日总 TPD 输入: {model_summary.get('total_tpd_input_today', 0):,}")
            lines.append("    状态分布:") # 添加状态分布小标题
            status_distribution = model_summary.get("status_distribution", []) # 获取状态分布列表
            if not status_distribution: # 如果没有状态分布数据
                 lines.append(f"      {COLOR_WARNING}无状态数据。{COLOR_RESET}") # 添加提示信息
            else:
                # 遍历每个状态及其对应的 Key 数量
                for status_info in status_distribution:
                    lines.append(f"      - 数量: {status_info.get('count', 0)}, 状态: {status_info.get('status', 'N/A')}")
    return lines # 返回格式化后的文本行列表

def _format_overall_stats(report_data: Dict[str, Any]) -> List[str]:
    """(内部辅助函数) 格式化报告中的总体统计、预测、缓存使用情况和 Key 筛选跟踪部分。"""
    # 从报告数据中提取相关部分
    overall_stats = report_data.get("overall_stats", {})
    cache_stats = report_data.get("cache_stats", {})
    key_selection_stats = report_data.get("key_selection_stats", {}) # 获取 Key 筛选统计数据

    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} 总体统计与预测 {COLOR_RESET}\n{SEPARATOR_LINE}"] # 添加章节标题
    # 添加总体统计信息
    lines.append(f"  活跃 Key 数量: {overall_stats.get('active_keys_count', 0)}")
    lines.append(f"  启动时无效 Key 数量: {overall_stats.get('invalid_keys_at_startup', 0)}")
    # 添加 RPD 容量估算
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
    # 添加 TPD 输入容量估算
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
    # 添加今日用量和预估
    lines.append(f"  今日已用 RPD: {overall_stats.get('current_rpd_today', 0):,}")
    lines.append(f"  今日已用 TPD 输入: {overall_stats.get('current_tpd_input_today', 0):,}")
    lines.append(f"  预估今日总 RPD: {overall_stats.get('estimated_rpd_today', 'N/A')} (基于已过去 {overall_stats.get('estimation_fraction_of_day', 0):.1%} 时间)")
    lines.append(f"  预估今日总 TPD 输入: {overall_stats.get('estimated_tpd_input_today', 'N/A')} (基于已过去 {overall_stats.get('estimation_fraction_of_day', 0):.1%} 时间)")
    # 添加历史平均 RPD
    historical_average_usage = overall_stats.get("historical_average_usage", {})
    lines.append(f"  历史平均每日 RPD ({historical_average_usage.get('days_included', 0)} 天): {historical_average_usage.get('avg_daily_rpd', 'N/A')}")

    # 添加缓存使用情况统计
    lines.append(f"\n{COLOR_SECTION_HEADER} 缓存使用情况 {COLOR_RESET}") # 添加子标题
    lines.append(f"  缓存命中次数: {cache_stats.get('hit_count', 0):,}")
    lines.append(f"  缓存未命中次数: {cache_stats.get('miss_count', 0):,}")
    lines.append(f"  节省的总 Token 数: {cache_stats.get('total_tokens_saved', 0):,}")
    lines.append(f"  缓存命中率: {cache_stats.get('hit_rate', 'N/A')}") # 添加命中率

    # 添加 Key 筛选原因统计
    lines.append(f"\n{COLOR_SECTION_HEADER} Key 筛选原因统计 {COLOR_RESET}") # 添加子标题
    total_by_reason = key_selection_stats.get('total_by_reason', {}) # 获取按原因统计的总数
    if not total_by_reason: # 如果没有数据
        lines.append(f"    {COLOR_WARNING}无 Key 筛选原因数据。{COLOR_RESET}") # 添加提示
    else:
        lines.append("  总计 (按原因):") # 添加小标题
        # 按次数降序显示原因
        for reason, count in sorted(total_by_reason.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"    - {reason}: {count:,} 次")
    # 可以选择性地添加 details_by_key 的格式化输出，但可能会很长
    # details_by_key = key_selection_stats.get('details_by_key', {})
    # if details_by_key:
    #     lines.append("\n  详情 (按 Key 和原因):")
    #     for key, reasons in sorted(details_by_key.items()):
    #         lines.append(f"    - Key '{key}':")
    #         for reason, count in sorted(reasons.items(), key=lambda item: item[1], reverse=True):
    #             lines.append(f"      - {reason}: {count:,} 次")

    return lines # 返回格式化后的文本行列表

def _format_key_suggestion(suggestion: str) -> List[str]:
    """(内部辅助函数) 格式化报告中的 Key 数量建议部分，根据建议内容添加颜色。"""
    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} Key 数量建议 {COLOR_RESET}\n{SEPARATOR_LINE}"] # 添加章节标题
    # 根据建议内容判断颜色
    if "强烈建议" in suggestion or "接近或达到上限" in suggestion:
        lines.append(f"  {COLOR_ERROR}{suggestion}{COLOR_RESET}") # 紧急建议用红色
    elif "建议增加" in suggestion or "用量较高" in suggestion:
        lines.append(f"  {COLOR_WARNING}{suggestion}{COLOR_RESET}") # 普通增加建议用黄色
    elif "可以考虑减少" in suggestion:
        lines.append(f"  {COLOR_INFO}{suggestion}{COLOR_RESET}") # 减少建议用白色/默认色
    else: # 保持当前数量的建议
        lines.append(f"  {COLOR_POSITIVE}{suggestion}{COLOR_RESET}") # 保持建议用绿色
    return lines # 返回格式化后的文本行列表

def _format_top_ips(top_ips: Dict[str, Any]) -> List[str]:
    """(内部辅助函数) 格式化报告中的 Top 5 IP 地址统计部分。"""
    lines = [f"\n{SEPARATOR_LINE}\n{COLOR_SECTION_HEADER} Top 5 IP 地址统计 {COLOR_RESET}\n{SEPARATOR_LINE}"] # 添加章节标题

    # --- Top 请求 IP ---
    lines.append(f"\n  {COLOR_INFO}Top 请求 IP:{COLOR_RESET}") # 添加子标题
    # 遍历时间段：今天、本周、本月
    for period in ["today", "week", "month"]:
        lines.append(f"    {period.capitalize()}:") # 添加时间段标题
        ip_list = top_ips.get("requests", {}).get(period, []) # 获取对应时间段的 IP 列表
        if not ip_list: # 如果列表为空
             lines.append(f"      {COLOR_WARNING}无数据。{COLOR_RESET}") # 添加提示
        else: # 如果有数据
            # 遍历 Top IP 信息
            for ip_info in ip_list:
                lines.append(f"      - {ip_info.get('ip', 'N/A')}: {ip_info.get('count', 0):,} 次请求") # 添加 IP 和请求次数

    # --- Top Token IP (输入) ---
    lines.append(f"\n  {COLOR_INFO}Top Token IP (输入):{COLOR_RESET}") # 添加子标题
    # 遍历时间段
    for period in ["today", "week", "month"]:
        lines.append(f"    {period.capitalize()}:") # 添加时间段标题
        ip_list = top_ips.get("tokens", {}).get(period, []) # 获取对应时间段的 IP 列表
        if not ip_list: # 如果列表为空
             lines.append(f"      {COLOR_WARNING}无数据。{COLOR_RESET}") # 添加提示
        else: # 如果有数据
            # 遍历 Top IP 信息
            for ip_info in ip_list:
                lines.append(f"      - {ip_info.get('ip', 'N/A')}: {ip_info.get('tokens', 0):,} Tokens") # 添加 IP 和 Token 数量
    return lines # 返回格式化后的文本行列表


# --- 周期性报告日志记录函数 ---
def log_usage_report(key_manager: 'APIKeyManager'):
    """
    (同步函数) 生成使用情况报告并将其记录到日志。
    此函数由 APScheduler 定期调用。

    Args:
        key_manager (APIKeyManager): APIKeyManager 的实例。
    """
    logger.info("尝试执行 log_usage_report 任务...") # 新增：确认任务是否被调用
    logger.info("正在记录周期性使用情况报告到终端...") # 记录开始日志
    try:
        # 1. 调用 report_usage 函数获取包含所有统计数据的字典
        # report_usage 内部会获取锁并复制共享数据
        report_data = report_usage(key_manager)

        # 2. (已移至 report_usage 内部) 获取缓存和 Key 筛选统计数据
        # from gap.core import tracking
        # cache_stats = {...}
        # key_selection_stats = {...}
        # report_data["cache_stats"] = cache_stats
        # report_data["key_selection_stats"] = key_selection_stats

        # 3. 使用辅助函数将报告数据字典格式化为带颜色的文本行列表
        report_lines = [f"{COLOR_TITLE}--- API 使用情况报告 ({report_data.get('timestamp', 'N/A')}) ---{COLOR_RESET}"] # 报告标题
        report_lines.extend(_format_key_usage_summary(report_data.get("key_usage_summary", {}).get("models", []))) # 格式化 Key 使用摘要
        report_lines.extend(_format_overall_stats(report_data)) # 格式化总体统计、缓存、筛选
        report_lines.extend(_format_key_suggestion(report_data.get("key_suggestion", "无建议。"))) # 格式化 Key 建议
        report_lines.extend(_format_top_ips(report_data.get("top_ips", {}))) # 格式化 Top IP

        # 4. 将所有报告行合并为一个字符串
        full_report_string = "\n".join(report_lines)
        # 5. 使用配置中定义的日志级别记录完整的报告字符串
        logger.log(REPORT_LOG_LEVEL_INT, full_report_string)

        logger.info("周期性使用情况报告已记录到终端。") # 记录完成日志

    except Exception as e: # 捕获报告生成或记录过程中发生的异常
        logger.error(f"记录周期性使用情况报告到终端失败: {e}", exc_info=True) # 记录错误日志


# --- 调度器设置和启动 ---

def _add_memory_context_cleanup_job(context_store_manager: ContextStore):
    """
    (内部辅助函数) 向调度器添加用于清理内存上下文的定时任务。
    仅在 CONTEXT_STORAGE_MODE 为 'memory' 时添加。

    Args:
        context_store_manager (ContextStore): ContextStore 的实例。
    """
    if config.CONTEXT_STORAGE_MODE == "memory": # 检查是否为内存上下文模式
        cleanup_interval = config.MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS
        if cleanup_interval <= 0:
            logger.info("内存上下文清理任务的间隔配置为非正数，任务将不被添加。")
            return

        scheduler.add_job(
            context_store_manager.perform_memory_cleanup, # 直接调用异步方法
            'interval', # 触发器类型：间隔触发
            seconds=cleanup_interval, # 触发间隔（秒）
            id='memory_context_cleanup', # 作业的唯一 ID
            name='内存上下文清理 (ContextStore)', # 作业的名称
            replace_existing=True, # 如果已存在同 ID 作业，则替换
            executor='asyncio' # 确保使用 asyncio 执行器
        )
        logger.info(f"内存上下文清理任务 (ContextStore) 已添加，运行间隔: {cleanup_interval} 秒。")
    else:
         logger.info("非内存上下文存储模式，跳过添加内存上下文清理任务 (ContextStore)。")


def setup_scheduler(key_manager: 'APIKeyManager', context_store_manager: ContextStore):
    """
    设置 APScheduler，添加所有需要的后台定时任务。

    Args:
        key_manager (APIKeyManager): APIKeyManager 的实例。
        context_store_manager (ContextStore): ContextStore 的实例。
    """

    logger.info("正在设置后台任务调度器...") # 记录开始设置日志
    # --- 添加日志清理任务 ---
    # 使用 cron 触发器，每天凌晨 3:00 执行
    # args=[30] 表示保留最近 30 天的日志
    scheduler.add_job(cleanup_old_logs, 'cron', hour=3, minute=0, args=[30], id='log_cleanup', name='日志清理', replace_existing=True)

    # --- 添加每日计数重置任务 ---
    # 使用 cron 触发器，在太平洋时间 (PT) 的午夜 00:00 执行
    # 指定 executor='asyncio' 来确保协程被正确执行
    scheduler.add_job(reset_daily_counts, 'cron', hour=0, minute=0, timezone='America/Los_Angeles', id='daily_reset', name='每日限制重置', replace_existing=True, executor='asyncio')

    # --- 添加周期性使用报告任务 ---
    # 使用 interval 触发器，按配置的分钟数间隔执行
    scheduler.add_job(log_usage_report, 'interval', minutes=USAGE_REPORT_INTERVAL_MINUTES, args=[key_manager], id='usage_report', name='使用报告', replace_existing=True)

    # --- 添加 Key 分数缓存更新任务 ---
    # 使用 interval 触发器，按配置的秒数间隔执行
    # 注意：_refresh_all_key_scores 是一个异步函数，需要指定使用 asyncio 执行器
    scheduler.add_job(_refresh_all_key_scores, 'interval', seconds=CACHE_REFRESH_INTERVAL_SECONDS, args=[key_manager], id='key_score_update', name='Key 得分更新', replace_existing=True, executor='asyncio')

    # --- 添加内存数据库上下文清理任务 (如果需要) ---
    _add_memory_context_cleanup_job(context_store_manager)

    # 记录已调度的任务名称
    job_names = [job.name for job in scheduler.get_jobs()]
    logger.info(f"后台任务已调度: {', '.join(job_names)}") # 记录调度完成日志

def start_scheduler():
    """
    启动后台任务调度器。
    如果调度器已在运行，则不执行任何操作。
    """
    try:
        if not scheduler.running: # 检查调度器是否已在运行
            scheduler.start() # 启动调度器
            logger.info("后台调度器已启动。") # 记录启动日志
        else:
            logger.info("后台调度器已在运行。") # 记录已运行日志
    except Exception as e: # 捕获启动过程中可能发生的异常
        logger.error(f"启动后台调度器失败: {e}", exc_info=True) # 记录错误日志

def shutdown_scheduler():
    """
    关闭后台任务调度器。
    通常在应用关闭时调用，以确保任务被优雅地停止。
    """
    if scheduler.running: # 检查调度器是否在运行
        logger.info("正在关闭后台调度器...") # 记录关闭日志
        scheduler.shutdown() # 关闭调度器
        logger.info("后台调度器已关闭。") # 记录关闭完成日志
