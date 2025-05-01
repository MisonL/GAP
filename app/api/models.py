# 导入类型注解相关的模块
from typing import List, Dict, Optional, Union, Literal, Any # 导入 Any 类型
# 导入 Pydantic 用于数据验证和模型定义
from pydantic import BaseModel, Field # 导入 BaseModel 和 Field

# 定义聊天消息的模型，用于表示单条聊天记录，与 OpenAI API 兼容
class Message(BaseModel):
    """
    表示聊天消息的结构。
    """
    role: str  # 消息发送者的角色 (例如 "user", "assistant", "system")
    content: Union[str, List[Dict]]  # 消息内容。可以是纯文本字符串，也可以是包含多部分（如文本和图像）的字典列表，以支持多模态输入。

# 定义模型响应消息的模型，用于表示模型生成的单条消息，可能包含工具调用
class ResponseMessage(BaseModel):
    """
    表示模型响应消息的结构，可能包含工具调用。
    """
    role: str # 消息发送者的角色，对于响应消息通常是 "assistant"
    content: Optional[str] = None # 响应内容，对于纯工具调用可能为 None
    tool_calls: Optional[List[Dict[str, Any]]] = None # 模型请求的工具调用列表


# 定义聊天补全请求的模型，包含了调用模型所需的所有参数，与 OpenAI API 兼容
class ChatCompletionRequest(BaseModel):
    """
    表示聊天补全请求的结构。
    """
    model: str  # 要使用的模型名称
    messages: List[Message]  # 包含聊天历史的消息列表
    temperature: float = 0.7  # 控制生成文本的随机性，值越高越随机
    top_p: Optional[float] = 1.0  # 控制核心采样的概率阈值
    n: int = 1  # 为每个输入消息生成多少个聊天补全选项 (目前代理只支持 1)
    stream: bool = False  # 是否以流式方式返回响应
    stop: Optional[Union[str, List[str]]] = None  # 指定停止生成的序列
    max_tokens: Optional[int] = None  # 限制生成的最大 token 数量
    presence_penalty: Optional[float] = 0.0  # 对新出现 token 的惩罚因子
    frequency_penalty: Optional[float] = 0.0  # 对已出现 token 的惩罚因子

# 定义聊天补全响应中的单个选项模型
class Choice(BaseModel):
    """
    表示聊天补全响应中的一个选项。
    """
    index: int  # 选项的索引 (通常为 0)
    message: ResponseMessage  # 模型生成的消息内容，使用 ResponseMessage 以支持工具调用
    finish_reason: Optional[str] = None  # 生成停止的原因 (例如 "stop", "length", "safety")

# 定义 API 调用中 token 使用情况的模型
class Usage(BaseModel):
    """
    表示 API 调用中的 token 使用情况。
    """
    prompt_tokens: int = 0  # 输入提示的 token 数量
    completion_tokens: int = 0  # 生成内容的 token 数量
    total_tokens: int = 0  # 总 token 数量

# 定义聊天补全响应的整体模型，包含了所有返回信息，与 OpenAI API 兼容
class ChatCompletionResponse(BaseModel):
    """
    表示聊天补全响应的整体结构。
    """
    id: str  # 响应的唯一标识符 (目前为固定值)
    object: Literal["chat.completion"]  # 对象类型，固定为 "chat.completion"
    created: int  # 响应创建的时间戳 (目前为固定值)
    model: str  # 使用的模型名称
    choices: List[Choice]  # 包含生成结果的选项列表
    usage: Usage = Field(default_factory=Usage)  # Token 使用情况，如果未提供则使用默认工厂创建

# 定义 API 错误响应的模型
class ErrorResponse(BaseModel):
    """
    表示 API 错误响应的结构。
    """
    message: str  # 错误信息
    type: str  # 错误类型 (例如 "invalid_request_error", "internal_error")
    param: Optional[str] = None  # 导致错误的参数 (如果适用)
    code: Optional[str] = None  # 错误代码 (如果适用)

# 定义获取可用模型列表的响应模型
class ModelList(BaseModel):
    """
    表示模型列表响应的结构。
    """
    object: str = "list"  # 对象类型，固定为 "list"
    data: List[Dict]  # 包含模型信息的字典列表


class GeminiContentPart(BaseModel):
    """
    表示 Gemini 内容中的一个部分 (例如文本或内嵌数据)。
    """
    text: Optional[str] = None # 文本内容
    # TODO: 未来可能需要添加对 inline_data (图像等) 的支持

class GeminiContent(BaseModel):
    """
    表示 Gemini 对话中的一段内容，包含角色和多个部分。
    """
    role: str # 内容的角色 (例如 "user", "model")
    parts: List[GeminiContentPart] # 内容的各个部分

class GeminiGenerationConfig(BaseModel):
    """
    表示 Gemini 生成内容的配置参数。
    """
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0) # 控制随机性
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0) # 控制核心采样
    top_k: Optional[int] = Field(None, ge=1) # 控制 Top-K 采样
    candidate_count: Optional[int] = Field(None, ge=1) # 生成的候选数量
    max_output_tokens: Optional[int] = Field(None, ge=1) # 最大输出 token 数量
    stop_sequences: Optional[List[str]] = None # 停止生成的序列

class GeminiSafetySetting(BaseModel):
    """
    表示 Gemini 安全设置，用于指定某个类别的阈值。
    """
    category: str # 安全类别 (例如 "HARM_CATEGORY_HARASSMENT")
    threshold: str # 阈值 (例如 "BLOCK_MEDIUM_AND_ABOVE")

class GeminiSafetyRating(BaseModel):
    """
    表示 Gemini 安全评分，用于指示某个类别的风险概率。
    """
    category: str # 安全类别
    probability: str # 风险概率
    blocked: Optional[bool] = None # 是否被阻止

class GeminiPromptFeedback(BaseModel):
    """
    表示 Gemini 对输入提示的反馈，例如安全评分。
    """
    safety_ratings: Optional[List[GeminiSafetyRating]] = None # 安全评分列表
    block_reason: Optional[str] = None # 阻止原因

class GeminiCandidate(BaseModel):
    """
    表示 Gemini 生成的单个响应候选。
    """
    content: GeminiContent # 候选内容 (Candidate content)
    finish_reason: Optional[str] = None # 生成停止的原因
    safety_ratings: Optional[List[GeminiSafetyRating]] = None # 候选的安全评分
    citation_metadata: Optional[Dict[str, Any]] = None # 引用元数据
    # TODO: 未来可能需要添加对 Grounding 信息的支持

class GeminiGenerateContentRequestV2(BaseModel):
    """
    表示 Gemini /v2/models/{model}:generateContent 请求的结构。
    """
    contents: List[GeminiContent] # 对话内容列表
    generation_config: Optional[GeminiGenerationConfig] = None # 生成配置
    safety_settings: Optional[List[GeminiSafetySetting]] = None # 安全设置
    # TODO: 未来可能需要添加对 tools 和 tool_config 的支持

class GeminiGenerateContentResponseV2(BaseModel):
    """
    表示 Gemini /v2/models/{model}:generateContent 响应的结构。
    """
    candidates: List[GeminiCandidate] # 生成的候选列表
    prompt_feedback: Optional[GeminiPromptFeedback] = None # 对输入提示的反馈
    usage_metadata: Optional[Dict[str, Any]] = None # 使用情况元数据
