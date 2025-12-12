# -*- coding: utf-8 -*-
"""
封装 Gemini API 响应的包装类。
提供便捷的属性访问方法来获取响应中的关键信息，例如文本内容、完成原因、Token 计数等。
主要用于处理非流式（non-streaming）的 API 响应。
"""
import json  # 导入 json 模块，用于序列化原始数据以供调试
import logging  # 导入日志模块
from dataclasses import dataclass  # 导入 dataclass 装饰器，用于创建简单的数据类
from typing import (  # 导入类型提示
    Any,
    Dict,
    List,
    Optional,
    TypeVar,
    Union,
)

# 获取日志记录器实例
# 注意：确保在使用此模块前已配置好日志记录器
logger = logging.getLogger("my_logger")

# 定义一个类型变量 T，用于 _safe_get 函数的泛型返回类型
T = TypeVar("T")


@dataclass
class GeneratedText:
    """
    (可能未使用/已废弃) 一个简单的数据类，用于表示文本生成结果。
    """

    text: str  # 生成的文本内容
    finish_reason: Optional[str] = (
        None  # 完成原因 (例如 "STOP", "MAX_TOKENS", "SAFETY" 等)
    )


class ResponseWrapper:
    """
    封装从 Gemini API 返回的（通常是非流式）响应数据。
    此类旨在简化对嵌套响应结构中常见字段的访问，
    例如提取主要文本内容、完成原因、Token 使用量、思考过程和工具调用信息。
    它通过内部方法解析原始数据，并将提取的信息作为只读属性暴露出来。
    """

    def __init__(self, data: Dict[Any, Any]):
        """
        初始化 ResponseWrapper 实例。

        Args:
            data (Dict[Any, Any]): 从 Gemini API 返回的原始 JSON 数据（已解析为 Python 字典）。
                                   期望的结构通常包含 'candidates' 和 'usageMetadata' 等键。
        """
        self._data = data  # 存储原始响应字典
        # --- 在初始化时提取关键信息并存储为内部属性 ---
        # 使用内部的 _extract_* 方法来解析原始数据
        self._text: str = self._extract_text()  # 提取的主要文本内容
        self._finish_reason: Optional[str] = self._extract_finish_reason()  # 完成原因
        self._prompt_token_count: Optional[int] = (
            self._extract_prompt_token_count()
        )  # 输入 Token 数
        self._candidates_token_count: Optional[int] = (
            self._extract_candidates_token_count()
        )  # 输出 Token 数
        self._total_token_count: Optional[int] = (
            self._extract_total_token_count()
        )  # 总 Token 数
        self._thoughts: Optional[str] = (
            self._extract_thoughts()
        )  # 思考过程文本 (如果存在)
        self._tool_calls: Optional[List[Dict[str, Any]]] = (
            self._extract_tool_calls()
        )  # 工具调用列表 (如果存在)

        # --- 存储格式化的 JSON 字符串 (用于调试) ---
        # 将原始数据格式化为易于阅读的 JSON 字符串，方便调试时查看完整的 API 响应
        try:
            # indent=4 用于缩进，ensure_ascii=False 保证中文等字符正确显示
            self._json_dumps: str = json.dumps(self._data, indent=4, ensure_ascii=False)
        except TypeError:  # 处理可能的序列化错误 (例如包含无法序列化的对象)
            logger.error("序列化响应数据时出错", exc_info=True)  # 记录错误
            # 提供一个错误提示字符串作为备用
            self._json_dumps: str = '{ "error": "Failed to serialize response data" }'

    def _safe_get(
        self,
        path: List[Union[str, int]],
        default: Optional[T] = None,
        expected_type: Optional[type] = None,
    ) -> Optional[T]:
        """
        (内部辅助方法) 安全地从嵌套的字典或列表中获取值。
        可以处理路径中可能出现的 KeyError (字典键不存在)、IndexError (列表索引越界)、
        TypeError (类型不匹配导致无法索引) 和 AttributeError (尝试访问不存在的属性)。

        Args:
            path (List[Union[str, int]]): 一个包含字符串键和/或整数索引的列表，表示访问嵌套结构的路径。
                                          例如: ['candidates', 0, 'content', 'parts', 0, 'text']
            default (Optional[T]): 如果在访问路径中任何一步失败或最终值的类型不匹配时，返回的默认值。默认为 None。
            expected_type (Optional[type]): 期望获取到的值的类型。如果提供此参数，并且获取到的值不是此类型，
                                            则返回 `default`。

        Returns:
            Optional[T]: 如果成功获取到值且类型匹配（或未指定期望类型），则返回该值；否则返回 `default`。
        """
        data = self._data  # 从原始数据开始查找
        try:
            # 逐步遍历路径中的每个键或索引
            for key in path:
                if isinstance(data, dict):  # 如果当前数据是字典
                    data = data.get(key)  # 使用 get 获取值，避免 KeyError
                elif (
                    isinstance(data, list)
                    and isinstance(key, int)
                    and 0 <= key < len(data)
                ):  # 如果是列表且索引有效
                    data = data[key]  # 按索引获取值
                else:  # 如果路径无效（例如在非列表上使用整数索引，或在非字典上使用字符串键）
                    return default  # 返回默认值

                # 如果在路径中间遇到 None，则无法继续深入，返回默认值
                if data is None:
                    return default

            # 检查最终获取到的值的类型是否符合预期
            if expected_type is not None and not isinstance(data, expected_type):
                logger.debug(
                    f"安全获取路径 {path} 的值类型不匹配 (期望 {expected_type}, 得到 {type(data)})，返回默认值。"
                )  # 记录类型不匹配的调试信息
                return default  # 类型不匹配，返回默认值

            # 忽略类型检查器的警告，因为我们已经处理了多种可能性
            return data  # type: ignore # 成功获取到值，返回它
        except (
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ):  # 捕获可能的访问错误
            # 在调试时可以取消注释以下行来查看具体错误
            # logger.debug(f"安全获取路径 {path} 时出错")
            return default  # 发生任何预期的访问错误时，返回默认值

    def _extract_thoughts(self) -> Optional[str]:
        """
        (内部辅助方法) 从响应数据中提取模型的思考过程文本（如果存在）。
        Gemini API 的某些配置或模型可能会在响应的 'parts' 中包含带有 'thought' 键的部分。
        注意：此功能并非标准，取决于具体的 API 使用方式。

        Returns:
            Optional[str]: 提取到的思考过程文本，如果不存在则返回空字符串 ""。
        """
        # 安全地获取第一个候选者的 content parts 列表
        parts = self._safe_get(
            ["candidates", 0, "content", "parts"], default=[], expected_type=list
        )
        # 遍历 parts 列表
        for part in parts or []:  # 使用 or [] 确保 parts 为 None 时也能安全迭代
            # 检查 part 是否为字典且包含 'thought' 键
            if isinstance(part, dict) and "thought" in part:
                # 如果找到，返回该 part 中的 'text' 内容 (如果存在)，否则返回空字符串
                return part.get("text", "")
        # 如果遍历完所有 parts 都没找到 'thought'，返回空字符串
        return ""

    def _extract_text(self) -> str:
        """
        (内部辅助方法) 从响应数据中提取主要的生成文本内容。
        此方法会查找第一个候选者 (candidate) 的内容 (content) 中的所有部分 (parts)，
        并合并所有不包含 'thought' 或 'functionCall' 键的文本部分 ('text')。

        Returns:
            str: 合并后的主要文本内容。如果找不到文本部分，则返回空字符串。
        """
        text_parts = []  # 初始化用于存储文本片段的列表
        # 安全地获取第一个候选者的 content parts 列表
        parts = self._safe_get(
            ["candidates", 0, "content", "parts"], default=[], expected_type=list
        )
        # 遍历 parts 列表
        for part in parts or []:  # 使用 or [] 确保 parts 为 None 时也能安全迭代
            # 检查 part 是否为字典，并且 *不* 包含 'thought' 或 'functionCall' 键
            if (
                isinstance(part, dict)
                and "thought" not in part
                and "functionCall" not in part
            ):
                # 如果是普通的文本部分，提取其 'text' 值 (如果存在)，否则添加空字符串
                text_parts.append(part.get("text", ""))
        # 将所有提取到的文本片段连接成一个字符串并返回
        return "".join(text_parts)

    def _extract_finish_reason(self) -> Optional[str]:
        """
        (内部辅助方法) 从响应数据中提取生成完成的原因。
        路径: ['candidates', 0, 'finishReason']

        Returns:
            Optional[str]: 完成原因的字符串表示 (如 "STOP", "MAX_TOKENS", "SAFETY")，如果不存在则返回 None。
        """
        # 使用 _safe_get 安全地获取值，期望类型为字符串
        return self._safe_get(
            ["candidates", 0, "finishReason"], default=None, expected_type=str
        )

    def _extract_prompt_token_count(self) -> Optional[int]:
        """
        (内部辅助方法) 从响应的元数据（usageMetadata）中提取输入提示（prompt）的 token 数量。
        路径: ['usageMetadata', 'promptTokenCount']

        Returns:
            Optional[int]: 输入 Token 数量，如果不存在则返回 None。
        """
        # 使用 _safe_get 安全地获取值，期望类型为整数
        return self._safe_get(
            ["usageMetadata", "promptTokenCount"], default=None, expected_type=int
        )

    def _extract_candidates_token_count(self) -> Optional[int]:
        """
        (内部辅助方法) 从响应的元数据（usageMetadata）中提取生成内容（candidates）的 token 数量。
        路径: ['usageMetadata', 'candidatesTokenCount']

        Returns:
            Optional[int]: 输出 Token 数量，如果不存在则返回 None。
        """
        # 使用 _safe_get 安全地获取值，期望类型为整数
        return self._safe_get(
            ["usageMetadata", "candidatesTokenCount"], default=None, expected_type=int
        )

    def _extract_total_token_count(self) -> Optional[int]:
        """
        (内部辅助方法) 从响应的元数据（usageMetadata）中提取总的 token 数量。
        路径: ['usageMetadata', 'totalTokenCount']

        Returns:
            Optional[int]: 总 Token 数量，如果不存在则返回 None。
        """
        # 使用 _safe_get 安全地获取值，期望类型为整数
        return self._safe_get(
            ["usageMetadata", "totalTokenCount"], default=None, expected_type=int
        )

    def _extract_tool_calls(self) -> Optional[List[Dict[str, Any]]]:
        """
        (内部辅助方法) 从响应数据中提取函数/工具调用信息（如果存在）。
        Gemini API 将工具调用信息放在第一个候选者的 content parts 中，
        每个工具调用对应一个包含 'functionCall' 键的 part 字典。

        Returns:
            Optional[List[Dict[str, Any]]]: 包含所有工具调用字典的列表，如果不存在则返回 None。
        """
        tool_calls_list = []  # 初始化工具调用列表
        # 安全地获取第一个候选者的 content parts 列表
        parts = self._safe_get(
            ["candidates", 0, "content", "parts"], default=[], expected_type=list
        )
        # 遍历 parts 列表
        for part in parts or []:  # 使用 or [] 确保 parts 为 None 时也能安全迭代
            # 检查 part 是否为字典且包含 'functionCall' 键
            if isinstance(part, dict) and "functionCall" in part:
                # 将 'functionCall' 字典（包含调用详情）添加到列表中
                tool_calls_list.append(part["functionCall"])
        # 如果列表非空（即找到了工具调用），则返回列表；否则返回 None
        return tool_calls_list if tool_calls_list else None

    # --- 公开属性 ---
    # 使用 @property 装饰器将内部提取方法的结果暴露为只读属性，
    # 使得外部调用者可以像访问普通属性一样方便地获取信息。

    @property
    def text(self) -> str:
        """返回提取的主要生成文本内容。"""
        return self._text

    @property
    def finish_reason(self) -> Optional[str]:
        """返回生成完成的原因 (例如 "STOP", "MAX_TOKENS", "SAFETY")。"""
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
        """返回格式化后的原始响应 JSON 字符串，主要用于调试目的。"""
        return self._json_dumps

    @property
    def usage_metadata(self) -> Optional[Dict[str, Any]]:
        """直接返回原始的 usageMetadata 字典，如果存在的话。"""
        # 使用 _safe_get 安全地获取整个 usageMetadata 字典
        return self._safe_get(["usageMetadata"], default=None, expected_type=dict)
