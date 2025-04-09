# 导入类型注解相关的模块
from typing import List, Dict, Optional, Union, Literal
# 导入 Pydantic 用于数据验证和模型定义
from pydantic import BaseModel, Field

# 定义消息模型，与 OpenAI API 兼容
class Message(BaseModel):
    """表示聊天消息的结构"""
    role: str  # 消息发送者的角色 (例如 "user", "assistant", "system")
    content: Union[str, List[Dict]]  # 消息内容。可以是纯文本字符串，也可以是包含多部分（如文本和图像）的字典列表，以支持多模态输入。

# 定义聊天补全请求的模型，与 OpenAI API 兼容
class ChatCompletionRequest(BaseModel):
    """表示聊天补全请求的结构"""
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

# 定义聊天补全响应中的选项模型
class Choice(BaseModel):
    """表示聊天补全响应中的一个选项"""
    index: int  # 选项的索引 (通常为 0)
    message: Message  # 模型生成的消息
    finish_reason: Optional[str] = None  # 生成停止的原因 (例如 "stop", "length", "safety")

# 定义 token 使用情况的模型
class Usage(BaseModel):
    """表示 API 调用中的 token 使用情况"""
    prompt_tokens: int = 0  # 输入提示的 token 数量
    completion_tokens: int = 0  # 生成内容的 token 数量
    total_tokens: int = 0  # 总 token 数量

# 定义聊天补全响应的模型，与 OpenAI API 兼容
class ChatCompletionResponse(BaseModel):
    """表示聊天补全响应的整体结构"""
    id: str  # 响应的唯一标识符 (目前为固定值)
    object: Literal["chat.completion"]  # 对象类型，固定为 "chat.completion"
    created: int  # 响应创建的时间戳 (目前为固定值)
    model: str  # 使用的模型名称
    choices: List[Choice]  # 包含生成结果的选项列表
    usage: Usage = Field(default_factory=Usage)  # Token 使用情况，如果未提供则使用默认工厂创建

# 定义错误响应的模型
class ErrorResponse(BaseModel):
    """表示 API 错误响应的结构"""
    message: str  # 错误信息
    type: str  # 错误类型 (例如 "invalid_request_error", "internal_error")
    param: Optional[str] = None  # 导致错误的参数 (如果适用)
    code: Optional[str] = None  # 错误代码 (如果适用)

# 定义模型列表响应的模型
class ModelList(BaseModel):
    """表示模型列表响应的结构"""
    object: str = "list"  # 对象类型，固定为 "list"
    data: List[Dict]  # 包含模型信息的字典列表