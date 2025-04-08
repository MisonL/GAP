import logging
import os
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime
import tempfile

# 创建日志目录
try:
    # 首先尝试在项目目录中创建logs目录
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
    os.makedirs(log_dir, exist_ok=True)
except PermissionError:
    # 如果没有权限，则使用系统临时目录
    log_dir = os.path.join(tempfile.gettempdir(), 'gemini_api_proxy_logs')
    os.makedirs(log_dir, exist_ok=True)
    print(f"警告: 无法在应用目录创建日志文件夹，将使用临时目录: {log_dir}")
except Exception as e:
    # 如果出现其他错误，使用当前目录
    log_dir = os.path.join(os.getcwd(), 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
    except:
        # 最后的备选方案：完全禁用文件日志
        log_dir = None
        print(f"警告: 无法创建日志目录: {e}，文件日志将被禁用")

# 日志文件路径
if log_dir:
    app_log_file = os.path.join(log_dir, 'app.log')
    error_log_file = os.path.join(log_dir, 'error.log')
    access_log_file = os.path.join(log_dir, 'access.log')
else:
    # 如果log_dir为None，则禁用文件日志
    app_log_file = error_log_file = access_log_file = None

# 日志格式
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
LOG_FORMAT_DEBUG = '%(asctime)s - %(levelname)s - %(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s%(error_fmt)s'
LOG_FORMAT_NORMAL = '%(key_fmt)s%(request_type)s%(model_fmt)s%(status_code)s: %(message)s'

# 日志轮转配置
MAX_LOG_SIZE = int(os.environ.get("MAX_LOG_SIZE", "10")) * 1024 * 1024  # 默认10MB
MAX_LOG_BACKUPS = int(os.environ.get("MAX_LOG_BACKUPS", "5"))  # 默认保留5个备份
LOG_ROTATION_INTERVAL = os.environ.get("LOG_ROTATION_INTERVAL", "midnight")  # 默认每天午夜轮转

def setup_logger():
    """配置日志系统"""
    # 获取logger实例
    logger = logging.getLogger("my_logger")
    logger.setLevel(logging.DEBUG)
    
    # 清除现有的处理程序
    if logger.handlers:
        logger.handlers.clear()
    
    # 控制台处理程序
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件日志处理程序 - 仅在log_dir不为None时添加
    if log_dir:
        try:
            # 基于大小的文件处理程序 - 应用日志
            file_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            try:
                file_handler = RotatingFileHandler(
                    app_log_file,
                    maxBytes=MAX_LOG_SIZE,
                    backupCount=MAX_LOG_BACKUPS,
                    encoding='utf-8'
                )
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                print(f"警告: 无法创建应用日志处理程序: {e}")
            
            try:
                # 基于时间的文件处理程序 - 错误日志
                error_handler = TimedRotatingFileHandler(
                    error_log_file,
                    when=LOG_ROTATION_INTERVAL,
                    backupCount=MAX_LOG_BACKUPS,
                    encoding='utf-8'
                )
                error_handler.setLevel(logging.ERROR)
                error_handler.setFormatter(file_formatter)
                logger.addHandler(error_handler)
            except Exception as e:
                print(f"警告: 无法创建错误日志处理程序: {e}")
            
            try:
                # 基于大小的文件处理程序 - 访问日志
                access_handler = RotatingFileHandler(
                    access_log_file,
                    maxBytes=MAX_LOG_SIZE,
                    backupCount=MAX_LOG_BACKUPS,
                    encoding='utf-8'
                )
                access_handler.setLevel(logging.INFO)
                access_handler.setFormatter(file_formatter)
                logger.addHandler(access_handler)
            except Exception as e:
                print(f"警告: 无法创建访问日志处理程序: {e}")
        except Exception as e:
            print(f"警告: 设置文件日志处理程序时出错: {e}")
            # 确保至少有控制台日志可用
    
    return logger

def format_log_message(level, message, extra=None):
    """格式化日志消息"""
    extra = extra or {}
    
    # 处理空字段，为空时不显示方括号
    key = extra.get('key', '')
    request_type = extra.get('request_type', '')
    model = extra.get('model', '')
    status_code = extra.get('status_code', '')
    error_message = extra.get('error_message', '')
    
    # 根据字段是否为空来格式化输出
    key_fmt = f"[{key}]-" if key else ""
    model_fmt = f"[{model}]-" if model else ""
    error_fmt = f" - {error_message}" if error_message else ""
    
    log_values = {
        'asctime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'levelname': level,
        'key_fmt': key_fmt,
        'request_type': request_type if request_type else '',
        'model_fmt': model_fmt,
        'status_code': status_code if status_code else '',
        'error_fmt': error_fmt,
        'message': message
    }
    log_format = LOG_FORMAT_DEBUG if DEBUG else LOG_FORMAT_NORMAL
    return log_format % log_values

def cleanup_old_logs(max_days=30):
    """清理超过指定天数的日志文件"""
    import glob
    import time
    
    # 如果log_dir为None，则跳过清理
    if not log_dir:
        return
    
    try:
        now = time.time()
        max_age = max_days * 86400  # 转换为秒
        
        # 查找所有日志文件
        log_files = glob.glob(os.path.join(log_dir, '*.log*'))
        
        for file_path in log_files:
            try:
                # 获取文件修改时间
                file_mtime = os.path.getmtime(file_path)
                
                # 如果文件超过最大保留时间，则删除
                if now - file_mtime > max_age:
                    try:
                        os.remove(file_path)
                        print(f"已删除过期日志文件: {file_path}")
                    except Exception as e:
                        print(f"删除日志文件失败 {file_path}: {e}")
            except Exception as e:
                print(f"处理日志文件时出错 {file_path}: {e}")
    except Exception as e:
        print(f"清理日志文件时出错: {e}")
        # 即使清理失败，也不影响应用运行