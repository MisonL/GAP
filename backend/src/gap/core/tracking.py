# -*- coding: utf-8 -*-
"""
全局跟踪模块。
定义用于在内存中跟踪 API 使用情况、速率限制、缓存统计、Key 分数等的全局变量和线程锁。
提供更新这些统计数据的辅助函数。
注意：这些数据是内存中的，应用重启后会丢失（除非有持久化机制）。
"""
import logging  # 导入日志模块
import threading  # 导入线程模块，用于创建锁保护共享数据
import time  # 导入时间模块，用于时间戳
from collections import (  # 导入 defaultdict 和 Counter，方便数据统计
    Counter,
    defaultdict,
)
from typing import Any, Dict  # 导入类型提示

logger = logging.getLogger(__name__)  # 获取当前模块的 logger 实例

# 导入统一锁管理器
try:
    from gap.core.concurrency.lock_manager import lock_manager
except ImportError:
    logger.warning("统一锁管理器不可用，将使用传统锁机制")
    lock_manager = None

# --- 使用情况跟踪数据结构 ---

# `usage_data`: 存储每个 API Key 对每个模型的使用情况统计。
# 结构: {api_key: {model_name: {统计项: 值}}}
# 统计项包括:
#   - 'rpm_count': 当前 RPM (每分钟请求数) 窗口内的请求计数。
#   - 'rpm_timestamp': 当前 RPM 窗口的开始时间戳。
#   - 'rpd_count': 当日 (太平洋时间) 的总请求计数。
#   - 'tpd_input_count': 当日 (太平洋时间) 的总输入 Token 计数。
#   - 'tpm_input_count': 当前 TPM (每分钟输入 Token 数) 窗口内的输入 Token 计数。
#   - 'tpm_input_timestamp': 当前 TPM 输入窗口的开始时间戳。
#   - 'last_request_timestamp': 此 Key-模型组合最后一次被请求的时间戳 (用于 Key 选择策略)。
usage_data: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(
    lambda: defaultdict(
        lambda: {  # 使用嵌套 defaultdict 简化初始化
            "rpm_count": 0,
            "rpm_timestamp": 0.0,
            "rpd_count": 0,
            "tpd_input_count": 0,
            "tpm_input_count": 0,
            "tpm_input_timestamp": 0.0,
            "last_request_timestamp": 0.0,
        }
    )
)
# `usage_lock`: 用于保护对 `usage_data` 并发访问的线程锁。
usage_lock = threading.Lock()  # 保留传统锁作为备用


# --- Key 健康度评分缓存 ---

# `key_scores_cache`: 存储每个 API Key 对每个模型的健康度评分（或其他评分）。
# 结构: {model_name: {api_key: score}}
key_scores_cache: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
# `cache_lock`: 用于保护对 `key_scores_cache` 和 `cache_last_updated` 并发访问的线程锁。
cache_lock = threading.Lock()  # 保留传统锁作为备用
# `cache_last_updated`: 记录每个模型的分数缓存上次更新的时间戳。
# 结构: {model_name: timestamp}
cache_last_updated: Dict[str, float] = defaultdict(float)

# --- 每日 RPD 总量跟踪 ---

# `daily_rpd_totals`: 存储每天 (太平洋时间) 所有 Key 的总 RPD (每日请求数)。
# 结构: {'YYYY-MM-DD': total_rpd}
daily_rpd_totals: Dict[str, int] = defaultdict(int)
# `daily_totals_lock`: 用于保护对 `daily_rpd_totals` 并发访问的线程锁。
daily_totals_lock = threading.Lock()  # 保留传统锁作为备用

# --- 每日 IP 输入 Token 消耗计数 ---

# `ip_daily_input_token_counts`: 存储每个 IP 地址每天 (太平洋时间) 的总输入 Token 消耗。
# 结构: {'YYYY-MM-DD': Counter({'ip_address': total_input_tokens})}
ip_daily_input_token_counts: Dict[str, Counter[str]] = defaultdict(
    Counter
)  # 使用 Counter 更方便计数
# `ip_input_token_counts_lock`: 用于保护对 `ip_daily_input_token_counts` 并发访问的线程锁。
ip_input_token_counts_lock = threading.Lock()  # 保留传统锁作为备用

# --- 缓存使用情况跟踪 ---

# `cache_hit_count`: 记录原生缓存的总命中次数。
cache_hit_count: int = 0
# `cache_miss_count`: 记录原生缓存的总未命中次数。
cache_miss_count: int = 0
# `total_tokens_saved`: 记录通过缓存命估算节省的总 Token 数量。
total_tokens_saved: int = 0
# `cache_tracking_lock`: 用于保护以上缓存跟踪变量并发访问的线程锁。
cache_tracking_lock = threading.Lock()  # 保留传统锁作为备用

