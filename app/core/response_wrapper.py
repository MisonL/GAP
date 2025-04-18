# -*- coding: utf-8 -*-
"""
封装 Gemini API 响应，提供便捷的属性访问方法。
"""
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

# 获取名为 'my_logger' 的日志记录器实例
# 注意：如果此模块在没有配置日志记录器的情况下被导入，可能会引发问题。
# 更好的做法是从调用模块传递日志记录器实例，或使用标准的日志记录配置。
# 为简单起见，暂时保留此方式，但需注意潜在的初始化问题。
logger = logging.getLogger('my_logger')

@dataclass
class GeneratedText:
    """简单的文本生成结果数据类"""
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
        self._data = data  # 存储原始响应字典
        # 提取关键信息并存储为内部属性
        self._text = self._extract_text()
        self._finish_reason = self._extract_finish_reason()
        self._prompt_token_count = self._extract_prompt_token_count()
        self._candidates_token_count = self._extract_candidates_token_count()
        self._total_token_count = self._extract_total_token_count()
        self._thoughts = self._extract_thoughts()  # 提取可能的模型思考过程文本
        self._tool_calls = self._extract_tool_calls() # 提取可能的工具调用信息
        # 将原始数据格式化为 JSON 字符串，方便调试时查看完整响应
        # 使用 try-except 块处理可能的序列化错误
        try:
            self._json_dumps = json.dumps(self._data, indent=4, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"序列化响应数据时出错: {e}", exc_info=True)
            self._json_dumps = "{ \"error\": \"Failed to serialize response data\" }"


    def _extract_thoughts(self) -> Optional[str]:
        """
        从响应数据中提取模型的思考过程文本（如果存在）。
        注意：此功能通常用于特定的模型或配置，并非所有响应都包含思考过程。
        """
        try:
            # 遍历第一个候选响应的内容部分（parts）
            for part in self._data['candidates'][0]['content']['parts']:
                # 如果某个部分包含 'thought' 键，则认为它是思考过程文本
                if 'thought' in part:
                    return part.get('text', '') # 使用 get 获取文本，增加健壮性
            return ""  # 如果遍历完所有部分都没有找到 'thought'，返回空字符串
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期（缺少键、索引越界、类型错误）的情况
            return ""

    def _extract_text(self) -> str:
        """
        从响应数据中提取主要的生成文本内容。
        此方法会合并所有不包含 'thought' 或 'functionCall' 的部分的文本。
        """
        text_parts = []
        try:
            # 遍历第一个候选响应的内容部分（parts）
            for part in self._data['candidates'][0]['content']['parts']:
                # 仅当部分既不包含 'thought' 也不包含 'functionCall' 时，才提取其文本
                if 'thought' not in part and 'functionCall' not in part:
                    text_parts.append(part.get('text', '')) # 使用 get 获取文本，增加健壮性
            return "".join(text_parts) # 将所有提取的文本部分连接成一个字符串
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期的情况
            return ""

    def _extract_finish_reason(self) -> Optional[str]:
        """
        从响应数据中提取生成完成的原因。
        """
        try:
            # 尝试获取第一个候选响应的 'finishReason' 字段
            return self._data['candidates'][0].get('finishReason')
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期的情况
            return None

    def _extract_prompt_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取输入提示（prompt）的 token 数量。
        """
        try:
            # 尝试获取 'usageMetadata' 中的 'promptTokenCount'
            return self._data['usageMetadata'].get('promptTokenCount')
        except (KeyError, AttributeError): # 添加 AttributeError 处理 _data['usageMetadata'] 不是字典的情况
            # 处理缺少 'usageMetadata' 或其类型不正确的情况
            return None

    def _extract_candidates_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取生成内容（candidates）的 token 数量。
        """
        try:
            # 尝试获取 'usageMetadata' 中的 'candidatesTokenCount'
            return self._data['usageMetadata'].get('candidatesTokenCount')
        except (KeyError, AttributeError):
            # 处理缺少 'usageMetadata' 或其类型不正确的情况
            return None

    def _extract_total_token_count(self) -> Optional[int]:
        """
        从响应的元数据（usageMetadata）中提取总的 token 数量。
        """
        try:
            # 尝试获取 'usageMetadata' 中的 'totalTokenCount'
            return self._data['usageMetadata'].get('totalTokenCount')
        except (KeyError, AttributeError):
            # 处理缺少 'usageMetadata' 或其类型不正确的情况
            return None

    def _extract_tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """
        从响应数据中提取函数调用（在 Gemini 中称为工具调用），如果存在的话。
        Gemini API 将工具调用信息放在包含 'functionCall' 键的 'parts' 元素中。
        """
        tool_calls_list = []
        try:
            # 遍历第一个候选响应的内容部分（parts）
            for part in self._data['candidates'][0]['content']['parts']:
                # 如果某个部分包含 'functionCall' 键
                if 'functionCall' in part:
                    # 将 'functionCall' 字典添加到列表中
                    tool_calls_list.append(part['functionCall'])
            # 如果列表非空（即找到了工具调用），则返回列表，否则返回 None
            return tool_calls_list if tool_calls_list else None
        except (KeyError, IndexError, TypeError):
            # 处理数据结构不符合预期的情况
            # logger.debug("无法提取工具调用，响应结构无效或缺失。", exc_info=True) # Debug 日志可能过于频繁，注释掉
            return None

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
        try:
            return self._data.get('usageMetadata')
        except AttributeError:
            return None