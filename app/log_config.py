# 导入必要的库
import logging  # Python 标准日志库
import os       # 用于路径操作和环境变量
import sys      # 用于系统相关操作 (例如退出钩子)
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler  # 日志轮转处理器
from datetime import datetime  # 用于获取当前时间
import tempfile # 用于获取系统临时目录

# --- 日志目录设置 ---
# 尝试创建日志目录，优先在项目根目录下的 'logs' 文件夹
try:
    # 获取当前文件所在目录的上级目录 (即项目根目录)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(project_root, 'logs')  # 定义日志目录路径
    os.makedirs(log_dir, exist_ok=True)  # 创建目录，如果已存在则忽略
except PermissionError:
    # 如果在项目目录创建失败 (例如权限不足)，则尝试使用系统临时目录
    log_dir = os.path.join(tempfile.gettempdir(), 'gemini_api_proxy_logs')
    os.makedirs(log_dir, exist_ok=True)
    print(f"警告: 无法在应用目录创建日志文件夹，将使用临时目录: {log_dir}")
except Exception as e:
    # 如果出现其他创建目录的错误，尝试在当前工作目录创建 'logs'
    log_dir = os.path.join(os.getcwd(), 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as final_e:
        # 如果所有尝试都失败，则禁用文件日志
        log_dir = None
        print(f"警告: 无法创建日志目录: {final_e}，文件日志将被禁用")

# --- 日志文件路径定义 ---
if log_dir:
    # 如果成功创建了日志目录，定义各个日志文件的完整路径
    app_log_file = os.path.join(log_dir, 'app.log')      # 应用主日志
    error_log_file = os.path.join(log_dir, 'error.log')    # 错误日志
    access_log_file = os.path.join(log_dir, 'access.log')  # 访问日志 (暂未使用，但保留定义)
else:
    # 如果无法创建日志目录，则将文件路径设为 None，禁用文件日志记录
    app_log_file = error_log_file = access_log_file = None

# --- 日志格式配置 ---
# 从环境变量读取 DEBUG 模式设置，默认为 false
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
# 定义 DEBUG 模式下的详细日志格式
LOG_FORMAT_DEBUG = '%(asctime)s - %(levelname)s - %(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s%(error_fmt)s'
# 定义普通模式下的简洁日志格式
LOG_FORMAT_NORMAL = '%(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s'

# --- 日志轮转配置 ---
# 从环境变量读取单个日志文件最大大小 (MB)，转换为字节，默认 10MB
MAX_LOG_SIZE = int(os.environ.get("MAX_LOG_SIZE", "10")) * 1024 * 1024
# 从环境变量读取保留的备份文件数量，默认 5 个
MAX_LOG_BACKUPS = int(os.environ.get("MAX_LOG_BACKUPS", "5"))
# 从环境变量读取日志轮转的时间间隔 (例如 'S', 'M', 'H', 'D', 'W0'-'W6', 'midnight')，默认 'midnight'
LOG_ROTATION_INTERVAL = os.environ.get("LOG_ROTATION_INTERVAL", "midnight")
# 从环境变量读取日志文件的最大保留天数，默认 30 天
LOG_CLEANUP_DAYS = int(os.environ.get("LOG_CLEANUP_DAYS", "30"))

def setup_logger():
    """
    配置并返回一个日志记录器实例。
    包含控制台输出和（如果可能）文件输出（应用日志、错误日志）。
    """
    # 获取名为 'my_logger' 的日志记录器实例
    logger = logging.getLogger("my_logger")
    # 设置日志记录器处理的最低级别为 DEBUG
    logger.setLevel(logging.DEBUG)

    # 清除可能已存在的旧的处理程序，防止重复添加
    if logger.handlers:
        logger.handlers.clear()

    # --- 控制台处理程序 ---
    console_handler = logging.StreamHandler()  # 创建流处理程序 (输出到 stderr)
    console_handler.setLevel(logging.INFO)     # 设置控制台输出的最低级别为 INFO
    # 定义控制台输出的格式 (只包含消息本身)
    formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(formatter)    # 应用格式
    logger.addHandler(console_handler)         # 将处理程序添加到记录器

    # --- 文件日志处理程序 ---
    # 仅在成功创建日志目录时才添加文件处理程序
    if log_dir:
        try:
            # 定义通用的文件日志格式 (包含时间、级别和消息)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

            # --- 应用日志处理程序 (基于大小轮转) ---
            if app_log_file: # 检查路径是否有效
                try:
                    # 创建按大小轮转的文件处理程序
                    file_handler = RotatingFileHandler(
                        app_log_file,                  # 日志文件路径
                        maxBytes=MAX_LOG_SIZE,         # 单个文件最大字节数
                        backupCount=MAX_LOG_BACKUPS,   # 保留的备份文件数量
                        encoding='utf-8'               # 使用 UTF-8 编码
                    )
                    file_handler.setLevel(logging.DEBUG)  # 应用日志记录 DEBUG 及以上级别
                    file_handler.setFormatter(file_formatter) # 应用格式
                    logger.addHandler(file_handler)         # 添加到记录器
                except Exception as e:
                    print(f"警告: 无法创建应用日志处理程序: {e}")

            # --- 错误日志处理程序 (基于时间轮转) ---
            if error_log_file: # 检查路径是否有效
                try:
                    # 创建按时间轮转的文件处理程序
                    error_handler = TimedRotatingFileHandler(
                        error_log_file,                # 日志文件路径
                        when=LOG_ROTATION_INTERVAL,    # 轮转时间间隔单位
                        backupCount=MAX_LOG_BACKUPS,   # 保留的备份文件数量
                        encoding='utf-8'               # 使用 UTF-8 编码
                    )
                    error_handler.setLevel(logging.ERROR) # 错误日志只记录 ERROR 及以上级别
                    error_handler.setFormatter(file_formatter) # 应用格式
                    logger.addHandler(error_handler)         # 添加到记录器
                except Exception as e:
                    print(f"警告: 无法创建错误日志处理程序: {e}")

            # --- 访问日志处理程序 (基于大小轮转, 暂未使用但保留) ---
            # if access_log_file: # 检查路径是否有效
            #     try:
            #         access_handler = RotatingFileHandler(
            #             access_log_file,
            #             maxBytes=MAX_LOG_SIZE,
            #             backupCount=MAX_LOG_BACKUPS,
            #             encoding='utf-8'
            #         )
            #         access_handler.setLevel(logging.INFO) # 访问日志记录 INFO 及以上级别
            #         access_handler.setFormatter(file_formatter) # 应用格式
            #         logger.addHandler(access_handler)         # 添加到记录器
            #     except Exception as e:
            #         print(f"警告: 无法创建访问日志处理程序: {e}")

        except Exception as e:
            # 捕获设置文件日志处理程序时的任何其他异常
            print(f"警告: 设置文件日志处理程序时出错: {e}")
            # 即使文件日志设置失败，也要确保控制台日志仍然可用

    return logger # 返回配置好的日志记录器实例

def format_log_message(level, message, extra=None):
    """
    根据 DEBUG 模式和提供的额外信息格式化日志消息字符串。

    Args:
        level (str): 日志级别 (例如 'INFO', 'ERROR')。
        message (str): 主要的日志消息内容。
        extra (dict, optional): 包含额外上下文信息的字典 (例如 key, model, status_code)。

    Returns:
        str: 格式化后的日志消息字符串。
    """
    extra = extra or {}  # 如果 extra 为 None，则使用空字典

    # 从 extra 字典中安全地获取各个字段的值，如果不存在则使用空字符串
    key = extra.get('key', '')
    request_type = extra.get('request_type', '')
    model = extra.get('model', '')
    status_code = extra.get('status_code', '')
    error_message = extra.get('error_message', '')

    # 根据字段是否为空来条件性地添加格式化前缀/后缀
    key_fmt = f"[{key}]-" if key else ""  # 如果 key 不为空，格式为 "[key]-"
    model_fmt = f"[{model}]-" if model else "" # 如果 model 不为空，格式为 "[model]-"
    error_fmt = f" - {error_message}" if error_message else "" # 如果 error_message 不为空，格式为 " - error_message"

    # 构建用于格式化字符串的字典
    log_values = {
        'asctime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # 当前时间
        'levelname': level,             # 日志级别
        'key_fmt': key_fmt,             # 格式化后的 key
        'request_type': request_type if request_type else '', # 请求类型
        'model_fmt': model_fmt,         # 格式化后的 model
        'status_code': status_code if status_code else '', # 状态码
        'error_fmt': error_fmt,         # 格式化后的 error_message
        'message': message              # 主要消息内容
    }
    # 根据 DEBUG 模式选择使用详细格式还是普通格式
    log_format = LOG_FORMAT_DEBUG if DEBUG else LOG_FORMAT_NORMAL
    # 使用选定的格式和值来生成最终的日志字符串
    return log_format % log_values

def cleanup_old_logs(max_days=LOG_CLEANUP_DAYS):
    """
    清理指定日志目录中超过指定天数的日志文件（包括轮转产生的备份文件）。

    Args:
        max_days (int): 日志文件的最大保留天数。
    """
    import glob  # 用于查找文件路径模式
    import time  # 用于获取当前时间戳

    # 如果日志目录无效 (log_dir 为 None)，则直接返回，不执行清理
    if not log_dir:
        print("信息: 日志目录无效，跳过日志清理。")
        return

    try:
        now = time.time()  # 获取当前时间戳 (秒)
        max_age = max_days * 86400  # 将最大保留天数转换为秒 (1天 = 86400秒)

        # 查找日志目录下所有匹配 '*.log*' 的文件 (包括 .log, .log.1, .log.2023-10-27 等)
        log_files = glob.glob(os.path.join(log_dir, '*.log*'))

        deleted_count = 0 # 记录删除的文件数量
        # 遍历找到的所有日志文件
        for file_path in log_files:
            try:
                # 获取文件的最后修改时间戳
                file_mtime = os.path.getmtime(file_path)

                # 如果文件的年龄超过了最大保留时间
                if now - file_mtime > max_age:
                    try:
                        # 删除文件
                        os.remove(file_path)
                        deleted_count += 1
                        # 打印删除信息 (可选，也可以使用 logger.info)
                        # print(f"已删除过期日志文件: {file_path}")
                    except Exception as e:
                        # 如果删除失败，打印错误信息
                        print(f"删除日志文件失败 {file_path}: {e}")
            except Exception as e:
                # 如果获取文件信息或比较时间时出错，打印错误信息
                print(f"处理日志文件时出错 {file_path}: {e}")
        if deleted_count > 0:
            print(f"日志清理完成，共删除 {deleted_count} 个过期文件。")
        else:
            print("日志清理完成，没有需要删除的过期文件。")
    except Exception as e:
        # 捕获清理过程中的任何其他异常
        print(f"清理日志文件时出错: {e}")
        # 即使清理失败，也不应影响主应用的运行