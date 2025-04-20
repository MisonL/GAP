# -*- coding: utf-8 -*-
"""
应用程序配置模块。
从环境变量加载配置，并提供默认值。
"""
import os
import logging
import json
from typing import Dict, List, Any
from dotenv import load_dotenv

# 加载 .env 文件 (如果存在)
load_dotenv()

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 应用版本 ---
__version__ = "1.4.1" # 更新版本号，代码结构优化和 TODO 清理


# --- 应用配置 ---
PASSWORD = os.environ.get("PASSWORD") # Web UI 密码 (强制设置)
WEB_UI_PASSWORDS: List[str] = [p.strip() for p in PASSWORD.split(',') if p.strip()] if PASSWORD else []

SECRET_KEY = os.environ.get("SECRET_KEY") # 用于 Session 中间件，必须设置！
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY") # 管理员 API Key
MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30")) # 每分钟最大请求数 (本地限制)
MAX_REQUESTS_PER_DAY_PER_IP: int = int(os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600")) # 每个 IP 每天最大请求数
DISABLE_SAFETY_FILTERING: bool = os.environ.get("DISABLE_SAFETY_FILTERING", "false").lower() == "true" # 是否禁用安全过滤
PROTECT_STATUS_PAGE: bool = os.environ.get("PROTECT_STATUS_PAGE", "false").lower() == "true" # 是否为状态页面启用密码保护

# --- JWT 配置 ---
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256") # JWT 签名算法
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30")) # JWT 有效期（分钟）


# --- 报告配置 ---
# 读取使用情况报告间隔，默认30分钟
_default_report_interval = 30 # 默认报告间隔（分钟）
try:
    USAGE_REPORT_INTERVAL_MINUTES: int = int(os.environ.get("USAGE_REPORT_INTERVAL_MINUTES", str(_default_report_interval))) # 从环境变量读取报告间隔，使用默认值
    if USAGE_REPORT_INTERVAL_MINUTES <= 0:
        # 此警告将在 main.py 启动时记录
        USAGE_REPORT_INTERVAL_MINUTES = _default_report_interval
except ValueError:
    # 此警告将在 main.py 启动时记录
    USAGE_REPORT_INTERVAL_MINUTES = _default_report_interval

# 读取报告日志级别，默认为 INFO
_log_level_map: Dict[str, int] = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL} # 日志级别字符串到整数的映射
REPORT_LOG_LEVEL_STR: str = os.environ.get("REPORT_LOG_LEVEL", "INFO").upper() # 从环境变量读取报告日志级别字符串
REPORT_LOG_LEVEL_INT: int = _log_level_map.get(REPORT_LOG_LEVEL_STR, logging.INFO) # 将日志级别字符串转换为整数
# 日志级别设置确认/警告将在 main.py 启动时记录

# --- 缓存配置 ---
CACHE_REFRESH_INTERVAL_SECONDS: int = int(os.environ.get("CACHE_REFRESH_INTERVAL_SECONDS", "10")) # Key 分数缓存刷新间隔（秒）

# --- Gemini 安全设置 ---
# 标准安全设置 (BLOCK_NONE)
safety_settings: List[Dict[str, str]] = [ # 标准安全设置列表 (阻止无)
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
safety_settings_g2: List[Dict[str, str]] = [ # G2 安全设置列表 (关闭)
    {"category": c, "threshold": "OFF"}
    for c in [
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_CIVIC_INTEGRITY", # 基于原始代码添加
    ]
]

# --- 上下文管理配置 ---
# 数据库文件路径 (如果设置了此环境变量，则使用文件存储，否则使用内存 :memory:)
CONTEXT_DB_PATH = os.environ.get('CONTEXT_DB_PATH') # 直接获取环境变量，不提供默认路径
DEFAULT_MAX_CONTEXT_TOKENS = int(os.environ.get('DEFAULT_MAX_CONTEXT_TOKENS', "30000")) # 默认最大上下文 Token 数
CONTEXT_TOKEN_SAFETY_MARGIN = int(os.environ.get('CONTEXT_TOKEN_SAFETY_MARGIN', "200")) # 上下文 Token 安全边际
DEFAULT_CONTEXT_TTL_DAYS = 7 # 这个值主要用于 context_store 初始化数据库
# 新增：内存上下文清理运行间隔（秒），默认 1 小时
MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS = int(os.environ.get('MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS', "3600")) # 内存上下文清理间隔（秒）
# 新增：内存模式下最大上下文记录数，默认 5000
MAX_CONTEXT_RECORDS_MEMORY = int(os.environ.get('MAX_CONTEXT_RECORDS_MEMORY', "5000")) # 内存模式下最大上下文记录数

# 新增：是否在流式响应结束后保存模型回复 (默认 false，保存回复会增加流中断时丢失上下文的风险)
STREAM_SAVE_REPLY: bool = os.environ.get("STREAM_SAVE_REPLY", "false").lower() == "true" # 是否在流式响应结束后保存回复
# --- 模型限制 ---
MODEL_LIMITS: Dict[str, Any] = {} # 初始化为空字典

def load_model_limits():
    """从 JSON 文件加载模型限制到全局变量 MODEL_LIMITS"""
    global MODEL_LIMITS # 声明我们要修改全局变量
    current_dir = os.path.dirname(os.path.abspath(__file__)) # 获取当前文件所在目录
    model_limits_path = os.path.join(current_dir, 'data', 'model_limits.json') # 构建模型限制文件的完整路径
    logger.info(f"尝试从 {model_limits_path} 加载模型限制...")
    try:
        if os.path.exists(model_limits_path):
            with open(model_limits_path, 'r', encoding='utf-8') as f: # 以 UTF-8 编码打开文件
                MODEL_LIMITS = json.load(f) # 从 JSON 文件加载数据
            logger.info(f"成功加载模型限制。找到的模型: {list(MODEL_LIMITS.keys())}")
            # 验证加载的数据
            for model, limits in MODEL_LIMITS.items():
                 if not isinstance(limits, dict): # 检查限制是否为字典
                     logger.warning(f"模型 '{model}' 的限制不是字典格式，已忽略。")
                     continue
                 if "input_token_limit" not in limits: # 检查是否缺少 'input_token_limit'
                      logger.warning(f"模型 '{model}' 在 model_limits.json 中缺少 'input_token_limit' 字段。")
                 elif limits["input_token_limit"] is None: # 检查 'input_token_limit' 是否为 null
                      logger.warning(f"模型 '{model}' 在 model_limits.json 中的 'input_token_limit' 为 null。")
        else:
             logger.error(f"模型限制文件未找到: {model_limits_path}。将使用空限制。")
             MODEL_LIMITS = {} # 文件未找到，使用空字典
    except json.JSONDecodeError as e:
        logger.error(f"解析模型限制文件 {model_limits_path} 失败: {e}。将使用空限制。")
        MODEL_LIMITS = {} # JSON 解析失败，使用空字典
    except Exception as e:
        logger.error(f"加载模型限制时发生未知错误: {e}", exc_info=True)
        MODEL_LIMITS = {} # 其他加载错误，使用空字典

# 注意：加载函数定义好了，但调用将在 main.py 的 lifespan 中进行

# --- 其他全局变量 ---