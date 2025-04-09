# 导入 FastAPI 和相关模块
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
# 导入本地定义的模型
from .models import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse, ModelList
# 导入 Gemini 客户端和响应包装器
from .gemini import GeminiClient, ResponseWrapper
# 导入工具函数 (错误处理, 防滥用, API 密钥管理)
from .utils import handle_gemini_error, protect_from_abuse, APIKeyManager, test_api_key
# 导入日志配置和工具
from .log_config import setup_logger, format_log_message, cleanup_old_logs
# 导入版本信息
from .version import __version__
# 导入标准库
import os
import json
import asyncio
from typing import Literal # 用于类型注解，指定字面量类型
import random
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler # 用于后台定时任务 (日志清理)
import sys
import logging
from dotenv import load_dotenv # 用于从 .env 文件加载环境变量

# --- 初始化和配置 ---

# 从 .env 文件加载环境变量 (如果存在)
load_dotenv()

# 禁用 uvicorn 默认的日志记录器，避免重复日志
logging.getLogger("uvicorn").disabled = True
logging.getLogger("uvicorn.access").disabled = True

# 配置并获取自定义的日志记录器实例
logger = setup_logger()

# --- 错误处理 ---

def translate_error(message: str) -> str:
    """将常见的英文错误信息翻译成中文"""
    if "quota exceeded" in message.lower():
        return "API 密钥配额已用尽"
    if "invalid argument" in message.lower():
        return "无效参数"
    if "internal server error" in message.lower():
        return "服务器内部错误"
    if "service unavailable" in message.lower():
        return "服务不可用"
    return message # 如果没有匹配的翻译，返回原始信息

def handle_exception(exc_type, exc_value, exc_traceback):
    """全局异常处理钩子，用于捕获未处理的异常并记录日志"""
    # 如果是键盘中断 (Ctrl+C)，则使用默认处理方式
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback) # 注意：调用原始 excepthook
        return
    # 翻译错误信息
    error_message = translate_error(str(exc_value))
    # 格式化日志消息
    log_msg = format_log_message('ERROR', f"未捕获的异常: %s" % error_message, extra={'status_code': 500, 'error_message': error_message})
    # 记录错误日志
    logger.error(log_msg)

# 设置系统默认的异常处理钩子为自定义的 handle_exception
sys.excepthook = handle_exception

# --- FastAPI 应用实例 ---
app = FastAPI(title="Gemini API Proxy", version=__version__) # 添加标题和版本信息

# --- 后台任务：日志清理 ---
log_cleanup_scheduler = BackgroundScheduler()
# 添加一个定时任务，使用 cron 表达式，在每天凌晨 3:00 执行 cleanup_old_logs 函数
# args=[30] 表示传递给 cleanup_old_logs 的参数，即清理超过 30 天的日志
log_cleanup_scheduler.add_job(cleanup_old_logs, 'cron', hour=3, minute=0, args=[30])
log_cleanup_scheduler.start() # 启动调度器

# --- 应用配置 ---
# 从环境变量获取访问密码，如果未设置则使用默认值 "123"
PASSWORD = os.environ.get("PASSWORD", "123")
# 从环境变量获取每分钟最大请求数，默认为 30
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"))
# 从环境变量获取每天每个 IP 的最大请求数，默认为 600
MAX_REQUESTS_PER_DAY_PER_IP = int(
    os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))
# 从环境变量读取是否禁用安全过滤的设置
DISABLE_SAFETY_FILTERING = os.environ.get("DISABLE_SAFETY_FILTERING", "false").lower() == "true"
# 如果禁用了安全过滤，则在启动时记录一条信息日志
if DISABLE_SAFETY_FILTERING:
   logger.info("全局安全过滤已禁用 (DISABLE_SAFETY_FILTERING=true)")
# 重试相关的配置 (目前未使用 MAX_RETRIES，重试次数由密钥数量决定)
# MAX_RETRIES = int(os.environ.get('MaxRetries', '3').strip() or '3')
RETRY_DELAY = 1 # 初始重试延迟 (秒) - 当前未使用
MAX_RETRY_DELAY = 16 # 最大重试延迟 (秒) - 当前未使用

