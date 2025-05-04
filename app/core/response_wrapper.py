# 导入类型提示
from typing import Any, Dict, List, Optional, Union
# -*- coding: utf-8 -*-
"""
封装 Gemini API 响应，提供便捷的属性访问方法。
"""
import json # 导入 json 模块
import logging # 导入 logging 模块 (Import logging module)
from dataclasses import dataclass # 导入 dataclass 装饰器 (Import dataclass decorator)
from typing import Optional, Dict, Any, List, Tuple, TypeVar, Callable # 导入类型提示 (Import type hints)

# 获取名为 'my_logger' 的日志记录器实例
# Get the logger instance named 'my_logger'
# 注意：如果此模块在没有配置日志记录器的情况下被导入，可能会引发问题。
# Note: If this module is imported without a configured logger, it might cause issues.
# 更好的做法是从调用模块传递日志记录器实例，或使用标准的日志记录配置。
# A better approach would be to pass the logger instance from the calling module, or use standard logging configuration.
# 为简单起见，暂时保留此方式，但需注意潜在的初始化问题。
# For simplicity, this approach is kept for now, but be aware of potential initialization issues.
logger = logging.getLogger('my_logger')

T = TypeVar('T') # 定义一个类型变量

@dataclass
class GeneratedText:
    """
    简单的文本生成结果数据类。
    """
    text: str  # 生成的文本内容
    finish_reason: Optional[str] = None  # 完成原因 (例如 "STOP", "MAX_TOKENS", "SAFETY" 等)

