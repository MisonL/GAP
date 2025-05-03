# app/core/gemini.py
# 导入必要的库
import json      # 用于处理 JSON 数据
import os        # 用于访问环境变量
import asyncio   # 用于异步操作
# 注意：调整导入路径以反映新的目录结构
from app.api.models import ChatCompletionRequest # 仅导入需要的模型
from typing import Optional, Dict, Any, List, AsyncGenerator, Union # 增加了 AsyncGenerator, Union
import httpx     # 用于发送异步 HTTP 请求
import logging   # 用于日志记录
from app.core.response_wrapper import ResponseWrapper # 新增导入
# convert_messages 不再由此类直接调用，由外部调用者处理

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger('my_logger')

# 定义与 Gemini API 交互的客户端类
class GeminiClient:
    AVAILABLE_MODELS = []  # 类变量，存储可用的模型列表
    # 从环境变量读取额外的模型名称，用逗号分隔
    EXTRA_MODELS = [model.strip() for model in os.environ.get("EXTRA_MODELS", "").split(",") if model.strip()] # 确保去除首尾空格并过滤空字符串

    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        if not api_key:
            raise ValueError("API Key 不能为空") # API Key 不能为空
        if not http_client:
             raise ValueError("http_client 不能为空") # http_client 不能为空
        self.api_key = api_key # 存储 API 密钥
        self.http_client = http_client # 存储共享的 HTTP 客户端

    async def stream_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]]) -> AsyncGenerator[Union[str, Dict[str, Any]], None]:
        logger.info(f"流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model}) →")
        text_yielded = False # 标记是否已产生文本
        safety_issue_detected = None # 存储检测到的安全问题
        usage_metadata = None # 存储使用情况元数据
        final_finish_reason = "STOP" # 存储最终完成原因，默认为 STOP
        # 根据模型名称选择 API 版本 (这个逻辑可能需要更新或移除，取决于 Google API 的演进)
        api_version = "v1beta" # 默认使用 v1beta API 版本
        # 统一使用 generateContent，流式通过 stream=true 参数控制 (如果 API 支持)
        # 查阅最新文档，似乎 streamGenerateContent 仍然是推荐的流式端点
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:streamGenerateContent?key={self.api_key}&alt=sse" # 构建 API 请求 URL

        headers = {"Content-Type": "application/json"} # 设置请求头
        data = { # 构建请求体数据
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                # topP, topK 等其他生成参数可以根据需要添加
            },
            "safetySettings": safety_settings,
        }
        if system_instruction:
            data["system_instruction"] = system_instruction # 如果有系统指令则添加到请求体

        try:
            # 设置请求超时：总超时 600 秒，读取超时 120 秒
            async with self.http_client.stream("POST", url, headers=headers, json=data, timeout=httpx.Timeout(600.0, read=120.0)) as response: # 发送流式 POST 请求
                # 检查初始 HTTP 响应状态码
                if response.status_code >= 400:
                         # 尝试读取错误响应体
                         error_body = await response.aread()
                         error_detail = f"API 请求失败，状态码: {response.status_code}, 响应: {error_body.decode('utf-8', errors='replace')}" # 格式化错误详情
                         logger.error(error_detail) # 记录错误
                         # 根据状态码抛出特定异常或通用异常
                         response.raise_for_status() # 这会根据状态码自动抛出 httpx.HTTPStatusError

                buffer = b"" # 初始化缓冲区
                async for line in response.aiter_lines(): # 异步迭代响应的行
                    if not line.strip(): continue # 跳过空行
                    if line.startswith("data: "): line = line[len("data: "):] # 移除 SSE 格式的 "data: " 前缀
                    buffer += line.encode('utf-8') # 将行添加到缓冲区
                    try:
                        data_chunk = json.loads(buffer.decode('utf-8')) # 尝试解析缓冲区中的 JSON
                        buffer = b"" # 清空缓冲区

                        if 'usageMetadata' in data_chunk:
                            usage_metadata = data_chunk['usageMetadata'] # 提取使用情况元数据
                            logger.debug(f"流接收到 usageMetadata: {usage_metadata}") # 流接收到 usageMetadata

                        if 'candidates' in data_chunk and data_chunk['candidates']:
                            candidate = data_chunk['candidates'][0] # 获取第一个候选
                            current_finish_reason = candidate.get("finishReason") # 获取当前完成原因

                            # 提取文本部分
                            text_in_chunk = "" # 初始化块中的文本
                            if 'content' in candidate and 'parts' in candidate['content']:
                                for part in candidate['content']['parts']:
                                    if 'text' in part:
                                        text_in_chunk += part['text'] # 累加文本

                            if text_in_chunk:
                                yield text_in_chunk # Yield 文本块
                                text_yielded = True # 标记已产生文本

                            # 处理完成原因和安全问题
                            if current_finish_reason and current_finish_reason != "STOP":
                                logger.warning(f"流式响应被标记: {current_finish_reason}, Model: {request.model}, Key: {self.api_key[:8]}...") # 流式响应被标记
                                safety_issue_detected = f"完成原因: {current_finish_reason}" # 记录安全问题详情
                                final_finish_reason = current_finish_reason # 更新最终原因

                            if 'safetyRatings' in candidate:
                                for rating in candidate['safetyRatings']:
                                    if rating.get('blocked') or rating.get('probability') in ['HIGH', 'MEDIUM']: # 也考虑 MEDIUM 概率
                                        log_level = logging.WARNING if rating.get('blocked') or rating.get('probability') == 'HIGH' else logging.INFO # 根据严重程度设置日志级别
                                        logger.log(log_level, f"流式响应安全评分: Category={rating['category']}, Probability={rating.get('probability', 'N/A')}, Blocked={rating.get('blocked', 'N/A')}, Model: {request.model}, Key: {self.api_key[:8]}...") # 流式响应安全评分
                                        if rating.get('blocked') or rating.get('probability') == 'HIGH':
                                            safety_issue_detected = f"安全问题: {rating['category']}" # 记录安全问题详情
                                            if final_finish_reason == "STOP": final_finish_reason = "SAFETY" # 如果最终原因是 STOP，则更新为 SAFETY

                                            # 新增：如果检测到安全问题且尚未产生文本，yield 安全详情块
                                            if not text_yielded:
                                                yield {'_safety_issue': safety_issue_detected}
                                                # 标记已发送安全提示，避免重复发送
                                                safety_issue_detected = None # 清空，表示已处理

                    except json.JSONDecodeError:
                        logger.debug(f"JSON 解析错误, 当前缓冲区: {buffer}") # JSON 解析错误
                        continue # 继续处理下一行
                    except Exception as inner_e: # 捕获处理流数据块时内部的异常
                        logger.error(f"处理流数据块时出错: {inner_e}", exc_info=True) # 处理流数据块时出错
                        raise # 重新抛出异常，让外部调用者知道发生了错误

        except httpx.HTTPStatusError as e:
            logger.error(f"流式 API 请求失败 (HTTPStatusError): {e.response.status_code} - {e.response.text}", exc_info=False) # 流式 API 请求失败 (HTTPStatusError)
            raise # 重新抛出，由调用者处理
        except httpx.RequestError as e:
            logger.error(f"流式 API 请求网络错误 (RequestError): {e}", exc_info=True) # 流式 API 请求网络错误 (RequestError)
            raise # 重新抛出网络请求错误
        except Exception as e:
            # 捕获流处理过程中的其他异常
            error_detail = f"流处理意外错误: {e}" # 格式化错误详情
            logger.error(error_detail, exc_info=True) # 记录错误
            # 可以抛出自定义异常或重新抛出原始异常
            raise RuntimeError(error_detail) from e # 使用 RuntimeError 包装原始异常
        finally:
            logger.info(f"流式请求结束 (Key: {self.api_key[:8]}..., Model: {request.model}) ←") # 流式请求结束
            # 如果流结束但从未产生文本且检测到安全问题，记录错误但不在此处抛出异常，
            # 让调用者根据最终的 finish_reason 和 usage_metadata 来处理这种情况
            # 这里的 safety_issue_detected 在上面 yield 后可能已经被清空，但保留日志以防万一
            if not text_yielded and safety_issue_detected:
                logger.error(f"流结束但未产生文本，检测到安全问题 ({safety_issue_detected}), Key: {self.api_key[:8]}...") # 流结束但未产生文本，检测到安全问题

            yield {'_final_finish_reason': final_finish_reason}
            if usage_metadata:
                yield {'_usage_metadata': usage_metadata}


    async def complete_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]]) -> ResponseWrapper:
        logger.info(f"非流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model})")
        # 根据模型名称选择 API 版本
        api_version = "v1beta" # 默认使用 v1beta API 版本
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:generateContent?key={self.api_key}" # 构建 API 请求 URL
        headers = {"Content-Type": "application/json"} # 设置请求头
        data = { # 构建请求体数据
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
            "safetySettings": safety_settings,
        }
        if system_instruction:
            data["system_instruction"] = system_instruction # 如果有系统指令则添加到请求体

        # 使用共享的 HTTP 客户端实例
        # 设置请求超时：总超时 600 秒，读取超时 120 秒
        response = await self.http_client.post(url, headers=headers, json=data, timeout=httpx.Timeout(600.0, read=120.0)) # 发送 POST 请求
        if response.status_code >= 400:
             error_detail = f"API 请求失败，状态码: {response.status_code}, 响应: {response.text}" # 格式化错误详情
             logger.error(error_detail) # 记录错误
        response.raise_for_status() # 检查 HTTP 错误并抛出异常
        # 将响应的 JSON 数据包装在 ResponseWrapper 对象中并返回
        logger.info(f"非流式请求成功 (Key: {self.api_key[:8]}..., Model: {request.model})") # 非流式请求成功
        return ResponseWrapper(response.json()) # 返回 ResponseWrapper 实例

    @staticmethod
    async def list_available_models(api_key: str, http_client: httpx.AsyncClient) -> List[str]:
        if not api_key:
            raise ValueError("API Key 不能为空") # API Key 不能为空

        logger.info(f"尝试使用 Key {api_key[:8]}... 获取模型列表") # 尝试使用 Key 获取模型列表
        api_version = "v1beta" # 通常使用 v1beta API 版本获取模型列表
        url = f"https://generativelanguage.googleapis.com/{api_version}/models?key={api_key}" # 构建 API 请求 URL
        headers = {"Content-Type": "application/json"} # 设置请求头

        try:
            # 使用共享的 HTTP 客户端实例
            response = await http_client.get(url, headers=headers, timeout=60.0) # 发送 GET 请求，增加超时
            response.raise_for_status() # 检查 HTTP 错误
            data = response.json() # 解析 JSON 响应

            model_names = [] # 初始化模型名称列表
            if "models" in data and isinstance(data["models"], list):
                for model_info in data["models"]:
                    if isinstance(model_info, dict) and "name" in model_info:
                            # 移除 "models/" 前缀
                            model_name = model_info["name"]
                            if model_name.startswith("models/"):
                                model_name = model_name[len("models/"):]
                            model_names.append(model_name) # 添加模型名称到列表
            logger.info(f"成功获取到 {len(model_names)} 个模型 (Key: {api_key[:8]}...)") # 成功获取到模型
            return model_names # 返回模型名称列表
        except httpx.HTTPStatusError as e:
             logger.error(f"获取模型列表失败 (HTTPStatusError): {e.response.status_code} - {e.response.text}", exc_info=False) # 获取模型列表失败 (HTTPStatusError)
             raise # 重新抛出
        except httpx.RequestError as e:
             logger.error(f"获取模型列表网络错误 (RequestError): {e}", exc_info=True) # 获取模型列表网络错误 (RequestError)
             raise # 重新抛出
        except (json.JSONDecodeError, KeyError, TypeError) as e:
             logger.error(f"解析模型列表响应失败: {e}", exc_info=True) # 解析模型列表响应失败
             raise Exception(f"解析模型列表响应失败: {e}") from e # 包装为通用异常
        except Exception as e:
             logger.error(f"获取模型列表时发生未知错误: {e}", exc_info=True) # 获取模型列表时发生未知错误
             raise # 重新抛出未知错误
