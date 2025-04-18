# 导入必要的库
# import requests  # 不再需要，使用 httpx
import json      # 用于处理 JSON 数据
import os        # 用于访问环境变量
import asyncio   # 用于异步操作
# 注意：调整导入路径以反映新的目录结构
from ..api.models import ChatCompletionRequest # 仅导入需要的模型
from typing import Optional, Dict, Any, List, AsyncGenerator, Union # 增加了 AsyncGenerator, Union
import httpx     # 用于发送异步 HTTP 请求
import logging   # 用于日志记录
# from .utils import StreamProcessingError # 移除了，因为 stream_chat 内部处理了
from .response_wrapper import ResponseWrapper # 新增导入
# convert_messages 不再由此类直接调用，由外部调用者处理

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger('my_logger')

# 定义与 Gemini API 交互的客户端类
class GeminiClient:
    """
    用于与 Google Gemini API 进行交互的客户端。
    此类现在专注于 API 调用，消息转换由外部处理。
    """
    AVAILABLE_MODELS = []  # 类变量，存储可用的模型列表
    # 从环境变量读取额外的模型名称，用逗号分隔
    EXTRA_MODELS = [model.strip() for model in os.environ.get("EXTRA_MODELS", "").split(",") if model.strip()] # 确保去除空格并过滤空字符串

    def __init__(self, api_key: str):
        """
        初始化 GeminiClient。

        Args:
            api_key (str): 用于访问 Gemini API 的 API 密钥。
        """
        if not api_key:
            raise ValueError("API Key 不能为空")
        self.api_key = api_key

    async def stream_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]]) -> AsyncGenerator[Union[str, Dict[str, Any]], None]:
        """
        以流式方式向 Gemini API 发送聊天请求并处理响应。
        现在接收已转换的 contents 和 system_instruction。

        Args:
            request (ChatCompletionRequest): 包含请求参数的 ChatCompletionRequest 对象 (主要用于获取模型名称和参数)。
            contents: Gemini API 格式的消息历史列表。
            safety_settings: 要应用的安全设置列表。
            system_instruction: Gemini API 格式的系统指令字典 (如果提供)。

        Yields:
            Union[str, Dict[str, Any]]: 从 API 返回的文本块 (str) 或包含 _usage_metadata 或 _final_finish_reason 的字典。

        Raises:
            httpx.HTTPStatusError: 如果 API 返回错误状态码。
            httpx.RequestError: 如果发生网络连接错误。
            Exception: 其他意外错误。
        """
        logger.info(f"流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model}) →")
        text_yielded = False
        safety_issue_detected = None
        usage_metadata = None
        final_finish_reason = "STOP"
        # 根据模型名称选择 API 版本 (这个逻辑可能需要更新或移除，取决于 Google API 的演进)
        api_version = "v1beta" # 默认使用 v1beta
        # url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:streamGenerateContent?key={self.api_key}&alt=sse"
        # 统一使用 generateContent，流式通过 stream=true 参数控制 (如果 API 支持)
        # 查阅最新文档，似乎 streamGenerateContent 仍然是推荐的流式端点
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:streamGenerateContent?key={self.api_key}&alt=sse"

        headers = {"Content-Type": "application/json"}
        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                # topP, topK 等其他参数可以按需添加
            },
            "safetySettings": safety_settings,
        }
        if system_instruction:
            data["system_instruction"] = system_instruction

        try:
            async with httpx.AsyncClient() as client:
                # 增加读超时为 120 秒，总超时保持 600 秒
                async with client.stream("POST", url, headers=headers, json=data, timeout=httpx.Timeout(600.0, read=120.0)) as response:
                    # 检查初始响应状态码
                    if response.status_code >= 400:
                         # 尝试读取错误详情
                         error_body = await response.aread()
                         error_detail = f"API 请求失败，状态码: {response.status_code}, 响应: {error_body.decode('utf-8', errors='replace')}"
                         logger.error(error_detail)
                         # 根据状态码抛出特定异常或通用异常
                         response.raise_for_status() # 这会根据状态码抛出 HTTPStatusError

                    buffer = b""
                    async for line in response.aiter_lines():
                        if not line.strip(): continue
                        if line.startswith("data: "): line = line[len("data: "):]
                        buffer += line.encode('utf-8')
                        try:
                            data_chunk = json.loads(buffer.decode('utf-8'))
                            buffer = b""

                            if 'usageMetadata' in data_chunk:
                                usage_metadata = data_chunk['usageMetadata']
                                logger.debug(f"流接收到 usageMetadata: {usage_metadata}")

                            if 'candidates' in data_chunk and data_chunk['candidates']:
                                candidate = data_chunk['candidates'][0]
                                current_finish_reason = candidate.get("finishReason")

                                # 提取文本部分
                                text_in_chunk = ""
                                if 'content' in candidate and 'parts' in candidate['content']:
                                    for part in candidate['content']['parts']:
                                        if 'text' in part:
                                            text_in_chunk += part['text']

                                if text_in_chunk:
                                    yield text_in_chunk
                                    text_yielded = True

                                # 处理完成原因和安全问题
                                if current_finish_reason and current_finish_reason != "STOP":
                                    logger.warning(f"流式响应被标记: {current_finish_reason}, Model: {request.model}, Key: {self.api_key[:8]}...")
                                    safety_issue_detected = f"完成原因: {current_finish_reason}"
                                    final_finish_reason = current_finish_reason # 更新最终原因

                                if 'safetyRatings' in candidate:
                                    for rating in candidate['safetyRatings']:
                                        if rating.get('blocked') or rating.get('probability') in ['HIGH', 'MEDIUM']: # 考虑 MEDIUM
                                            log_level = logging.WARNING if rating.get('blocked') or rating.get('probability') == 'HIGH' else logging.INFO
                                            logger.log(log_level, f"流式响应安全评分: Category={rating['category']}, Probability={rating.get('probability', 'N/A')}, Blocked={rating.get('blocked', 'N/A')}, Model: {request.model}, Key: {self.api_key[:8]}...")
                                            if rating.get('blocked') or rating.get('probability') == 'HIGH':
                                                safety_issue_detected = f"安全问题: {rating['category']}"
                                                if final_finish_reason == "STOP": final_finish_reason = "SAFETY"

                        except json.JSONDecodeError:
                            logger.debug(f"JSON 解析错误, 当前缓冲区: {buffer}")
                            continue
                        except Exception as inner_e: # 捕获处理块内部的异常
                            logger.error(f"处理流数据块时出错: {inner_e}", exc_info=True)
                            # 可以选择在这里中断或继续处理下一个块
                            raise # 重新抛出，让外部知道出错了

        except httpx.HTTPStatusError as e:
            logger.error(f"流式 API 请求失败 (HTTPStatusError): {e.response.status_code} - {e.response.text}", exc_info=False) # 只记录关键信息
            raise # 重新抛出，由调用者处理
        except httpx.RequestError as e:
            logger.error(f"流式 API 请求网络错误 (RequestError): {e}", exc_info=True)
            raise # 重新抛出
        except Exception as e:
            # 捕获流处理过程中的其他异常
            error_detail = f"流处理意外错误: {e}"
            logger.error(error_detail, exc_info=True)
            # 可以抛出自定义异常或重新抛出原始异常
            raise RuntimeError(error_detail) from e # 使用 RuntimeError 包装
        finally:
            logger.info(f"流式请求结束 (Key: {self.api_key[:8]}..., Model: {request.model}) ←")
            # 如果流结束但从未产生文本且检测到安全问题，记录错误但不在此处抛出异常，
            # 让调用者根据 final_finish_reason 和 usage_metadata 处理
            if not text_yielded and safety_issue_detected:
                logger.error(f"流结束但未产生文本，检测到安全问题 ({safety_issue_detected}), Key: {self.api_key[:8]}...")

            # 在生成器结束时，按顺序 yield 最终完成原因和使用情况元数据
            yield {'_final_finish_reason': final_finish_reason}
            if usage_metadata:
                yield {'_usage_metadata': usage_metadata}


    async def complete_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]]) -> ResponseWrapper:
        """
        [异步] 以非流式方式向 Gemini API 发送聊天请求并获取完整响应。
        现在接收已转换的 contents 和 system_instruction。

        Args:
            request (ChatCompletionRequest): 包含请求参数的 ChatCompletionRequest 对象。
            contents: Gemini API 格式的消息历史列表。
            safety_settings: 要应用的安全设置列表。
            system_instruction: Gemini API 格式的系统指令字典 (如果提供)。

        Returns:
            ResponseWrapper: 包含解析后响应数据的 ResponseWrapper 对象。

        Raises:
            httpx.RequestError: 如果发生网络请求错误。
            httpx.HTTPStatusError: 如果 API 返回错误状态码。
        """
        logger.info(f"非流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model})")
        # 根据模型名称选择 API 版本
        api_version = "v1beta" # 默认使用 v1beta
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                 # topP, topK 等其他参数可以按需添加
            },
            "safetySettings": safety_settings,
        }
        if system_instruction:
            data["system_instruction"] = system_instruction

        async with httpx.AsyncClient() as client:
             # 增加读超时为 120 秒，总超时保持 600 秒
            response = await client.post(url, headers=headers, json=data, timeout=httpx.Timeout(600.0, read=120.0))
            # 如果响应状态码表示错误，则抛出 HTTPStatusError
            # 在抛出前记录更详细的错误信息
            if response.status_code >= 400:
                 error_detail = f"API 请求失败，状态码: {response.status_code}, 响应: {response.text}"
                 logger.error(error_detail)
            response.raise_for_status()
            # 将响应的 JSON 数据包装在 ResponseWrapper 中并返回
            logger.info(f"非流式请求成功 (Key: {self.api_key[:8]}..., Model: {request.model})")
            return ResponseWrapper(response.json())


    @staticmethod
    async def list_available_models(api_key: str) -> List[str]:
        """
        [静态方法] 获取指定 API Key 可用的模型列表。

        Args:
            api_key: 用于查询的 Google Gemini API Key。

        Returns:
            List[str]: 可用模型名称列表 (移除了 "models/" 前缀)。

        Raises:
            httpx.RequestError: 如果发生网络请求错误。
            httpx.HTTPStatusError: 如果 API 返回错误状态码。
            Exception: 其他解析错误。
        """
        if not api_key:
            raise ValueError("API Key 不能为空")

        logger.info(f"尝试使用 Key {api_key[:8]}... 获取模型列表")
        api_version = "v1beta" # 通常使用 v1beta 获取模型列表
        url = f"https://generativelanguage.googleapis.com/{api_version}/models?key={api_key}"
        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=60.0) # 增加超时
                response.raise_for_status() # 检查 HTTP 错误
                data = response.json()

                model_names = []
                if "models" in data and isinstance(data["models"], list):
                    for model_info in data["models"]:
                        if isinstance(model_info, dict) and "name" in model_info:
                            # 移除 "models/" 前缀
                            model_name = model_info["name"]
                            if model_name.startswith("models/"):
                                model_name = model_name[len("models/"):]
                            model_names.append(model_name)
                logger.info(f"成功获取到 {len(model_names)} 个模型 (Key: {api_key[:8]}...)")
                return model_names
        except httpx.HTTPStatusError as e:
             logger.error(f"获取模型列表失败 (HTTPStatusError): {e.response.status_code} - {e.response.text}", exc_info=False)
             raise # 重新抛出
        except httpx.RequestError as e:
             logger.error(f"获取模型列表网络错误 (RequestError): {e}", exc_info=True)
             raise # 重新抛出
        except (json.JSONDecodeError, KeyError, TypeError) as e:
             logger.error(f"解析模型列表响应失败: {e}", exc_info=True)
             raise Exception(f"解析模型列表响应失败: {e}") from e # 包装为通用异常
        except Exception as e:
             logger.error(f"获取模型列表时发生未知错误: {e}", exc_info=True)
             raise # 重新抛出未知错误