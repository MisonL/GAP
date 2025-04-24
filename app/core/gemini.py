# 导入必要的库
# Import necessary libraries
import json      # 用于处理 JSON 数据 (Used for handling JSON data)
import os        # 用于访问环境变量 (Used for accessing environment variables)
import asyncio   # 用于异步操作 (Used for asynchronous operations)
# 注意：调整导入路径以反映新的目录结构
# Note: Adjust import paths to reflect the new directory structure
from ..api.models import ChatCompletionRequest # 仅导入需要的模型 (Import only the required model)
from typing import Optional, Dict, Any, List, AsyncGenerator, Union # 增加了 AsyncGenerator, Union (Added AsyncGenerator, Union)
import httpx     # 用于发送异步 HTTP 请求 (Used for sending asynchronous HTTP requests)
import logging   # 用于日志记录 (Used for logging)
from .response_wrapper import ResponseWrapper # 新增导入 (New import)
# convert_messages 不再由此类直接调用，由外部调用者处理
# convert_messages is no longer called directly by this class, handled by the external caller

# 获取名为 'my_logger' 的日志记录器实例
# Get the logger instance named 'my_logger'
logger = logging.getLogger('my_logger')

# 定义与 Gemini API 交互的客户端类
# Define the client class for interacting with the Gemini API
class GeminiClient:
    """
    用于与 Google Gemini API 进行交互的客户端。
    此类现在专注于 API 调用，消息转换由外部处理。
    Client for interacting with the Google Gemini API.
    This class now focuses on API calls, message conversion is handled externally.
    """
    AVAILABLE_MODELS = []  # 类变量，存储可用的模型列表 (Class variable, stores the list of available models)
    # 从环境变量读取额外的模型名称，用逗号分隔
    # Read additional model names from environment variables, separated by commas
    EXTRA_MODELS = [model.strip() for model in os.environ.get("EXTRA_MODELS", "").split(",") if model.strip()] # 确保去除首尾空格并过滤空字符串 (Ensure leading/trailing whitespace is removed and empty strings are filtered)

    def __init__(self, api_key: str):
        """
        初始化 GeminiClient。
        Initializes the GeminiClient.

        Args:
            api_key (str): 用于访问 Gemini API 的 API 密钥。The API key used to access the Gemini API.
        """
        if not api_key:
            raise ValueError("API Key 不能为空") # Raise error if API key is empty
        self.api_key = api_key # 存储 API 密钥 (Store the API key)

    async def stream_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]]) -> AsyncGenerator[Union[str, Dict[str, Any]], None]:
        """
        以流式方式向 Gemini API 发送聊天请求并处理响应。
        现在接收已转换的 contents 和 system_instruction。
        Sends a chat request to the Gemini API in a streaming manner and processes the response.
        Now receives converted contents and system_instruction.

        Args:
            request (ChatCompletionRequest): 包含请求参数的 ChatCompletionRequest 对象 (主要用于获取模型名称和参数)。ChatCompletionRequest object containing request parameters (mainly used to get model name and parameters).
            contents: Gemini API 格式的消息历史列表。List of message history in Gemini API format.
            safety_settings: 要应用的安全设置列表。List of safety settings to apply.
            system_instruction: Gemini API 格式的系统指令字典 (如果提供)。Dictionary of system instructions in Gemini API format (if provided).

        Yields:
            联合类型[str, Dict[str, Any]]: 从 API 返回的文本块 (str) 或包含特殊键 (_usage_metadata 或 _final_finish_reason) 的字典。Union[str, Dict[str, Any]]: Text chunks (str) returned from the API or dictionaries containing special keys (_usage_metadata or _final_finish_reason).

        Raises:
            httpx.HTTPStatusError: 如果 API 返回错误状态码。If the API returns an error status code.
            httpx.RequestError: 如果发生网络连接错误。If a network connection error occurs.
            Exception: 其他意外错误。Other unexpected errors.
        """
        logger.info(f"流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model}) →") # Log the start of the streaming request
        text_yielded = False # 标记是否已产生文本 (Flag indicating if text has been yielded)
        safety_issue_detected = None # 存储检测到的安全问题 (Stores detected safety issues)
        usage_metadata = None # 存储使用情况元数据 (Stores usage metadata)
        final_finish_reason = "STOP" # 存储最终完成原因，默认为 STOP (Stores the final finish reason, defaults to STOP)
        # 根据模型名称选择 API 版本 (这个逻辑可能需要更新或移除，取决于 Google API 的演进)
        # Select API version based on model name (this logic might need updating or removal depending on Google API evolution)
        api_version = "v1beta" # 默认使用 v1beta API 版本 (Default to v1beta API version)
        # url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:streamGenerateContent?key={self.api_key}&alt=sse"
        # 统一使用 generateContent，流式通过 stream=true 参数控制 (如果 API 支持)
        # Use generateContent uniformly, streaming controlled by stream=true parameter (if API supports)
        # 查阅最新文档，似乎 streamGenerateContent 仍然是推荐的流式端点
        # Consulting the latest documentation, it seems streamGenerateContent is still the recommended streaming endpoint
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:streamGenerateContent?key={self.api_key}&alt=sse" # 构建 API 请求 URL (Build the API request URL)

        headers = {"Content-Type": "application/json"} # 设置请求头 (Set request headers)
        data = { # 构建请求体数据 (Build request body data)
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                # topP, topK 等其他生成参数可以根据需要添加
                # topP, topK, etc. other generation parameters can be added as needed
            },
            "safetySettings": safety_settings,
        }
        if system_instruction:
            data["system_instruction"] = system_instruction # 如果有系统指令则添加到请求体 (Add system instruction to request body if provided)

        try:
            async with httpx.AsyncClient() as client: # 创建异步 HTTP 客户端 (Create an asynchronous HTTP client)
                # 设置请求超时：总超时 600 秒，读取超时 120 秒
                # Set request timeout: total timeout 600 seconds, read timeout 120 seconds
                async with client.stream("POST", url, headers=headers, json=data, timeout=httpx.Timeout(600.0, read=120.0)) as response: # 发送流式 POST 请求 (Send streaming POST request)
                    # 检查初始 HTTP 响应状态码
                    # Check initial HTTP response status code
                    if response.status_code >= 400:
                         # 尝试读取错误响应体
                         # Attempt to read error response body
                         error_body = await response.aread()
                         error_detail = f"API 请求失败，状态码: {response.status_code}, 响应: {error_body.decode('utf-8', errors='replace')}" # 格式化错误详情 (Format error details)
                         logger.error(error_detail) # 记录错误 (Log the error)
                         # 根据状态码抛出特定异常或通用异常
                         # Raise specific or general exception based on status code
                         response.raise_for_status() # 这会根据状态码自动抛出 httpx.HTTPStatusError (This will automatically raise httpx.HTTPStatusError based on status code)

                    buffer = b"" # 初始化缓冲区 (Initialize buffer)
                    async for line in response.aiter_lines(): # 异步迭代响应的行 (Asynchronously iterate over response lines)
                        if not line.strip(): continue # 跳过空行 (Skip empty lines)
                        if line.startswith("data: "): line = line[len("data: "):] # 移除 SSE 格式的 "data: " 前缀 (Remove "data: " prefix for SSE format)
                        buffer += line.encode('utf-8') # 将行添加到缓冲区 (Add line to buffer)
                        try:
                            data_chunk = json.loads(buffer.decode('utf-8')) # 尝试解析缓冲区中的 JSON (Attempt to parse JSON from buffer)
                            buffer = b"" # 清空缓冲区 (Clear the buffer)

                            if 'usageMetadata' in data_chunk:
                                usage_metadata = data_chunk['usageMetadata'] # 提取使用情况元数据 (Extract usage metadata)
                                logger.debug(f"流接收到 usageMetadata: {usage_metadata}") # 记录使用情况元数据 (Log usage metadata)

                            if 'candidates' in data_chunk and data_chunk['candidates']:
                                candidate = data_chunk['candidates'][0] # 获取第一个候选 (Get the first candidate)
                                current_finish_reason = candidate.get("finishReason") # 获取当前完成原因 (Get the current finish reason)

                                # 提取文本部分
                                # Extract text part
                                text_in_chunk = "" # 初始化块中的文本 (Initialize text in chunk)
                                if 'content' in candidate and 'parts' in candidate['content']:
                                    for part in candidate['content']['parts']:
                                        if 'text' in part:
                                            text_in_chunk += part['text'] # 累加文本 (Accumulate text)

                                if text_in_chunk:
                                    yield text_in_chunk # Yield 文本块 (Yield the text chunk)
                                    text_yielded = True # 标记已产生文本 (Mark that text has been yielded)

                                # 处理完成原因和安全问题
                                # Handle finish reason and safety issues
                                if current_finish_reason and current_finish_reason != "STOP":
                                    logger.warning(f"流式响应被标记: {current_finish_reason}, Model: {request.model}, Key: {self.api_key[:8]}...") # Log warning for non-STOP finish reason
                                    safety_issue_detected = f"完成原因: {current_finish_reason}" # 记录安全问题详情 (Record safety issue details)
                                    final_finish_reason = current_finish_reason # 更新最终原因 (Update the final finish reason)

                                if 'safetyRatings' in candidate:
                                    for rating in candidate['safetyRatings']:
                                        if rating.get('blocked') or rating.get('probability') in ['HIGH', 'MEDIUM']: # 也考虑 MEDIUM 概率 (Also consider MEDIUM probability)
                                            log_level = logging.WARNING if rating.get('blocked') or rating.get('probability') == 'HIGH' else logging.INFO # 根据严重程度设置日志级别 (Set log level based on severity)
                                            logger.log(log_level, f"流式响应安全评分: Category={rating['category']}, Probability={rating.get('probability', 'N/A')}, Blocked={rating.get('blocked', 'N/A')}, Model: {request.model}, Key: {self.api_key[:8]}...") # Log safety rating
                                            if rating.get('blocked') or rating.get('probability') == 'HIGH':
                                                safety_issue_detected = f"安全问题: {rating['category']}" # 记录安全问题详情 (Record safety issue details)
                                                if final_finish_reason == "STOP": final_finish_reason = "SAFETY" # 如果最终原因是 STOP，则更新为 SAFETY (If final reason is STOP, update to SAFETY)

                        except json.JSONDecodeError:
                            logger.debug(f"JSON 解析错误, 当前缓冲区: {buffer}") # Log JSON parsing error (DEBUG level)
                            continue # 继续处理下一行 (Continue processing the next line)
                        except Exception as inner_e: # 捕获处理流数据块时内部的异常 (Catch internal exceptions when processing stream data chunks)
                            logger.error(f"处理流数据块时出错: {inner_e}", exc_info=True) # Log error with exception info
                            # 可以选择在此处中断流或继续处理下一个块
                            # Can choose to break the stream here or continue processing the next chunk
                            raise # 重新抛出异常，让外部调用者知道发生了错误 (Re-raise the exception so the external caller knows an error occurred)

        except httpx.HTTPStatusError as e:
            logger.error(f"流式 API 请求失败 (HTTPStatusError): {e.response.status_code} - {e.response.text}", exc_info=False) # 只记录关键错误信息，避免日志过长 (Only log key error information to avoid long logs)
            raise # 重新抛出，由调用者处理 (Re-raise, handled by the caller)
        except httpx.RequestError as e:
            logger.error(f"流式 API 请求网络错误 (RequestError): {e}", exc_info=True) # Log network error with exception info
            raise # 重新抛出网络请求错误 (Re-raise network request error)
        except Exception as e:
            # 捕获流处理过程中的其他异常
            # Catch other exceptions during stream processing
            error_detail = f"流处理意外错误: {e}" # 格式化错误详情 (Format error details)
            logger.error(error_detail, exc_info=True) # Log error with exception info
            # 可以抛出自定义异常或重新抛出原始异常
            # Can raise a custom exception or re-raise the original exception
            raise RuntimeError(error_detail) from e # 使用 RuntimeError 包装原始异常 (Wrap the original exception in a RuntimeError)
        finally:
            logger.info(f"流式请求结束 (Key: {self.api_key[:8]}..., Model: {request.model}) ←") # Log the end of the streaming request
            # 如果流结束但从未产生文本且检测到安全问题，记录错误但不在此处抛出异常，
            # If the stream ends but no text was ever yielded and a safety issue was detected, log an error but do not raise an exception here,
            # 让调用者根据最终的 finish_reason 和 usage_metadata 来处理这种情况
            # allowing the caller to handle this situation based on the final finish_reason and usage_metadata
            if not text_yielded and safety_issue_detected:
                logger.error(f"流结束但未产生文本，检测到安全问题 ({safety_issue_detected}), Key: {self.api_key[:8]}...") # Log error if stream ended without text and safety issue detected

            # 在生成器正常结束时，按顺序 yield 最终完成原因和使用情况元数据（如果存在）
            # When the generator ends normally, yield the final finish reason and usage metadata (if they exist) in order
            yield {'_final_finish_reason': final_finish_reason} # Yield final finish reason
            if usage_metadata:
                yield {'_usage_metadata': usage_metadata} # Yield usage metadata if available


    async def complete_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]]) -> ResponseWrapper:
        """
        [异步] 以非流式方式向 Gemini API 发送聊天请求并获取完整响应。
        现在接收已转换的 contents 和 system_instruction。
        [Async] Sends a chat request to the Gemini API in a non-streaming manner and gets the complete response.
        Now receives converted contents and system_instruction.

        Args:
            request (ChatCompletionRequest): 包含请求参数的 ChatCompletionRequest 对象。ChatCompletionRequest object containing request parameters.
            contents: Gemini API 格式的消息历史列表。List of message history in Gemini API format.
            safety_settings: 要应用的安全设置列表。List of safety settings to apply.
            system_instruction: Gemini API 格式的系统指令字典 (如果提供)。Dictionary of system instructions in Gemini API format (if provided).

        Returns:
            ResponseWrapper: 包含解析后响应数据的 ResponseWrapper 对象。ResponseWrapper object containing parsed response data.

        Raises:
            httpx.RequestError: 如果发生网络请求错误。If a network request error occurs.
            httpx.HTTPStatusError: 如果 API 返回错误状态码。If the API returns an error status code.
        """
        logger.info(f"非流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model})") # Log the start of the non-streaming request
        # 根据模型名称选择 API 版本
        # Select API version based on model name
        api_version = "v1beta" # 默认使用 v1beta API 版本 (Default to v1beta API version)
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:generateContent?key={self.api_key}" # 构建 API 请求 URL (Build the API request URL)
        headers = {"Content-Type": "application/json"} # 设置请求头 (Set request headers)
        data = { # 构建请求体数据 (Build request body data)
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                 # topP, topK 等其他生成参数可以根据需要添加
                 # topP, topK, etc. other generation parameters can be added as needed
            },
            "safetySettings": safety_settings,
        }
        if system_instruction:
            data["system_instruction"] = system_instruction # 如果有系统指令则添加到请求体 (Add system instruction to request body if provided)

        async with httpx.AsyncClient() as client: # 创建异步 HTTP 客户端 (Create an asynchronous HTTP client)
             # 设置请求超时：总超时 600 秒，读取超时 120 秒
             # Set request timeout: total timeout 600 seconds, read timeout 120 seconds
            response = await client.post(url, headers=headers, json=data, timeout=httpx.Timeout(600.0, read=120.0)) # 发送 POST 请求 (Send POST request)
            # 如果响应状态码表示错误 (>= 400)，则抛出 HTTPStatusError
            # If the response status code indicates an error (>= 400), raise HTTPStatusError
            # 在抛出异常前记录更详细的错误信息
            # Log more detailed error information before raising the exception
            if response.status_code >= 400:
                 error_detail = f"API 请求失败，状态码: {response.status_code}, 响应: {response.text}" # 格式化错误详情 (Format error details)
                 logger.error(error_detail) # 记录错误 (Log the error)
            response.raise_for_status() # 检查 HTTP 错误并抛出异常 (Check for HTTP errors and raise exception)
            # 将响应的 JSON 数据包装在 ResponseWrapper 对象中并返回
            # Wrap the response's JSON data in a ResponseWrapper object and return it
            logger.info(f"非流式请求成功 (Key: {self.api_key[:8]}..., Model: {request.model})") # Log successful non-streaming request
            return ResponseWrapper(response.json()) # 返回 ResponseWrapper 实例 (Return ResponseWrapper instance)


    @staticmethod
    async def list_available_models(api_key: str) -> List[str]:
        """
        [静态方法] 获取指定 API Key 可用的模型列表。
        [Static Method] Gets the list of available models for the specified API Key.

        Args:
            api_key: 用于查询的 Google Gemini API Key。The Google Gemini API Key used for the query.

        Returns:
            List[str]: 可用模型名称列表 (移除了 "models/" 前缀)。List of available model names (with "models/" prefix removed).

        Raises:
            httpx.RequestError: 如果发生网络请求错误。If a network request error occurs.
            httpx.HTTPStatusError: 如果 API 返回错误状态码。If the API returns an error status code.
            Exception: 其他解析错误。Other parsing errors.
        """
        if not api_key:
            raise ValueError("API Key 不能为空") # Raise error if API key is empty

        logger.info(f"尝试使用 Key {api_key[:8]}... 获取模型列表") # Log attempt to get model list
        api_version = "v1beta" # 通常使用 v1beta API 版本获取模型列表 (Usually use v1beta API version to get model list)
        url = f"https://generativelanguage.googleapis.com/{api_version}/models?key={api_key}" # 构建 API 请求 URL (Build the API request URL)
        headers = {"Content-Type": "application/json"} # 设置请求头 (Set request headers)

        try:
            async with httpx.AsyncClient() as client: # 创建异步 HTTP 客户端 (Create an asynchronous HTTP client)
                response = await client.get(url, headers=headers, timeout=60.0) # 发送 GET 请求，增加超时 (Send GET request, increased timeout)
                response.raise_for_status() # 检查 HTTP 错误 (Check for HTTP errors)
                data = response.json() # 解析 JSON 响应 (Parse the JSON response)

                model_names = [] # 初始化模型名称列表 (Initialize list of model names)
                if "models" in data and isinstance(data["models"], list):
                    for model_info in data["models"]:
                        if isinstance(model_info, dict) and "name" in model_info:
                            # 移除 "models/" 前缀
                            # Remove "models/" prefix
                            model_name = model_info["name"]
                            if model_name.startswith("models/"):
                                model_name = model_name[len("models/"):]
                            model_names.append(model_name) # 添加模型名称到列表 (Add model name to the list)
                logger.info(f"成功获取到 {len(model_names)} 个模型 (Key: {api_key[:8]}...)") # Log successful retrieval and number of models
                return model_names # 返回模型名称列表 (Return the list of model names)
        except httpx.HTTPStatusError as e:
             logger.error(f"获取模型列表失败 (HTTPStatusError): {e.response.status_code} - {e.response.text}", exc_info=False) # Log HTTPStatusError
             raise # 重新抛出 (Re-raise)
        except httpx.RequestError as e:
             logger.error(f"获取模型列表网络错误 (RequestError): {e}", exc_info=True) # Log RequestError
             raise # 重新抛出 (Re-raise)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
             logger.error(f"解析模型列表响应失败: {e}", exc_info=True) # Log parsing errors
             raise Exception(f"解析模型列表响应失败: {e}") from e # 包装为通用异常 (Wrap in a general exception)
        except Exception as e:
             logger.error(f"获取模型列表时发生未知错误: {e}", exc_info=True) # Log unknown errors
             raise # 重新抛出未知错误 (Re-raise unknown error)