# --- Gemini 安全设置 ---
# 默认安全设置：不阻止任何内容，但 API 可能会在响应中标记风险
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": 'HARM_CATEGORY_CIVIC_INTEGRITY', "threshold": 'BLOCK_NONE'}
]
# 安全设置 G2：完全关闭所有类别的过滤 (阈值为 OFF)
safety_settings_g2 = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
    {"category": 'HARM_CATEGORY_CIVIC_INTEGRITY', "threshold": 'OFF'}
]

# --- API 密钥管理 ---
# 实例化 API 密钥管理器
key_manager = APIKeyManager()
# 获取初始可用的 API 密钥 (如果启动时没有可用密钥，这里会是 None)
current_api_key = key_manager.get_available_key()

def switch_api_key():
    """尝试切换到下一个可用的 API 密钥"""
    global current_api_key # 声明要修改全局变量
    key = key_manager.get_available_key() # 从管理器获取下一个可用密钥
    if key:
        current_api_key = key # 更新当前使用的密钥
        # 记录密钥切换信息
        log_msg = format_log_message('INFO', f"API key 替换为 → {current_api_key[:8]}...", extra={'key': current_api_key[:8], 'request_type': 'switch_key'})
        logger.info(log_msg)
    else:
        # 如果没有更多可用密钥，记录错误
        log_msg = format_log_message('ERROR', "API key 替换失败，所有API key都已尝试，请重新配置或稍后重试", extra={'key': 'N/A', 'request_type': 'switch_key', 'status_code': 'N/A'})
        logger.error(log_msg)

async def check_keys():
    """在应用启动时检查所有配置的 API 密钥的有效性"""
    available_keys = [] # 存储有效的密钥
    # 遍历密钥管理器中的所有密钥
    for key in key_manager.api_keys:
        is_valid = await test_api_key(key) # 测试密钥是否有效
        status_msg = "有效" if is_valid else "无效"
        # 记录每个密钥的测试结果
        log_msg = format_log_message('INFO', f"API Key {key[:10]}... {status_msg}.")
        logger.info(log_msg)
        if is_valid:
            available_keys.append(key) # 将有效的密钥添加到列表中
    # 如果没有找到任何有效的密钥，记录错误
    if not available_keys:
        log_msg = format_log_message('ERROR', "没有可用的 API 密钥！", extra={'key': 'N/A', 'request_type': 'startup', 'status_code': 'N/A'})
        logger.error(log_msg)
    return available_keys # 返回有效密钥列表

# --- FastAPI 事件处理 ---
@app.on_event("startup")
async def startup_event():
    """应用启动时执行的异步事件处理函数"""
    log_msg = format_log_message('INFO', f"Starting Gemini API proxy v{__version__}...")
    logger.info(log_msg)
    # 检查 API 密钥有效性
    available_keys = await check_keys()
    if available_keys:
        # 更新密钥管理器中的密钥列表为有效的密钥
        key_manager.api_keys = available_keys
        # 重置密钥栈 (确保使用随机顺序)
        key_manager._reset_key_stack()
        # 显示所有有效的密钥 (部分隐藏)
        key_manager.show_all_keys()
        log_msg = format_log_message('INFO', f"可用 API 密钥数量：{len(key_manager.api_keys)}")
        logger.info(log_msg)
        # 设置最大重试次数等于可用密钥数量
        log_msg = format_log_message('INFO', f"最大重试次数设置为：{len(key_manager.api_keys)}")
        logger.info(log_msg)
        # 如果有可用密钥，则获取并存储可用的模型列表
        if key_manager.api_keys:
            try:
                # 使用第一个有效密钥获取模型列表
                all_models = await GeminiClient.list_available_models(key_manager.api_keys[0])
                # 存储模型列表 (移除 "models/" 前缀)
                GeminiClient.AVAILABLE_MODELS = [model.replace(
                    "models/", "") for model in all_models]
                log_msg = format_log_message('INFO', f"Available models: {GeminiClient.AVAILABLE_MODELS}")
                logger.info(log_msg)
            except Exception as e:
                # 如果获取模型列表失败，记录错误
                log_msg = format_log_message('ERROR', f"获取模型列表失败: {e}", extra={'request_type': 'startup', 'status_code': 'N/A'})
                logger.error(log_msg)

