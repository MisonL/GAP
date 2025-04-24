# 导入必要的库
# Import necessary libraries
import logging  # Python 标准日志库 (Python standard logging library)
import os       # 用于路径操作和访问环境变量 (Used for path operations and accessing environment variables)
import sys      # 用于系统相关操作（例如设置退出钩子） (Used for system-related operations (e.g., setting exit hooks))
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler  # 日志文件轮转处理器 (Log file rotation handlers)
from datetime import datetime  # 用于获取当前日期和时间 (Used for getting current date and time)
import tempfile # 用于获取系统临时目录路径 (Used for getting system temporary directory path)

# --- 日志目录设置 ---
# --- Log Directory Setup ---
# 尝试创建日志目录，优先在项目根目录下的 'logs' 文件夹
# Attempt to create the log directory, prioritizing the 'logs' folder in the project root
try:
    # 获取当前文件所在目录的上级目录 (即项目根目录)
    # Get the parent directory of the current file's directory (i.e., project root)
    # !! 注意：这里的路径计算可能需要根据新的目录结构调整 !!
    # !! Note: The path calculation here might need adjustment based on the new directory structure !!
    # 假设 handlers 目录位于 app 目录下，而 app 目录位于项目根目录下
    # Assume the handlers directory is under the app directory, and the app directory is under the project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # 获取项目根目录路径 (Get project root directory path)
    log_dir = os.path.join(project_root, 'logs')  # 定义日志目录路径为 '项目根目录/logs' (Define log directory path as 'project_root/logs')
    os.makedirs(log_dir, exist_ok=True)  # 创建日志目录，如果目录已存在则忽略错误 (Create log directory, ignore error if directory already exists)
except PermissionError:
    # 如果在项目根目录下创建 'logs' 文件夹失败（例如因为权限不足）
    # If creating the 'logs' folder in the project root fails (e.g., due to insufficient permissions)
    # 则尝试在系统的临时目录下创建一个名为 'gemini_api_proxy_logs' 的文件夹
    # Then attempt to create a folder named 'gemini_api_proxy_logs' in the system's temporary directory
    log_dir = os.path.join(tempfile.gettempdir(), 'gemini_api_proxy_logs') # 定义临时日志目录路径 (Define temporary log directory path)
    os.makedirs(log_dir, exist_ok=True) # 尝试创建临时日志目录 (Attempt to create temporary log directory)
    print(f"警告: 无法在项目目录创建日志文件夹，将使用系统临时目录: {log_dir}") # 打印警告信息 (Print warning message)
except Exception as e:
    # 如果在项目根目录和临时目录创建都失败，则尝试在当前工作目录下创建 'logs' 文件夹
    # If creating in both project root and temporary directory fails, attempt to create a 'logs' folder in the current working directory
    log_dir = os.path.join(os.getcwd(), 'logs') # 定义当前工作目录下的日志目录路径 (Define log directory path in the current working directory)
    try:
        os.makedirs(log_dir, exist_ok=True) # 尝试在当前工作目录创建 (Attempt to create in current working directory)
    except Exception as final_e:
        # 如果所有尝试都失败了，则将 log_dir 设置为 None，禁用文件日志记录
        # If all attempts fail, set log_dir to None to disable file logging
        log_dir = None # 将日志目录设为 None (Set log directory to None)
        print(f"警告: 尝试在多个位置创建日志目录均失败: {final_e}。文件日志记录将被禁用。") # 打印最终警告信息 (Print final warning message)

# --- 日志文件路径定义 ---
# --- Log File Path Definition ---
if log_dir: # 如果日志目录有效 (If log directory is valid)
    # 如果成功创建了日志目录，定义各个日志文件的完整路径
    # If the log directory was successfully created, define the full paths for each log file
    app_log_file = os.path.join(log_dir, 'app.log')      # 应用主日志 (Application main log)
    error_log_file = os.path.join(log_dir, 'error.log')    # 错误日志 (Error log)
    access_log_file = os.path.join(log_dir, 'access.log')  # 访问日志 (暂未使用，但保留定义) (Access log (not currently used, but definition kept))
