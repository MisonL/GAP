import os
import logging
from typing import Dict, List # 添加 List 导入

# --- 应用版本 ---
__version__ = "1.2.1"


# --- 应用配置 ---
PASSWORD: str = os.environ.get("PASSWORD", "123") # API 访问密码/密钥
MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30")) # 每分钟最大请求数 (本地限制)
MAX_REQUESTS_PER_DAY_PER_IP: int = int(os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600")) # 每个 IP 每天最大请求数
DISABLE_SAFETY_FILTERING: bool = os.environ.get("DISABLE_SAFETY_FILTERING", "false").lower() == "true" # 是否禁用安全过滤
PROTECT_STATUS_PAGE: bool = os.environ.get("PROTECT_STATUS_PAGE", "false").lower() == "true" # 是否为状态页面启用密码保护

# --- 报告配置 ---
# 读取使用情况报告间隔，默认30分钟
_default_report_interval = 30
try:
    USAGE_REPORT_INTERVAL_MINUTES: int = int(os.environ.get("USAGE_REPORT_INTERVAL_MINUTES", str(_default_report_interval)))
    if USAGE_REPORT_INTERVAL_MINUTES <= 0:
        # 此警告将在 main.py 启动时记录
        USAGE_REPORT_INTERVAL_MINUTES = _default_report_interval
except ValueError:
    # 此警告将在 main.py 启动时记录
    USAGE_REPORT_INTERVAL_MINUTES = _default_report_interval

# 读取报告日志级别，默认为 INFO
_log_level_map: Dict[str, int] = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}
REPORT_LOG_LEVEL_STR: str = os.environ.get("REPORT_LOG_LEVEL", "INFO").upper()
REPORT_LOG_LEVEL_INT: int = _log_level_map.get(REPORT_LOG_LEVEL_STR, logging.INFO)
# 日志级别设置确认/警告将在 main.py 启动时记录

# --- Gemini 安全设置 ---
# 标准安全设置 (BLOCK_NONE)
safety_settings: List[Dict[str, str]] = [
    {"category": c, "threshold": "BLOCK_NONE"}
    for c in [
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_CIVIC_INTEGRITY", # 基于原始代码添加
    ]
]

# G2 安全设置 (OFF) - 当 DISABLE_SAFETY_FILTERING 为 true 或用于特定模型时使用
safety_settings_g2: List[Dict[str, str]] = [
    {"category": c, "threshold": "OFF"}
    for c in [
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_CIVIC_INTEGRITY", # 基于原始代码添加
    ]
]

# --- 模型限制 (加载逻辑将在 main.py 的 startup 中处理) ---
MODEL_LIMITS: Dict[str, Dict[str, int | None]] = {} # 初始化为空，启动时加载

# --- 启动时状态 (将在 key_management.py 中管理) ---
INITIAL_KEY_COUNT: int = 0
INVALID_KEYS: List[str] = []

# --- 调度器 (将在 reporting.py 或 main.py 中管理) ---
# scheduler = BackgroundScheduler() # 初始化已移动

# --- 其他全局变量 (根据需要移动或保留在 main.py) ---
# REPORT_LOG_LEVEL_INT 已在上面定义