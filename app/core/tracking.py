# app/tracking.py -> app/core/tracking.py
import threading # 导入线程模块 (Import threading module)
import time # 导入时间模块 (Import time module)
from collections import defaultdict # 导入 defaultdict
from typing import Dict, Any, Optional # 导入类型提示

# --- 使用情况跟踪数据结构 ---
# --- Usage Tracking Data Structures ---

# 存储格式: key -> model -> {rpm_count, rpm_timestamp, rpd_count, tpd_input_count, tpm_input_count, tpm_input_timestamp, last_request_timestamp}
# Storage format: key -> model -> {rpm_count, rpm_timestamp, rpd_count, tpd_input_count, tpm_input_count, tpm_input_timestamp, last_request_timestamp}
# rpm_timestamp: 上次 RPM 计数增加的时间戳 (用于判断 60 秒窗口)
# rpm_timestamp: Timestamp of the last RPM count increment (used to determine the 60-second window)
# tpm_input_timestamp: 上次 TPM_Input 计数增加的时间戳 (用于判断 60 秒窗口)
# tpm_input_timestamp: Timestamp of the last TPM_Input count increment (used to determine the 60-second window)
# last_request_timestamp: 记录最后一次使用此 key-model 组合的时间戳
# last_request_timestamp: Records the timestamp of the last use of this key-model combination
usage_data: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {
    'rpm_count': 0, # 每分钟请求计数 (Requests per minute count)
    'rpm_timestamp': 0.0, # 每分钟请求时间戳 (Requests per minute timestamp)
    'rpd_count': 0, # 每日请求计数 (Requests per day count)
    'tpd_input_count': 0, # 新增：每日输入 Token 计数 (New: Daily input token count)
    'tpm_input_count': 0, # 新增：每分钟输入 Token 计数 (New: Tokens per minute input count)
    'tpm_input_timestamp': 0.0, # 新增：每分钟输入 Token 时间戳 (New: Tokens per minute input timestamp)
    'last_request_timestamp': 0.0 # 最后请求时间戳 (Last request timestamp)
}))
usage_lock = threading.Lock() # 保护 usage_data 访问的锁 (Lock to protect access to usage_data)


# --- Key 健康度评分缓存 ---
# --- Key Health Score Cache ---

# 存储格式: key -> model -> score (得分)
# Storage format: key -> model -> score
key_scores_cache: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float)) # Key 分数缓存 (Key scores cache)
cache_lock = threading.Lock() # 保护 key_scores_cache 访问的锁 (Lock to protect access to key_scores_cache)
# 记录每个模型缓存上次更新的时间戳
# Records the timestamp of the last update for each model cache
cache_last_updated: Dict[str, float] = defaultdict(float) # 改为字典 (Changed to dictionary)

# --- 每日 RPD 总量跟踪 ---
# --- Daily RPD Total Tracking ---

# 存储格式: date_str (太平洋时间 YYYY-MM-DD) -> total_rpd (当日总请求数)
# Storage format: date_str (Pacific Time YYYY-MM-DD) -> total_rpd (Total requests for the day)
daily_rpd_totals: Dict[str, int] = defaultdict(int) # 每日 RPD 总计 (Daily RPD totals)
daily_totals_lock = threading.Lock() # 保护 daily_rpd_totals 访问的锁 (Lock to protect access to daily_rpd_totals)

# --- 每日 IP 输入 Token 消耗计数 ---
# --- Daily IP Input Token Consumption Count ---

# 存储格式: date_str (太平洋时间 YYYY-MM-DD) -> ip_address -> total_input_tokens (总输入 Token 数)
# Storage format: date_str (Pacific Time YYYY-MM-DD) -> ip_address -> total_input_tokens (Total input tokens)
ip_daily_input_token_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int)) # 重命名 (Renamed)
ip_input_token_counts_lock = threading.Lock() # 重命名 (Renamed)

# --- 常量 ---
# --- Constants ---
RPM_WINDOW_SECONDS = 60 # RPM 计算的时间窗口（秒） (Time window for RPM calculation (seconds))
TPM_WINDOW_SECONDS = 60 # TPM_Input 计算的时间窗口（秒） (Time window for TPM_Input calculation (seconds))
CACHE_REFRESH_INTERVAL_SECONDS = 300 # Key 得分缓存刷新间隔 (秒，改为 5 分钟) (Key score cache refresh interval (seconds, changed to 5 minutes))

# --- 更新函数 ---
# --- Update Function ---
def update_cache_timestamp(model_name: str): # 添加 model_name 参数 (Added model_name parameter)
    """
    更新指定模型缓存时间戳为当前时间。
    Updates the cache timestamp for the specified model to the current time.

    Args:
        model_name: 模型名称。The name of the model.
    """
    global cache_last_updated # 声明我们要修改全局变量 (Declare that we are modifying a global variable)
    cache_last_updated[model_name] = time.time() # 更新字典中对应模型的时间戳 (Update the timestamp for the corresponding model in the dictionary)
