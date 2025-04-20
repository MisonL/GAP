# app/tracking.py -> app/core/tracking.py
import threading
import time
from collections import defaultdict
from typing import Dict, Any, Optional

# --- 使用情况跟踪数据结构 ---

# 存储格式: key -> model -> {rpm_count, rpm_timestamp, rpd_count, tpd_input_count, tpm_input_count, tpm_input_timestamp, last_request_timestamp}
# rpm_timestamp: 上次 RPM 计数增加的时间戳 (用于判断 60 秒窗口)
# tpm_input_timestamp: 上次 TPM_Input 计数增加的时间戳 (用于判断 60 秒窗口)
# last_request_timestamp: 记录最后一次使用此 key-model 组合的时间戳
usage_data: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {
    'rpm_count': 0,
    'rpm_timestamp': 0.0,
    'rpd_count': 0,
    'tpd_input_count': 0, # 新增：每日输入 Token 计数
    'tpm_input_count': 0, # 新增：每分钟输入 Token 计数
    'tpm_input_timestamp': 0.0, # 新增：每分钟输入 Token 时间戳
    'last_request_timestamp': 0.0
}))
usage_lock = threading.Lock() # 保护 usage_data 访问的锁


# --- Key 健康度评分缓存 ---

# 存储格式: key -> model -> score (得分)
key_scores_cache: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
cache_lock = threading.Lock() # 保护 key_scores_cache 访问的锁
# 记录每个模型缓存上次更新的时间戳
cache_last_updated: Dict[str, float] = defaultdict(float) # 改为字典

# --- 每日 RPD 总量跟踪 ---

# 存储格式: date_str (太平洋时间 YYYY-MM-DD) -> total_rpd (当日总请求数)
daily_rpd_totals: Dict[str, int] = defaultdict(int)
daily_totals_lock = threading.Lock() # 保护 daily_rpd_totals 访问的锁

# --- 每日 IP 输入 Token 消耗计数 ---

# 存储格式: date_str (太平洋时间 YYYY-MM-DD) -> ip_address -> total_input_tokens (总输入 Token 数)
ip_daily_input_token_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int)) # 重命名
ip_input_token_counts_lock = threading.Lock() # 重命名

# --- 常量 ---
RPM_WINDOW_SECONDS = 60 # RPM 计算的时间窗口（秒）
TPM_WINDOW_SECONDS = 60 # TPM_Input 计算的时间窗口（秒）
CACHE_REFRESH_INTERVAL_SECONDS = 300 # Key 得分缓存刷新间隔 (秒，改为 5 分钟)

# --- 更新函数 ---
def update_cache_timestamp(model_name: str): # 添加 model_name 参数
    """更新指定模型缓存时间戳为当前时间"""
    global cache_last_updated
    cache_last_updated[model_name] = time.time() # 更新字典中对应模型的时间戳