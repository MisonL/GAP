# -*- coding: utf-8 -*-
"""
封装 Gemini API 响应，提供便捷的属性访问方法。
"""
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

# 获取名为 'my_logger' 的日志记录器实例
# 注意：如果此模块在没有配置日志记录器的情况下被导入，可能会出现问题。
# 更好的做法可能是从调用模块传递日志记录器，或使用标准日志记录配置。
# 为简单起见，我们暂时保留它，但要注意潜在问题。
logger = logging.getLogger('my_logger')

@dataclass
class GeneratedText:
    """简单的文本生成结果数据类"""
    text: str  # 生成的文本内容
    finish_reason: Optional[str] = None  # 完成原因 (例如 "STOP", "MAX_TOKENS", "SAFETY")

class ResponseWrapper:
    """
    封装 Gemini API 响应，提供便捷的属性访问方法，主要用于非流式响应。
    """
    def __init__(self, data: Dict[Any, Any]):
        """
        初始化 ResponseWrapper。

        Args:
            data: 从 Gemini API 返回的原始 JSON 数据 (字典格式)。
        """
        self._data = data  # 存储原始响应数据
        # 提取关键信息并存储为内部变量
        self._text = self._extract_text()
        self._finish_reason = self._extract_finish_reason()
        self._prompt_token_count = self._extract_prompt_token_count()
        self._candidates_token_count = self._extract_candidates_token_count()
        self._total_token_count = self._extract_total_token_count()
        self._thoughts = self._extract_thoughts()  # 提取可能的思考过程文本
        self._tool_calls = self._extract_tool_calls() # 提取可能的工具调用
        # 将原始数据格式化为 JSON 字符串，便于调试查看
        # 使用 try-except 块以防序列化失败
        try:
            self._json_dumps = json.dumps(self._data, indent=4, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"序列化响应数据时出错: {e}", exc_info=True)
            self._json_dumps = "{ \"error\": \"Failed to serialize response data\" }"


    def _extract_thoughts(self) -> Optional[str]:
        """
        从响应数据中提取模型的思考过程文本 (如果存在)。
        注意：这通常用于特定模型或配置。
        """
        try:
            # 遍历响应候选项的第一个候选项的内容部分
            for part in self._data['candidates'][0]['content']['parts']:
                # 如果部分包含 'thought' 键，则返回其文本
                if 'thought' in part:
                    return part.get('text', '') # 使用 get 增加健壮性
            return ""  # 如果没有找到思考过程文本，返回空字符串
        except (KeyError, IndexError, TypeError):
            # 如果数据结构不符合预期 (缺少键或索引或类型错误)，返回空字符串
            return ""

    def _extract_text(self) -> str:
        """
        从响应数据中提取主要的生成文本内容。
        会跳过包含 'thought' 或 'functionCall' 的部分。
        """
        text_parts = []
        try:
            # 遍历响应候选项的第一个候选项的内容部分
            for part in self._data['candidates'][0]['content']['parts']:
                # 如果部分不包含 'thought' 和 'functionCall' 键，则认为是主要文本
                if 'thought' not in part and 'functionCall' not in part:
                    text_parts.append(part.get('text', '')) # 使用 get 增加健壮性
            return "".join(text_parts) # 合并所有文本部分
        except (KeyError, IndexError, TypeError):
            # 如果数据结构不符合预期，返回空字符串
            return ""

    def _extract_finish_reason(self) -> Optional[str]:
        """
        从响应数据中提取完成原因。
        """
        try:
            # 获取第一个候选项的 'finishReason' 字段
            return self._data['candidates'][0].get('finishReason')
        except (KeyError, IndexError, TypeError):
            # 如果数据结构不符合预期，返回 None
            return None

    def _extract_prompt_token_count(self) -> Optional[int]:
        """
        从响应的元数据中提取提示部分的 token 数量。
        """
        try:
            # 获取 'usageMetadata' 中的 'promptTokenCount'
            return self._data['usageMetadata'].get('promptTokenCount')
        except (KeyError, AttributeError): # 添加 AttributeError 处理非字典情况
            # 如果缺少 'usageMetadata' 或其不是字典，返回 None
            return None

    def _extract_candidates_token_count(self) -> Optional[int]:
        """
        从响应的元数据中提取生成内容部分的 token 数量。
        """
        try:
            # 获取 'usageMetadata' 中的 'candidatesTokenCount'
            return self._data['usageMetadata'].get('candidatesTokenCount')
        except (KeyError, AttributeError):
            # 如果缺少 'usageMetadata' 或其不是字典，返回 None
            return None

    def _extract_total_token_count(self) -> Optional[int]:
        """
        从响应的元数据中提取总的 token 数量。
        """
        try:
            # 获取 'usageMetadata' 中的 'totalTokenCount'
            return self._data['usageMetadata'].get('totalTokenCount')
        except (KeyError, AttributeError):
            # 如果缺少 'usageMetadata' 或其不是字典，返回 None
            return None

    def _extract_tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """
        从响应数据中提取函数调用（工具调用），如果存在的话。
        Gemini 将工具调用作为包含 'functionCall' 键的 parts 返回。
        """
        tool_calls_list = []
        try:
            # 遍历第一个候选者内容中的 parts
            for part in self._data['candidates'][0]['content']['parts']:
                if 'functionCall' in part:
                    # 将 functionCall 字典附加到列表中
                    tool_calls_list.append(part['functionCall'])
            # 如果列表不为空则返回列表，否则返回 None
            return tool_calls_list if tool_calls_list else None
        except (KeyError, IndexError, TypeError):
            # 处理预期结构丢失或无效的情况
            # logger.debug("无法提取工具调用，结构无效或丢失。", exc_info=True) # Debug 日志可能过于频繁
            return None

    # 使用 @property 装饰器将方法转换为只读属性，方便外部访问
    @property
    def text(self) -> str:
        """返回提取的主要生成文本。"""
        return self._text

    @property
    def finish_reason(self) -> Optional[str]:
        """返回完成原因。"""
        return self._finish_reason

    @property
    def prompt_token_count(self) -> Optional[int]:
        """返回提示部分的 token 数量。"""
        return self._prompt_token_count

    @property
    def candidates_token_count(self) -> Optional[int]:
        """返回生成内容部分的 token 数量。"""
        return self._candidates_token_count

    @property
    def total_token_count(self) -> Optional[int]:
        """返回总的 token 数量。"""
        return self._total_token_count

    @property
    def thoughts(self) -> Optional[str]:
        """返回提取的思考过程文本。"""
        return self._thoughts

    @property
    def tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """返回提取的工具调用列表，或 None。"""
        return self._tool_calls

    @property
    def json_dumps(self) -> str:
        """返回格式化后的原始响应 JSON 字符串。"""
        return self._json_dumps

    @property
    def usage_metadata(self) -> Optional[Dict[str, Any]]:
        """直接返回 usageMetadata 字典，如果存在的话"""
        try:
            return self._data.get('usageMetadata')
        except AttributeError:
            return None