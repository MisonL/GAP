# -*- coding: utf-8 -*-
"""
API 数据模型定义。
使用 Pydantic 定义 API 请求体、响应体以及内部使用的数据结构。
"""
import time  # 导入 time 模块

# 导入 datetime 和 time 用于类型提示和默认值
from datetime import datetime

# 导入类型注解相关的模块
from typing import Any, Dict, List, Literal, Optional, Union  # 导入常用类型提示

# 导入 Pydantic 用于数据验证和模型定义
from pydantic import (  # 导入 Pydantic 基类、字段定义工具和配置字典
    BaseModel,
    ConfigDict,
    Field,
)

# --- OpenAI 兼容模型 ---


# 定义聊天消息的模型，用于表示单条聊天记录，与 OpenAI API 兼容
class Message(BaseModel):
    """
    表示聊天消息的结构，兼容 OpenAI API 格式。
    """

    role: str  # 消息发送者的角色 (例如 "user", "assistant", "system")
    # 消息内容。可以是纯文本字符串，也可以是包含多部分（如文本和图像 Data URI）的字典列表，以支持多模态输入。
    content: Union[str, List[Dict[str, Any]]]  # 使用 Union 支持字符串或列表


# 定义模型响应消息的模型，用于表示模型生成的单条消息，可能包含工具调用
class ResponseMessage(BaseModel):
    """
    表示模型响应消息的结构，兼容 OpenAI API 格式，并增加了对工具调用的支持。
    """

    role: str  # 消息发送者的角色，对于响应消息通常是 "assistant"
    content: Optional[str] = None  # 响应的文本内容。对于纯工具调用，此字段可能为 None。
    tool_calls: Optional[List[Dict[str, Any]]] = (
        None  # 模型请求的工具调用列表 (如果模型支持并触发了工具调用)。
    )


# 定义聊天补全请求的模型，包含了调用模型所需的所有参数，与 OpenAI API 兼容
class ChatCompletionRequest(BaseModel):
    """
    表示发送给 `/v1/chat/completions` 端点的聊天补全请求结构，兼容 OpenAI API。
    """

    model: str  # 必须字段：指定要使用的模型名称 (例如 "gemini-pro")。
    messages: List[
        Message
    ]  # 必须字段：包含对话历史的消息列表，每个元素都是一个 Message 对象。
    temperature: float = Field(
        0.7, ge=0.0, le=2.0
    )  # 可选字段：控制生成文本的随机性。值越高越随机，越低越确定。默认 0.7，范围 [0.0, 2.0]。
    top_p: Optional[float] = Field(
        1.0, ge=0.0, le=1.0
    )  # 可选字段：控制核心采样的概率阈值。默认 1.0。
    n: int = Field(
        1, ge=1
    )  # 可选字段：为每个输入消息生成多少个聊天补全选项。代理目前只支持 n=1。默认 1。
    stream: bool = False  # 可选字段：是否以流式方式返回响应。默认 False。
    stop: Optional[Union[str, List[str]]] = (
        None  # 可选字段：指定一个或多个序列，模型在生成到这些序列时会停止。
    )
    max_tokens: Optional[int] = Field(
        None, ge=1
    )  # 可选字段：限制模型生成的最大 token 数量。
    presence_penalty: Optional[float] = Field(
        0.0, ge=-2.0, le=2.0
    )  # 可选字段：对新出现 token 的惩罚因子，鼓励模型谈论新主题。范围 [-2.0, 2.0]。
    frequency_penalty: Optional[float] = Field(
        0.0, ge=-2.0, le=2.0
    )  # 可选字段：对已出现 token 的惩罚因子，降低重复相同内容的可能性。范围 [-2.0, 2.0]。
    user_id: Optional[str] = None  # 可选字段：用户标识符，用于启用粘性会话等功能。


# 定义聊天补全响应中的单个选项模型
class Choice(BaseModel):
    """
    表示聊天补全响应中的一个生成选项 (Choice)。
    """

    index: int  # 选项的索引，通常从 0 开始。
    message: (
        ResponseMessage  # 模型生成的消息内容，使用 ResponseMessage 模型以支持工具调用。
    )
    finish_reason: Optional[str] = (
        None  # 指示生成停止的原因 (例如 "stop", "length", "safety", "tool_calls")。
    )


# 定义 API 调用中 token 使用情况的模型
class Usage(BaseModel):
    """
    表示 API 调用中的 token 使用情况统计。
    """

    prompt_tokens: int = 0  # 输入提示消耗的 token 数量。
    completion_tokens: int = 0  # 模型生成内容消耗的 token 数量。
    total_tokens: int = 0  # 本次调用消耗的总 token 数量。