else:
    # 如果无法创建日志目录，则将文件路径设为 None，禁用文件日志记录
    # If the log directory cannot be created, set file paths to None to disable file logging
    app_log_file = error_log_file = access_log_file = None # 将文件路径设为 None (Set file paths to None)

# --- 日志格式配置 ---
# --- Log Format Configuration ---
# 从环境变量读取 DEBUG 模式设置，默认为 false
# Read DEBUG mode setting from environment variable, default is false
DEBUG = os.environ.get("DEBUG", "false").lower() == "true" # 获取 DEBUG 环境变量并转换为布尔值 (Get DEBUG environment variable and convert to boolean)
# 定义 DEBUG 模式下的详细日志格式
# Define detailed log format for DEBUG mode
LOG_FORMAT_DEBUG = '%(asctime)s - %(levelname)s - %(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s%(error_fmt)s' # DEBUG 模式日志格式 (DEBUG mode log format)
# 定义普通模式下的简洁日志格式
# Define concise log format for normal mode
LOG_FORMAT_NORMAL = '%(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s' # 普通模式日志格式 (Normal mode log format)

# --- 日志轮转配置 ---
# --- Log Rotation Configuration ---
# 从环境变量读取单个日志文件最大大小 (MB)，转换为字节，默认 10MB
# Read maximum size of a single log file (MB) from environment variable, convert to bytes, default 10MB
MAX_LOG_SIZE = int(os.environ.get("MAX_LOG_SIZE", "10")) * 1024 * 1024 # 计算最大日志文件大小 (Calculate max log file size)
# 从环境变量读取保留的备份文件数量，默认 5 个
# Read the number of backup files to keep from environment variable, default 5
MAX_LOG_BACKUPS = int(os.environ.get("MAX_LOG_BACKUPS", "5")) # 获取最大备份文件数量 (Get max number of backup files)
# 从环境变量读取日志轮转的时间间隔 (例如 'S', 'M', 'H', 'D', 'W0'-'W6', 'midnight')，默认 'midnight'
# Read the time interval for log rotation from environment variable (e.g., 'S', 'M', 'H', 'D', 'W0'-'W6', 'midnight'), default 'midnight'
LOG_ROTATION_INTERVAL = os.environ.get("LOG_ROTATION_INTERVAL", "midnight") # 获取日志轮转间隔 (Get log rotation interval)
# 从环境变量读取日志文件的最大保留天数，默认 30 天
# Read the maximum number of days to keep log files from environment variable, default 30 days
LOG_CLEANUP_DAYS = int(os.environ.get("LOG_CLEANUP_DAYS", "30")) # 获取日志清理天数 (Get log cleanup days)

