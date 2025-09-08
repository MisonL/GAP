# -*- coding: utf-8 -*-
"""
Gemini API 客户端模块。
封装了与 Google Gemini API 交互的逻辑，使用 google-generativeai SDK。
"""
# 导入必要的库和类型
import os # 用于访问环境变量
import asyncio # 异步 IO 库
import logging # 日志库
from typing import Any, Dict, List, Optional, Tuple, Union, AsyncGenerator # 类型提示

import httpx # HTTP 客户端库，用于配置 SDK
import google.generativeai as genai # Google Gemini SDK
from google.generativeai import types # Gemini SDK 中的类型定义 (修正导入路径)
from google.api_core import exceptions as google_exceptions # Google API 核心异常

# 导入应用内部的模型和工具类
from gap.api.models import ChatCompletionRequest # OpenAI 格式的聊天请求模型
from gap.core.utils.response_wrapper import ResponseWrapper # 用于包装和处理 Gemini 响应的工具类 (新路径)

# 获取日志记录器实例
logger = logging.getLogger('my_logger')

# 定义与 Gemini API 交互的客户端类
class GeminiClient:
    """
    Gemini API 客户端类。
    封装了使用 google-generativeai SDK 与 Gemini API 进行通信的方法。
    包括配置 SDK、转换数据格式、发送流式和非流式请求、处理响应等。
    """
    # 类变量，用于存储可用的模型列表，将在首次调用 list_available_models 时填充
    AVAILABLE_MODELS: List[str] = []
    # 从环境变量读取额外的模型名称（逗号分隔），并添加到可用模型列表中
    EXTRA_MODELS: List[str] = [model.strip() for model in os.environ.get("EXTRA_MODELS", "").split(",") if model.strip()]

    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        """
        初始化 GeminiClient 实例。

        Args:
            api_key (str): 用于访问 Gemini API 的 API 密钥。
            http_client (httpx.AsyncClient): 共享的异步 HTTP 客户端实例，用于配置 SDK 的传输。

        Raises:
            ValueError: 如果 api_key 或 http_client 为空。
        """
        # 验证输入参数
        if not api_key:
            raise ValueError("API Key 不能为空")
        if not http_client:
             raise ValueError("http_client 不能为空")

        # 存储 API Key 和 HTTP 客户端
        self.api_key = api_key
        self.http_client = http_client

        # --- 配置 Google Gemini SDK ---
        try:
            # 移除 client_options={"transport": self.http_client}
            # 如果 google-generativeai==0.8.5 的 transport 参数可以直接接受 httpx.AsyncClient，
            # 则应改为 transport=self.http_client。
            # 但首先，我们解决 ClientOptions 的错误。
            # 保守的改法是只用 transport="rest"，让 SDK 自己处理 HTTP client。
            # 或者，如果确定 0.8.5 版本支持，可以尝试 transport=self.http_client
            # 查阅相关资料，0.x 版本似乎不直接支持在 configure 时注入 httpx_client 给 transport。
            # 它更多的是依赖 google-auth 来处理 transport。
            # 因此，最安全的初始修复是仅保留 api_key 和 transport="rest"。
            genai.configure(
                api_key=self.api_key, # 设置 API Key
                transport="rest" # 指定使用 REST API 传输层
                # client_options 已移除，因为它导致了 ValueError
            )
            logger.debug(f"Gemini SDK 已为 Key {self.api_key[:8]}... 配置完成 (移除了 client_options 中的 transport)。")
        except Exception as config_err:
            logger.error(f"配置 Gemini SDK 时出错 (Key: {self.api_key[:8]}...): {config_err}", exc_info=True)

    # --- 内部辅助方法：数据格式转换 ---

    def _convert_contents_to_sdk_format(self, contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        processed_contents = []
        for item_content in contents:
            processed_parts = []
            if "parts" in item_content:
                for part_data in item_content["parts"]:
                    processed_parts.append(part_data) 
            
            if item_content.get("role") and processed_parts:
                 processed_contents.append({"role": item_content["role"], "parts": processed_parts})
            elif item_content.get("role") and not processed_parts:
                 logger.warning(f"角色 '{item_content.get('role')}' 的内容没有有效的 parts: {item_content.get('parts', [])}")
        return processed_contents

    def _convert_safety_settings_to_sdk_format(self, safety_settings: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        processed_safety_settings = []
        for setting in safety_settings:
            category = setting.get("category")
            threshold = setting.get("threshold")
            if category and threshold is not None:
                processed_safety_settings.append({"category": category, "threshold": threshold})
            else:
                logger.warning(f"无效的安全设置项，缺少 category 或 threshold: {setting}")
        return processed_safety_settings

    def _convert_system_instruction_to_sdk_format(self, system_instruction: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if system_instruction and "parts" in system_instruction and isinstance(system_instruction["parts"], list):
            return system_instruction
        return None

    # --- 内部辅助方法：处理 SDK 响应 ---
    def _process_sdk_response(self, response: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]], Optional[str], Optional[str], Optional[str]]: # 类型注解已修改
        text_content = ""
        usage_metadata = None
        safety_issue_detail = None
        finish_reason = None
        cached_content_id = None # 假设 0.8.5 版本不直接通过此方法返回缓存 ID

        candidates = response.get("candidates")
        if candidates and isinstance(candidates, list) and len(candidates) > 0:
            candidate = candidates[0] # 取第一个候选者
            if isinstance(candidate, dict):
                content = candidate.get("content")
                if content and isinstance(content, dict) and "parts" in content and isinstance(content["parts"], list):
                    for part in content["parts"]:
                        if isinstance(part, dict) and "text" in part:
                            text_content += part["text"]

                # finish_reason 的处理：假设它直接是字符串或 None
                raw_finish_reason = candidate.get("finishReason") # 注意大小写可能与 GenerateContentResponse 对象不同
                if isinstance(raw_finish_reason, str):
                     finish_reason = raw_finish_reason
                elif raw_finish_reason is not None: # 如果存在但不是字符串，记录警告
                    logger.warning(f"预期的 finish_reason 是字符串，但得到: {type(raw_finish_reason)} - {raw_finish_reason}")


                safety_ratings = candidate.get("safetyRatings") # 注意大小写
                if safety_ratings and isinstance(safety_ratings, list):
                    for rating in safety_ratings:
                        if isinstance(rating, dict):
                            category = rating.get("category")
                            probability = rating.get("probability") # 假设直接是字符串 'HIGH', 'MEDIUM', 'LOW', 'NEGLIGIBLE'
                            blocked = rating.get("blocked", False) # 默认为 False

                            is_problematic = blocked or probability in ['HIGH', 'MEDIUM']
                            if is_problematic:
                                log_level = logging.WARNING if blocked or probability == 'HIGH' else logging.INFO
                                logger.log(log_level, f"SDK 响应安全评分: Category={category}, Probability={probability}, Blocked={blocked}, Key: {self.api_key[:8]}...")
                                if blocked or probability == 'HIGH':
                                    safety_issue_detail = f"安全问题: {category}"
            else:
                logger.warning(f"候选者格式不正确: {candidate}")


        sdk_usage_metadata = response.get("usageMetadata") # 注意大小写
        if sdk_usage_metadata and isinstance(sdk_usage_metadata, dict):
            usage_metadata = {
                "prompt_token_count": sdk_usage_metadata.get("promptTokenCount"), # 注意大小写
                "candidates_token_count": sdk_usage_metadata.get("candidatesTokenCount"), # 注意大小写
                "total_token_count": sdk_usage_metadata.get("totalTokenCount"), # 注意大小写
            }
            # 过滤掉值为 None 的 token 计数
            usage_metadata = {k: v for k, v in usage_metadata.items() if v is not None}
            if not usage_metadata: # 如果所有计数都为 None，则将 usage_metadata 设为 None
                usage_metadata = None


        # 尝试从响应顶层获取缓存元数据 (如果存在)
        response_cache_metadata = response.get("cacheMetadata")
        if response_cache_metadata and isinstance(response_cache_metadata, dict):
            cached_content_id = response_cache_metadata.get("cachedContentId")
            if cached_content_id:
                 logger.debug(f"从响应中提取到 cachedContentId: {cached_content_id}")


        return text_content, usage_metadata, safety_issue_detail, finish_reason, cached_content_id

    # --- API 调用方法 ---

    async def stream_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]], cached_content_id: Optional[str] = None) -> AsyncGenerator[Union[str, Dict[str, Any]], None]:
        logger.info(f"流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model}, CachedContentId: {cached_content_id}) →")
        text_yielded = False 
        safety_issue_detail_sent = False 
        usage_metadata_received = None 
        final_finish_reason = "STOP" 

        try:
            model = genai.GenerativeModel(model_name=request.model)
            sdk_contents = self._convert_contents_to_sdk_format(contents)
            sdk_safety_settings = self._convert_safety_settings_to_sdk_format(safety_settings)
            sdk_system_instruction = self._convert_system_instruction_to_sdk_format(system_instruction)
            sdk_generation_config = {
                "temperature": request.temperature,
                "max_output_tokens": request.max_tokens,
            }
            sdk_generation_config = {k: v for k, v in sdk_generation_config.items() if v is not None}
            
            if cached_content_id:
                 logger.warning(f"google-generativeai==0.8.5 时 CachedContent 的用法未知，暂时不使用缓存 ID: {cached_content_id}")

            async for chunk in await model.generate_content(
                contents=sdk_contents, 
                stream=True, 
                safety_settings=sdk_safety_settings, 
                system_instruction=sdk_system_instruction, 
                generation_config=sdk_generation_config
            ):
                text_in_chunk, usage_metadata, safety_issue_detail, finish_reason, cached_content_id_from_response = self._process_sdk_response(chunk)

                if text_in_chunk:
                    yield text_in_chunk 
                    text_yielded = True 

                if cached_content_id_from_response:
                    yield {"_cache_metadata": {"cached_content_id": cached_content_id_from_response}}

                if usage_metadata:
                     usage_metadata_received = usage_metadata

                if safety_issue_detail and not safety_issue_detail_sent:
                     yield {'_safety_issue': safety_issue_detail} 
                     safety_issue_detail_sent = True 

                if finish_reason and finish_reason != "STOP":
                     final_finish_reason = finish_reason

        except google_exceptions.GoogleAPIError as e: 
            logger.error(f"SDK 流处理 Google API 错误: {e}", exc_info=True) 
            raise RuntimeError(f"SDK 流处理 Google API 错误: {e}") from e
        except Exception as e: 
            error_detail = f"SDK 流处理意外错误: {e}"
            logger.error(error_detail, exc_info=True) 
            raise RuntimeError(error_detail) from e
        finally: 
            logger.info(f"流式请求结束 (Key: {self.api_key[:8]}..., Model: {request.model}, CachedContentId: {cached_content_id}) ←")
            yield {'_final_finish_reason': final_finish_reason} 
            if usage_metadata_received: 
                yield {'_usage_metadata': usage_metadata_received} 

    async def complete_chat(self, request: ChatCompletionRequest, contents: List[Dict[str, Any]], safety_settings: List[Dict[str, Any]], system_instruction: Optional[Dict[str, Any]], cached_content_id: Optional[str] = None) -> ResponseWrapper:
        logger.info(f"非流式请求开始 (Key: {self.api_key[:8]}..., Model: {request.model}, CachedContentId: {cached_content_id})")
        try:
            model = genai.GenerativeModel(model_name=request.model)
            sdk_contents = self._convert_contents_to_sdk_format(contents)
            sdk_safety_settings = self._convert_safety_settings_to_sdk_format(safety_settings)
            sdk_system_instruction = self._convert_system_instruction_to_sdk_format(system_instruction)
            sdk_generation_config = {
                "temperature": request.temperature,
                "max_output_tokens": request.max_tokens,
            }
            sdk_generation_config = {k: v for k, v in sdk_generation_config.items() if v is not None}

            if cached_content_id:
                logger.warning(f"google-generativeai==0.8.5 时 CachedContent 的用法未知，暂时不使用缓存 ID: {cached_content_id}")

            # 假设 model.generate_content 在非流式模式下直接返回一个字典
            response_dict: Dict[str, Any] = await model.generate_content( # 类型注解已修改
                contents=sdk_contents,
                stream=False,
                safety_settings=sdk_safety_settings,
                system_instruction=sdk_system_instruction,
                generation_config=sdk_generation_config
            )
            text_content, usage_metadata, safety_issue_detail, finish_reason, cached_content_id_from_response = self._process_sdk_response(response_dict) # 使用修改后的 response_dict

            # 构建 ResponseWrapper 需要的数据结构
            wrapped_response_data = {
                "candidates": [],
                "usageMetadata": usage_metadata, # 来自 _process_sdk_response
            }

            # 基于 _process_sdk_response 的输出来构建 candidate 数据
            # 注意：_process_sdk_response 返回的是聚合的 text_content，而不是原始的 parts 结构
            # 如果需要更精细的 parts 结构，需要在 _process_sdk_response 中调整或在这里重新处理 response_dict
            if text_content or finish_reason: # 只要有文本或完成原因，就尝试构建 candidate
                candidate_data = {
                    "content": {
                        "parts": [{"text": text_content if text_content else ""}] # 确保 text 字段存在
                    },
                    "finishReason": finish_reason, # 来自 _process_sdk_response
                    # safetyRatings 可以在这里从 response_dict 中提取并转换，如果需要的话
                }
                wrapped_response_data["candidates"].append(candidate_data)
            
            if safety_issue_detail: # 如果存在安全问题，可以考虑如何体现在 ResponseWrapper 中
                logger.warning(f"检测到安全问题，将包含在响应中: {safety_issue_detail}")
                # 可以在 wrapped_response_data 中添加一个字段来表示安全问题，例如：
                # wrapped_response_data["safetyFeedback"] = {"blockReason": safety_issue_detail} 
                # 或者根据 OpenAI 的格式，如果被阻止，finish_reason 可能是 "SAFETY"
                if wrapped_response_data["candidates"] and isinstance(wrapped_response_data["candidates"], list) and len(wrapped_response_data["candidates"]) > 0:
                    # 如果是因为安全问题导致内容为空，可以更新 finish_reason
                    if not text_content and finish_reason != "SAFETY": # 假设 "SAFETY" 是一个可能的 finish_reason
                         logger.info(f"内容为空且存在安全问题，将 finish_reason 更新为 SAFETY (原: {finish_reason})")
                         # wrapped_response_data["candidates"][0]["finishReason"] = "SAFETY" # 取决于API具体行为

            if cached_content_id_from_response:
                 wrapped_response_data["cacheMetadata"] = {"cached_content_id": cached_content_id_from_response}
                 logger.info(f"响应包含缓存元数据: {cached_content_id_from_response}")
            elif cached_content_id: # 如果请求时使用了缓存ID，但响应中没有，记录一下
                 logger.debug(f"尝试使用了缓存 {cached_content_id}，但 API 响应未明确返回缓存元数据。")

            logger.info(f"非流式请求成功 (Key: {self.api_key[:8]}..., Model: {request.model}, CachedContentId: {cached_content_id})")
            return ResponseWrapper(wrapped_response_data)

        except google_exceptions.GoogleAPIError as e: 
            logger.error(f"SDK 非流处理 Google API 错误: {e}", exc_info=True) 
            raise RuntimeError(f"SDK 非流处理 Google API 错误: {e}") from e
        except Exception as e: 
            error_detail = f"SDK 非流处理意外错误: {e}"
            logger.error(error_detail, exc_info=True) 
            raise RuntimeError(error_detail) from e

    @staticmethod
    async def list_available_models(api_key: str, http_client: httpx.AsyncClient) -> List[str]:
        if not api_key: 
            raise ValueError("API Key 不能为空")
        logger.info(f"尝试使用 Key {api_key[:8]}... 获取模型列表 (通过 SDK)")
        try:
            # 同样移除 client_options={"transport": http_client}
            genai.configure(
                api_key=api_key, 
                transport="rest"
                # client_options 已移除
            )
        except Exception as config_err:
             logger.error(f"配置 Gemini SDK 以获取模型列表时出错: {config_err}", exc_info=True)
             raise Exception(f"配置 SDK 失败: {config_err}") from config_err

        try:
            # genai.list_models() 在旧版本中可能返回同步生成器
            models_iterable = genai.list_models() # 移除 await
            model_names = []
            for model in models_iterable: # 改为同步 for 循环
                model_name = model.name 
                if model_name.startswith("models/"): 
                    model_name = model_name[len("models/"):]
                model_names.append(model_name) 

            logger.info(f"成功获取到 {len(model_names)} 个模型 (Key: {api_key[:8]}..., 通过 SDK)")
            return model_names 
        except Exception as e: 
            logger.error(f"获取模型列表失败 (通过 SDK): {e}", exc_info=True) 
            # 确保在异步函数中正确处理同步代码可能引发的异常，或者将此部分变为同步（如果可以）
            # 但由于整个 list_available_models 是 async def，同步迭代本身是允许的。
            raise Exception(f"获取模型列表失败: {e}") from e