# --- Key 筛选跟踪 ---
# 这些变量用于统计 Key 选择策略的执行情况和效果。
key_selection_total_attempts: int = 0  # Key 选择的总尝试次数
key_selection_successful_selections: int = 0  # 成功选定 Key 的次数
key_selection_failed_selections: int = 0  # 未能选定 Key 的次数
key_selection_failure_reasons: Dict[str, int] = defaultdict(
    int
)  # 按原因统计选择失败的次数
# key_selection_lock = threading.Lock() # 注意：原代码中定义了锁但未使用，如果需要并发更新这些统计量，应使用锁

# --- 统一锁获取辅助函数 ---


def _get_lock(lock_name: str):
    """获取统一锁管理器中的锁，如果不可用则回退到传统锁"""
    if lock_manager:
        return lock_manager.get_thread_lock(lock_name)
    else:
        # 回退到传统锁映射
        lock_map = {
            "usage_data": usage_lock,
            "key_scores_cache": cache_lock,
            "daily_rpd_totals": daily_totals_lock,
            "ip_input_token_counts": ip_input_token_counts_lock,
            "cache_tracking": cache_tracking_lock,
        }
        return lock_map.get(lock_name)


# --- 缓存统计更新函数 ---


def increment_cache_hit_count():
    """(线程安全) 增加缓存命中计数。"""
    lock = _get_lock("cache_tracking")
    with lock:  # 获取锁
        global cache_hit_count  # 声明修改全局变量
        cache_hit_count += 1  # 计数加 1
        logger.debug(f"缓存命中计数: {cache_hit_count}")  # 记录调试日志


def increment_cache_miss_count():
    """(线程安全) 增加缓存未命中计数。"""
    lock = _get_lock("cache_tracking")
    with lock:  # 获取锁
        global cache_miss_count  # 声明修改全局变量
        cache_miss_count += 1  # 计数加 1
        logger.debug(f"缓存未命中计数: {cache_miss_count}")  # 记录调试日志


def add_tokens_saved(tokens: int):
    """(线程安全) 增加通过缓存节省的总 Token 数。"""
    if tokens > 0:  # 只有当节省的 Token 数大于 0 时才更新
        lock = _get_lock("cache_tracking")
        with lock:  # 获取锁
            global total_tokens_saved  # 声明修改全局变量
            total_tokens_saved += tokens  # 累加 Token 数
            logger.debug(f"节省的总 token 数: {total_tokens_saved}")  # 记录调试日志


def track_cache_hit(request_id: str, cache_id: str, tokens_saved: int):
    """
    (线程安全) 记录一次缓存命中事件，并更新相关统计数据。

    Args:
        request_id (str): 相关的请求 ID。
        cache_id (str): 命中的缓存条目的 ID (Gemini Cache ID 或数据库 ID)。
        tokens_saved (int): 本次命中估算节省的 Token 数量。
    """
    lock = _get_lock("cache_tracking")
    with lock:  # 获取锁
        global cache_hit_count, total_tokens_saved  # 声明修改全局变量
        cache_hit_count += 1  # 命中计数加 1
        total_tokens_saved += tokens_saved  # 累加节省的 Token 数
        # 记录详细的命中日志
        logger.info(
            f"缓存命中: Request ID: {request_id}, Cache ID: {cache_id}, 节省 Token: {tokens_saved}"
        )


def track_cache_miss(request_id: str, content_hash: str):
    """
    (线程安全) 记录一次缓存未命中事件，并更新相关统计数据。

    Args:
        request_id (str): 相关的请求 ID。
        content_hash (str): 未命中内容的哈希值。
    """
    lock = _get_lock("cache_tracking")
    with lock:  # 获取锁
        global cache_miss_count  # 声明修改全局变量
        cache_miss_count += 1  # 未命中计数加 1
        # 记录详细的未命中日志
        logger.info(
            f"缓存未命中: Request ID: {request_id}, Content Hash: {content_hash[:10]}..."
        )  # 只记录哈希前缀


# --- 常量定义 ---
RPM_WINDOW_SECONDS = 60  # RPM (每分钟请求数) 计算的时间窗口（秒）
TPM_WINDOW_SECONDS = 60  # TPM (每分钟 Token 数) 计算的时间窗口（秒）
CACHE_REFRESH_INTERVAL_SECONDS = (
    300  # Key 分数缓存的刷新间隔 (秒，例如 300 秒 = 5 分钟)
)


# --- Key 分数缓存更新函数 ---
def update_cache_timestamp(model_name: str):
    """
    (线程安全) 更新指定模型的分数缓存的最后更新时间戳为当前时间。

    Args:
        model_name (str): 需要更新时间戳的模型名称。
    """
    lock = _get_lock("key_scores_cache")
    with lock:  # 获取分数缓存锁
        cache_last_updated[model_name] = time.time()  # 更新时间戳
