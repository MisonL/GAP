# -*- coding: utf-8 -*-
"""
应用程序配置模块。
从环境变量加载配置，并提供默认值。
使用 python-dotenv 库来支持从 .env 文件加载环境变量。
"""
import os # 导入 os 模块，用于访问环境变量
from typing import Optional, Dict, List, Any # 导入类型提示
import logging # 导入日志模块
import json # 导入 JSON 模块
from dotenv import load_dotenv # 导入 python-dotenv 库

# --- 加载环境变量 ---
# load_dotenv() 会查找当前目录或上级目录中的 .env 文件并加载其中的变量到环境变量中
# 如果 .env 文件不存在，此函数不会报错
load_dotenv()

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 应用版本 ---
# 定义应用程序的版本号
__version__ = "1.9.0" # 当前版本

# --- 应用核心配置 ---
# PASSWORD: 用于 Web UI 登录的密码。可以设置多个密码，用逗号分隔。
# 如果未设置，Web UI 登录功能将被视为禁用（但 API 仍可能需要 Key）。
PASSWORD: Optional[str] = os.environ.get("PASSWORD")
# WEB_UI_PASSWORDS: 将 PASSWORD 环境变量按逗号分割处理后的密码列表。
WEB_UI_PASSWORDS: List[str] = [p.strip() for p in PASSWORD.split(',') if p.strip()] if PASSWORD else []

# SECRET_KEY: 用于 JWT 签名和验证的密钥。**必须设置，且应为强随机字符串！**
# 强烈建议不要硬编码，而是通过环境变量设置。
SECRET_KEY: Optional[str] = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    logger.critical("严重错误：JWT SECRET_KEY 未在环境变量中设置！Web UI 登录和管理功能将无法正常工作。")
    # 在实际生产环境中，可能需要在此处退出应用或采取其他措施
    # raise ValueError("JWT SECRET_KEY is not set in environment variables")

# ADMIN_API_KEY: 可选的管理 API Key。如果设置，持有此 Key 的用户将被视为管理员，
# 可以访问管理界面和执行管理操作。
ADMIN_API_KEY: Optional[str] = os.environ.get("ADMIN_API_KEY")

# MAX_REQUESTS_PER_MINUTE: (可能已废弃) 基于 IP 的每分钟最大请求数限制。默认 60。
MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "60"))
# MAX_REQUESTS_PER_DAY_PER_IP: (可能已废弃) 基于 IP 的每日最大请求数限制。默认 600。
MAX_REQUESTS_PER_DAY_PER_IP: int = int(os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))

# DISABLE_SAFETY_FILTERING: 是否全局禁用 Gemini API 的安全内容过滤。默认为 False。
# 设置为 True 时，所有发送给 Gemini API 的请求将不包含 safety_settings 参数。
DISABLE_SAFETY_FILTERING: bool = os.environ.get("DISABLE_SAFETY_FILTERING", "false").lower() == "true"

# PROTECT_STATUS_PAGE: (可能已废弃) 是否为状态页面启用密码保护。默认为 False。
PROTECT_STATUS_PAGE: bool = os.environ.get("PROTECT_STATUS_PAGE", "false").lower() == "true"

# --- JWT (JSON Web Token) 配置 ---
# JWT_ALGORITHM: 用于签名 JWT 的算法。默认为 "HS256"。
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
# ACCESS_TOKEN_EXPIRE_MINUTES: JWT 访问令牌的有效时间（分钟）。默认 30 分钟。
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


# --- 报告配置 ---
# USAGE_REPORT_INTERVAL_MINUTES: 生成使用情况报告的间隔时间（分钟）。默认 30 分钟。
_default_report_interval = 30 # 定义默认间隔
try:
    # 尝试从环境变量读取并转换为整数
    _usage_report_interval = int(os.environ.get("USAGE_REPORT_INTERVAL_MINUTES", str(_default_report_interval)))
    # 确保间隔大于 0
    if _usage_report_interval <= 0:
        logger.warning(f"环境变量 USAGE_REPORT_INTERVAL_MINUTES ({os.environ.get('USAGE_REPORT_INTERVAL_MINUTES')}) 必须为正整数，将使用默认值 {_default_report_interval} 分钟。")
        _usage_report_interval = _default_report_interval
