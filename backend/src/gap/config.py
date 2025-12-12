# -*- coding: utf-8 -*-
"""
应用程序配置模块。
从环境变量加载配置，并提供默认值。
使用 python-dotenv 库来支持从 .env 文件加载环境变量。
"""
import json  # 导入 JSON 模块
import logging  # 导入日志模块
import os  # 导入 os 模块，用于访问环境变量
from typing import Any, Dict, List, Optional, Tuple  # 导入类型提示

from dotenv import load_dotenv  # 导入 python-dotenv 库

# --- 加载环境变量 ---
# load_dotenv() 会查找当前目录或上级目录中的 .env 文件并加载其中的变量到环境变量中
# 如果 .env 文件不存在，此函数不会报错
load_dotenv()

logger = logging.getLogger("my_logger")  # 获取日志记录器实例

# --- 应用版本 ---
# 定义应用程序的版本号
__version__ = "1.9.0"  # 当前版本

# --- 应用核心配置 ---
# PASSWORD: 用于 Web UI 登录的密码。可以设置多个密码，用逗号分隔。
# 如果未设置，Web UI 登录功能将被视为禁用（但 API 仍可能需要 Key）。
PASSWORD: Optional[str] = os.environ.get("PASSWORD")
# WEB_UI_PASSWORDS: 将 PASSWORD 环境变量按逗号分割处理后的密码列表。
WEB_UI_PASSWORDS: List[str] = (
    [p.strip() for p in PASSWORD.split(",") if p.strip()] if PASSWORD else []
)

# SECRET_KEY: 用于 JWT 签名和验证的密钥。**必须设置，且应为强随机字符串！**
# 强烈建议不要硬编码，而是通过环境变量设置
SECRET_KEY: Optional[str] = os.environ.get("SECRET_KEY")


def generate_fallback_secret() -> str:
    """生成临时的安全密钥，仅用于紧急情况"""
    import secrets

    return secrets.token_urlsafe(32)


# 检查SECRET_KEY配置
if not SECRET_KEY:
    # 检查是否为开发环境
    env = os.environ.get("ENVIRONMENT", "development").lower()
    if env in ["development", "dev", "test"]:
        # 开发环境：生成临时密钥并发出警告
        SECRET_KEY = generate_fallback_secret()
        logger.warning(
            f"开发环境检测到JWT SECRET_KEY未设置，已生成临时密钥：{SECRET_KEY[:8]}... "
            f"请在生产环境设置强随机SECRET_KEY环境变量！"
        )
    else:
        # 生产环境：记录严重错误但允许启动，Web功能将被禁用
        logger.error(
            "生产环境JWT SECRET_KEY未设置！Web UI登录和管理功能将被禁用。"
            "请设置JWT_SECRET_KEY环境变量以启用完整功能。"
        )
        # 设置一个标记，标识认证功能不可用
        SECRET_KEY = None

# 设置认证功能可用性标记
AUTH_ENABLED = bool(SECRET_KEY)

# ADMIN_API_KEY: 可选的管理 API Key。如果设置，持有此 Key 的用户将被视为管理员，
# 可以访问管理界面和执行管理操作。
ADMIN_API_KEY: Optional[str] = os.environ.get("ADMIN_API_KEY")

# MAX_REQUESTS_PER_MINUTE: (可能已废弃) 基于 IP 的每分钟最大请求数限制。默认 60。
MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "60"))
# MAX_REQUESTS_PER_DAY_PER_IP: (可能已废弃) 基于 IP 的每日最大请求数限制。默认 600。
MAX_REQUESTS_PER_DAY_PER_IP: int = int(
    os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600")
)

# DISABLE_SAFETY_FILTERING: 是否全局禁用 Gemini API 的安全内容过滤。默认为 False。
# 设置为 True 时，所有发送给 Gemini API 的请求将不包含 safety_settings 参数。
DISABLE_SAFETY_FILTERING: bool = (
    os.environ.get("DISABLE_SAFETY_FILTERING", "false").lower() == "true"
)

