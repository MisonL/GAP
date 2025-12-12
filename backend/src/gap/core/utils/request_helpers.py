# -*- coding: utf-8 -*-
"""
请求处理相关的辅助函数。
包含获取客户端 IP、基于 IP 的速率限制（可能已废弃）以及获取时间戳的功能。
"""
import logging  # 导入日志模块
import time  # 导入时间模块，用于获取时间戳
from collections import defaultdict  # 导入默认字典，方便初始化嵌套字典
from datetime import datetime  # 导入日期时间处理相关类
from typing import Dict, List, Tuple, Union  # 导入类型提示

import pytz  # 导入时区库，用于处理太平洋时区
from fastapi import HTTPException, Request  # 导入 FastAPI 的请求对象和 HTTP 异常类

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger("my_logger")

# --- IP 地址和滥用防护 ---

# 用于存储每个 IP 地址的请求时间戳和每日计数 (可能已废弃或需要与 Key 级别限制协调)
# 结构: {'ip_address': {'daily_count': int, 'timestamps': List[float]}}
ip_request_data: Dict[str, Dict[str, Union[int, List[float]]]] = defaultdict(
    lambda: {"daily_count": 0, "timestamps": []}
)

# 获取太平洋时区对象，用于每日计数重置
pacific_tz = pytz.timezone("America/Los_Angeles")


def get_client_ip(request: Request) -> str:
    """
    从 FastAPI 请求对象中提取真实的客户端 IP 地址。
    优先检查常见的代理头 ('X-Forwarded-For', 'X-Real-IP')，
    如果不存在，则回退到直接连接的客户端地址 (`request.client.host`)。

    Args:
        request (Request): FastAPI 请求对象。

    Returns:
        str: 客户端 IP 地址字符串。如果无法确定，则返回 "Unknown"。
    """
    # 检查 'X-Forwarded-For' 头，通常由代理服务器添加
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        # 'X-Forwarded-For' 可能包含多个 IP (client, proxy1, proxy2, ...)，取第一个通常是原始客户端 IP
        ip = x_forwarded_for.split(",")[0].strip()  # 按逗号分割并取第一个，去除空白
        logger.debug(f"从 X-Forwarded-For 获取 IP: {ip}")  # 记录日志
        return ip
    # 检查 'X-Real-IP' 头，一些反向代理（如 Nginx）会使用这个头
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        logger.debug(f"从 X-Real-IP 获取 IP: {x_real_ip}")  # 记录日志
        return x_real_ip
    # 如果代理头都不存在，回退到 FastAPI 提供的直接连接客户端信息
    # request.client 包含 (host, port) 元组
    client_host = request.client.host if request.client else None
    if client_host:
        logger.debug(f"从 request.client.host 获取 IP: {client_host}")  # 记录日志
        return client_host
    else:  # 如果无法获取任何 IP 信息
        logger.warning("无法从请求头或 client 属性中获取客户端 IP 地址。")  # 记录警告
        return "Unknown"  # 返回 "Unknown"


