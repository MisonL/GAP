import sys # 导入 sys 模块
import logging # 导入 logging 模块
from fastapi import Request, HTTPException, status # 导入 Request, HTTPException 和 status
from fastapi.responses import JSONResponse, RedirectResponse # 导入 JSONResponse 和 RedirectResponse

# 从其他模块导入必要的组件
# 注意：调整导入路径
from app.handlers.log_config import format_log_message # 同级目录导入
from app.api.models import ErrorResponse # 上一级 api 目录导入
from app.core.request_helpers import get_client_ip # 导入获取客户端 IP 的函数

logger = logging.getLogger('my_logger')

# --- 错误翻译 ---
def translate_error(message: str) -> str:
    """
    将常见的 Gemini 错误消息翻译成中文。
    """
    if "quota exceeded" in message.lower(): return "API 密钥配额已用尽" # 翻译配额用尽错误
    if "invalid argument" in message.lower(): return "无效参数" # 翻译无效参数错误
    if "internal server error" in message.lower(): return "服务器内部错误" # 翻译服务器内部错误
    if "service unavailable" in message.lower(): return "服务不可用" # 翻译服务不可用错误
    # 根据需要添加更多翻译
    return message # 返回原始消息如果未找到翻译

# --- 未捕获异常处理器 (用于 sys.excepthook) ---
def handle_exception(exc_type, exc_value, exc_traceback):
    """
    处理未捕获的异常，记录日志并翻译错误消息。
    旨在赋值给 sys.excepthook。
    """
    # 不干扰 KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        original_excepthook = getattr(sys, "__excepthook__", None) # 获取原始 excepthook
        if original_excepthook:
            original_excepthook(exc_type, exc_value, exc_traceback) # 调用原始 excepthook
        return

    error_message = translate_error(str(exc_value)) # 翻译错误消息
    log_msg = format_log_message('ERROR', f"未捕获的异常: %s" % error_message, extra={'status_code': 500, 'error_message': error_message}) # 格式化日志消息
    # 使用 exc_info=True 在日志中包含回溯信息
    logger.error(log_msg, exc_info=(exc_type, exc_value, exc_traceback)) # 传递元组以获得更好的日志记录

# --- FastAPI 全局异常处理器 ---
async def global_exception_handler(request: Request, exc: Exception):
    """
    FastAPI 异常处理器，用于捕获请求处理期间所有未处理的异常。
    需要使用 @app.exception_handler(Exception) 在 FastAPI 应用实例上注册。
    """
    status_code = 500 # 默认状态码
    detail = "服务器内部错误" # 翻译

    # 如果是 HTTPException，则使用特定的状态码和详细信息
    if isinstance(exc, HTTPException):
        status_code = exc.status_code # 获取状态码
        detail = exc.detail # 获取详细信息
        # 如果是认证相关的错误 (401 或 403)，重定向到登录页面
        if status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]:
            logger.warning(f"认证失败 ({status_code})，重定向到登录页。")
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER) # 重定向到根路径 (登录页)
    else:
        # 对于非 HTTP 异常，如果可能，翻译错误消息
        detail = translate_error(str(exc)) # 翻译错误消息

    # 获取请求上下文信息
    client_ip = get_client_ip(request) # 获取客户端 IP
    request_method = request.method # 获取请求方法
    request_path = request.url.path # 获取请求路径

    # 记录带有回溯信息的错误，包含请求上下文
    log_message = f"全局异常处理器捕获到错误 (IP: {client_ip}, 方法: {request_method}, 路径: {request_path}): {exc}" # 格式化日志消息
    logger.error(log_message, exc_info=True) # 记录错误

    # 返回标准化的 JSON 错误响应
    return JSONResponse(
        status_code=status_code, # 状态码
        content=ErrorResponse(message=str(detail), type=type(exc).__name__, code=str(status_code)).dict(), # 错误响应内容
    )

# 注意：原 utils.py 中没有明确的 create_error_response 函数。
# 如果有其他与错误处理相关的 *独立* 辅助函数，也应移到此处。
