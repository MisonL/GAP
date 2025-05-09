# -*- coding: utf-8 -*-
"""
日志配置和管理模块。
负责设置应用程序的日志记录器，包括日志级别、格式、输出目标（控制台和文件）、
日志轮转以及旧日志文件的清理。
"""
# 导入必要的库
import logging  # Python 标准日志库
import os       # 用于路径操作和访问环境变量
import sys      # 用于系统相关操作（例如设置退出钩子）
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler  # 日志文件轮转处理器
from datetime import datetime  # 用于获取当前日期和时间
import tempfile # 用于获取系统临时目录路径
from typing import Optional, Dict, Any, List # 导入类型提示

# --- 日志目录设置 ---
# 尝试在项目根目录下创建 'logs' 文件夹来存储日志文件
log_dir = None # 初始化日志目录变量
try:
    # 动态计算项目根目录路径 (假设此文件位于 app/handlers/ 下)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(project_root, 'logs')  # 定义日志目录路径
    os.makedirs(log_dir, exist_ok=True)  # 创建目录，如果已存在则忽略
    print(f"日志目录设置为: {log_dir}") # 打印日志目录路径
except PermissionError: # 如果因权限问题无法在项目目录创建
    # 尝试在系统临时目录下创建
    log_dir = os.path.join(tempfile.gettempdir(), 'gemini_api_proxy_logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
        print(f"警告: 无法在项目目录创建日志文件夹，将使用系统临时目录: {log_dir}") # 打印警告
    except Exception as temp_e: # 如果在临时目录创建也失败
        log_dir = None # 禁用文件日志
        print(f"警告: 尝试在项目目录和临时目录创建日志文件夹均失败: {temp_e}。文件日志记录将被禁用。") # 打印最终警告
except Exception as e: # 捕获其他创建目录的异常
    # 尝试在当前工作目录下创建
    log_dir = os.path.join(os.getcwd(), 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
        print(f"警告: 在项目目录创建日志文件夹失败 ({e})，将尝试使用当前工作目录: {log_dir}") # 打印警告
    except Exception as final_e: # 如果所有尝试都失败
        log_dir = None # 禁用文件日志
        print(f"警告: 尝试在多个位置创建日志目录均失败: {final_e}。文件日志记录将被禁用。") # 打印最终警告

# --- 日志文件路径定义 ---
if log_dir: # 仅当日志目录有效时定义文件路径
    app_log_file = os.path.join(log_dir, 'app.log')      # 应用主日志文件路径
    error_log_file = os.path.join(log_dir, 'error.log')    # 错误日志文件路径
    access_log_file = os.path.join(log_dir, 'access.log')  # 访问日志文件路径 (暂未使用)
else: # 如果日志目录无效
    app_log_file = error_log_file = access_log_file = None # 将所有文件路径设为 None

# --- 日志格式配置 ---
# 从环境变量读取 DEBUG 模式设置，默认为 "false"
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
# 定义 DEBUG 模式下的详细日志格式，包含更多上下文信息
LOG_FORMAT_DEBUG = '%(asctime)s - %(levelname)s - %(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s%(error_fmt)s'
# 定义普通模式下的简洁日志格式
LOG_FORMAT_NORMAL = '%(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s'

# --- 日志轮转配置 ---
# 从环境变量读取单个日志文件最大大小 (MB)，转换为字节，默认 10MB
MAX_LOG_SIZE = int(os.environ.get("MAX_LOG_SIZE", "10")) * 1024 * 1024
# 从环境变量读取保留的备份文件数量，默认 5 个
MAX_LOG_BACKUPS = int(os.environ.get("MAX_LOG_BACKUPS", "5"))
# 从环境变量读取错误日志轮转的时间间隔单位 (when)，默认 'midnight' (每天午夜)
# 其他可选值: 'S', 'M', 'H', 'D', 'W0'-'W6' (每周的某一天)
LOG_ROTATION_INTERVAL = os.environ.get("LOG_ROTATION_INTERVAL", "midnight")
# 从环境变量读取日志文件的最大保留天数，默认 30 天
LOG_CLEANUP_DAYS = int(os.environ.get("LOG_CLEANUP_DAYS", "30"))

def setup_logger():
    """
    配置并返回应用程序使用的日志记录器 (`logging.Logger`) 实例。
    - 设置日志级别（基于 DEBUG 环境变量）。
    - 添加控制台处理程序 (StreamHandler) 用于将日志输出到标准错误流。
    - 如果日志目录有效，添加文件处理程序 (RotatingFileHandler 和 TimedRotatingFileHandler)
      用于将日志写入文件，并配置日志轮转。

    Returns:
        logging.Logger: 配置好的日志记录器实例。
    """
    # 获取名为 'my_logger' 的日志记录器实例 (确保与应用中其他地方使用的名称一致)
    logger = logging.getLogger("my_logger")
    # 根据 DEBUG 环境变量设置日志记录器的基础级别 (DEBUG 或 WARNING)
    base_log_level = logging.DEBUG if DEBUG else logging.WARNING
    logger.setLevel(base_log_level)
    print(f"日志基础级别设置为: {logging.getLevelName(base_log_level)}") # 打印启动信息

    # 清除可能由先前配置或库添加的任何现有处理程序，以避免日志重复输出
    if logger.hasHandlers(): # 检查是否存在处理程序
        logger.handlers.clear() # 清空处理程序列表

    # --- 配置控制台处理程序 ---
    console_handler = logging.StreamHandler()  # 创建一个流处理程序，默认输出到 sys.stderr
    # 设置控制台输出的日志级别 (DEBUG 模式下输出 DEBUG 及以上，否则输出 INFO 及以上)
    console_log_level = logging.DEBUG if DEBUG else logging.INFO
    console_handler.setLevel(console_log_level)
    print(f"控制台日志级别设置为: {logging.getLevelName(console_log_level)}") # 打印启动信息
    # 为控制台输出定义一个简洁的格式化器，通常只包含消息本身
    formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(formatter)    # 应用格式化器
    logger.addHandler(console_handler)         # 将控制台处理程序添加到记录器

    # --- 配置文件处理程序 (仅当日志目录有效时) ---
    if log_dir:
        try:
            # 定义通用的文件日志格式化器 (包含时间戳、级别和消息)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s', # 日志格式字符串
                datefmt='%Y-%m-%d %H:%M:%S' # 日期时间格式
            )

            # --- 配置应用主日志文件处理程序 (app.log) ---
            if app_log_file: # 检查应用日志文件路径是否有效
                try:
                    # 使用 RotatingFileHandler 实现基于文件大小的轮转
                    file_handler = RotatingFileHandler(
                        app_log_file,                  # 日志文件路径
                        maxBytes=MAX_LOG_SIZE,         # 单个文件最大大小 (字节)
                        backupCount=MAX_LOG_BACKUPS,   # 保留的备份文件数量
                        encoding='utf-8'               # 使用 UTF-8 编码
                    )
                    file_handler.setLevel(logging.DEBUG)  # 应用日志记录 DEBUG 及以上级别
                    file_handler.setFormatter(file_formatter) # 设置文件日志格式
                    logger.addHandler(file_handler)         # 添加到记录器
                    print(f"应用日志将写入: {app_log_file}") # 打印日志文件路径
                except Exception as e: # 捕获创建处理程序时的错误
                    print(f"警告: 无法创建应用日志处理程序 ({app_log_file}): {e}") # 打印警告

            # --- 配置错误日志文件处理程序 (error.log) ---
            if error_log_file: # 检查错误日志文件路径是否有效
                try:
                    # 使用 TimedRotatingFileHandler 实现基于时间的轮转
                    error_handler = TimedRotatingFileHandler(
                        error_log_file,                # 日志文件路径
                        when=LOG_ROTATION_INTERVAL,    # 轮转时间间隔单位 (例如 'midnight')
                        backupCount=MAX_LOG_BACKUPS,   # 保留的备份文件数量
                        encoding='utf-8'               # 使用 UTF-8 编码
                    )
                    error_handler.setLevel(logging.ERROR) # 错误日志只记录 ERROR 及以上级别
                    error_handler.setFormatter(file_formatter) # 设置文件日志格式
                    logger.addHandler(error_handler)         # 添加到记录器
                    print(f"错误日志将写入: {error_log_file}") # 打印日志文件路径
                except Exception as e: # 捕获创建处理程序时的错误
                    print(f"警告: 无法创建错误日志处理程序 ({error_log_file}): {e}") # 打印警告

        except Exception as e: # 捕获设置文件日志时的其他异常
            print(f"警告: 设置文件日志处理程序时出错: {e}")
            # 即使文件日志设置失败，控制台日志仍然可用

    return logger # 返回配置好的日志记录器实例

def format_log_message(level: str, message: str, extra: Optional[Dict[str, Any]] = None) -> str:
    """
    根据日志级别、主要消息和可选的附加信息，格式化日志消息字符串。
    在 DEBUG 模式下使用更详细的格式，包含时间戳、级别和所有附加信息。
    在普通模式下使用更简洁的格式，只包含关键附加信息和主要消息。

    Args:
        level (str): 日志级别字符串 (例如 'INFO', 'ERROR')。
        message (str): 主要的日志消息内容。
        extra (Optional[Dict[str, Any]]): 包含额外上下文信息的字典。
                                           支持的键: 'key', 'request_type', 'model', 'status_code', 'error_message'。
                                           默认为 None。

    Returns:
        str: 格式化后的日志消息字符串。
    """
    extra = extra or {}  # 如果 extra 为 None，则初始化为空字典

    # --- 从 extra 字典中安全地提取字段值 ---
    # 使用 .get() 方法提供默认空字符串，避免因缺少键而引发 KeyError
    key = extra.get('key', '')             # API Key (或其前缀)
    request_type = extra.get('request_type', '') # 请求类型 (例如 'chat', 'list_models')
    model = extra.get('model', '')           # 模型名称
    status_code = extra.get('status_code', '') # HTTP 状态码
    error_message = extra.get('error_message', '') # 具体的错误消息

    # --- 条件格式化附加信息 ---
    # 仅当字段值不为空时，才添加格式化的前缀或后缀
    key_fmt = f"[{key}]-" if key else ""             # 格式: "[key]-" 或 ""
    model_fmt = f"[{model}]-" if model else ""       # 格式: "[model]-" 或 ""
    error_fmt = f" - {error_message}" if error_message else "" # 格式: " - error_message" 或 ""
    # 对于 request_type 和 status_code，如果为空则直接使用空字符串，避免添加多余的空格或连字符

    # --- 构建用于格式化字符串的值字典 ---
    log_values = {
        'asctime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # 当前时间字符串
        'levelname': level,             # 日志级别
        'key_fmt': key_fmt,             # 格式化后的 Key 前缀
        'request_type': request_type if request_type else '', # 请求类型
        'model_fmt': model_fmt,         # 格式化后的模型前缀
        'status_code': status_code if status_code else '', # 状态码
        'error_fmt': error_fmt,         # 格式化后的错误消息后缀
        'message': message              # 主要日志消息
    }
    # --- 选择日志格式并应用 ---
    # 根据全局 DEBUG 变量选择详细格式或普通格式
    log_format = LOG_FORMAT_DEBUG if DEBUG else LOG_FORMAT_NORMAL
    # 使用字符串格式化操作符 (%) 将值填充到选定的格式字符串中
    return log_format % log_values

def cleanup_old_logs(max_days: int = LOG_CLEANUP_DAYS):
    """
    清理指定日志目录中最后修改时间早于 `max_days` 天前的日志文件。
    这包括主日志文件 (`.log`) 和由轮转处理程序生成的备份文件 (`.log.*`)。

    Args:
        max_days (int): 日志文件的最大保留天数。默认为 `LOG_CLEANUP_DAYS` 配置值。
    """
    import glob  # 导入 glob 模块，用于查找文件路径名模式
    import time  # 导入 time 模块，用于获取时间戳

    # 检查日志目录是否有效
    if not log_dir:
        print("信息: 日志目录无效，跳过日志清理。") # 打印提示信息
        return # 直接返回

    try:
        now = time.time()  # 获取当前时间戳 (秒)
        # 计算最大保留时间的秒数
        max_age = max_days * 86400  # 1 天 = 24 * 60 * 60 = 86400 秒

        # 使用 glob 查找日志目录下所有匹配 '*.log*' 的文件
        # 这会匹配 .log 文件以及 .log.1, .log.2, .log.YYYY-MM-DD 等备份文件
        log_files = glob.glob(os.path.join(log_dir, '*.log*'))

        deleted_count = 0 # 初始化已删除文件计数器
        # 遍历找到的所有日志文件路径
        for file_path in log_files:
            try:
                # 获取文件的最后修改时间戳
                file_mtime = os.path.getmtime(file_path)

                # 计算文件的“年龄”（当前时间 - 最后修改时间）
                # 如果文件年龄超过了最大保留秒数
                if now - file_mtime > max_age:
                    try:
                        # 尝试删除过期的日志文件
                        os.remove(file_path)
                        deleted_count += 1 # 增加计数
                        # 可以取消注释以下行来记录每个被删除的文件
                        # logger.info(f"已删除过期日志文件: {file_path}")
                    except OSError as e: # 捕获删除文件时可能发生的操作系统错误
                        # 记录删除失败的错误，但继续处理其他文件
                        print(f"删除日志文件失败 {file_path}: {e}")
            except FileNotFoundError: # 如果在处理过程中文件被意外删除
                 # 忽略此错误，继续处理下一个文件
                 continue
            except Exception as e: # 捕获获取文件信息或比较时间时的其他错误
                # 记录处理单个文件时的错误
                print(f"处理日志文件时出错 {file_path}: {e}")

        # 清理完成后打印总结信息
        if deleted_count > 0: # 如果删除了文件
            print(f"日志清理完成，共删除 {deleted_count} 个超过 {max_days} 天的日志文件。")
        else: # 如果没有删除文件
            print(f"日志清理完成，没有找到超过 {max_days} 天的日志文件需要删除。")
    except Exception as e: # 捕获日志清理顶层逻辑中的任何其他异常
        print(f"执行日志清理任务时发生错误: {e}")
        # 注意：即使日志清理失败，也不应影响主应用程序的运行