except ValueError: # 处理无法转换为整数的情况
    logger.warning(f"无法将环境变量 USAGE_REPORT_INTERVAL_MINUTES ('{os.environ.get('USAGE_REPORT_INTERVAL_MINUTES')}') 解析为整数，将使用默认值 {_default_report_interval} 分钟。")
    _usage_report_interval = _default_report_interval
USAGE_REPORT_INTERVAL_MINUTES: int = _usage_report_interval

# REPORT_LOG_LEVEL_STR / REPORT_LOG_LEVEL_INT: 控制使用情况报告输出到日志的级别。
# 默认为 INFO。可以设置为 DEBUG, WARNING, ERROR, CRITICAL。
_log_level_map: Dict[str, int] = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL} # 日志级别名称到整数值的映射
REPORT_LOG_LEVEL_STR: str = os.environ.get("REPORT_LOG_LEVEL", "INFO").upper() # 从环境变量读取级别字符串 (转大写)
REPORT_LOG_LEVEL_INT: int = _log_level_map.get(REPORT_LOG_LEVEL_STR, logging.INFO) # 获取对应的整数级别，无效则默认为 INFO
# 日志级别设置的确认信息将在 main.py 启动时打印

# --- 缓存配置 ---
# CACHE_REFRESH_INTERVAL_SECONDS: Key 健康度评分缓存的刷新间隔时间（秒）。默认 600 秒 (10 分钟)。
CACHE_REFRESH_INTERVAL_SECONDS: int = int(os.environ.get("CACHE_REFRESH_INTERVAL_SECONDS", "600"))

# --- Gemini 安全设置 ---
# 定义标准的 Gemini API 安全设置，默认将所有类别的阈值设为 BLOCK_NONE (不阻止)。
safety_settings: List[Dict[str, str]] = [
    {"category": c, "threshold": "BLOCK_NONE"}
    for c in [
        "HARM_CATEGORY_HARASSMENT",        # 骚扰内容
        "HARM_CATEGORY_HATE_SPEECH",       # 仇恨言论
        "HARM_CATEGORY_SEXUALLY_EXPLICIT", # 色情内容
        "HARM_CATEGORY_DANGEROUS_CONTENT", # 危险内容
        # "HARM_CATEGORY_CIVIC_INTEGRITY", # 公民诚信 (可能较新，根据需要添加)
    ]
]

# 定义另一套安全设置，将所有阈值设为 OFF (完全关闭安全过滤)。
# 这套设置在全局 DISABLE_SAFETY_FILTERING 为 True 时，或针对特定模型（如实验性模型）时使用。
safety_settings_g2: List[Dict[str, str]] = [
    {"category": c, "threshold": "BLOCK_NONE"} # 注意：Gemini API 可能没有 'OFF' 阈值，BLOCK_NONE 是最低设置
    for c in [
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        # "HARM_CATEGORY_CIVIC_INTEGRITY",
    ]
]

# --- 上下文管理配置 ---
# CONTEXT_DB_PATH: SQLite 数据库文件的路径。如果设置了此环境变量，则使用文件数据库进行持久化存储。
# 如果未设置，则使用内存数据库 (应用重启后数据丢失)。
CONTEXT_DB_PATH: Optional[str] = os.environ.get('CONTEXT_DB_PATH')

# DEFAULT_MAX_CONTEXT_TOKENS: 默认的最大上下文 Token 数量，用于截断对话历史。默认 30000。
DEFAULT_MAX_CONTEXT_TOKENS: int = int(os.environ.get('DEFAULT_MAX_CONTEXT_TOKENS', "30000"))
# CONTEXT_TOKEN_SAFETY_MARGIN: 在截断上下文时保留的安全边际 Token 数。默认 200。
CONTEXT_TOKEN_SAFETY_MARGIN: int = int(os.environ.get('CONTEXT_TOKEN_SAFETY_MARGIN', "200"))
# DEFAULT_CONTEXT_TTL_DAYS: 上下文记录的默认生存时间（天）。默认 7 天。
# 注意：此设置可能与数据库中的 'context_ttl_days' 设置交互。
DEFAULT_CONTEXT_TTL_DAYS: int = int(os.environ.get('DEFAULT_CONTEXT_TTL_DAYS', "7")) # 默认 7 天

# MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS: 内存数据库模式下，后台清理任务的运行间隔（秒）。默认 3600 秒 (1 小时)。
MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS: int = int(os.environ.get('MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS', "3600"))
# MAX_CONTEXT_RECORDS_MEMORY: 内存数据库模式下，允许存储的最大上下文记录数量。超过此数量将清理最旧的记录。默认 5000。
MAX_CONTEXT_RECORDS_MEMORY: int = int(os.environ.get('MAX_CONTEXT_RECORDS_MEMORY', "5000"))

# CONTEXT_STORAGE_MODE: 控制对话上下文的存储和加载方式。
# - 'database': 从 SQLite 数据库加载和管理上下文 (如果 CONTEXT_DB_PATH 已设置)。
# - 'memory': 在内存中临时管理上下文 (应用重启后数据丢失)。
# 默认为 'memory'，特别是在 CONTEXT_DB_PATH 未设置时。
_context_storage_mode_env = os.environ.get("CONTEXT_STORAGE_MODE", "memory").lower()
if _context_storage_mode_env not in ['database', 'memory']:
    logger.warning(f"无效的环境变量 CONTEXT_STORAGE_MODE 值 '{os.environ.get('CONTEXT_STORAGE_MODE')}'。将使用默认值 'memory'。")
    _final_context_storage_mode: str = "memory"
elif _context_storage_mode_env == "database" and not CONTEXT_DB_PATH:
    logger.warning("CONTEXT_STORAGE_MODE 设置为 'database'，但 CONTEXT_DB_PATH 未设置。将强制使用 'memory' 模式。")
    _final_context_storage_mode = "memory"
else:
    _final_context_storage_mode = _context_storage_mode_env
CONTEXT_STORAGE_MODE: str = _final_context_storage_mode
logger.info(f"上下文存储模式设置为: {CONTEXT_STORAGE_MODE}")

# ENABLE_CONTEXT_COMPLETION: 全局默认是否启用传统上下文补全功能。默认为 True。
# 可以被单个 Key 的配置覆盖。如果 ENABLE_NATIVE_CACHING 为 True，此设置会被忽略。
ENABLE_CONTEXT_COMPLETION: bool = os.environ.get("ENABLE_CONTEXT_COMPLETION", "true").lower() == "true"

# STREAM_SAVE_REPLY: (可能已废弃) 是否在流式响应结束后尝试保存模型回复到上下文。默认为 False。
# 保存流式回复可能增加因连接中断导致上下文丢失的风险。
STREAM_SAVE_REPLY: bool = os.environ.get("STREAM_SAVE_REPLY", "false").lower() == "true"
# ENABLE_STICKY_SESSION: 是否启用粘性会话功能。如果启用，Key 选择器会优先尝试用户上次使用的 Key。默认为 False。
ENABLE_STICKY_SESSION: bool = os.environ.get("ENABLE_STICKY_SESSION", "false").lower() == "true"

# --- API Key 存储模式配置 ---
# KEY_STORAGE_MODE: 控制 API Key 的存储和加载方式。
# - 'database': 从 SQLite 数据库加载和管理 Key (推荐用于生产)。
# - 'memory': 从环境变量 `GEMINI_API_KEYS` 加载 Key，并在内存中临时管理 (适用于简单部署或测试)。
# 默认为 'memory'。
_key_storage_mode_env = os.environ.get("KEY_STORAGE_MODE", "memory").lower() # 读取环境变量并转小写
# 验证环境变量值是否有效
if _key_storage_mode_env not in ['database', 'memory']:
    logger.warning(f"无效的环境变量 KEY_STORAGE_MODE 值 '{os.environ.get('KEY_STORAGE_MODE')}'。将使用默认值 'memory'。") # 记录警告
    _final_key_storage_mode: str = "memory" # 使用默认值
else:
    _final_key_storage_mode = _key_storage_mode_env # 使用环境变量值
KEY_STORAGE_MODE: str = _final_key_storage_mode
logger.info(f"API Key 存储模式设置为: {KEY_STORAGE_MODE}") # 记录最终使用的模式

# GEMINI_API_KEYS: 在内存模式 (`KEY_STORAGE_MODE='memory'`) 下使用的 API Key 列表，从环境变量读取，用逗号分隔。
GEMINI_API_KEYS: Optional[str] = os.environ.get("GEMINI_API_KEYS")
# 如果是内存模式但未提供 GEMINI_API_KEYS 环境变量，记录警告
if KEY_STORAGE_MODE == 'memory' and not GEMINI_API_KEYS:
    logger.warning("KEY_STORAGE_MODE 设置为 'memory'，但未找到 GEMINI_API_KEYS 环境变量。内存模式下将没有可用的 API Key。")


