# 导入必要的库
import requests  # 用于发送同步 HTTP 请求
import json      # 用于处理 JSON 数据
import os        # 用于访问环境变量
import asyncio   # 用于异步操作
# 注意：调整导入路径以反映新的目录结构
from ..api.models import ChatCompletionRequest, Message  # 从本地 models 模块导入数据模型
from dataclasses import dataclass  # 用于创建数据类
from typing import Optional, Dict, Any, List, AsyncGenerator, Union # 增加了 AsyncGenerator, Union
import httpx     # 用于发送异步 HTTP 请求
import logging   # 用于日志记录
import re        # 新增：用于正则表达式
from .utils import StreamProcessingError # 新增导入自定义异常

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger('my_logger')

# 新增：定义 Gemini 支持的图片 MIME 类型
SUPPORTED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

# 新增：编译用于解析和验证 Data URI 的正则表达式
# 匹配 data:image/<mime>;base64,<data>
# <mime> 必须是 SUPPORTED_IMAGE_MIME_TYPES 中的一个
# 捕获组 1: mime_type, 捕获组 2: base64_data
DATA_URI_REGEX = re.compile(r"^data:(" + "|".join(re.escape(m) for m in SUPPORTED_IMAGE_MIME_TYPES) + r");base64,(.+)$")


# 定义一个数据类，用于封装生成的文本及其完成原因
@dataclass
class GeneratedText:
    """简单的文本生成结果数据类"""
    text: str  # 生成的文本内容
    finish_reason: Optional[str] = None  # 完成原因 (例如 "STOP", "MAX_TOKENS", "SAFETY")


# 定义一个包装类，用于解析和访问 Gemini API 的响应数据
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
        self._json_dumps = json.dumps(self._data, indent=4, ensure_ascii=False)

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
                    return part['text']
            return ""  # 如果没有找到思考过程文本，返回空字符串
        except (KeyError, IndexError):
            # 如果数据结构不符合预期 (缺少键或索引)，返回空字符串
            return ""

    def _extract_text(self) -> str:
        """
        从响应数据中提取主要的生成文本内容。
        会跳过包含 'thought' 的部分。
        """
        try:
            # 遍历响应候选项的第一个候选项的内容部分
            for part in self._data['candidates'][0]['content']['parts']:
                # 如果部分不包含 'thought' 键，则认为是主要文本，返回它
                if 'thought' not in part:
                    return part['text']
            return ""  # 如果没有找到主要文本，返回空字符串
        except (KeyError, IndexError):
            # 如果数据结构不符合预期，返回空字符串
            return ""

    def _extract_finish_reason(self) -> Optional[str]:
        """
        从响应数据中提取完成原因。
        """
        try:
            # 获取第一个候选项的 'finishReason' 字段
            return self._data['candidates'][0].get('finishReason')
        except (KeyError, IndexError):
            # 如果数据结构不符合预期，返回 None
            return None

    def _extract_prompt_token_count(self) -> Optional[int]:
        """
        从响应的元数据中提取提示部分的 token 数量。
        """
        try:
            # 获取 'usageMetadata' 中的 'promptTokenCount'
            return self._data['usageMetadata'].get('promptTokenCount')
        except KeyError:
            # 如果缺少 'usageMetadata'，返回 None
            return None

    def _extract_candidates_token_count(self) -> Optional[int]:
        """
        从响应的元数据中提取生成内容部分的 token 数量。
        """
        try:
            # 获取 'usageMetadata' 中的 'candidatesTokenCount'
            return self._data['usageMetadata'].get('candidatesTokenCount')
        except KeyError:
            # 如果缺少 'usageMetadata'，返回 None
            return None

    def _extract_total_token_count(self) -> Optional[int]:
        """
        从响应的元数据中提取总的 token 数量。
        """
        try:
            # 获取 'usageMetadata' 中的 'totalTokenCount'
            return self._data['usageMetadata'].get('totalTokenCount')
        except KeyError:
            # 如果缺少 'usageMetadata'，返回 None
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
            logger.debug("无法提取工具调用，结构无效或丢失。", exc_info=True)
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