# PROTECT_STATUS_PAGE: (可能已废弃) 是否为状态页面启用密码保护。默认为 False。
PROTECT_STATUS_PAGE: bool = (
    os.environ.get("PROTECT_STATUS_PAGE", "false").lower() == "true"
)

# --- JWT (JSON Web Token) 配置 ---
# JWT_ALGORITHM: 用于签名 JWT 的算法。默认为 "HS256"。
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
# ACCESS_TOKEN_EXPIRE_MINUTES: JWT 访问令牌的有效时间（分钟）。默认 30 分钟。
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)


# --- 报告配置 ---
# USAGE_REPORT_INTERVAL_MINUTES: 生成使用情况报告的间隔时间（分钟）。默认 30 分钟。
_default_report_interval = 30  # 定义默认间隔
try:
    # 尝试从环境变量读取并转换为整数
    _usage_report_interval = int(
        os.environ.get("USAGE_REPORT_INTERVAL_MINUTES", str(_default_report_interval))
    )
    # 确保间隔大于 0
    if _usage_report_interval <= 0:
        logger.warning(
            f"环境变量 USAGE_REPORT_INTERVAL_MINUTES ({os.environ.get('USAGE_REPORT_INTERVAL_MINUTES')}) 必须为正整数，将使用默认值 {_default_report_interval} 分钟。"
        )
        _usage_report_interval = _default_report_interval
except ValueError:  # 处理无法转换为整数的情况
    logger.warning(
        f"无法将环境变量 USAGE_REPORT_INTERVAL_MINUTES ('{os.environ.get('USAGE_REPORT_INTERVAL_MINUTES')}') 解析为整数，将使用默认值 {_default_report_interval} 分钟。"
    )
    _usage_report_interval = _default_report_interval
USAGE_REPORT_INTERVAL_MINUTES: int = _usage_report_interval

# REPORT_LOG_LEVEL_STR / REPORT_LOG_LEVEL_INT: 控制使用情况报告输出到日志的级别。
# 默认为 INFO。可以设置为 DEBUG, WARNING, ERROR, CRITICAL。
_log_level_map: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}  # 日志级别名称到整数值的映射
REPORT_LOG_LEVEL_STR: str = os.environ.get(
    "REPORT_LOG_LEVEL", "INFO"
).upper()  # 从环境变量读取级别字符串 (转大写)
REPORT_LOG_LEVEL_INT: int = _log_level_map.get(
    REPORT_LOG_LEVEL_STR, logging.INFO
)  # 获取对应的整数级别，无效则默认为 INFO
# 日志级别设置的确认信息将在 main.py 启动时打印

# --- 缓存配置 ---
# CACHE_REFRESH_INTERVAL_SECONDS: Key 健康度评分缓存的刷新间隔时间（秒）。默认 600 秒 (10 分钟)。
CACHE_REFRESH_INTERVAL_SECONDS: int = int(
    os.environ.get("CACHE_REFRESH_INTERVAL_SECONDS", "600")
)

# --- Gemini 安全设置 ---
# 定义标准的 Gemini API 安全设置，默认将所有类别的阈值设为 BLOCK_NONE (不阻止)。
safety_settings: List[Dict[str, str]] = [
    {"category": c, "threshold": "BLOCK_NONE"}
    for c in [
        "HARM_CATEGORY_HARASSMENT",  # 骚扰内容
        "HARM_CATEGORY_HATE_SPEECH",  # 仇恨言论
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",  # 色情内容
        "HARM_CATEGORY_DANGEROUS_CONTENT",  # 危险内容
        # "HARM_CATEGORY_CIVIC_INTEGRITY", # 公民诚信 (可能较新，根据需要添加)
    ]
]

