import sys
import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

# 从其他模块导入必要的组件
# 注意：调整导入路径
from .log_config import format_log_message # 同级目录导入
from ..api.models import ErrorResponse # 上一级 api 目录导入

logger = logging.getLogger('my_logger') # 使用相同的日志记录器实例名称

# --- 错误翻译 ---
def translate_error(message: str) -> str:
    """将常见的 Gemini 错误消息翻译成中文。"""
    if "quota exceeded" in message.lower(): return "API 密钥配额已用尽"
    if "invalid argument" in message.lower(): return "无效参数"
    if "internal server error" in message.lower(): return "服务器内部错误"
    if "service unavailable" in message.lower(): return "服务不可用"
    # 根据需要添加更多翻译
    return message

# --- 未捕获异常处理器 (用于 sys.excepthook) ---
def handle_exception(exc_type, exc_value, exc_traceback):
    """
    处理未捕获的异常，记录日志并翻译错误消息。
    旨在赋值给 sys.excepthook。
    """
    # 不干扰 KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        original_excepthook = getattr(sys, "__excepthook__", None)
        if original_excepthook:
            original_excepthook(exc_type, exc_value, exc_traceback)
        return

    error_message = translate_error(str(exc_value))
    log_msg = format_log_message('ERROR', f"未捕获的异常: %s" % error_message, extra={'status_code': 500, 'error_message': error_message})
    # 使用 exc_info=True 在日志中包含回溯信息
    logger.error(log_msg, exc_info=(exc_type, exc_value, exc_traceback)) # 传递元组以获得更好的日志记录

# --- FastAPI 全局异常处理器 ---
async def global_exception_handler(request: Request, exc: Exception):
    """
    FastAPI 异常处理器，用于捕获请求处理期间所有未处理的异常。
    需要使用 @app.exception_handler(Exception) 在 FastAPI 应用实例上注册。
    """
    status_code = 500
    detail = "服务器内部错误" # 翻译

    # 如果是 HTTPException，则使用特定的状态码和详细信息
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        detail = exc.detail
    else:
        # 对于非 HTTP 异常，如果可能，翻译错误消息
        detail = translate_error(str(exc))


    # 记录带有回溯信息的错误
    logger.error(f"全局异常处理器捕获到错误 (请求路径 {request.url.path}): {exc}", exc_info=True) # 翻译

    # 返回标准化的 JSON 错误响应
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=str(detail), type=type(exc).__name__, code=str(status_code)).dict(),
    )