# --- 模型限制配置 ---
# MODEL_LIMITS: 存储从 JSON 文件加载的各模型速率限制和 Token 限制的字典。
# 结构: {model_name: {"rpd": int, "rpm": int, "tpd_input": int, "tpm_input": int, "input_token_limit": int, ...}}
MODEL_LIMITS: Dict[str, Any] = {} # 声明 MODEL_LIMITS 为字典类型，并在此处初始化为空字典

def load_model_limits():
    """
    从位于 `app/data/model_limits.json` 的 JSON 文件加载模型限制数据，
    并填充到全局变量 `MODEL_LIMITS` 字典中。
    在应用启动时由 `main.py` 中的 `lifespan` 函数调用。
    """
    # 不再使用 global MODEL_LIMITS，而是返回数据
    model_limits_data: Dict[str, Any] = {} # 初始化为空字典，用于存储加载的数据
    # 获取当前文件 (config.py) 所在的目录，即 app 目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 构建模型限制 JSON 文件的正确路径，应为 app/data/model_limits.json
    model_limits_path = os.path.join(current_dir, 'data', 'model_limits.json') # 移除 '..'
    logger.info(f"尝试从 {model_limits_path} 加载模型限制...") # 记录加载日志
    try:
        # 检查文件是否存在
        if os.path.exists(model_limits_path):
            # 以 UTF-8 编码打开并读取文件内容
            with open(model_limits_path, 'r', encoding='utf-8') as f:
                model_limits_data = json.load(f) # 解析 JSON 数据并赋值给临时变量
            logger.info(f"成功加载模型限制。找到的模型: {list(model_limits_data.keys())}") # 记录成功日志和加载的模型列表
            # --- 可选：验证加载的数据结构 ---
            for model, limits in model_limits_data.items():
                 if not isinstance(limits, dict): # 检查每个模型的限制是否为字典
                    logger.warning(f"模型 '{model}' 的限制不是字典格式，已忽略。")
                    continue # 跳过无效条目
                 # 可以添加更多验证，例如检查必需的限制字段是否存在或类型是否正确
                 # if "input_token_limit" not in limits:
                 #    logger.warning(f"模型 '{model}' 在 model_limits.json 中缺少 'input_token_limit' 字段。")
                 # elif limits.get("input_token_limit") is None: # 检查值是否为 JSON null
                 #    logger.warning(f"模型 '{model}' 在 model_limits.json 中的 'input_token_limit' 为 null。")
        else: # 如果文件不存在
             logger.error(f"模型限制文件未找到: {model_limits_path}。将使用空限制。") # 记录错误
             model_limits_data = {} # 使用空字典作为默认值
    except json.JSONDecodeError as e: # 捕获 JSON 解析错误
        logger.error(f"解析模型限制文件 {model_limits_path} 失败: {e}。将使用空限制。", exc_info=True) # 记录错误
        model_limits_data = {} # 使用空字典
    except Exception as e: # 捕获其他可能的加载错误
        logger.error(f"加载模型限制时发生未知错误: {e}", exc_info=True) # 记录错误
        model_limits_data = {} # 使用空字典
    return model_limits_data # 返回加载的数据

# 注意：load_model_limits 函数的调用在 main.py 的 lifespan 中进行。

# --- 文档配置 ---
# ENABLE_DOCS: 是否启用 API 文档页面 (/docs)。默认为 True。
ENABLE_DOCS: bool = os.environ.get("ENABLE_DOCS", "true").lower() == "true"

# --- 其他全局配置 ---
# REPORT_FILE_PATH: (已禁用) 原用于指定使用情况报告文件的路径。
# 由于 Hugging Face Spaces 免费层不支持持久化文件存储，此功能已禁用。
REPORT_FILE_PATH: Optional[str] = None
# ENABLE_NATIVE_CACHING: 全局默认是否启用 Gemini API 的原生缓存功能。默认为 False。
# 可以被单个 Key 的配置覆盖（如果未来实现）。
ENABLE_NATIVE_CACHING: bool = os.environ.get("ENABLE_NATIVE_CACHING", "false").lower() == "true"