# 定义另一套安全设置，将所有阈值设为 OFF (完全关闭安全过滤)。
# 这套设置在全局 DISABLE_SAFETY_FILTERING 为 True 时，或针对特定模型（如实验性模型）时使用。
safety_settings_g2: List[Dict[str, str]] = [
    {
        "category": c,
        "threshold": "BLOCK_NONE",
    }  # 注意：Gemini API 可能没有 'OFF' 阈值，BLOCK_NONE 是最低设置
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
CONTEXT_DB_PATH: Optional[str] = os.environ.get("CONTEXT_DB_PATH")

# DEFAULT_MAX_CONTEXT_TOKENS: 默认的最大上下文 Token 数量，用于截断对话历史。默认 30000。
DEFAULT_MAX_CONTEXT_TOKENS: int = int(
    os.environ.get("DEFAULT_MAX_CONTEXT_TOKENS", "30000")
)
# CONTEXT_TOKEN_SAFETY_MARGIN: 在截断上下文时保留的安全边际 Token 数。默认 200。
CONTEXT_TOKEN_SAFETY_MARGIN: int = int(
    os.environ.get("CONTEXT_TOKEN_SAFETY_MARGIN", "200")
)
# DEFAULT_CONTEXT_TTL_DAYS: 上下文记录的默认生存时间（天）。默认 7 天。
# 注意：此设置可能与数据库中的 'context_ttl_days' 设置交互。
DEFAULT_CONTEXT_TTL_DAYS: int = int(
    os.environ.get("DEFAULT_CONTEXT_TTL_DAYS", "7")
)  # 默认 7 天

# MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS: 内存数据库模式下，后台清理任务的运行间隔（秒）。默认 3600 秒 (1 小时)。
MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS: int = int(
    os.environ.get("MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS", "3600")
)
# MAX_CONTEXT_RECORDS_MEMORY: 内存数据库模式下，允许存储的最大上下文记录数量。超过此数量将清理最旧的记录。默认 5000。
MAX_CONTEXT_RECORDS_MEMORY: int = int(
    os.environ.get("MAX_CONTEXT_RECORDS_MEMORY", "5000")
)

# CONTEXT_STORAGE_MODE: 控制对话上下文的存储和加载方式。
# - 'database': 从 SQLite 数据库加载和管理上下文 (如果 CONTEXT_DB_PATH 已设置)。
# - 'memory': 在内存中临时管理上下文 (应用重启后数据丢失)。
# 默认为 'memory'，特别是在 CONTEXT_DB_PATH 未设置时。
_context_storage_mode_env = os.environ.get("CONTEXT_STORAGE_MODE", "memory").lower()
if _context_storage_mode_env not in ["database", "memory"]:
    logger.warning(
        f"无效的环境变量 CONTEXT_STORAGE_MODE 值 '{os.environ.get('CONTEXT_STORAGE_MODE')}'。将使用默认值 'memory'。"
    )
    _final_context_storage_mode: str = "memory"
elif _context_storage_mode_env == "database" and not CONTEXT_DB_PATH:
    logger.warning(
        "CONTEXT_STORAGE_MODE 设置为 'database'，但 CONTEXT_DB_PATH 未设置。将强制使用 'memory' 模式。"
    )
    _final_context_storage_mode = "memory"
else:
    _final_context_storage_mode = _context_storage_mode_env
CONTEXT_STORAGE_MODE: str = _final_context_storage_mode
logger.info(f"上下文存储模式设置为: {CONTEXT_STORAGE_MODE}")

# ENABLE_CONTEXT_COMPLETION: 全局默认是否启用传统上下文补全功能。默认为 True。
# 可以被单个 Key 的配置覆盖。如果 ENABLE_NATIVE_CACHING 为 True，此设置会被忽略。
ENABLE_CONTEXT_COMPLETION: bool = (
    os.environ.get("ENABLE_CONTEXT_COMPLETION", "true").lower() == "true"
)

# STREAM_SAVE_REPLY: (可能已废弃) 是否在流式响应结束后尝试保存模型回复到上下文。默认为 False。
# 保存流式回复可能增加因连接中断导致上下文丢失的风险。
STREAM_SAVE_REPLY: bool = os.environ.get("STREAM_SAVE_REPLY", "false").lower() == "true"
# ENABLE_STICKY_SESSION: 是否启用粘性会话功能。如果启用，Key 选择器会优先尝试用户上次使用的 Key。默认为 False。
ENABLE_STICKY_SESSION: bool = (
    os.environ.get("ENABLE_STICKY_SESSION", "false").lower() == "true"
)

# --- HTTP 客户端超时配置 ---
# HTTP_TIMEOUT_CONNECT: HTTP客户端连接超时时间（秒）。默认 10 秒。
_default_http_connect_timeout = 10.0
try:
    _http_connect_timeout = float(
        os.environ.get("HTTP_TIMEOUT_CONNECT", str(_default_http_connect_timeout))
    )
    # 确保超时大于 0
    if _http_connect_timeout <= 0:
        logger.warning(
            f"环境变量 HTTP_TIMEOUT_CONNECT ({os.environ.get('HTTP_TIMEOUT_CONNECT')}) 必须为正数，将使用默认值 {_default_http_connect_timeout} 秒。"
        )
        _http_connect_timeout = _default_http_connect_timeout
except ValueError:
    logger.warning(
        f"无法将环境变量 HTTP_TIMEOUT_CONNECT ('{os.environ.get('HTTP_TIMEOUT_CONNECT')}') 解析为数字，将使用默认值 {_default_http_connect_timeout} 秒。"
    )
    _http_connect_timeout = _default_http_connect_timeout
HTTP_TIMEOUT_CONNECT: float = _http_connect_timeout

# HTTP_TIMEOUT_READ: HTTP客户端读取超时时间（秒）。默认 30 秒。
_default_http_read_timeout = 30.0
try:
    _http_read_timeout = float(
        os.environ.get("HTTP_TIMEOUT_READ", str(_default_http_read_timeout))
    )
    # 确保超时大于 0
    if _http_read_timeout <= 0:
        logger.warning(
            f"环境变量 HTTP_TIMEOUT_READ ({os.environ.get('HTTP_TIMEOUT_READ')}) 必须为正数，将使用默认值 {_default_http_read_timeout} 秒。"
        )
        _http_read_timeout = _default_http_read_timeout
except ValueError:
    logger.warning(
        f"无法将环境变量 HTTP_TIMEOUT_READ ('{os.environ.get('HTTP_TIMEOUT_READ')}') 解析为数字，将使用默认值 {_default_http_read_timeout} 秒。"
    )
    _http_read_timeout = _default_http_read_timeout
HTTP_TIMEOUT_READ: float = _http_read_timeout

# HTTP_TIMEOUT_WRITE: HTTP客户端写入超时时间（秒）。默认 30 秒。
_default_http_write_timeout = 30.0
try:
    _http_write_timeout = float(
        os.environ.get("HTTP_TIMEOUT_WRITE", str(_default_http_write_timeout))
    )
    # 确保超时大于 0
    if _http_write_timeout <= 0:
        logger.warning(
            f"环境变量 HTTP_TIMEOUT_WRITE ({os.environ.get('HTTP_TIMEOUT_WRITE')}) 必须为正数，将使用默认值 {_default_http_write_timeout} 秒。"
        )
        _http_write_timeout = _default_http_write_timeout
except ValueError:
    logger.warning(
        f"无法将环境变量 HTTP_TIMEOUT_WRITE ('{os.environ.get('HTTP_TIMEOUT_WRITE')}') 解析为数字，将使用默认值 {_default_http_write_timeout} 秒。"
    )
    _http_write_timeout = _default_http_write_timeout
HTTP_TIMEOUT_WRITE: float = _http_write_timeout

# HTTP_TIMEOUT_POOL: HTTP客户端连接池超时时间（秒）。默认 30 秒。
_default_http_pool_timeout = 30.0
try:
    _http_pool_timeout = float(
        os.environ.get("HTTP_TIMEOUT_POOL", str(_default_http_pool_timeout))
    )
    # 确保超时大于 0
    if _http_pool_timeout <= 0:
        logger.warning(
            f"环境变量 HTTP_TIMEOUT_POOL ({os.environ.get('HTTP_TIMEOUT_POOL')}) 必须为正数，将使用默认值 {_default_http_pool_timeout} 秒。"
        )
        _http_pool_timeout = _default_http_pool_timeout
except ValueError:
    logger.warning(
        f"无法将环境变量 HTTP_TIMEOUT_POOL ('{os.environ.get('HTTP_TIMEOUT_POOL')}') 解析为数字，将使用默认值 {_default_http_pool_timeout} 秒。"
    )
    _http_pool_timeout = _default_http_pool_timeout
HTTP_TIMEOUT_POOL: float = _http_pool_timeout

# --- API 操作超时配置 ---
# API_TIMEOUT_MODELS_LIST: 获取可用模型列表的超时时间（秒）。默认 60 秒。
_default_api_models_timeout = 60.0
try:
    _api_models_timeout = float(
        os.environ.get("API_TIMEOUT_MODELS_LIST", str(_default_api_models_timeout))
    )
    # 确保超时大于 0
    if _api_models_timeout <= 0:
        logger.warning(
            f"环境变量 API_TIMEOUT_MODELS_LIST ({os.environ.get('API_TIMEOUT_MODELS_LIST')}) 必须为正数，将使用默认值 {_default_api_models_timeout} 秒。"
        )
        _api_models_timeout = _default_api_models_timeout
except ValueError:
    logger.warning(
        f"无法将环境变量 API_TIMEOUT_MODELS_LIST ('{os.environ.get('API_TIMEOUT_MODELS_LIST')}') 解析为数字，将使用默认值 {_default_api_models_timeout} 秒。"
    )
    _api_models_timeout = _default_api_models_timeout
API_TIMEOUT_MODELS_LIST: float = _api_models_timeout

# API_TIMEOUT_KEY_TEST: API Key测试验证的超时时间（秒）。默认 10 秒。
_default_api_key_test_timeout = 10.0
try:
    _api_key_test_timeout = float(
        os.environ.get("API_TIMEOUT_KEY_TEST", str(_default_api_key_test_timeout))
    )
    # 确保超时大于 0
    if _api_key_test_timeout <= 0:
        logger.warning(
            f"环境变量 API_TIMEOUT_KEY_TEST ({os.environ.get('API_TIMEOUT_KEY_TEST')}) 必须为正数，将使用默认值 {_default_api_key_test_timeout} 秒。"
        )
        _api_key_test_timeout = _default_api_key_test_timeout
except ValueError:
    logger.warning(
        f"无法将环境变量 API_TIMEOUT_KEY_TEST ('{os.environ.get('API_TIMEOUT_KEY_TEST')}') 解析为数字，将使用默认值 {_default_api_key_test_timeout} 秒。"
    )
    _api_key_test_timeout = _default_api_key_test_timeout
API_TIMEOUT_KEY_TEST: float = _api_key_test_timeout

# --- API Key 存储模式配置 ---
# KEY_STORAGE_MODE: 控制 API Key 的存储和加载方式。
# - 'database': 从 SQLite 数据库加载和管理 Key (推荐用于生产)。
# - 'memory': 从环境变量 `GEMINI_API_KEYS` 加载 Key，并在内存中临时管理 (适用于简单部署或测试)。
# 默认为 'memory'。
_key_storage_mode_env = os.environ.get(
    "KEY_STORAGE_MODE", "memory"
).lower()  # 读取环境变量并转小写
# 验证环境变量值是否有效
if _key_storage_mode_env not in ["database", "memory"]:
    logger.warning(
        f"无效的环境变量 KEY_STORAGE_MODE 值 '{os.environ.get('KEY_STORAGE_MODE')}'。将使用默认值 'memory'。"
    )  # 记录警告
    _final_key_storage_mode: str = "memory"  # 使用默认值
else:
    _final_key_storage_mode = _key_storage_mode_env  # 使用环境变量值
KEY_STORAGE_MODE: str = _final_key_storage_mode
logger.info(f"API Key 存储模式设置为: {KEY_STORAGE_MODE}")  # 记录最终使用的模式

# GEMINI_API_KEYS: 在内存模式 (`KEY_STORAGE_MODE='memory'`) 下使用的 API Key 列表，从环境变量读取，用逗号分隔。
GEMINI_API_KEYS: Optional[str] = os.environ.get("GEMINI_API_KEYS")
# 如果是内存模式但未提供 GEMINI_API_KEYS 环境变量，记录警告
if KEY_STORAGE_MODE == "memory" and not GEMINI_API_KEYS:
    logger.warning(
        "KEY_STORAGE_MODE 设置为 'memory'，但未找到 GEMINI_API_KEYS 环境变量。内存模式下将没有可用的 API Key。"
    )


# --- 模型限制配置 ---
# MODEL_LIMITS: 存储从 JSON 文件加载的各模型速率限制和 Token 限制的字典。
# 结构: {model_name: {"rpd": int, "rpm": int, "tpd_input": int, "tpm_input": int, "input_token_limit": int, ...}}
MODEL_LIMITS: Dict[str, Any] = (
    {}
)  # 声明 MODEL_LIMITS 为字典类型，并在此处初始化为空字典


def load_model_limits():
    """
    从位于 `app/data/model_limits.json` 的 JSON 文件加载模型限制数据，
    并填充到全局变量 `MODEL_LIMITS` 字典中。
    在应用启动时由 `main.py` 中的 `lifespan` 函数调用。

    Returns:
        Dict[str, Any]: 包含模型限制配置的字典

    Raises:
        ValueError: 当模型限制文件存在但内容格式错误时
    """
    # 初始化为空字典，用于存储加载的数据
    model_limits_data: Dict[str, Any] = {}

    # 获取当前文件 (config.py) 所在的目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 构建模型限制 JSON 文件的正确路径
    model_limits_path = os.path.join(current_dir, "data", "model_limits.json")

    logger.info(f"尝试从 {model_limits_path} 加载模型限制...")

    try:
        # 检查文件是否存在
        if not os.path.exists(model_limits_path):
            logger.warning(
                f"模型限制文件未找到: {model_limits_path}。将使用内置默认限制。"
            )
            # 返回内置默认模型限制
            model_limits_data = _get_default_model_limits()
            logger.info(
                f"使用内置默认限制。加载的模型: {list(model_limits_data.keys())}"
            )
            return model_limits_data

        # 检查文件权限
        if not os.access(model_limits_path, os.R_OK):
            logger.error(f"无法读取模型限制文件: {model_limits_path}。请检查文件权限。")
            return _get_default_model_limits()

        # 获取文件大小检查
        file_size = os.path.getsize(model_limits_path)
        if file_size == 0:
            logger.error(f"模型限制文件为空: {model_limits_path}。将使用内置默认限制。")
            return _get_default_model_limits()

        # 以 UTF-8 编码打开并读取文件内容
        with open(model_limits_path, "r", encoding="utf-8") as f:
            try:
                raw_data = f.read()
                if not raw_data.strip():
                    logger.error(
                        f"模型限制文件内容为空: {model_limits_path}。将使用内置默认限制。"
                    )
                    return _get_default_model_limits()

                model_limits_data = json.loads(raw_data)

                # 验证 JSON 是否为字典
                if not isinstance(model_limits_data, dict):
                    raise ValueError("模型限制文件的根元素必须是字典")

            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {model_limits_path} - {e}")
                logger.error("请检查JSON格式是否正确。建议使用JSON验证工具检查文件。")
                return _get_default_model_limits()
            except ValueError as e:
                logger.error(f"数据结构验证失败: {model_limits_path} - {e}")
                return _get_default_model_limits()

        # 验证和清理加载的数据
        validated_limits = {}
        validation_errors = []
        validation_warnings = []

        for model_name, limits in model_limits_data.items():
            if not isinstance(model_name, str) or not model_name.strip():
                validation_errors.append("发现无效的模型名称")
                continue

            model_name = model_name.strip()

            if not isinstance(limits, dict):
                validation_errors.append(f"模型 '{model_name}' 的限制数据不是字典格式")
                continue

            # 验证必需字段
            required_fields = [
                "rpd",
                "rpm",
                "tpd_input",
                "tpm_input",
                "input_token_limit",
                "output_token_limit",
            ]
            missing_fields = [field for field in required_fields if field not in limits]

            if missing_fields:
                validation_errors.append(
                    f"模型 '{model_name}' 缺少必需字段: {', '.join(missing_fields)}"
                )
                continue

            # 验证数值类型和范围
            validated_model_limits = {}
            model_warnings = []

            for field in required_fields:
                value = limits[field]

                # 检查是否为数字
                if not isinstance(value, (int, float)):
                    validation_errors.append(
                        f"模型 '{model_name}' 的字段 '{field}' 必须为数字，当前类型: {type(value).__name__}"
                    )
                    continue

                # 检查是否为正数
                if value <= 0:
                    validation_errors.append(
                        f"模型 '{model_name}' 的字段 '{field}' 必须为正数，当前值: {value}"
                    )
                    continue

                # 检查合理性范围
                if field == "rpm" and value > 1000:
                    model_warnings.append(
                        f"模型 '{model_name}' 的RPM值过高 ({value})，可能不符合API限制"
                    )
                elif field == "rpd" and value > 10000:
                    model_warnings.append(
                        f"模型 '{model_name}' 的RPD值过高 ({value})，可能不符合API限制"
                    )
                elif field == "input_token_limit" and value > 2000000:
                    model_warnings.append(
                        f"模型 '{model_name}' 的输入token限制过高 ({value})，请确认是否正确"
                    )
                elif field == "input_token_limit" and value < 1000:
                    model_warnings.append(
                        f"模型 '{model_name}' 的输入token限制过低 ({value})"
                    )
                elif field == "output_token_limit" and value < 100:
                    model_warnings.append(
                        f"模型 '{model_name}' 的输出token限制过低 ({value})"
                    )

                validated_model_limits[field] = (
                    int(value)
                    if isinstance(value, float) and value.is_integer()
                    else value
                )

            # 检查可选字段
            optional_fields = ["tpd_output", "tpm_output"]
            for field in optional_fields:
                if field in limits:
                    value = limits[field]
                    if not isinstance(value, (int, float)) or value <= 0:
                        validation_errors.append(
                            f"模型 '{model_name}' 的可选字段 '{field}' 必须为正数"
                        )
                    else:
                        validated_model_limits[field] = (
                            int(value)
                            if isinstance(value, float) and value.is_integer()
                            else value
                        )

            validated_limits[model_name] = validated_model_limits
            validation_warnings.extend(model_warnings)

        # 记录验证结果
        if validation_errors:
            logger.error(f"模型限制验证失败，发现 {len(validation_errors)} 个错误:")
            for error in validation_errors:
                logger.error(f"  - {error}")
            logger.warning("使用内置默认限制作为fallback")
            return _get_default_model_limits()

        if validation_warnings:
            logger.warning(f"模型限制验证通过，但有 {len(validation_warnings)} 个警告:")
            for warning in validation_warnings:
                logger.warning(f"  - {warning}")

        # 成功验证和加载
        logger.info(
            f"成功加载并验证模型限制。验证通过的模型: {list(validated_limits.keys())}"
        )
        logger.info(f"共加载 {len(validated_limits)} 个模型的限制配置")

        return validated_limits

    except PermissionError as e:
        logger.error(f"权限错误，无法访问模型限制文件 {model_limits_path}: {e}")
        return _get_default_model_limits()
    except OSError as e:
        logger.error(f"系统错误，无法读取模型限制文件 {model_limits_path}: {e}")
        return _get_default_model_limits()
    except Exception as e:
        logger.error(f"加载模型限制时发生未知错误: {e}", exc_info=True)
        return _get_default_model_limits()


def _get_default_model_limits() -> Dict[str, Any]:
    """
    获取内置默认模型限制配置

    Returns:
        Dict[str, Any]: 默认的模型限制配置
    """
    logger.info("使用内置默认模型限制配置")

    return {
        "gemini-1.5-pro-latest": {
            "rpd": 1000,
            "rpm": 60,
            "tpd_input": 2000000,
            "tpm_input": 32000,
            "input_token_limit": 1048576,
            "output_token_limit": 8192,
        },
        "gemini-1.5-flash-latest": {
            "rpd": 1500,
            "rpm": 100,
            "tpd_input": 1000000000,
            "tpm_input": 4000000,
            "input_token_limit": 1048576,
            "output_token_limit": 8192,
        },
        "gemini-1.0-pro": {
            "rpd": 1500,
            "rpm": 100,
            "tpd_input": 3000000,
            "tpm_input": 60000,
            "input_token_limit": 30720,
            "output_token_limit": 2048,
        },
        "gemini-pro": {
            "rpd": 1000,
            "rpm": 60,
            "tpd_input": 2000000,
            "tpm_input": 32000,
            "input_token_limit": 1048576,
            "output_token_limit": 8192,
        },
    }


def validate_model_limits(
    model_limits: Dict[str, Any],
) -> Tuple[bool, List[str], List[str]]:
    """
    验证模型限制配置的完整性

    Args:
        model_limits: 要验证的模型限制字典

    Returns:
        Tuple[bool, List[str], List[str]]: (是否有效, 错误列表, 警告列表)
    """
    errors = []
    warnings = []

    if not model_limits:
        errors.append("模型限制配置为空")
        return False, errors, warnings

    required_fields = [
        "rpd",
        "rpm",
        "tpd_input",
        "tpm_input",
        "input_token_limit",
        "output_token_limit",
    ]

    for model_name, limits in model_limits.items():
        if not isinstance(limits, dict):
            errors.append(f"模型 '{model_name}' 的配置必须为字典类型")
            continue

        # 检查必需字段
        missing_fields = [field for field in required_fields if field not in limits]
        if missing_fields:
            errors.append(
                f"模型 '{model_name}' 缺少必需字段: {', '.join(missing_fields)}"
            )

        # 检查字段类型和值
        for field, value in limits.items():
            if not isinstance(value, (int, float)):
                errors.append(f"模型 '{model_name}' 的字段 '{field}' 必须为数字")
            elif value <= 0:
                errors.append(f"模型 '{model_name}' 的字段 '{field}' 必须为正数")
            elif field == "input_token_limit" and value > 2000000:
                warnings.append(f"模型 '{model_name}' 的输入token限制过高 ({value})")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


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
ENABLE_NATIVE_CACHING: bool = (
    os.environ.get("ENABLE_NATIVE_CACHING", "false").lower() == "true"
)

# --- 测试和调试配置 ---
# TESTING: 标识是否为测试环境
TESTING: str = os.environ.get("TESTING", "false").lower()

# LOG_LEVEL: 应用程序日志级别
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

# DATABASE_URL: 数据库连接URL
DATABASE_URL: Optional[str] = os.environ.get("DATABASE_URL")

# REDIS_URL: Redis连接URL
REDIS_URL: Optional[str] = os.environ.get("REDIS_URL")