# --- API 端点 ---
@app.get("/v1/models", response_model=ModelList)
def list_models():
    """处理获取模型列表的 GET 请求"""
    log_msg = format_log_message('INFO', "Received request to list models", extra={'request_type': 'list_models', 'status_code': 200})
    logger.info(log_msg)
    # 返回符合 OpenAI 格式的模型列表响应
    return ModelList(data=[{"id": model, "object": "model", "created": 1678888888, "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS])

async def verify_password(request: Request):
    """依赖项函数，用于验证请求头中的 Bearer Token 是否与配置的密码匹配"""
    # 仅在设置了 PASSWORD 环境变量时进行验证
    if PASSWORD:
        auth_header = request.headers.get("Authorization") # 获取 Authorization 请求头
        # 检查请求头是否存在且格式是否正确 ("Bearer <token>")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail="Unauthorized: Missing or invalid token")
        token = auth_header.split(" ")[1] # 提取 token 部分
        # 检查 token 是否与配置的密码匹配
        if token != PASSWORD:
            raise HTTPException(
                status_code=401, detail="Unauthorized: Invalid token")

async def process_request(chat_request: ChatCompletionRequest, http_request: Request, request_type: Literal['stream', 'non-stream']):
    """
    核心请求处理函数，处理聊天补全请求 (流式和非流式)。

    Args:
        chat_request: 解析后的聊天请求体 (ChatCompletionRequest 模型)。
        http_request: FastAPI 的原始请求对象，用于检查断开连接等。
        request_type: 请求类型 ('stream' 或 'non-stream')。

    Returns:
        StreamingResponse: 如果是流式请求。
        ChatCompletionResponse: 如果是非流式请求。

    Raises:
        HTTPException: 如果发生错误 (例如无效请求、无可用密钥、所有密钥失败等)。
    """
    global current_api_key # 声明需要访问全局变量
    # 应用防滥用检查
    protect_from_abuse(
        http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP)

    # --- 请求验证 ---
    # 检查 messages 字段是否为空
    if not chat_request.messages:
        error_msg = "Messages cannot be empty"
        extra_log = {'request_type': request_type, 'model': chat_request.model, 'status_code': 400, 'error_message': error_msg}
        log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
        logger.error(log_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    # 检查请求的模型是否在可用模型列表中
    # 确保 GeminiClient.AVAILABLE_MODELS 已经初始化
    if not GeminiClient.AVAILABLE_MODELS and key_manager.api_keys:
         logger.warning("可用模型列表为空，可能启动时获取失败，尝试重新获取...")
         try:
             # 使用第一个有效密钥重新获取模型列表
             all_models = await GeminiClient.list_available_models(key_manager.api_keys[0])
             GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models]
             logger.info(f"重新获取可用模型: {GeminiClient.AVAILABLE_MODELS}")
         except Exception as e:
             logger.error(f"重新获取模型列表失败: {e}")
             # 即使获取失败，也允许请求继续，但可能会因模型无效而失败

    if chat_request.model not in GeminiClient.AVAILABLE_MODELS:
        error_msg = f"无效的模型: {chat_request.model}. 可用模型: {GeminiClient.AVAILABLE_MODELS}"
        extra_log = {'request_type': request_type, 'model': chat_request.model, 'status_code': 400, 'error_message': error_msg}
        log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
        logger.error(log_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    # --- 重试逻辑 ---
    # 重置本次请求已尝试过的密钥集合
    key_manager.reset_tried_keys_for_request()

    # 检查当前是否有可用的 API 密钥
    # 注意：这里检查的是全局 current_api_key，它可能在应用启动时就因无有效密钥而为 None
    # 或者在之前的请求失败且所有密钥都尝试过后变为 None
    # 增加有效性检查，因为密钥可能在运行时失效
    is_current_key_valid = await test_api_key(current_api_key) if current_api_key else False
    if current_api_key is None or not is_current_key_valid:
        # 尝试再获取一次，以防在应用运行期间有密钥恢复或添加
        logger.info(f"当前 API 密钥 {'无效' if current_api_key else '为空'}，尝试获取新的可用密钥...")
        current_api_key = key_manager.get_available_key(force_check=True) # 添加 force_check 确保重新评估
        if current_api_key is None: # 如果仍然没有
            error_msg = "没有可用的 API 密钥"
            extra_log = {'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': error_msg}
            log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
            logger.error(log_msg)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_msg)
        else:
             logger.info(f"已获取新的可用密钥: {current_api_key[:8]}...")


    # 初始化变量，用于存储转换后的消息和系统指令
    contents = None
    system_instruction = None

    # 设置重试次数为可用密钥的数量 (至少为 1)
    retry_attempts = len(key_manager.api_keys) if key_manager.api_keys else 1
    # 开始重试循环
    for attempt in range(1, retry_attempts + 1):
        # 在第一次尝试时获取一个可用的密钥 (后续失败时会在 handle_gemini_error 中切换)
        # 注意：如果第一次尝试就失败，handle_gemini_error 会切换密钥，所以后续循环开始时不需要再次 get_available_key
        # if attempt == 1: # 移除此逻辑，因为 current_api_key 在循环开始前已确保有效或获取新的
            # 确保我们使用的是当前有效的密钥 (可能在上次请求失败后切换过)
            # 如果 current_api_key 在循环开始前就无效，这里会获取一个新的
            # is_key_still_valid = await test_api_key(current_api_key) if current_api_key else False # 检查当前密钥是否仍然有效
            # if not is_key_still_valid:
            #      current_api_key = key_manager.get_available_key()

        # 再次检查密钥是否有效 (可能在切换后变为 None)
        if current_api_key is None:
            log_msg_no_key = format_log_message('WARNING', "没有可用的 API 密钥，跳过本次尝试", extra={'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A'})
            logger.warning(log_msg_no_key)
            break  # 没有可用密钥，跳出重试循环

        # 记录当前尝试使用的密钥
        extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A', 'error_message': ''}
        log_msg = format_log_message('INFO', f"第 {attempt}/{retry_attempts} 次尝试 ... 使用密钥: {current_api_key[:8]}...", extra=extra_log)
        logger.info(log_msg)

        # 再次进行安全检查
        if current_api_key is None:
            log_msg_no_key = format_log_message('WARNING', "API密钥为空，无法创建GeminiClient实例", extra={'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A'})
            logger.warning(log_msg_no_key)
            continue  # 跳过本次循环

        # --- 调用 Gemini API ---
        try:
            # 使用当前密钥创建 GeminiClient 实例
            gemini_client = GeminiClient(current_api_key)
            # 仅在第一次尝试时转换消息格式 (避免重复转换)
            if contents is None and system_instruction is None:
                # 转换消息，注意 convert_messages 现在不是异步的
                conversion_result = gemini_client.convert_messages(chat_request.messages)
                # 检查转换结果是否为错误列表
                if isinstance(conversion_result, list): # 如果 convert_messages 返回错误列表
                    if not conversion_result:  # 处理空列表情况 (理论上不应发生)
                        error_msg = "消息格式错误: 无效的消息格式"
                    elif all(isinstance(item, str) for item in conversion_result): # 确认是字符串错误列表
                        error_msg = "消息格式错误: " + ", ".join(conversion_result)
                    else: # 未知错误格式
                         error_msg = "消息转换时发生未知错误"

                    extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 400, 'error_message': error_msg}
                    log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
                    logger.error(log_msg)
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
                else:
                    # 解包转换结果
                    contents, system_instruction = conversion_result

        except Exception as e:
            # 捕获创建客户端或转换消息时的异常
            error_msg = f"创建GeminiClient或转换消息时出错: {str(e)}"
            extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A', 'error_message': error_msg}
            log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
            logger.error(log_msg)
            # 如果还有重试机会，切换密钥并继续下一次循环
            if attempt < retry_attempts:
                switch_api_key() # 手动切换密钥
                continue
            else: # 如果是最后一次尝试失败，则跳出循环
                break

        try:
            # --- 处理流式或非流式请求 ---
            # 根据环境变量和模型名称确定当前请求的安全设置
            # 将确定逻辑移到 stream/non-stream 判断之外，以便记录一次
            current_safety_settings = safety_settings_g2 if DISABLE_SAFETY_FILTERING or 'gemini-2.0-flash-exp' in chat_request.model else safety_settings
            # 记录为本次请求选择的安全设置 (DEBUG 级别)
            chosen_setting_name = "safety_settings_g2 (OFF)" if current_safety_settings == safety_settings_g2 else "safety_settings (BLOCK_NONE)"
            logger.debug(f"为模型 {chat_request.model} 选择的安全设置为: {chosen_setting_name}")

            if chat_request.stream:
                # --- 处理流式请求 ---
                async def stream_generator():
                    """异步生成器，用于产生流式响应块"""
                    try:
                        # 调用 GeminiClient 的 stream_chat 方法
                        async for chunk in gemini_client.stream_chat(chat_request, contents, current_safety_settings, system_instruction):
                            # 将返回的文本块格式化为 OpenAI SSE 格式
                            formatted_chunk = {"id": "chatcmpl-someid", "object": "chat.completion.chunk", "created": 1234567,
                                               "model": chat_request.model, "choices": [{"delta": {"role": "assistant", "content": chunk}, "index": 0, "finish_reason": None}]}
                            # 产生格式化后的数据块
                            yield f"data: {json.dumps(formatted_chunk)}\n\n"
                        # 流结束时发送 [DONE] 标记
                        yield "data: [DONE]\n\n"

                    except asyncio.CancelledError:
                        # 如果客户端断开连接导致任务取消
                        extra_log_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '客户端已断开连接'}
                        log_msg = format_log_message('INFO', "客户端连接已中断", extra=extra_log_cancel)
                        logger.info(log_msg)
                        # 此处不需要再 raise，生成器正常结束
                    except Exception as e:
                        # 捕获 stream_chat 内部可能抛出的其他异常 (例如安全过滤导致的 ValueError)
                        # 处理 Gemini API 错误，获取错误详情
                        error_detail = handle_gemini_error(
                            e, current_api_key, key_manager) # handle_gemini_error 会尝试切换密钥
                        # 在流中发送错误信息
                        yield f"data: {json.dumps({'error': {'message': error_detail, 'type': 'gemini_error'}})}\n\n"
                        # 错误已发送，生成器正常结束
                # 返回 StreamingResponse 对象
                return StreamingResponse(stream_generator(), media_type="text/event-stream")
            else:
                # --- 处理非流式请求 ---
                async def run_gemini_completion():
                    """在线程中运行同步的 complete_chat 方法"""
                    try:
                        # 调用 GeminiClient 的 complete_chat 方法 (在线程中运行避免阻塞事件循环)
                        # 注意：current_safety_settings 已在外部确定
                        response_content = await asyncio.to_thread(gemini_client.complete_chat, chat_request, contents, current_safety_settings, system_instruction)
                        return response_content
                    except asyncio.CancelledError:
                        # 如果任务被取消 (通常因为客户端断开)
                        extra_log_gemini_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '客户端断开导致API调用取消'}
                        log_msg = format_log_message('INFO', "API调用因客户端断开而取消", extra=extra_log_gemini_cancel)
                        logger.info(log_msg)
                        raise # 重新抛出 CancelledError

                async def check_client_disconnect():
                    """后台任务，定期检查客户端是否已断开连接"""
                    while True:
                        if await http_request.is_disconnected():
                            extra_log_client_disconnect = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '检测到客户端断开连接'}
                            log_msg = format_log_message('INFO', "客户端连接已中断，正在取消API请求", extra=extra_log_client_disconnect)
                            logger.info(log_msg)
                            return True # 返回 True 表示客户端已断开
                        await asyncio.sleep(0.5) # 每 0.5 秒检查一次

                # 创建 Gemini 请求任务和客户端断开检查任务
                gemini_task = asyncio.create_task(run_gemini_completion())
                disconnect_task = asyncio.create_task(check_client_disconnect())

                try:
                    # 等待两个任务中的任何一个首先完成
                    done, pending = await asyncio.wait(
                        [gemini_task, disconnect_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # 如果是断开检查任务先完成
                    if disconnect_task in done:
                        gemini_task.cancel() # 取消 Gemini 请求任务
                        try:
                            await gemini_task # 等待取消操作完成
                        except asyncio.CancelledError:
                            extra_log_gemini_task_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': 'API任务已终止'}
                            log_msg = format_log_message('INFO', "API任务已成功取消", extra=extra_log_gemini_task_cancel)
                            logger.info(log_msg)
                        # 抛出 HTTP 408 错误，表示客户端超时 (断开连接)
                        raise HTTPException(status_code=status.HTTP_408_REQUEST_TIMEOUT, detail="客户端连接已中断")

                    # 如果是 Gemini 请求任务先完成
                    if gemini_task in done:
                        disconnect_task.cancel() # 取消断开检查任务
                        try:
                            await disconnect_task # 等待取消完成
                        except asyncio.CancelledError:
                            pass # 忽略取消错误
                        # 获取 Gemini 响应结果
                        response_content = gemini_task.result()
                        # 检查响应文本是否为空 (可能由内容过滤导致)
                        if response_content.text == "":
                            extra_log_empty_response = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 204, 'error_message': '空响应'}
                            log_msg = format_log_message('WARNING', f"Gemini API 返回空响应，可能是模型限制或内容过滤，尝试下一个密钥", extra=extra_log_empty_response)
                            logger.warning(log_msg)
                            # 记录详细的原始响应 (DEBUG 级别)
                            if hasattr(response_content, 'json_dumps'):
                                logger.debug(f"完整响应: {response_content.json_dumps}")
                            # 如果还有重试机会，切换密钥并继续下一次循环
                            if attempt < retry_attempts:
                                switch_api_key() # 手动切换密钥
                                continue
                            else: # 如果是最后一次尝试仍然为空，跳出循环
                                break
                        # 构建符合 OpenAI 格式的成功响应
                        response = ChatCompletionResponse(id="chatcmpl-someid", object="chat.completion", created=1234567890, model=chat_request.model,
                                                        choices=[{"index": 0, "message": {"role": "assistant", "content": response_content.text}, "finish_reason": "stop"}])
                        # 记录成功日志
                        extra_log_success = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 200}
                        log_msg = format_log_message('INFO', "请求处理成功", extra=extra_log_success)
                        logger.info(log_msg)
                        # 返回成功响应，结束函数执行
                        return response

                except asyncio.CancelledError:
                    # 如果 process_request 本身被取消 (例如应用关闭)
                    extra_log_request_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message':"请求被取消" }
                    log_msg = format_log_message('INFO', "请求取消", extra=extra_log_request_cancel)
                    logger.info(log_msg)
                    raise # 重新抛出异常

        except HTTPException as e:
            # 捕获之前抛出的 HTTPException (例如客户端断开连接的 408)
            if e.status_code == status.HTTP_408_REQUEST_TIMEOUT:
                extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model,
                            'status_code': 408, 'error_message': '客户端连接中断'}
                log_msg = format_log_message('ERROR', "客户端连接中断，终止后续重试", extra=extra_log)
                logger.error(log_msg)
                raise # 重新抛出 408 异常，不再重试
            else:
                raise # 重新抛出其他 HTTPException
        except Exception as e:
            # 捕获调用 Gemini API 时发生的其他异常
            handle_gemini_error(e, current_api_key, key_manager) # 处理错误并尝试切换密钥
            # 如果还有重试机会，继续下一次循环
            if attempt < retry_attempts:
                # switch_api_key() # handle_gemini_error 内部会调用 switch_api_key
                continue
            else: # 如果是最后一次尝试失败，跳出循环
                break

    # --- 所有重试均失败 ---
    # 如果循环正常结束 (所有密钥都尝试过且未成功返回)
    msg = "所有API密钥均失败,请稍后重试"
    extra_log_all_fail = {'key': "ALL", 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': msg}
    log_msg = format_log_message('ERROR', msg, extra=extra_log_all_fail)
    logger.error(log_msg)
    # 抛出 HTTP 500 内部服务器错误
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest, http_request: Request, _: None = Depends(verify_password)):
    """处理聊天补全的 POST 请求"""
    # 记录收到的请求体 (DEBUG 级别)
    logger.debug(f"Received chat completion request: {request.dict()}")
    # 调用核心请求处理函数
    return await process_request(request, http_request, "stream" if request.stream else "non-stream")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """FastAPI 全局异常处理器，捕获所有未被特定处理器捕获的异常"""
    error_message = translate_error(str(exc)) # 翻译错误信息
    extra_log_unhandled_exception = {'status_code': 500, 'error_message': error_message}
    log_msg = format_log_message('ERROR', f"Unhandled exception: {error_message}", extra=extra_log_unhandled_exception)
    logger.error(log_msg) # 记录错误日志
    # 返回标准的 JSON 错误响应
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=ErrorResponse(message=str(exc), type="internal_error").dict())