def setup_logger():
    """
    配置并返回一个日志记录器实例。
    包含控制台输出和（如果可能）文件输出（应用日志、错误日志）。
    Configures and returns a logger instance.
    Includes console output and (if possible) file output (application log, error log).
    """
    # 获取名为 'my_logger' 的日志记录器实例
    # Get the logger instance named 'my_logger'
    logger = logging.getLogger("my_logger") # 获取日志记录器 (Get logger)
    # 根据 DEBUG 环境变量设置基础日志级别
    # Set base log level based on DEBUG environment variable
    base_log_level = logging.DEBUG if DEBUG else logging.INFO # 根据 DEBUG 设置基础日志级别 (Set base log level based on DEBUG)
    logger.setLevel(base_log_level) # 设置日志记录器级别 (Set logger level)
    print(f"日志基础级别设置为: {logging.getLevelName(base_log_level)}") # 添加启动时打印信息 (Add print info at startup)

    # 清除可能已存在的旧的处理程序，防止重复添加
    # Clear potentially existing old handlers to prevent duplicate additions
    if logger.handlers: # 如果存在处理程序 (If handlers exist)
        logger.handlers.clear() # 清除处理程序 (Clear handlers)

    # --- 控制台处理程序 ---
    # --- Console Handler ---
    console_handler = logging.StreamHandler()  # 创建流处理程序（默认输出到 stderr） (Create stream handler (defaults to stderr))
    # 控制台日志的级别也应根据 DEBUG 模式调整，或者固定为 INFO
    # The level of console logs should also be adjusted based on DEBUG mode, or fixed to INFO
    console_log_level = logging.DEBUG if DEBUG else logging.INFO # 根据 DEBUG 设置控制台日志级别 (Set console log level based on DEBUG)
    console_handler.setLevel(console_log_level) # 设置控制台处理程序的日志级别 (Set console handler level)
    print(f"控制台日志级别设置为: {logging.getLevelName(console_log_level)}") # 打印启动信息 (Print startup info)
    # 定义控制台输出的格式（通常只包含消息本身，以便更清晰地查看）
    # Define the format for console output (usually only includes the message itself for clearer viewing)
    formatter = logging.Formatter('%(message)s') # 创建格式器 (Create formatter)
    console_handler.setFormatter(formatter)    # 将格式器应用到处理程序 (Apply formatter to handler)
    logger.addHandler(console_handler)         # 将控制台处理程序添加到日志记录器 (Add console handler to logger)

    # --- 文件日志处理程序 ---
    # --- File Log Handlers ---
    # 仅在成功创建日志目录时才添加文件处理程序
    # Only add file handlers if the log directory was successfully created
    if log_dir: # 如果日志目录有效 (If log directory is valid)
        try:
            # 定义通用的文件日志格式 (包含时间、级别和消息)
            # Define a common file log format (including time, level, and message)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S' # 日期时间格式 (Date time format)
            )

            # --- 应用日志处理程序 (基于大小轮转) ---
            # --- Application Log Handler (Size-based rotation) ---
            if app_log_file: # 检查路径是否有效 (Check if path is valid)
                try:
                    # 创建按大小轮转的文件处理程序
                    # Create a size-based rotating file handler
                    file_handler = RotatingFileHandler(
                        app_log_file,                  # 日志文件路径 (Log file path)
                        maxBytes=MAX_LOG_SIZE,         # 单个文件最大字节数 (Maximum bytes per file)
                        backupCount=MAX_LOG_BACKUPS,   # 保留的备份文件数量 (Number of backup files to keep)
                        encoding='utf-8'               # 使用 UTF-8 编码 (Use UTF-8 encoding)
                    )
                    file_handler.setLevel(logging.DEBUG)  # 应用日志文件记录所有 DEBUG 及以上级别的日志 (Application log file records all logs at DEBUG level and above)
                    file_handler.setFormatter(file_formatter) # 应用通用的文件日志格式 (Apply common file log format)
                    logger.addHandler(file_handler)         # 将应用日志处理程序添加到记录器 (Add application log handler to logger)
                except Exception as e:
                    print(f"警告: 无法创建应用日志处理程序: {e}") # 打印警告信息 (Print warning message)

            # --- 错误日志处理程序 (基于时间轮转) ---
            # --- Error Log Handler (Time-based rotation) ---
            if error_log_file: # 检查路径是否有效 (Check if path is valid)
                try:
                    # 创建按时间轮转的文件处理程序
                    # Create a time-based rotating file handler
                    error_handler = TimedRotatingFileHandler(
                        error_log_file,                # 日志文件路径 (Log file path)
                        when=LOG_ROTATION_INTERVAL,    # 轮转时间间隔单位 (Time interval unit for rotation)
                        backupCount=MAX_LOG_BACKUPS,   # 保留的备份文件数量 (Number of backup files to keep)
                        encoding='utf-8'               # 使用 UTF-8 编码 (Use UTF-8 encoding)
                    )
                    error_handler.setLevel(logging.ERROR) # 错误日志文件只记录 ERROR 及以上级别的日志 (Error log file records only logs at ERROR level and above)
                    error_handler.setFormatter(file_formatter) # 应用通用的文件日志格式 (Apply common file log format)
                    logger.addHandler(error_handler)         # 将错误日志处理程序添加到记录器 (Add error log handler to logger)
                except Exception as e:
                    print(f"警告: 无法创建错误日志处理程序: {e}") # 打印警告信息 (Print warning message)

        except Exception as e:
            # 捕获设置文件日志处理程序时的任何其他异常
            # Catch any other exceptions that occur when setting up file log handlers
            print(f"警告: 设置文件日志处理程序时出错: {e}") # 打印警告信息 (Print warning message)
            # 即使文件日志处理程序的设置过程中出现错误，也要确保控制台日志记录仍然可用
            # Even if an error occurs during the setup of file log handlers, ensure console logging is still available

    return logger # 返回配置好的日志记录器实例 (Return the configured logger instance)

