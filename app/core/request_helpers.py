# app/core/request_helpers.py
import time      # 用于时间相关操作（例如速率限制、时间戳） (Used for time-related operations (e.g., rate limiting, timestamps))
import logging   # 用于应用程序的日志记录 (Used for application logging)
from datetime import datetime, timedelta  # 用于日期和时间计算 (Used for date and time calculations)
import pytz      # 用于处理不同的时区（例如太平洋时间） (Used for handling different time zones (e.g., Pacific Time))
from fastapi import Request, HTTPException # FastAPI 框架的请求对象和 HTTP 异常 (Request objects and HTTP exceptions for FastAPI framework)
from collections import defaultdict # 提供默认值的字典子类 (Subclass of dictionary that provides default values)
from threading import Lock # 用于线程同步的锁 (Used for thread synchronization locks)
from typing import Dict, Union, List # 类型提示 (Type hints)

# 获取名为 'my_logger' 的日志记录器实例
# Get the logger instance named 'my_logger'
logger = logging.getLogger("my_logger")

# --- IP 地址和滥用防护 ---
# --- IP Address and Abuse Protection ---

# 用于存储每个 IP 地址的每日请求计数
# Dictionary to store daily request counts for each IP address
ip_request_data: Dict[str, Dict[str, Union[int, List[float]]]] = defaultdict(lambda: {"daily_count": 0, "timestamps": []})
# 用于保护 ip_daily_request_counts 访问的线程锁
# Thread lock to protect access to ip_daily_request_counts
ip_daily_counts_lock = Lock()

# 获取太平洋时区对象
# Get the Pacific Timezone object
pacific_tz = pytz.timezone('America/Los_Angeles')

def get_client_ip(request: Request) -> str:
    """
    从请求头中获取真实的客户端 IP 地址。
    优先检查 'X-Forwarded-For' 和 'X-Real-IP' 头，然后回退到 request.client.host。
    Gets the real client IP address from request headers.
    Prioritizes 'X-Forwarded-For' and 'X-Real-IP' headers, then falls back to request.client.host.

    Args:
        request: FastAPI 请求对象。The FastAPI request object.

    Returns:
        客户端 IP 地址字符串。The client IP address string.
    """
    # 尝试从 'X-Forwarded-For' 获取 IP，它可能包含一个逗号分隔的列表
    # Try to get IP from 'X-Forwarded-For', which might contain a comma-separated list
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        # 取列表中的第一个 IP 地址，通常是原始客户端 IP
        # Take the first IP address in the list, which is usually the original client IP
        ip = x_forwarded_for.split(",")[0].strip()
        return ip
    # 尝试从 'X-Real-IP' 获取 IP
    # Try to get IP from 'X-Real-IP'
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip
    # 如果以上头都不存在，回退到直接连接的客户端 IP
    # If none of the above headers exist, fall back to the directly connected client IP
    return request.client.host if request.client else "Unknown"


