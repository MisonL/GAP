# 导入必要的库
import requests  # 用于发送同步 HTTP 请求
import json      # 用于处理 JSON 数据
import os        # 用于访问环境变量
import asyncio   # 用于异步操作
from app.models import ChatCompletionRequest, Message  # 从本地 models 模块导入数据模型
from dataclasses import dataclass  # 用于创建数据类
from typing import Optional, Dict, Any, List  # 用于类型注解
import httpx     # 用于发送异步 HTTP 请求
import logging   # 用于日志记录

# 获取名为 'my_logger' 的日志记录器实例
logger = logging.getLogger('my_logger')


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
    def json_dumps(self) -> str:
        """返回格式化后的原始响应 JSON 字符串。"""
        return self._json_dumps


# 定义与 Gemini API 交互的客户端类
class GeminiClient:
    """
    用于与 Google Gemini API 进行交互的客户端。
    """
    AVAILABLE_MODELS = []  # 类变量，存储可用的模型列表
    # 从环境变量读取额外的模型名称，以逗号分隔
    EXTRA_MODELS = os.environ.get("EXTRA_MODELS", "").split(",")

    def __init__(self, api_key: str):
        """
        初始化 GeminiClient。

        Args:
            api_key: 用于访问 Gemini API 的 API 密钥。
        """
        self.api_key = api_key

    async def stream_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction):
        """
        以流式方式向 Gemini API 发送聊天请求并处理响应。

        Args:
            request: 包含请求参数的 ChatCompletionRequest 对象。
            contents: 转换后的 Gemini 格式的消息历史。
            safety_settings: 要应用的安全设置列表。
            system_instruction: 系统指令 (如果提供)。

        Yields:
            str: 从 API 返回的文本块。

        Raises:
            ValueError: 如果流因安全问题被终止且未生成任何文本。
            httpx.HTTPStatusError: 如果 API 返回错误状态码。
            Exception: 其他网络或处理错误。
        """
        logger.info("流式开始 →")
        text_yielded = False  # 标记是否已产生过文本块
        safety_issue_detected = None  # 记录检测到的安全问题描述
        # 根据模型名称选择 API 版本 (v1alpha 用于特定模型, v1beta 用于通用模型)
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
                    # 异步迭代处理响应的每一行 (SSE 格式)
                    async for line in response.aiter_lines():
                        if not line.strip():  # 跳过空行
                            continue
                        if line.startswith("data: "):  # 移除 SSE 的 "data: " 前缀
                            line = line[len("data: "):]
                        buffer += line.encode('utf-8')  # 将行添加到缓冲区
                        try:
                            # 尝试解析缓冲区中的 JSON 数据
                            data = json.loads(buffer.decode('utf-8'))
                            buffer = b""  # 解析成功后清空缓冲区
                            # 检查响应结构是否符合预期
                            if 'candidates' in data and data['candidates']:
                                candidate = data['candidates'][0]
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
                                        # 如果完成原因不是 STOP，记录警告并标记安全问题
                                        if finish_reason and finish_reason != "STOP":
                                            logger.warning(f"模型的响应因违反内容政策而被标记: {finish_reason}，模型: {request.model}")
                                            safety_issue_detected = f"Finish Reason: {finish_reason}"
                                            # 不在此处抛出异常，继续处理流

                                        # 检查安全评分
                                        if 'safetyRatings' in candidate:
                                            for rating in candidate['safetyRatings']:
                                                # 如果被阻止或概率为高，记录警告并标记安全问题
                                                # 注意: 'blocked' 字段可能存在于某些 API 版本或响应中
                                                if rating.get('blocked') or rating.get('probability') == 'HIGH':
                                                    logger.warning(f"模型的响应因安全问题被阻止或标记: 类别={rating['category']}，模型: {request.model}，概率: {rating.get('probability', 'N/A')}, Blocked={rating.get('blocked', 'N/A')}")
                                                    safety_issue_detected = f"Safety Issue: {rating['category']}"
                                                    # 不在此处抛出异常，继续处理流

                        except json.JSONDecodeError:
                            # 如果 JSON 解析失败 (数据块不完整)，记录调试信息并继续接收下一行
                            logger.debug(f"JSON解析错误, 当前缓冲区内容: {buffer}")
                            continue
                        # 移除此处的通用 Exception 捕获，让特定错误（如 httpx 错误）可以冒泡出去
                except Exception as e:
                    # 捕获流处理过程中的其他异常
                    logger.error(f"流式处理错误: {e}")
                    # 如果错误不是在循环内部检测到的安全问题，则重新抛出原始异常
                    if not safety_issue_detected:
                        raise e
                finally:
                    # 流处理结束（正常或异常）
                    logger.info("流式结束 ←")
                    # 如果流结束了，但从未产生过文本，并且检测到了安全问题，则抛出异常
                    if not text_yielded and safety_issue_detected:
                         logger.error(f"流式传输因安全问题而终止，且未生成任何文本: {safety_issue_detected}")
                         # 抛出 ValueError，与之前显式抛出的异常类型保持一致
                         raise ValueError(f"流式传输因安全问题而终止，且未生成任何文本: {safety_issue_detected}")


    def complete_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction):
        """
        以非流式方式向 Gemini API 发送聊天请求并获取完整响应。

        Args:
            request: 包含请求参数的 ChatCompletionRequest 对象。
            contents: 转换后的 Gemini 格式的消息历史。
            safety_settings: 要应用的安全设置列表。
            system_instruction: 系统指令 (如果提供)。

        Returns:
            ResponseWrapper: 包含解析后响应数据的 ResponseWrapper 对象。

        Raises:
            requests.exceptions.RequestException: 如果发生网络请求错误。
            requests.exceptions.HTTPError: 如果 API 返回错误状态码。
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
        # 使用 requests 库发送同步 POST 请求
        response = requests.post(url, headers=headers, json=data)
        # 如果响应状态码表示错误，则抛出 HTTPError
        response.raise_for_status()
        # 将响应的 JSON 数据包装在 ResponseWrapper 中并返回
        return ResponseWrapper(response.json())

    def convert_messages(self, messages: List[Message], use_system_prompt=False):
        """
        将 OpenAI 格式的消息列表转换为 Gemini API 格式的 'contents' 列表。

        Args:
            messages: OpenAI 格式的消息列表 (包含 role 和 content)。
            use_system_prompt: 是否将第一个 'system' 角色的消息视为系统指令 (Gemini v1beta 支持)。

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

            # 记录正在处理的消息 (用于调试)
            logger.debug(f"Processing message {i}: role={role}, content={content}")

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

                    # 映射 OpenAI 角色到 Gemini 角色 ('user' 或 'model')
                    if role in ['user', 'system']:  # 将 'system' (非首条) 也视为 'user'
                        role_to_use = 'user'
                    elif role == 'assistant':
                        role_to_use = 'model'
                    else:
                        # 如果角色无效，记录错误并跳过此消息
                        errors.append(f"Invalid role: {role}")
                        continue

                    # 合并连续相同角色的消息
                    if gemini_history and gemini_history[-1]['role'] == role_to_use:
                        gemini_history[-1]['parts'].append({"text": content})
                    else:
                        # 添加新的消息条目
                        gemini_history.append(
                            {"role": role_to_use, "parts": [{"text": content}]})
            # 处理包含多部分的内容 (例如文本和图像)
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
                        # 检查是否为 Base64 编码的 Data URI
                        if image_data.startswith('data:image/'):
                            try:
                                # 解析 MIME 类型和 Base64 数据
                                mime_type, base64_data = image_data.split(';')[0].split(':')[1], image_data.split(',')[1]
                                # 添加内联图像数据部分
                                parts.append({
                                    "inline_data": {
                                        "mime_type": mime_type,
                                        "data": base64_data
                                    }
                                })
                            except (IndexError, ValueError):
                                # 如果 Data URI 格式无效，记录错误
                                errors.append(
                                    f"Invalid data URI for image: {image_data}")
                        else:
                            # 如果不是有效的 Data URI，记录错误 (目前不支持外部 URL)
                            errors.append(
                                f"Invalid image URL format for item: {item}")
                    else:
                        # 如果内容类型不受支持，记录错误
                        errors.append(f"Unsupported content type: {item.get('type')}")

                # 如果成功解析出 parts
                if parts:
                    # 映射角色
                    if role in ['user', 'system']:
                        role_to_use = 'user'
                    elif role == 'assistant':
                        role_to_use = 'model'
                    else:
                        errors.append(f"Invalid role: {role}")
                        continue
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
            # 注意：即使 system_instruction_text 为空，也返回结构
            return gemini_history, {"parts": [{"text": system_instruction_text}]}

    @staticmethod
    async def list_available_models(api_key) -> list:
        """
        静态方法，用于获取指定 API 密钥可用的 Gemini 模型列表。

        Args:
            api_key: 用于查询的 Gemini API 密钥。

        Returns:
            list: 可用模型名称的列表 (移除了 "models/" 前缀)。

        Raises:
            httpx.HTTPStatusError: 如果 API 请求失败。
        """
        # 构建获取模型列表的 URL
        url = "https://generativelanguage.googleapis.com/v1beta/models?key={}".format(
            api_key)
        # 使用 httpx 发送异步 GET 请求
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            # 如果响应状态码表示错误，则抛出异常
            response.raise_for_status()
            # 解析响应 JSON 数据
            data = response.json()
            # 提取模型名称，并移除 "models/" 前缀
            models = [model["name"].replace("models/", "") for model in data.get("models", [])]
            # 添加环境变量中指定的额外模型 (过滤空字符串)
            models.extend(m for m in GeminiClient.EXTRA_MODELS if m)
            return models
