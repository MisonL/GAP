# -*- coding: utf-8 -*-
"""
IP 速率限制功能。
"""
import asyncio  # 导入异步IO库
import logging  # 导入日志模块
import time  # 导入时间模块
from collections import defaultdict, deque  # 导入集合类型
from datetime import datetime, timedelta, timezone  # 导入 datetime 相关
from typing import Dict, Optional, Tuple  # 导入类型提示

from fastapi import HTTPException, Request, status  # 导入 FastAPI 相关组件

logger = logging.getLogger("my_logger")  # 获取日志记录器实例

# 导入统一锁管理器
try:
    from gap.core.concurrency.lock_manager import lock_manager
except ImportError:
    logger.warning("统一锁管理器不可用，将使用传统锁机制")
    lock_manager = None

# --- 存储 IP 请求数据 ---
# ip_timestamps: 存储每个 IP 最近的请求时间戳 (使用 deque 以方便移除旧条目)
# 注意：maxlen 只是一个大概的限制，实际限制由时间窗口和 max_requests_per_minute 控制
ip_timestamps: Dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=200))

# ip_daily_counts: 存储每个 IP 的 (每日计数, 当日午夜重置时间戳)
# (count, reset_timestamp_utc)
ip_daily_counts: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))

# --- 锁，用于保护共享数据结构的并发访问 ---
timestamps_lock = asyncio.Lock()  # 用于保护 ip_timestamps (保留作为备用)
daily_counts_lock = asyncio.Lock()  # 用于保护 ip_daily_counts (保留作为备用)


# 统一锁获取函数
async def _get_async_lock(lock_name: str):
    """获取统一锁管理器中的异步锁，如果不可用则回退到传统锁"""
    if lock_manager:
        return lock_manager.get_async_lock(lock_name)
    else:
        # 回退到传统锁映射
        lock_map = {
            "ip_timestamps": timestamps_lock,
            "ip_daily_counts": daily_counts_lock,
        }
        return lock_map.get(lock_name)


def get_client_ip(request: Request) -> Optional[str]:
    """
    辅助函数：获取客户端 IP 地址，考虑代理服务器的情况。

    Args:
        request (Request): FastAPI 请求对象。

    Returns:
        Optional[str]: 客户端 IP 地址，如果无法获取则返回 None。
    """
    # 尝试从 'x-forwarded-for' Header 获取 IP (通常由反向代理设置)
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        # 'x-forwarded-for' 可能包含多个 IP (client, proxy1, proxy2)，第一个通常是原始客户端 IP
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        # 如果没有 'x-forwarded-for'，则使用连接的直接客户端 IP
        ip = request.client.host if request.client else None
    return ip


async def protect_from_abuse(
    request: Request, max_requests_per_minute: int, max_requests_per_day_per_ip: int
):
    """
    根据客户端 IP 地址进行速率限制。
    检查每分钟请求数和每日总请求数。

    Args:
        request (Request): FastAPI 请求对象。
        max_requests_per_minute (int): 每分钟允许的最大请求数。
        max_requests_per_day_per_ip (int): 每个 IP 每日允许的最大请求数。

    Raises:
        HTTPException (429 Too Many Requests): 如果请求超过限制。
    """
    client_ip = get_client_ip(request)  # 获取客户端 IP

    # 如果无法获取 IP 地址，可以选择：
    # 1. 拒绝请求 (更安全，但可能误伤配置不当的代理后的合法用户)
    # 2. 放行请求 (更宽松，但无法对此类请求进行速率限制)
    # 3. 记录警告并放行 (当前选择)
    if not client_ip:
        logger.warning(
            "无法获取客户端 IP 地址进行速率限制，本次请求将跳过 IP 限制检查。"
        )
        return

    current_time = time.time()  # 获取当前时间戳 (秒)

    # --- 每分钟请求限制检查 ---
    if max_requests_per_minute > 0:  # 仅在配置了限制时检查
        lock = await _get_async_lock("ip_timestamps")
        async with lock:  # 获取锁以保护共享数据
            # 移除此 IP 记录中所有早于 (当前时间 - 60秒) 的时间戳
            while (
                ip_timestamps[client_ip]
                and ip_timestamps[client_ip][0] < current_time - 60
            ):
                ip_timestamps[client_ip].popleft()

            # 检查清理后，当前窗口内的请求数量是否超限
            if len(ip_timestamps[client_ip]) >= max_requests_per_minute:
                logger.warning(
                    f"IP {client_ip} 每分钟请求超限。限制: {max_requests_per_minute}, 当前: {len(ip_timestamps[client_ip]) + 1}"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"请求过于频繁，请稍后再试 (每分钟限制: {max_requests_per_minute} 次)。",
                )
            # 如果未超限，记录本次请求的时间戳
            ip_timestamps[client_ip].append(current_time)

    # --- 每日请求限制检查 ---
    if max_requests_per_day_per_ip > 0:  # 仅在配置了限制时检查
        lock = await _get_async_lock("ip_daily_counts")
        async with lock:  # 获取锁以保护共享数据
            count, reset_time = ip_daily_counts[client_ip]

            # 检查是否需要重置每日计数
            # 如果当前时间大于等于上次记录的重置时间，说明进入了新的一天 (或首次记录)
            if current_time >= reset_time:
                # 计算今天的 UTC 午夜作为新的重置时间点
                # 注意：这种简单的计算方式可能不完全精确到时区午夜，但对于每日限制足够
                # 更精确的方式是使用 datetime 对象处理日期和时区
                today_utc = datetime.fromtimestamp(current_time, tz=timezone.utc)
                next_midnight_utc = (today_utc + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                new_reset_time = next_midnight_utc.timestamp()

                count = 0  # 重置计数器
                reset_time = new_reset_time  # 更新重置时间
                # logger.debug(f"IP {client_ip} 的每日计数已重置。新的重置时间: {datetime.fromtimestamp(new_reset_time, tz=timezone.utc)}")

            # 检查每日请求数量是否超限
            if count >= max_requests_per_day_per_ip:
                logger.warning(
                    f"IP {client_ip} 每日请求超限。限制: {max_requests_per_day_per_ip}, 当前已达: {count}"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"今日请求已达上限 (每日限制: {max_requests_per_day_per_ip} 次)，请明天再试。",
                )

            # 如果未超限，增加计数并更新存储
            ip_daily_counts[client_ip] = (count + 1, reset_time)

    logger.debug(
        f"IP {client_ip} 请求通过速率限制检查。分钟内请求数: {len(ip_timestamps.get(client_ip, []))}, 今日请求数: {ip_daily_counts.get(client_ip, (0,0))[0]}"
    )
    return  # 所有检查通过
