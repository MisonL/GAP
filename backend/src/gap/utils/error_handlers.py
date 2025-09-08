# -*- coding: utf-8 -*-
"""
FastAPI 错误处理程序模块。
定义了用于翻译错误消息、处理未捕获异常以及全局异常处理的函数。
"""
import sys # 导入 sys 模块，用于访问系统特定的参数和函数 (例如 sys.excepthook)
import logging # 导入日志模块
from typing import Optional # 导入 Optional 类型提示
from types import TracebackType # 导入 TracebackType 类型提示
from fastapi import Request, HTTPException, status # 导入 FastAPI 相关组件
from fastapi.responses import JSONResponse, RedirectResponse # 导入 FastAPI 响应类型
from fastapi.templating import Jinja2Templates # 导入 Jinja2 模板

# 从其他模块导入必要的组件
from gap.utils.log_config import format_log_message # 导入日志格式化函数
from gap.api.models import ErrorResponse # 导入标准错误响应模型
from gap.core.utils.request_helpers import get_client_ip # 导入获取客户端 IP 的函数 (新路径)

logger = logging.getLogger('my_logger') # 获取日志记录器实例
templates = Jinja2Templates(directory="app/web/templates") # 初始化 Jinja2 模板

# --- 错误消息翻译 ---
def translate_error(message: str) -> str:
    """
    (辅助函数) 将常见的英文错误消息（特别是来自 Gemini API 的）翻译成更友好的中文提示。
    可以根据需要扩展此函数以包含更多翻译规则。

    Args:
        message (str): 原始错误消息字符串。

    Returns:
        str: 翻译后的中文错误消息，如果未找到匹配的翻译规则，则返回原始消息。
    """
    # 将消息转换为小写以便不区分大小写匹配
    lower_message = message.lower()
    # --- 添加翻译规则 ---
    if "quota exceeded" in lower_message: return "API 密钥配额已用尽或达到速率限制"
    if "api key not valid" in lower_message: return "提供的 API 密钥无效"
    if "invalid argument" in lower_message: return "请求参数无效或格式错误"
    if "internal server error" in lower_message: return "Gemini API 服务器内部错误，请稍后重试"
    if "service unavailable" in lower_message: return "Gemini API 服务暂时不可用，请稍后重试"
    if "permission denied" in lower_message: return "无权访问所请求的资源或 API"
    if "cancelled" in lower_message: return "操作被取消"
    if "deadline exceeded" in lower_message: return "请求超时"
    # 可以根据实际遇到的错误添加更多翻译规则
    # ...

    # 如果没有匹配的规则，返回原始消息
    return message

# --- 未捕获异常处理器 (用于 sys.excepthook) ---
def handle_exception(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: Optional[TracebackType]):
    """
    全局异常钩子函数，用于处理在 FastAPI 请求处理流程之外发生的未捕获异常。
    例如，在后台任务或应用启动/关闭过程中发生的异常。
    此函数旨在赋值给 `sys.excepthook`。

    Args:
        exc_type: 异常类型。
        exc_value: 异常实例。
        exc_traceback: 异常的回溯信息。
    """
    # 特殊处理 KeyboardInterrupt (Ctrl+C)，避免干扰正常的程序退出
    if issubclass(exc_type, KeyboardInterrupt):
        # 获取并调用原始的 excepthook (如果存在)
        original_excepthook = getattr(sys, "__excepthook__", None)
        if original_excepthook:
            original_excepthook(exc_type, exc_value, exc_traceback)
        return # 不再继续处理

    # 尝试翻译错误消息
    error_message = translate_error(str(exc_value))
    # 格式化日志消息
    log_msg = format_log_message('ERROR', f"未捕获的异常: {error_message}", extra={'status_code': 500, 'error_message': error_message})
    # 记录错误日志，并包含完整的异常信息 (exc_info=True 或传递异常元组)
    logger.error(log_msg, exc_info=(exc_type, exc_value, exc_traceback))

# --- FastAPI 全局异常处理器 ---
async def global_exception_handler(request: Request, exc: Exception):
    """
    FastAPI 全局异常处理器。
    捕获在处理 HTTP 请求过程中所有未被特定处理器捕获的异常。
    需要使用 `@app.exception_handler(Exception)` 装饰器在 FastAPI 应用实例上注册。

    Args:
        request (Request): FastAPI 请求对象。
        exc (Exception): 捕获到的异常实例。

    Returns:
        Union[JSONResponse, RedirectResponse]: 返回标准化的 JSON 错误响应，
                                               或者在特定情况下（如认证失败）返回重定向响应。
    """
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR # 默认设置状态码为 500 内部服务器错误
    detail = "服务器内部发生错误" # 默认错误详情

    # --- 特殊处理 HTTPException ---
    if isinstance(exc, HTTPException): # 如果捕获到的是 FastAPI 的 HTTPException
        status_code = exc.status_code # 使用 HTTPException 定义的状态码
        detail = exc.detail # 使用 HTTPException 定义的错误详情
        # 对于 API 端点，返回 JSON 响应而不是 HTML 模板
        if request.url.path.startswith('/api') or request.url.path.startswith('/v1') or request.url.path.startswith('/v2') or request.url.path == '/login':
            error_content = ErrorResponse(message=str(detail), type=type(exc).__name__, code=str(status_code)).model_dump()
            return JSONResponse(status_code=status_code, content=error_content, headers=exc.headers)
        else:
            # 对于非 API 端点，返回 JSON 响应
            error_content = ErrorResponse(message=str(detail), type=type(exc).__name__, code=str(status_code)).model_dump()
            return JSONResponse(status_code=status_code, content=error_content, headers=exc.headers)

    # --- 记录错误日志 (提前，以便包含原始异常信息) ---
    client_ip = get_client_ip(request)
    request_method = request.method
    request_path = request.url.path
    log_message = f"全局异常处理器捕获到错误 (IP: {client_ip}, 方法: {request_method}, 路径: {request_path}): {exc}"
    logger.error(log_message, exc_info=True)

    # --- 检查 HTTPException 是否意图重定向 ---
    if isinstance(exc, HTTPException) and exc.headers and "Location" in exc.headers:
        logger.info(f"全局异常处理器：HTTPException (状态码 {exc.status_code}) 包含 Location 头，执行重定向到 {exc.headers['Location']}")
        return RedirectResponse(url=exc.headers["Location"], status_code=exc.status_code)
    
    # 对于所有 HTTPException，返回 JSON 响应
    if isinstance(exc, HTTPException):
        error_content = ErrorResponse(message=str(exc.detail), type=type(exc).__name__, code=str(exc.status_code)).model_dump()
        return JSONResponse(status_code=exc.status_code, content=error_content, headers=exc.headers)

    # --- 对于所有其他未处理的 Exception ---
    error_content = ErrorResponse(message=translate_error(str(exc)), type=type(exc).__name__, code=str(status.HTTP_500_INTERNAL_SERVER_ERROR)).model_dump()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_content,
    )

# 注意：原 utils.py 中没有明确的 create_error_response 函数。
# 如果有其他与错误处理相关的 *独立* 辅助函数，也应移到此处。
# 例如，可以创建一个函数来专门处理 Gemini API 返回的特定错误结构。