@app.get("/", response_class=HTMLResponse)
async def root():
    """处理根路径 GET 请求，返回一个简单的 HTML 状态页面"""
    # 统计有效和无效的 API 密钥数量
    valid_keys_count = 0
    invalid_keys_count = 0

    # 异步检查所有配置的 API 密钥
    # 注意：这里每次访问根路径都会重新检查，可能会有性能影响，但提供了实时状态
    key_check_tasks = [test_api_key(key) for key in key_manager.api_keys]
    results = await asyncio.gather(*key_check_tasks, return_exceptions=True) # 并发执行检查

    for result in results:
        if isinstance(result, Exception) or not result: # 如果检查出错或返回 False
            invalid_keys_count += 1
        else:
            valid_keys_count += 1

    # 构建 HTML 页面内容
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gemini API 代理服务</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; max-width: 800px; margin: auto; padding: 20px; line-height: 1.6; }}
            h1, h2 {{ text-align: center; color: #333; }}
            .info-box {{ background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; padding: 20px; margin-bottom: 20px; }}
            .status {{ color: #28a745; font-weight: bold; }}
            .key-status {{ display: flex; justify-content: space-around; max-width: 400px; margin: 10px auto; }}
            .valid-key {{ color: #28a745; }}
            .invalid-key {{ color: #dc3545; }}
        </style>
    </head>
    <body>
        <h1>🤖 Gemini API 代理服务</h1>

        <div class="info-box">
            <h2>🟢 运行状态</h2>
            <p class="status">服务运行中</p>
            <p>版本: v{__version__}</p>
            <p>API密钥总数: {len(key_manager.api_keys)}</p>
            <div class="key-status">
                <p class="valid-key">有效API密钥: {valid_keys_count}</p>
                <p class="invalid-key">无效API密钥: {invalid_keys_count}</p>
            </div>
            <p>可用模型数量: {len(GeminiClient.AVAILABLE_MODELS)}</p>
            <p>全局安全过滤禁用: {'是' if DISABLE_SAFETY_FILTERING else '否'}</p>
        </div>

        <div class="info-box">
            <h2>⚙️ 环境配置</h2>
            <p>每分钟请求限制: {MAX_REQUESTS_PER_MINUTE}</p>
            <p>每IP每日请求限制: {MAX_REQUESTS_PER_DAY_PER_IP}</p>
            <p>最大重试次数 (等于可用密钥数): {len(key_manager.api_keys)}</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content) # 返回 HTML 响应