def protect_from_abuse(request: Request, max_rpm: int, max_rpd: int):
    """
    基于 IP 地址实现简单的请求速率和每日总量限制，以防止滥用。
    Implements simple request rate and daily total limiting based on IP address to prevent abuse.

    Args:
        request: FastAPI 请求对象。The FastAPI request object.
        max_rpm: 每个 IP 允许的最大每分钟请求数。Maximum requests per minute allowed per IP.
        max_rpd: 每个 IP 允许的最大每日请求数。Maximum requests per day allowed per IP.

    Raises:
        HTTPException (429 Too Many Requests): 如果超过速率或每日限制。If the rate or daily limit is exceeded.
    """
    global ip_daily_request_counts, ip_daily_counts_lock, pacific_tz # 声明使用全局变量 (Declare usage of global variables)
    ip = get_client_ip(request) # 获取客户端 IP (Get client IP)
    if ip == "Unknown":
        # 如果无法获取 IP，可以选择直接拒绝或允许，这里选择允许但记录警告
        # If IP cannot be obtained, choose to reject or allow; here, allow but log a warning
        logger.warning("无法获取客户端 IP 地址，跳过滥用检查。") # Log warning
        return

    now = time.time() # 获取当前时间戳 (Get current timestamp)
    # 获取当前太平洋时区的日期
    # Get the current date in Pacific Timezone
    today_pacific = datetime.now(pacific_tz).date()

    with ip_daily_counts_lock: # 获取 IP 计数锁 (Acquire IP count lock)
        ip_data = ip_request_data[ip] # 获取该 IP 的数据 (Get data for this IP)
        daily_count = ip_data.get("daily_count", 0) # 获取当日请求计数 (Get daily request count)
        timestamps = ip_data.get("timestamps", []) # 获取请求时间戳列表 (Get request timestamps list)

        # --- 检查每日请求限制 (RPD) ---
        # --- Check Daily Request Limit (RPD) ---
        # 如果上次请求不是今天（太平洋时间），则重置每日计数和时间戳列表
        # If the last request was not today (Pacific Time), reset the daily count and timestamps list
        # 检查时间戳列表是否为空，如果不为空，则获取最早的时间戳对应的日期
        last_request_date_pacific = datetime.fromtimestamp(timestamps[0], pacific_tz).date() if timestamps else None

        if last_request_date_pacific != today_pacific:
            daily_count = 0 # 重置计数 (Reset count)
            timestamps = [] # 重置时间戳列表 (Reset timestamps list)
            ip_data["daily_count"] = 0 # 更新存储中的计数 (Update stored count)
            ip_data["timestamps"] = [] # 更新存储中的时间戳列表 (Update stored timestamps list)

        # 检查是否超过每日限制
        # Check if the daily limit is exceeded
        if daily_count >= max_rpd:
            logger.warning(f"IP {ip} 已达到每日请求限制 ({max_rpd} RPD)。") # Log warning
            raise HTTPException(status_code=429, detail=f"您已达到每日请求限制 ({max_rpd} RPD)。请明天再试。You have reached the daily request limit ({max_rpd} RPD). Please try again tomorrow.")

        # --- 检查每分钟请求限制 (RPM) ---
        # --- Check Requests Per Minute Limit (RPM) ---
        # 滑动窗口 RPM 实现：移除窗口外的旧时间戳，检查剩余数量
        # Sliding window RPM implementation: Remove old timestamps outside the window, check remaining count
        rpm_window_seconds = 60 # RPM 窗口为 60 秒 (RPM window is 60 seconds)
        # 移除早于当前时间减去窗口时间的时间戳
        # Remove timestamps older than current time minus window time
        timestamps = [ts for ts in timestamps if now - ts < rpm_window_seconds]

        if len(timestamps) >= max_rpm:
            # 如果超过 RPM 限制，计算需要等待的时间
            # If RPM limit is exceeded, calculate wait time
            # 需要等到最早的那个请求的时间戳加上窗口时间之后
            # Need to wait until the timestamp of the earliest request plus window time
            earliest_timestamp = timestamps[0] if timestamps else now
            wait_time = earliest_timestamp + rpm_window_seconds - now
            # 确保等待时间不为负
            wait_time = max(0.0, wait_time)

            logger.warning(f"IP {ip} 请求过于频繁，触发 RPM 限制 ({max_rpm} RPM)。需要等待 {wait_time:.2f} 秒。") # Log warning
            raise HTTPException(status_code=429, detail=f"请求过于频繁。请在 {wait_time:.2f} 秒后重试。Requests are too frequent. Please try again in {wait_time:.2f} seconds.")

        # --- 更新计数和时间戳 ---
        # --- Update Counts and Timestamps ---
        ip_data["daily_count"] = daily_count + 1 # 增加每日计数 (Increment daily count)
        timestamps.append(now) # 将当前时间戳添加到列表中 (Append current timestamp to the list)
        ip_data["timestamps"] = timestamps # 更新存储中的时间戳列表 (Update stored timestamps list)
        logger.debug(f"IP {ip} 请求计数更新: RPD={ip_data['daily_count']}, RPM_Window_Count={len(timestamps)}") # Log count update (DEBUG level)
def get_current_timestamps():
    """
    获取当前时间戳和太平洋时区的日期字符串。
    Gets the current timestamp and the date string in Pacific Timezone.

    Returns:
        一个元组，包含当前时间戳 (float) 和太平洋时区的日期字符串 (str)。
        A tuple containing the current timestamp (float) and the date string in Pacific Timezone (str).
    """
    now = time.time()
    # 获取当前太平洋时区的日期并格式化为字符串
    # Get the current date in Pacific Timezone and format it as a string
    today_pacific = datetime.now(pacific_tz).date()
    today_date_str_pt = today_pacific.isoformat() # 使用 ISO 格式

    return now, today_date_str_pt