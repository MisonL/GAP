import sys # 导入 sys 模块 (Import sys module)
import logging # 导入 logging 模块 (Import logging module)
from fastapi import Request, HTTPException # 导入 Request 和 HTTPException (Import Request and HTTPException)
from fastapi.responses import JSONResponse # 导入 JSONResponse (Import JSONResponse)

# 从其他模块导入必要的组件
# Import necessary components from other modules
# 注意：调整导入路径
# Note: Adjust import paths
from .log_config import format_log_message # 同级目录导入 (Import from sibling directory)
from ..api.models import ErrorResponse # 上一级 api 目录导入 (Import from parent api directory)

logger = logging.getLogger('my_logger') # 使用相同的日志记录器实例名称 (Use the same logger instance name)

# --- 错误翻译 ---
# --- Error Translation ---
def translate_error(message: str) -> str:
    """
    将常见的 Gemini 错误消息翻译成中文。
    Translates common Gemini error messages into Chinese.
    """
    if "quota exceeded" in message.lower(): return "API 密钥配额已用尽" # 翻译配额用尽错误 (Translate quota exceeded error)
    if "invalid argument" in message.lower(): return "无效参数" # 翻译无效参数错误 (Translate invalid argument error)
    if "internal server error" in message.lower(): return "服务器内部错误" # 翻译服务器内部错误 (Translate internal server error)
    if "service unavailable" in message.lower(): return "服务不可用" # 翻译服务不可用错误 (Translate service unavailable error)
    # 根据需要添加更多翻译
    # Add more translations as needed
    return message # 返回原始消息如果未找到翻译 (Return original message if no translation found)

# --- 未捕获异常处理器 (用于 sys.excepthook) ---
# --- Uncaught Exception Handler (for sys.excepthook) ---
def handle_exception(exc_type, exc_value, exc_traceback):
    """
    处理未捕获的异常，记录日志并翻译错误消息。
    旨在赋值给 sys.excepthook。
    Handles uncaught exceptions, logs them, and translates error messages.
    Intended to be assigned to sys.excepthook.
    """
    # 不干扰 KeyboardInterrupt
    # Do not interfere with KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt): # 如果是 KeyboardInterrupt (If it's KeyboardInterrupt)
        original_excepthook = getattr(sys, "__excepthook__", None) # 获取原始 excepthook (Get original excepthook)
        if original_excepthook: # 如果存在原始 excepthook (If original excepthook exists)
            original_excepthook(exc_type, exc_value, exc_traceback) # 调用原始 excepthook (Call original excepthook)
        return # 返回 (Return)

    error_message = translate_error(str(exc_value)) # 翻译错误消息 (Translate error message)
    log_msg = format_log_message('ERROR', f"未捕获的异常: %s" % error_message, extra={'status_code': 500, 'error_message': error_message}) # 格式化日志消息 (Format log message)
    # 使用 exc_info=True 在日志中包含回溯信息
    # Use exc_info=True to include traceback information in the log
    logger.error(log_msg, exc_info=(exc_type, exc_value, exc_traceback)) # 传递元组以获得更好的日志记录 (Pass tuple for better logging) # 记录错误 (Log error)

# --- FastAPI 全局异常处理器 ---
# --- FastAPI Global Exception Handler ---
async def global_exception_handler(request: Request, exc: Exception):
    """
    FastAPI 异常处理器，用于捕获请求处理期间所有未处理的异常。
    需要使用 @app.exception_handler(Exception) 在 FastAPI 应用实例上注册。
    FastAPI exception handler to catch all unhandled exceptions during request processing.
    Needs to be registered on the FastAPI application instance using @app.exception_handler(Exception).
    """
    status_code = 500 # 默认状态码 (Default status code)
    detail = "服务器内部错误" # 翻译 (Translation)

    # 如果是 HTTPException，则使用特定的状态码和详细信息
    # If it's an HTTPException, use the specific status code and detail
    if isinstance(exc, HTTPException): # 如果是 HTTPException (If it's HTTPException)
        status_code = exc.status_code # 获取状态码 (Get status code)
        detail = exc.detail # 获取详细信息 (Get detail)
    else:
        # 对于非 HTTP 异常，如果可能，翻译错误消息
        # For non-HTTP exceptions, translate the error message if possible
        detail = translate_error(str(exc)) # 翻译错误消息 (Translate error message)


    # 记录带有回溯信息的错误
    # Log the error with traceback information
    logger.error(f"全局异常处理器捕获到错误 (请求路径 {request.url.path}): {exc}", exc_info=True) # 翻译 (Translation) # 记录错误 (Log error)

    # 返回标准化的 JSON 错误响应
    # Return a standardized JSON error response
    return JSONResponse(
        status_code=status_code, # 状态码 (Status code)
        content=ErrorResponse(message=str(detail), type=type(exc).__name__, code=str(status_code)).dict(), # 错误响应内容 (Error response content)
    )