# 定义聊天补全响应的整体模型，包含了所有返回信息，与 OpenAI API 兼容
class ChatCompletionResponse(BaseModel):
    """
    表示 `/v1/chat/completions` 端点返回的聊天补全响应的整体结构，兼容 OpenAI API。
    """

    id: str = Field(
        default_factory=lambda: f"chatcmpl-{int(time.time() * 1000)}"
    )  # 响应的唯一标识符 (使用默认工厂生成类似 OpenAI 的 ID)
    object: Literal["chat.completion"] = (
        "chat.completion"  # 对象类型，固定为 "chat.completion"
    )
    created: int = Field(
        default_factory=lambda: int(time.time())
    )  # 响应创建的 Unix 时间戳
    model: str  # 本次响应使用的模型名称。
    choices: List[Choice]  # 包含生成结果的选项列表 (通常只有一个选项)。
    usage: Usage = Field(
        default_factory=Usage
    )  # Token 使用情况。如果 API 未返回，则使用默认值 (全 0)。


# 定义 API 错误响应的模型
class ErrorResponse(BaseModel):
    """
    表示 API 返回错误时的标准响应结构。
    """

    message: str  # 人类可读的错误信息。
    type: (
        str  # 错误类型 (例如 "invalid_request_error", "internal_error", "api_error")。
    )
    param: Optional[str] = None  # 导致错误的参数名称 (如果适用)。
    code: Optional[str] = None  # 错误代码 (如果适用)。


# 定义获取可用模型列表的响应模型
class ModelData(BaseModel):
    """表示模型列表中的单个模型信息"""

    id: str  # 模型 ID (名称)
    object: str = "model"  # 对象类型，固定为 "model"
    created: int = Field(default_factory=lambda: int(time.time()))  # 创建时间戳 (模拟)
    owned_by: str = "organization-owner"  # 所有者 (模拟)


class ModelList(BaseModel):
    """
    表示 `/v1/models` 端点返回的模型列表响应结构，兼容 OpenAI API。
    """

    object: str = "list"  # 对象类型，固定为 "list"。
    data: List[ModelData]  # 包含模型信息的字典列表。


# --- Gemini 原生 API 模型 (用于 /v2 端点) ---


class InlineData(BaseModel):
    """
    表示 Gemini API 中的内联数据结构，通常用于图像。
    """

    mime_type: str  # 数据的 MIME 类型 (例如 "image/jpeg", "image/png")。
    data: str  # Base64 编码的数据字符串。


class GeminiContentPart(BaseModel):
    """
    表示 Gemini API 内容 (Content) 中的一个部分 (Part)。
    一个 Part 可以是文本 (`text`) 或内联数据 (`inline_data`) 等。
    """

    text: Optional[str] = None  # 文本内容。
    inline_data: Optional[InlineData] = None  # 内联数据 (例如图像)。
    # TODO: 根据需要添加对 functionCall, functionResponse, fileData 等其他 Part 类型的支持。


class GeminiContent(BaseModel):
    """
    表示 Gemini API 对话中的一段内容 (Content)。
    包含发送者角色 ('user' 或 'model') 和一个或多个部分 (parts)。
    """

    role: Optional[str] = (
        None  # 内容的角色 ('user' 或 'model')。对于 system_instruction，此字段省略。
    )
    parts: List[GeminiContentPart]  # 内容的各个部分列表。


class GeminiGenerationConfig(BaseModel):
    """
    表示 Gemini API 的生成配置参数 (`generationConfig`)。
    """

    temperature: Optional[float] = Field(
        None, description="控制随机性，范围 [0.0, 2.0]", ge=0.0, le=2.0
    )
    top_p: Optional[float] = Field(
        None, description="核心采样概率阈值，范围 [0.0, 1.0]", ge=0.0, le=1.0
    )
    top_k: Optional[int] = Field(None, description="Top-K 采样数量，必须 >= 1", ge=1)
    candidate_count: Optional[int] = Field(
        None, description="生成的候选响应数量，必须 >= 1", ge=1
    )
    max_output_tokens: Optional[int] = Field(
        None, description="最大输出 token 数量，必须 >= 1", ge=1
    )
    stop_sequences: Optional[List[str]] = Field(None, description="停止生成的序列列表")


class GeminiSafetySetting(BaseModel):
    """
    表示 Gemini API 的安全设置 (`safetySettings`) 中的一项。
    用于指定某个安全类别的内容过滤阈值。
    """

    category: str  # 安全类别枚举字符串 (例如 "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH" 等)。
    threshold: str  # 阻塞阈值枚举字符串 (例如 "BLOCK_NONE", "BLOCK_LOW_AND_ABOVE", "BLOCK_MEDIUM_AND_ABOVE", "BLOCK_HIGH_AND_ABOVE")。