def protect_from_abuse(request: Request, max_rpm: int, max_rpd: int):
    """
    (可能已废弃/需要审查) 基于 IP 地址实现简单的请求速率 (RPM) 和每日总量 (RPD) 限制。
    注意：此函数使用全局字典 `ip_request_data` 存储状态，可能与基于 Key 的限制冲突或重复。
          在当前系统中，速率限制主要由 Key Manager 处理，此函数可能不再需要或需要重新设计。

    Args:
        request (Request): FastAPI 请求对象。
        max_rpm (int): 每个 IP 允许的最大每分钟请求数。
        max_rpd (int): 每个 IP 允许的最大每日请求数。

    Raises:
        HTTPException (429 Too Many Requests): 如果检测到超过速率或每日限制。
    """
    logger.warning(
        "调用了可能已废弃的 protect_from_abuse 函数 (基于 IP 的速率限制)。"
    )  # 记录警告
    ip = get_client_ip(request)  # 获取客户端 IP
    if ip == "Unknown":  # 如果无法获取 IP
        logger.warning("无法获取客户端 IP 地址，跳过滥用检查。")  # 记录警告并跳过检查
        return

    # 使用统一的锁管理器
    try:
        from gap.core.concurrency.lock_manager import lock_manager
    except ImportError:
        # 如果锁管理器不可用，回退到无锁版本（虽然不完美但不会崩溃）
        logger.warning("锁管理器不可用，IP速率限制可能不安全")
        return

    now = time.time()  # 获取当前时间戳
    today_pacific = datetime.now(pacific_tz).date()  # 获取当前太平洋时区的日期

    with lock_manager.acquire_thread_lock("ip_rate_limit"):  # 使用统一锁管理器
        ip_data = ip_request_data[ip]  # 获取或创建该 IP 的数据字典
        daily_count = ip_data.get("daily_count", 0)  # 获取当日请求计数
        timestamps: List[float] = ip_data.get("timestamps", [])  # 获取请求时间戳列表

        # --- 检查每日请求限制 (RPD) ---
        # 获取列表中最早的时间戳对应的日期 (如果列表不为空)
        last_request_date_pacific = (
            datetime.fromtimestamp(timestamps[0], pacific_tz).date()
            if timestamps
            else None
        )
        # 如果上次请求不是今天 (太平洋时间)，则重置每日计数
        if last_request_date_pacific != today_pacific:
            daily_count = 0  # 重置计数
            timestamps = []  # 清空时间戳列表 (因为 RPM 检查也基于此列表)
            ip_data["daily_count"] = 0  # 更新存储的计数
            ip_data["timestamps"] = []  # 更新存储的时间戳列表
            logger.debug(f"IP {ip} 的每日计数已重置 (新的一天)。")  # 记录日志

        # 检查加上当前请求是否超过每日限制
        if daily_count >= max_rpd:
            logger.warning(f"IP {ip} 已达到每日请求限制 ({max_rpd} RPD)。")  # 记录警告
            # 抛出 429 错误
            raise HTTPException(
                status_code=429,
                detail=f"您已达到每日请求限制 ({max_rpd} RPD)。请明天再试。",
            )

        # --- 检查每分钟请求限制 (RPM) ---
        rpm_window_seconds = 60  # 定义 RPM 的时间窗口为 60 秒
        # 移除时间戳列表中所有早于 (当前时间 - 窗口时长) 的时间戳
        timestamps = [ts for ts in timestamps if now - ts < rpm_window_seconds]
        # 检查剩余时间戳的数量是否达到或超过 RPM 限制
        if len(timestamps) >= max_rpm:
            # 计算需要等待的时间：窗口时长 - (当前时间 - 最早的时间戳)
            earliest_timestamp = (
                timestamps[0] if timestamps else now
            )  # 获取窗口内最早的时间戳
            wait_time = max(
                0.0, earliest_timestamp + rpm_window_seconds - now
            )  # 计算剩余等待时间，确保不为负
            logger.warning(
                f"IP {ip} 请求过于频繁，触发 RPM 限制 ({max_rpm} RPM)。需要等待 {wait_time:.2f} 秒。"
            )  # 记录警告
            # 抛出 429 错误
            raise HTTPException(
                status_code=429, detail=f"请求过于频繁。请在 {wait_time:.2f} 秒后重试。"
            )

        # --- 更新计数和时间戳 ---
        # 如果检查通过，则更新计数和时间戳列表
        ip_data["daily_count"] = daily_count + 1  # 每日计数加 1
        timestamps.append(now)  # 将当前时间戳添加到列表末尾
        ip_data["timestamps"] = timestamps  # 更新存储的时间戳列表
        logger.debug(
            f"IP {ip} 请求计数更新: RPD={ip_data['daily_count']}, RPM_Window_Count={len(timestamps)}"
        )  # 记录调试日志


def get_current_timestamps() -> Tuple[float, str]:  # 返回类型修改为 Tuple[float, str]
    """
    获取当前的 Unix 时间戳和太平洋时区的日期字符串。

    Returns:
        Tuple[float, str]:
            - 第一个元素：当前的 Unix 时间戳 (float)。
            - 第二个元素：太平洋时区的当前日期字符串 (str, 'YYYY-MM-DD' 格式)。
    """
    now_timestamp = time.time()  # 获取当前 Unix 时间戳
    # 获取当前太平洋时区的日期并格式化为 ISO 格式字符串 ('YYYY-MM-DD')
    today_pacific = datetime.now(pacific_tz).date()
    today_date_str_pt = today_pacific.isoformat()

    return now_timestamp, today_date_str_pt  # 返回元组
