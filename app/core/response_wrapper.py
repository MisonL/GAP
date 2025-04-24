# -*- coding: utf-8 -*-
"""
封装 Gemini API 响应，提供便捷的属性访问方法。
Wraps Gemini API responses, providing convenient methods for accessing attributes.
"""
import json # 导入 json 模块 (Import json module)
import logging # 导入 logging 模块 (Import logging module)
from dataclasses import dataclass # 导入 dataclass 装饰器 (Import dataclass decorator)
from typing import Optional, Dict, Any, List # 导入类型提示 (Import type hints)

# 获取名为 'my_logger' 的日志记录器实例
# Get the logger instance named 'my_logger'
# 注意：如果此模块在没有配置日志记录器的情况下被导入，可能会引发问题。
# Note: If this module is imported without a configured logger, it might cause issues.
# 更好的做法是从调用模块传递日志记录器实例，或使用标准的日志记录配置。
# A better approach would be to pass the logger instance from the calling module, or use standard logging configuration.
# 为简单起见，暂时保留此方式，但需注意潜在的初始化问题。
# For simplicity, this approach is kept for now, but be aware of potential initialization issues.
logger = logging.getLogger('my_logger')

@dataclass
class GeneratedText:
    """
    简单的文本生成结果数据类。
    Simple data class for text generation results.
    """
    text: str  # 生成的文本内容 (Generated text content)
    finish_reason: Optional[str] = None  # 完成原因 (例如 "STOP", "MAX_TOKENS", "SAFETY" 等) (Finish reason (e.g., "STOP", "MAX_TOKENS", "SAFETY", etc.))