class GeminiSafetyRating(BaseModel):
    """
    表示 Gemini API 返回的安全评分 (`safetyRatings`) 中的一项。
    指示生成内容在某个安全类别上的风险概率。
    """

    category: str  # 安全类别枚举字符串。
    probability: (
        str  # 风险概率枚举字符串 (例如 "NEGLIGIBLE", "LOW", "MEDIUM", "HIGH")。
    )
    blocked: Optional[bool] = (
        None  # 指示内容是否因此类别而被阻止 (通常在 promptFeedback 中出现)。
    )


class GeminiPromptFeedback(BaseModel):
    """
    表示 Gemini API 对输入提示 (`prompt`) 的反馈信息 (`promptFeedback`)。
    主要包含安全相关的评分和阻止原因。
    """

    safety_ratings: Optional[List[GeminiSafetyRating]] = (
        None  # 输入提示的安全评分列表。
    )
    block_reason: Optional[str] = None  # 如果输入提示被阻止，说明原因 (例如 "SAFETY")。


class GeminiCandidate(BaseModel):
    """
    表示 Gemini API 生成的单个响应候选 (`candidates`)。
    """

    content: Optional[GeminiContent] = None  # 候选内容。如果被阻止，可能为空。
    finish_reason: Optional[str] = (
        None  # 生成停止的原因枚举字符串 (例如 "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER")。
    )
    safety_ratings: Optional[List[GeminiSafetyRating]] = (
        None  # 此候选内容的安全评分列表。
    )
    citation_metadata: Optional[Dict[str, Any]] = (
        None  # 引用元数据 (如果模型生成了引用信息)。
    )
    # TODO: 未来可能需要添加对 Grounding 信息的支持。


class GeminiGenerateContentRequestV2(BaseModel):
    """
    表示发送给 Gemini 原生 API `/v2/models/{model}:generateContent` 端点的请求体结构。
    """

    contents: List[GeminiContent]  # 必须字段：对话内容列表，包含用户和模型的交替回合。
    generation_config: Optional[GeminiGenerationConfig] = (
        None  # 可选字段：生成配置参数。
    )
    safety_settings: Optional[List[GeminiSafetySetting]] = None  # 可选字段：安全设置。
    # TODO: 未来可能需要添加对 tools 和 tool_config 的支持。


class GeminiGenerateContentResponseV2(BaseModel):
    """
    表示 Gemini 原生 API `/v2/models/{model}:generateContent` 端点返回的响应体结构。
    """

    candidates: Optional[List[GeminiCandidate]] = (
        None  # 生成的候选列表。如果 prompt 被阻止，可能为空。
    )
    prompt_feedback: Optional[GeminiPromptFeedback] = None  # 对输入提示的反馈信息。
    usage_metadata: Optional[Dict[str, Any]] = (
        None  # 使用情况元数据 (例如 token 计数)。
    )


# --- 缓存管理相关模型 ---


class CachedContentEntry(BaseModel):
    """
    表示数据库中缓存条目的 Pydantic 模型，用于 API 响应。
    """

    id: int  # 数据库自增 ID
    gemini_cache_id: str  # Gemini API 返回的缓存 ID/名称
    content_hash: str  # 缓存内容的 SHA-256 哈希值
    api_key_id: Optional[int] = None  # 关联的 API Key 的数据库 ID (可选)
    user_id: Optional[str] = None  # 关联的用户 ID (可选)
    created_at: datetime  # 数据库记录创建时间
    expires_at: datetime  # 缓存过期时间 (来自 Gemini API)
    last_used_at: Optional[datetime] = None  # 最后使用时间 (数据库记录)
    usage_count: Optional[int] = 0  # 使用次数 (数据库记录)

    # Pydantic V2: 启用 ORM 模式，允许从 SQLAlchemy 模型实例创建
    model_config = ConfigDict(from_attributes=True)


class CacheListResponse(BaseModel):
    """
    表示缓存列表 API (`/cache`) 的响应模型。
    """

    total: int  # 缓存条目总数
    caches: List[CachedContentEntry]  # 缓存条目列表


# 注意：原文件末尾重复导入了 datetime, Optional, BaseModel，已移除。
# 恢复 CacheEntryResponse 模型定义
class CacheEntryResponse(BaseModel):
    """
    表示单个缓存条目的响应模型 (与 CachedContentEntry 结构相同，但用于 API 响应类型提示)。
    """

    id: int
    gemini_cache_id: str
    content_hash: str
    api_key_id: Optional[int] = None  # 保持与 CachedContentEntry 一致
    user_id: Optional[str] = None  # 保持与 CachedContentEntry 一致
    created_at: datetime
    expires_at: datetime
    last_used_at: Optional[datetime] = None  # 保持与 CachedContentEntry 一致
    usage_count: Optional[int] = 0  # 保持与 CachedContentEntry 一致

    # 启用 ORM 模式
    model_config = ConfigDict(from_attributes=True)
