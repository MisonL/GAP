# -*- coding: utf-8 -*-
"""
FastAPI 错误处理程序模块。
定义了用于翻译错误消息、处理未捕获异常以及全局异常处理的函数。
"""
import sys # 导入 sys 模块，用于访问系统特定的参数和函数 (例如 sys.excepthook)
import logging # 导入日志模块
from fastapi import Request, HTTPException, status # 导入 FastAPI 相关组件
from fastapi.responses import JSONResponse, RedirectResponse # 导入 FastAPI 响应类型

# 从其他模块导入必要的组件
from app.handlers.log_config import format_log_message # 导入日志格式化函数
from app.api.models import ErrorResponse # 导入标准错误响应模型
from app.core.utils.request_helpers import get_client_ip # 导入获取客户端 IP 的函数 (新路径)

logger = logging.getLogger('my_logger') # 获取日志记录器实例

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
def handle_exception(exc_type, exc_value, exc_traceback):
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
        # --- 处理认证/授权失败：重定向到登录页 ---
        # 如果状态码是 401 (未授权) 或 403 (禁止访问)
        if status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]:
            logger.warning(f"认证/授权失败 ({status_code})，请求路径: {request.url.path}，将重定向到登录页。") # 记录警告日志
            # 返回一个 303 See Other 重定向响应，将用户导向根路径 (通常是登录页)
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    else: # --- 处理其他类型的异常 ---
        # 对于非 HTTPException 的其他 Python 内置异常或自定义异常
        # 尝试翻译异常的字符串表示形式
        detail = translate_error(str(exc))

    # --- 记录错误日志 ---
    # 获取请求的上下文信息，以便更好地诊断问题
    client_ip = get_client_ip(request) # 获取客户端 IP
    request_method = request.method # 获取请求方法 (GET, POST, etc.)
    request_path = request.url.path # 获取请求路径

    # 格式化包含上下文信息的错误日志消息
    log_message = f"全局异常处理器捕获到错误 (IP: {client_ip}, 方法: {request_method}, 路径: {request_path}): {exc}"
    # 记录错误日志，并包含完整的异常堆栈信息 (exc_info=True)
    logger.error(log_message, exc_info=True)

    # --- 返回标准化的 JSON 错误响应 ---
    # 使用 ErrorResponse Pydantic 模型来构建标准化的错误响应内容
    error_content = ErrorResponse(
        message=str(detail), # 错误消息详情
        type=type(exc).__name__, # 异常类型名称
        code=str(status_code) # 状态码 (字符串形式)
    ).model_dump() # 将 Pydantic 模型转换为字典

    # 返回 JSONResponse
    return JSONResponse(
        status_code=status_code, # 设置 HTTP 状态码
        content=error_content, # 设置响应体内容
    )

# 注意：原 utils.py 中没有明确的 create_error_response 函数。
# 如果有其他与错误处理相关的 *独立* 辅助函数，也应移到此处。
# 例如，可以创建一个函数来专门处理 Gemini API 返回的特定错误结构。