class ResponseWrapper:
    """
    封装 Gemini API 响应，提供便捷的属性访问方法，主要用于处理非流式（non-streaming）响应。
    """
    def __init__(self, data: Dict[Any, Any]):
        """
        初始化 ResponseWrapper。

        Args:
            data: 从 Gemini API 返回的原始 JSON 数据（已解析为 Python 字典）。
        """
        self._data = data
        # 提取关键信息并存储为内部属性
        self._text = self._extract_text()
        self._finish_reason = self._extract_finish_reason()
        self._prompt_token_count = self._extract_prompt_token_count()
        self._candidates_token_count = self._extract_candidates_token_count()
        self._total_token_count = self._extract_total_token_count()
        self._thoughts = self._extract_thoughts()
        self._tool_calls = self._extract_tool_calls()
        # 将原始数据格式化为 JSON 字符串，方便调试时查看完整响应
        # 使用 try-except 块处理可能的序列化错误
        try:
            self._json_dumps = json.dumps(self._data, indent=4, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"序列化响应数据时出错: {e}", exc_info=True)
            self._json_dumps = "{ \"error\": \"Failed to serialize response data\" }"

    def _safe_get(self, path: List[Union[str, int]], default: Optional[T] = None, expected_type: Optional[type] = None) -> Optional[T]:
        """
        安全地从嵌套字典/列表中获取值，处理 KeyError, IndexError, TypeError, AttributeError。

        Args:
            path: 访问嵌套结构的路径，例如 ['candidates', 0, 'content', 'parts', 0, 'text']。
            default: 获取失败时返回的默认值。
            expected_type: 期望返回值的类型，如果类型不匹配则返回默认值。

        Returns:
            获取到的值或默认值。
        """
        data = self._data
        try:
            for key in path:
                if isinstance(data, dict):
                    data = data.get(key)
                elif isinstance(data, list) and isinstance(key, int) and 0 <= key < len(data):
                    data = data[key]
                else:
                    return default # 路径无效或类型不匹配

            if expected_type is not None and not isinstance(data, expected_type):
                 return default # 类型不匹配

            return data # type: ignore # 返回获取到的值
        except (KeyError, IndexError, TypeError, AttributeError):
            return default # 捕获异常时返回默认值


    def _extract_thoughts(self) -> Optional[str]:
        """
        从响应数据中提取模型的思考过程文本（如果存在）。
        注意：此功能通常用于特定的模型或配置，并非所有响应都包含思考过程。
        """
        # 使用 _safe_get 简化提取逻辑
        # 路径: ['candidates', 0, 'content', 'parts'] -> 遍历 parts 查找包含 'thought' 的 part
        parts = self._safe_get(['candidates', 0, 'content', 'parts'], default=[], expected_type=list)
        for part in parts:
            if isinstance(part, dict) and 'thought' in part:
                return part.get('text', '') # 使用 get 获取文本，增加健壮性
        return "" # 如果遍历完所有部分都没有找到 'thought'，返回空字符串


    def _extract_text(self) -> str:
        """
        从响应数据中提取主要的生成文本内容。
        此方法会合并所有不包含 'thought' 或 'functionCall' 的部分的文本。
        """
        text_parts = []
        # 使用 _safe_get 简化提取逻辑
        # 路径: ['candidates', 0, 'content', 'parts'] -> 遍历 parts 查找文本
        parts = self._safe_get(['candidates', 0, 'content', 'parts'], default=[], expected_type=list)
        for part in parts:
            # 仅当部分既不包含 'thought' 也不包含 'functionCall' 时，才提取其文本
            if isinstance(part, dict) and 'thought' not in part and 'functionCall' not in part:
                text_parts.append(part.get('text', '')) # 使用 get 获取文本，增加健壮性
        return "".join(text_parts) # 将所有提取的文本部分连接成一个字符串


    def _extract_finish_reason(self) -> Optional[str]:
        """
        从响应数据中提取生成完成的原因。
        """
        # 使用 _safe_get 简化提取逻辑
        return self._safe_get(['candidates', 0, 'finishReason'], default=None, expected_type=str)


    def _extract_prompt_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取输入提示（prompt）的 token 数量。
        """
        # 使用 _safe_get 简化提取逻辑
        return self._safe_get(['usageMetadata', 'promptTokenCount'], default=None, expected_type=int)


    def _extract_candidates_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取生成内容（candidates）的 token 数量。
        """
        # 使用 _safe_get 简化提取逻辑
        return self._safe_get(['usageMetadata', 'candidatesTokenCount'], default=None, expected_type=int)


    def _extract_total_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取总的 token 数量。
        """
        # 使用 _safe_get 简化提取逻辑
        return self._safe_get(['usageMetadata', 'totalTokenCount'], default=None, expected_type=int)


    def _extract_tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """
        从响应数据中提取函数调用（在 Gemini 中称为工具调用），如果存在的话。
        Gemini API 将工具调用信息放在包含 'functionCall' 键的 'parts' 元素中。
        """
        tool_calls_list = []
        # 使用 _safe_get 简化提取逻辑
        # 路径: ['candidates', 0, 'content', 'parts'] -> 遍历 parts 查找包含 'functionCall' 的 part
        parts = self._safe_get(['candidates', 0, 'content', 'parts'], default=[], expected_type=list)
        for part in parts:
            # 如果某个部分包含 'functionCall' 键
            if isinstance(part, dict) and 'functionCall' in part:
                # 将 'functionCall' 字典添加到列表中
                tool_calls_list.append(part['functionCall'])
        # 如果列表非空（即找到了工具调用），则返回列表，否则返回 None
        return tool_calls_list if tool_calls_list else None


    # 使用 @property 装饰器将内部提取方法的结果暴露为只读属性，方便外部调用者访问
    @property
    def text(self) -> str:
        """返回提取的主要生成文本内容。"""
        return self._text

    @property
    def finish_reason(self) -> Optional[str]:
        """返回生成完成的原因。"""
        return self._finish_reason

    @property
    def prompt_token_count(self) -> Optional[int]:
        """返回输入提示（prompt）的 token 数量。"""
        return self._prompt_token_count

    @property
    def candidates_token_count(self) -> Optional[int]:
        """返回生成内容（candidates）的 token 数量。"""
        return self._candidates_token_count

    @property
    def total_token_count(self) -> Optional[int]:
        """返回本次 API 调用消耗的总 token 数量。"""
        return self._total_token_count

    @property
    def thoughts(self) -> Optional[str]:
        """返回提取的模型思考过程文本（如果存在）。"""
        return self._thoughts

    @property
    def tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """返回提取的工具调用信息列表，如果不存在则为 None。"""
        return self._tool_calls

    @property
    def json_dumps(self) -> str:
        """返回格式化后的原始响应 JSON 字符串，用于调试。"""
        return self._json_dumps

    @property
    def usage_metadata(self) -> Optional[Dict[str, Any]]:
        """直接返回原始的 usageMetadata 字典，如果存在的话。"""
        # 使用 _safe_get 简化提取逻辑
        return self._safe_get(['usageMetadata'], default=None, expected_type=dict)