class ResponseWrapper:
    """
    封装 Gemini API 响应，提供便捷的属性访问方法，主要用于处理非流式（non-streaming）响应。
    Wraps Gemini API responses, providing convenient methods for accessing attributes, mainly for handling non-streaming responses.
    """
    def __init__(self, data: Dict[Any, Any]):
        """
        初始化 ResponseWrapper。
        Initializes the ResponseWrapper.

        Args:
            data: 从 Gemini API 返回的原始 JSON 数据（已解析为 Python 字典）。Raw JSON data returned from the Gemini API (parsed into a Python dictionary).
        """
        self._data = data  # 存储原始响应字典 (Stores the raw response dictionary)
        # 提取关键信息并存储为内部属性
        # Extract key information and store as internal attributes
        self._text = self._extract_text() # 提取文本内容 (Extract text content)
        self._finish_reason = self._extract_finish_reason() # 提取完成原因 (Extract finish reason)
        self._prompt_token_count = self._extract_prompt_token_count() # 提取提示 token 数量 (Extract prompt token count)
        self._candidates_token_count = self._extract_candidates_token_count() # 提取候选 token 数量 (Extract candidates token count)
        self._total_token_count = self._extract_total_token_count() # 提取总 token 数量 (Extract total token count)
        self._thoughts = self._extract_thoughts()  # 提取可能的模型思考过程文本 (Extract possible model thought process text)
        self._tool_calls = self._extract_tool_calls() # 提取可能的工具调用信息 (Extract possible tool call information)
        # 将原始数据格式化为 JSON 字符串，方便调试时查看完整响应
        # Format the raw data into a JSON string for easy viewing of the complete response during debugging
        # 使用 try-except 块处理可能的序列化错误
        # Use a try-except block to handle potential serialization errors
        try:
            self._json_dumps = json.dumps(self._data, indent=4, ensure_ascii=False) # 格式化为 JSON 字符串 (Format as JSON string)
        except TypeError as e:
            logger.error(f"序列化响应数据时出错: {e}", exc_info=True) # 记录序列化错误 (Log serialization error)
            self._json_dumps = "{ \"error\": \"Failed to serialize response data\" }" # 设置错误消息 (Set error message)


    def _extract_thoughts(self) -> Optional[str]:
        """
        从响应数据中提取模型的思考过程文本（如果存在）。
        注意：此功能通常用于特定的模型或配置，并非所有响应都包含思考过程。
        Extracts the model's thought process text from the response data (if present).
        Note: This feature is typically used for specific models or configurations, and not all responses include thought processes.
        """
        try:
            # 遍历第一个候选响应的内容部分（parts）
            # Iterate through the content parts of the first candidate response
            for part in self._data['candidates'][0]['content']['parts']:
                # 如果某个部分包含 'thought' 键，则认为它是思考过程文本
                # If a part contains the 'thought' key, it is considered thought process text
                if 'thought' in part:
                    return part.get('text', '') # 使用 get 获取文本，增加健壮性 (Use get to get text, increasing robustness)
            return ""  # 如果遍历完所有部分都没有找到 'thought'，返回空字符串 (Return an empty string if 'thought' is not found after iterating through all parts)
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期（缺少键、索引越界、类型错误）的情况
            # Handle cases where the data structure is unexpected (missing keys, index out of bounds, type errors)
            return "" # 返回空字符串 (Return an empty string)

    def _extract_text(self) -> str:
        """
        从响应数据中提取主要的生成文本内容。
        此方法会合并所有不包含 'thought' 或 'functionCall' 的部分的文本。
        Extracts the main generated text content from the response data.
        This method merges the text from all parts that do not contain 'thought' or 'functionCall'.
        """
        text_parts = [] # 初始化文本部分列表 (Initialize list of text parts)
        try:
            # 遍历第一个候选响应的内容部分（parts）
            # Iterate through the content parts of the first candidate response
            for part in self._data['candidates'][0]['content']['parts']:
                # 仅当部分既不包含 'thought' 也不包含 'functionCall' 时，才提取其文本
                # Only extract text from parts that contain neither 'thought' nor 'functionCall'
                if 'thought' not in part and 'functionCall' not in part:
                    text_parts.append(part.get('text', '')) # 使用 get 获取文本，增加健壮性 (Use get to get text, increasing robustness)
            return "".join(text_parts) # 将所有提取的文本部分连接成一个字符串 (Join all extracted text parts into a single string)
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期的情况
            # Handle cases where the data structure is unexpected
            return "" # 返回空字符串 (Return an empty string)

    def _extract_finish_reason(self) -> Optional[str]:
        """
        从响应数据中提取生成完成的原因。
        Extracts the reason for generation completion from the response data.
        """
        try:
            # 尝试获取第一个候选响应的 'finishReason' 字段
            # Attempt to get the 'finishReason' field from the first candidate response
            return self._data['candidates'][0].get('finishReason')
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期的情况
            # Handle cases where the data structure is unexpected
            return None # 返回 None (Return None)

    def _extract_prompt_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取输入提示（prompt）的 token 数量。
        Extracts the token count of the input prompt from the response metadata (usageMetadata).
        """
        try:
            # 尝试获取 'usageMetadata' 中的 'promptTokenCount'
            # Attempt to get 'promptTokenCount' from 'usageMetadata'
            return self._data['usageMetadata'].get('promptTokenCount')
        except (KeyError, AttributeError): # 添加 AttributeError 处理 _data['usageMetadata'] 不是字典的情况 (Added AttributeError to handle cases where _data['usageMetadata'] is not a dictionary)
            # 处理缺少 'usageMetadata' 或其类型不正确的情况
            # Handle cases where 'usageMetadata' is missing or its type is incorrect
            return None # 返回 None (Return None)

    def _extract_candidates_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取生成内容（candidates）的 token 数量。
        Extracts the token count of the generated content (candidates) from the response metadata (usageMetadata).
        """
        try:
            # 尝试获取 'usageMetadata' 中的 'candidatesTokenCount'
            # Attempt to get 'candidatesTokenCount' from 'usageMetadata'
            return self._data['usageMetadata'].get('candidatesTokenCount')
        except (KeyError, AttributeError):
            # 处理缺少 'usageMetadata' 或其类型不正确的情况
            # Handle cases where 'usageMetadata' is missing or its type is incorrect
            return None # 返回 None (Return None)

    def _extract_total_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取总的 token 数量。
        Extracts the total token count from the response metadata (usageMetadata).
        """
        try:
            # 尝试获取 'usageMetadata' 中的 'totalTokenCount'
            # Attempt to get 'totalTokenCount' from 'usageMetadata'
            return self._data['usageMetadata'].get('totalTokenCount')
        except (KeyError, AttributeError):
            # 处理缺少 'usageMetadata' 或其类型不正确的情况
            # Handle cases where 'usageMetadata' is missing or its type is incorrect
            return None # 返回 None (Return None)

    def _extract_tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """
        从响应数据中提取函数调用（在 Gemini 中称为工具调用），如果存在的话。
        Gemini API 将工具调用信息放在包含 'functionCall' 键的 'parts' 元素中。
        Extracts function calls (referred to as tool calls in Gemini) from the response data, if present.
        The Gemini API places tool call information in 'parts' elements containing the 'functionCall' key.
        """
        tool_calls_list = [] # 初始化工具调用列表 (Initialize list of tool calls)
        try:
            # 遍历第一个候选响应的内容部分（parts）
            # Iterate through the content parts of the first candidate response
            for part in self._data['candidates'][0]['content']['parts']:
                # 如果某个部分包含 'functionCall' 键
                # If a part contains the 'functionCall' key
                if 'functionCall' in part:
                    # 将 'functionCall' 字典添加到列表中
                    # Append the 'functionCall' dictionary to the list
                    tool_calls_list.append(part['functionCall'])
            # 如果列表非空（即找到了工具调用），则返回列表，否则返回 None
            # If the list is not empty (i.e., tool calls were found), return the list, otherwise return None
            return tool_calls_list if tool_calls_list else None
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期的情况
            # Handle cases where the data structure is unexpected
            return None # 返回 None (Return None)

    # 使用 @property 装饰器将内部提取方法的结果暴露为只读属性，方便外部调用者访问
    # Use the @property decorator to expose the results of internal extraction methods as read-only attributes for convenient external access
    @property
    def text(self) -> str:
        """返回提取的主要生成文本内容。Returns the extracted main generated text content."""
        return self._text

    @property
    def finish_reason(self) -> Optional[str]:
        """返回生成完成的原因。Returns the reason for generation completion."""
        return self._finish_reason

    @property
    def prompt_token_count(self) -> Optional[int]:
        """返回输入提示（prompt）的 token 数量。Returns the token count of the input prompt."""
        return self._prompt_token_count

    @property
    def candidates_token_count(self) -> Optional[int]:
        """返回生成内容（candidates）的 token 数量。Returns the token count of the generated content (candidates)."""
        return self._candidates_token_count

    @property
    def total_token_count(self) -> Optional[int]:
        """返回本次 API 调用消耗的总 token 数量。Returns the total token count consumed by this API call."""
        return self._total_token_count

    @property
    def thoughts(self) -> Optional[str]:
        """返回提取的模型思考过程文本（如果存在）。Returns the extracted model thought process text (if present)."""
        return self._thoughts

    @property
    def tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """返回提取的工具调用信息列表，如果不存在则为 None。Returns the list of extracted tool call information, or None if none exist."""
        return self._tool_calls

    @property
    def json_dumps(self) -> str:
        """返回格式化后的原始响应 JSON 字符串，用于调试。Returns the formatted raw response JSON string, for debugging."""
        return self._json_dumps

    @property
    def usage_metadata(self) -> Optional[Dict[str, Any]]:
        """直接返回原始的 usageMetadata 字典，如果存在的话。Directly returns the raw usageMetadata dictionary, if it exists."""
        try:
            return self._data.get('usageMetadata')
        except AttributeError:
            return None