# 定义与 Gemini API 交互的客户端类
class GeminiClient:
    """
    用于与 Google Gemini API 进行交互的客户端。
    """
    AVAILABLE_MODELS = []  # 类变量，存储可用的模型列表
    # 从环境变量读取额外的模型名称，用逗号分隔
    EXTRA_MODELS = os.environ.get("EXTRA_MODELS", "").split(",")

    def __init__(self, api_key: str):
        """
        初始化 GeminiClient。

        Args:
            api_key (str): 用于访问 Gemini API 的 API 密钥。
        """
        self.api_key = api_key

    async def stream_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction) -> AsyncGenerator[Union[str, Dict[str, Any]], None]:
        """
        以流式方式向 Gemini API 发送聊天请求并处理响应。

        Args:
            request (ChatCompletionRequest): 包含请求参数的 ChatCompletionRequest 对象。
            contents: 转换后的 Gemini 格式的消息历史。
            safety_settings: 要应用的安全设置列表。
            system_instruction: 系统指令 (如果提供)。

        Yields:
            Union[str, Dict[str, Any]]: 从 API 返回的文本块 (str) 或包含 usageMetadata 或 _final_finish_reason 的字典。

        Raises:
            StreamProcessingError: 如果流处理中发生错误或因安全问题被阻止。
            httpx.HTTPStatusError: 如果 API 返回错误状态码。
            Exception: 其他网络或处理错误。
        """
        logger.info("流式开始 →")
        text_yielded = False  # 标记是否已产生过文本块
        safety_issue_detected = None  # 记录检测到的安全问题描述
        usage_metadata = None # 用于存储 usageMetadata
        final_finish_reason = "STOP" # 初始化最终完成原因，默认为 STOP
        # 根据模型名称选择 API 版本 (v1alpha 用于特定模型，v1beta 用于通用模型)
        api_version = "v1alpha" if "think" in request.model else "v1beta"
        # 构建流式请求的 URL
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:streamGenerateContent?key={self.api_key}&alt=sse"
        # 设置请求头
        headers = {
            "Content-Type": "application/json",
        }
        # 构建请求体数据
        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
            "safetySettings": safety_settings,
        }
        # 如果有系统指令，添加到请求体中
        if system_instruction:
            data["system_instruction"] = system_instruction

        # 使用 httpx 进行异步流式请求
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, json=data, timeout=600) as response:
                buffer = b""  # 用于存储不完整的 JSON 数据块
                try:
                    # 异步迭代处理响应的每一行（SSE 格式）
                    async for line in response.aiter_lines():
                        if not line.strip():  # 跳过空行
                            continue
                        if line.startswith("data: "):  # 移除 SSE 的 "data: " 前缀
                            line = line[len("data: "):]
                        buffer += line.encode('utf-8')  # 将行添加到缓冲区
                        try:
                            # 尝试解析缓冲区中的 JSON 数据
                            data_chunk = json.loads(buffer.decode('utf-8'))
                            buffer = b""  # 解析成功后清空缓冲区

                            # 检查并存储 usageMetadata
                            if 'usageMetadata' in data_chunk:
                                usage_metadata = data_chunk['usageMetadata']
                                logger.debug(f"接收到 usageMetadata: {usage_metadata}")
                                # 如果 usageMetadata 块也包含 candidates，则继续处理文本部分
                                # 否则，可以认为这是最后一个块，但为了安全起见，我们不在这里中断

                            # 检查响应结构是否符合预期（提取文本）
                            if 'candidates' in data_chunk and data_chunk['candidates']:
                                candidate = data_chunk['candidates'][0]
                                if 'content' in candidate:
                                    content = candidate['content']
                                    if 'parts' in content and content['parts']:
                                        parts = content['parts']
                                        # 提取当前数据块中的文本
                                        text_in_chunk = ""
                                        for part in parts:
                                            if 'text' in part:
                                                text_in_chunk += part['text']

                                        # 如果当前块有文本，则产生它
                                        if text_in_chunk:
                                            yield text_in_chunk
                                            text_yielded = True  # 标记已产生文本

                                # 在处理完文本后检查安全问题
                                finish_reason = candidate.get("finishReason")
                                # 如果完成原因不是 STOP，记录警告、标记安全问题并更新最终原因
                                if finish_reason and finish_reason != "STOP":
                                    logger.warning(f"模型的响应因违反内容政策而被标记: {finish_reason}，模型: {request.model}")
                                    safety_issue_detected = f"完成原因: {finish_reason}" # 翻译
                                    final_finish_reason = finish_reason # 更新最终原因

                                # 检查安全评分
                                if 'safetyRatings' in candidate:
                                    for rating in candidate['safetyRatings']:
                                        # 如果被阻止或概率为高，记录警告并标记安全问题
                                        if rating.get('blocked') or rating.get('probability') == 'HIGH':
                                            logger.warning(f"模型的响应因安全问题被阻止或标记: 类别={rating['category']}，模型: {request.model}，概率: {rating.get('probability', 'N/A')}, Blocked={rating.get('blocked', 'N/A')}")
                                            safety_issue_detected = f"安全问题: {rating['category']}" # 翻译
                                            # 如果因为安全问题被阻止，也更新最终原因
                                            if final_finish_reason == "STOP": final_finish_reason = "SAFETY" # 仅在未被其他原因覆盖时更新为 SAFETY

                        except json.JSONDecodeError:
                            # 如果 JSON 解析失败（数据块不完整），记录调试信息并继续接收下一行
                            logger.debug(f"JSON 解析错误, 当前缓冲区内容: {buffer}")
                            continue
                except Exception as e:
                    # 捕获流处理过程中的其他异常
                    error_detail = f"流处理内部错误: {e}" # 准备错误信息
                    logger.error(error_detail, exc_info=True) # 添加 exc_info
                    # 抛出自定义异常，以便调用者可以捕获并处理
                    raise StreamProcessingError(error_detail)
                finally:
                    # 流处理结束（正常或异常）
                    logger.info("流式结束 ←")
                    # 如果流结束了，但从未产生过文本，并且检测到了安全问题，则抛出 StreamProcessingError 异常
                    if not text_yielded and safety_issue_detected:
                        error_message = f"响应因安全策略被阻止 ({safety_issue_detected})，未生成任何内容"
                        logger.error(error_message)
                        # 抛出自定义异常，以便调用者（例如 endpoints.py）可以捕获并处理
                        raise StreamProcessingError(error_message)

                    # 在生成器结束时，按顺序 yield 最终完成原因和使用情况元数据
                    # 1. 产生最终完成原因
                    yield {'_final_finish_reason': final_finish_reason}
                    # 2. 如果捕获到了 usage_metadata，则 yield 它
                    if usage_metadata:
                        yield {'_usage_metadata': usage_metadata}


    async def complete_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction):
        """
        [异步] 以非流式方式向 Gemini API 发送聊天请求并获取完整响应。

        Args:
            request (ChatCompletionRequest): 包含请求参数的 ChatCompletionRequest 对象。
            contents: 转换后的 Gemini 格式的消息历史。
            safety_settings: 要应用的安全设置列表。
            system_instruction: 系统指令 (如果提供)。

        Returns:
            ResponseWrapper: 包含解析后响应数据的 ResponseWrapper 对象。

        Raises:
            httpx.RequestError: 如果发生网络请求错误。
            httpx.HTTPStatusError: 如果 API 返回错误状态码。
        """
        # 根据模型名称选择 API 版本
        api_version = "v1alpha" if "think" in request.model else "v1beta"
        # 构建非流式请求的 URL
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:generateContent?key={self.api_key}"
        # 设置请求头
        headers = {
            "Content-Type": "application/json",
        }
        # 构建请求体数据
        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
            "safetySettings": safety_settings,
        }
        # 如果有系统指令，添加到请求体中
        if system_instruction:
            data["system_instruction"] = system_instruction
        # 使用 httpx 库发送异步 POST 请求
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data, timeout=600) # 添加了超时
            # 如果响应状态码表示错误，则抛出 HTTPStatusError
            response.raise_for_status()
            # 将响应的 JSON 数据包装在 ResponseWrapper 中并返回
            return ResponseWrapper(response.json())

    def convert_messages(self, messages: List[Message], use_system_prompt=False):
        """
        将 OpenAI 格式的消息列表转换为 Gemini API 格式的 'contents' 列表。

        Args:
            messages (List[Message]): OpenAI 格式的消息列表 (包含 role 和 content)。
            use_system_prompt (bool): 是否将第一个 'system' 角色的消息视为系统指令 (Gemini v1beta 支持)。

        Returns:
            tuple: 包含转换后的 contents 列表和 system_instruction 字典 (如果适用)。
                   如果转换过程中出现错误，则返回包含错误信息的列表。
        """
        gemini_history = []  # 存储转换后的 Gemini 消息历史
        errors = []          # 存储转换过程中的错误信息
        system_instruction_text = ""  # 存储提取的系统指令文本
        is_system_phase = use_system_prompt  # 标记是否处于处理系统指令的阶段

        # 遍历输入的 OpenAI 消息列表
        for i, message in enumerate(messages):
            role = message.role      # 获取消息角色
            content = message.content  # 获取消息内容

            # 记录正在处理的消息（用于调试）
            logger.debug(f"正在处理消息 {i}: role={role}, content={content}") # 翻译

            # 处理纯文本内容
            if isinstance(content, str):
                # 如果启用了系统指令处理且当前角色是 'system'
                if is_system_phase and role == 'system':
                    # 将系统消息内容累加到 system_instruction_text
                    if system_instruction_text:
                        system_instruction_text += "\n" + content
                    else:
                        system_instruction_text = content
                else:
                    # 一旦遇到非系统消息或未启用系统指令处理，则退出系统指令处理阶段
                    is_system_phase = False

                    # 映射 OpenAI 角色到 Gemini 角色（'user' 或 'model'）
                    if role in ['user', 'system']:  # 将 'system'（非首条）也视为 'user'
                        role_to_use = 'user'
                    elif role == 'assistant':
                        role_to_use = 'model'
                    else:
                        # 如果角色无效，记录错误并跳过此消息
                        errors.append(f"无效的角色: {role}") # 翻译
                        continue

                    # 合并连续相同角色的消息
                    if gemini_history and gemini_history[-1]['role'] == role_to_use:
                        gemini_history[-1]['parts'].append({"text": content})
                    else:
                        # 添加新的消息条目
                        gemini_history.append(
                            {"role": role_to_use, "parts": [{"text": content}]})
            # 处理包含多部分的内容（例如文本和图像）
            elif isinstance(content, list):
                parts = []  # 存储转换后的 Gemini 'parts' 列表
                # 遍历内容列表中的每个项目
                for item in content:
                    if item.get('type') == 'text':
                        # 添加文本部分
                        parts.append({"text": item.get('text')})
                    elif item.get('type') == 'image_url':
                        # 处理图像 URL
                        image_data = item.get('image_url', {}).get('url', '')
                        # 修改：使用正则表达式解析和验证 Data URI
                        match = DATA_URI_REGEX.match(image_data)
                        if match:
                            mime_type = match.group(1)
                            base64_data = match.group(2)
                            # 添加内联图像数据部分
                            parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64_data
                                }
                            })
                        else:
                            # 如果 Data URI 格式无效或 MIME 类型不支持
                            if image_data.startswith('data:image/'):
                                errors.append(f"无效或不支持的图像 Data URI：MIME 类型不在 {SUPPORTED_IMAGE_MIME_TYPES} 中或格式无效。") # 翻译
                            else:
                                errors.append(f"无效的图像格式：仅接受支持的 MIME 类型 ({', '.join(SUPPORTED_IMAGE_MIME_TYPES)}) 的 Base64 编码 Data URI。") # 翻译
                    else:
                        # 如果内容类型不受支持，记录错误
                        errors.append(f"不支持的内容类型: {item.get('type')}") # 翻译

                # 如果成功解析出 parts 且没有错误发生在此 item 上
                if parts and not errors: # 检查 errors 确保只在无错时添加
                    # 映射角色
                    if role in ['user', 'system']:
                        role_to_use = 'user'
                    elif role == 'assistant':
                        role_to_use = 'model'
                    else:
                        errors.append(f"无效的角色: {role}") # 翻译
                        continue # 跳过此消息
                    # 合并连续相同角色的消息
                    if gemini_history and gemini_history[-1]['role'] == role_to_use:
                        gemini_history[-1]['parts'].extend(parts)
                    else:
                        # 添加新的消息条目
                        gemini_history.append(
                            {"role": role_to_use, "parts": parts})
        # 如果转换过程中有错误，返回错误列表
        if errors:
            return errors
        else:
            # 否则，返回转换后的消息历史和系统指令
            system_instruction_dict = {"parts": [{"text": system_instruction_text}]} if system_instruction_text else None
            return gemini_history, system_instruction_dict

    @staticmethod
    async def list_available_models(api_key) -> list:
        """
        [静态方法] 获取指定 API 密钥可用的 Gemini 模型列表。
        注意：此方法使用同步的 requests 库，因为它可能在同步上下文中被调用。
        """
        if not api_key:
            logger.error("尝试列出模型但未提供 API 密钥。") # 翻译
            return []
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models?key={}".format(api_key)
            # 改为使用 httpx 进行异步请求以保持一致性
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=20) # 增加超时
                response.raise_for_status()
                models_data = response.json()
                model_names = [m['name'] for m in models_data.get('models', [])]
                # 添加环境变量中定义的额外模型
                extra_models_list = [m.strip() for m in GeminiClient.EXTRA_MODELS if m.strip()]
                if extra_models_list:
                    model_names.extend(extra_models_list)
                    model_names = sorted(list(set(model_names))) # 去重并排序
                return model_names
        except httpx.HTTPStatusError as e:
            logger.error(f"列出模型时发生 HTTP 错误 (Key: {api_key[:8]}...): {e.response.status_code} - {e.response.text}") # 翻译
            return []
        except Exception as e:
            logger.error(f"列出模型时发生未知错误 (Key: {api_key[:8]}...): {e}", exc_info=True) # 翻译
            return []