def format_log_message(level, message, extra=None):
    """
    根据 DEBUG 模式和提供的额外信息格式化日志消息字符串。
    Formats the log message string based on DEBUG mode and provided extra information.

    Args:
        level (str): 日志级别 (例如 'INFO', 'ERROR')。Log level (e.g., 'INFO', 'ERROR').
        message (str): 主要的日志消息内容。The main log message content.
        extra (dict, optional): 包含额外上下文信息的字典 (例如 key, model, status_code)。Dictionary containing extra context information (e.g., key, model, status_code).

    Returns:
        str: 格式化后的日志消息字符串。The formatted log message string.
    """
    extra = extra or {}  # 如果 extra 为 None，则使用空字典 (Use an empty dictionary if extra is None)

    # 从 extra 字典中安全地获取各个字段的值，如果不存在则使用空字符串
    # Safely get the values of each field from the extra dictionary, use empty string if not present
    key = extra.get('key', '') # 获取 key (Get key)
    request_type = extra.get('request_type', '') # 获取 request_type (Get request_type)
    model = extra.get('model', '') # 获取 model (Get model)
    status_code = extra.get('status_code', '') # 获取 status_code (Get status_code)
    error_message = extra.get('error_message', '') # 获取 error_message (Get error_message)

    # 根据字段是否为空来条件性地添加格式化前缀/后缀
    # Conditionally add formatting prefixes/suffixes based on whether fields are empty
    key_fmt = f"[{key}]-" if key else ""  # 如果 key 不为空，格式化为 "[key]-" (If key is not empty, format as "[key]-")
    model_fmt = f"[{model}]-" if model else "" # 如果 model 不为空，格式化为 "[model]-" (If model is not empty, format as "[model]-")
    error_fmt = f" - {error_message}" if error_message else "" # 如果 error_message 不为空，格式化为 " - error_message" (If error_message is not empty, format as " - error_message")

    # 构建用于格式化字符串的字典
    # Build a dictionary for formatting the string
    log_values = {
        'asctime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # 当前时间 (Current time)
        'levelname': level,             # 日志级别 (Log level)
        'key_fmt': key_fmt,             # 格式化后的 key (Formatted key)
        'request_type': request_type if request_type else '', # 请求类型 (Request type)
        'model_fmt': model_fmt,         # 格式化后的 model (Formatted model)
        'status_code': status_code if status_code else '', # 状态码 (Status code)
        'error_fmt': error_fmt,         # 格式化后的 error_message (Formatted error_message)
        'message': message              # 主要消息内容 (Main message content)
    }
    # 根据 DEBUG 模式选择使用详细格式还是普通格式
    # Choose to use detailed format or normal format based on DEBUG mode
    log_format = LOG_FORMAT_DEBUG if DEBUG else LOG_FORMAT_NORMAL # 选择日志格式 (Select log format)
    # 使用选定的格式和值来生成最终的日志字符串
    # Use the selected format and values to generate the final log string
    return log_format % log_values # 返回格式化后的字符串 (Return the formatted string)

def cleanup_old_logs(max_days=LOG_CLEANUP_DAYS):
    """
    清理指定日志目录中超过指定天数的日志文件（包括轮转产生的备份文件）。
    Cleans up log files (including rotated backup files) in the specified log directory that are older than the specified number of days.

    Args:
        max_days (int): 日志文件的最大保留天数。The maximum number of days to keep log files.
    """
    import glob  # 用于查找匹配特定模式的文件路径 (Used for finding file paths matching a specific pattern)
    import time  # 用于获取当前时间戳以计算文件年龄 (Used for getting current timestamp to calculate file age)

    # 如果日志目录无效 (log_dir 为 None)，则直接返回，不执行清理
    # If the log directory is invalid (log_dir is None), return directly and do not perform cleanup
    if not log_dir: # 如果日志目录无效 (If log directory is invalid)
        print("信息: 日志目录无效，跳过日志清理。") # 打印信息 (Print info)
        return # 返回 (Return)

    try:
        now = time.time()  # 获取当前时间戳 (秒) (Get current timestamp (seconds))
        max_age = max_days * 86400  # 将最大保留天数转换为秒 (1天 = 86400秒) (Convert maximum retention days to seconds (1 day = 86400 seconds))

        # 查找日志目录下所有匹配 '*.log*' 的文件 (包括 .log, .log.1, .log.2023-10-27 等)
        # Find all files matching '*.log*' in the log directory (including .log, .log.1, .log.2023-10-27, etc.)
        log_files = glob.glob(os.path.join(log_dir, '*.log*')) # 查找日志文件 (Find log files)

        deleted_count = 0 # 初始化已删除文件的计数器 (Initialize counter for deleted files)
        # 遍历所有找到的日志文件（包括备份文件）
        # Iterate through all found log files (including backup files)
        for file_path in log_files: # 遍历文件路径 (Iterate through file paths)
            try:
                # 获取文件的最后修改时间戳（modification time）
                # Get the last modification timestamp of the file
                file_mtime = os.path.getmtime(file_path) # 获取文件修改时间 (Get file modification time)

                # 计算文件的年龄（当前时间 - 最后修改时间）
                # Calculate the age of the file (current time - last modification time)
                # 如果文件年龄超过了设定的最大保留秒数
                # If the file age exceeds the set maximum retention seconds
                if now - file_mtime > max_age: # 如果文件已过期 (If file is expired)
                    try:
                        # 尝试删除这个过期的日志文件
                        # Attempt to delete this expired log file
                        os.remove(file_path) # 删除文件 (Remove file)
                        deleted_count += 1 # 增加已删除文件计数 (Increment deleted file count)
                        # 可以选择性地打印或记录删除信息
                        # Can optionally print or log deletion information
                        # print(f"已删除过期日志文件: {os.path.basename(file_path)}")
                        # logger.info(f"已删除过期日志文件: {file_path}")
                    except OSError as e: # 捕获删除文件时可能发生的 OS 错误 (Catch potential OS errors when deleting files)
                        # 如果删除失败，打印错误信息，但继续处理其他文件
                        # If deletion fails, print error message, but continue processing other files
                        print(f"删除日志文件失败 {file_path}: {e}") # 打印删除失败信息 (Print deletion failure info)
            except FileNotFoundError:
                 # 如果在处理过程中文件被删除（例如并发清理），则忽略
                 # If the file is deleted during processing (e.g., by concurrent cleanup), ignore
                 continue # 继续 (Continue)
            except Exception as e:
                # 如果在获取文件信息或比较时间时发生其他错误，打印错误信息
                # If other errors occur while getting file info or comparing time, print error message
                print(f"处理日志文件时出错 {file_path}: {e}") # 打印处理文件错误信息 (Print error processing file info)

        # 清理完成后打印总结信息
        # Print summary information after cleanup is complete
        if deleted_count > 0: # 如果删除了文件 (If files were deleted)
            print(f"日志清理完成，共删除 {deleted_count} 个超过 {max_days} 天的日志文件。") # 打印清理总结 (Print cleanup summary)
        else:
            print(f"日志清理完成，没有找到超过 {max_days} 天的日志文件需要删除。") # 打印没有需要删除的文件信息 (Print info about no files to delete)
    except Exception as e:
        # 捕获在日志清理的顶层逻辑中发生的任何其他异常
        # Catch any other exceptions that occur in the top-level logic of log cleanup
        print(f"执行日志清理任务时发生错误: {e}") # 打印执行清理任务错误 (Print error executing cleanup task)
        # 注意：即使日志清理失败，也不应中断主应用程序的运行
        # Note: Even if log cleanup fails, it should not interrupt the main application's operation
