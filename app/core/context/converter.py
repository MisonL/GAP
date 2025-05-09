# -*- coding: utf-8 -*-
"""
消息格式转换器。
主要负责将 OpenAI API 格式的消息列表转换为 Gemini API 兼容的 'contents' 列表格式。
支持处理文本内容、图像内容 (通过 Base64 编码的 Data URI)，以及可选的系统指令提取。
"""
import re # 导入正则表达式模块，用于解析 Data URI
import logging # 导入日志模块
from typing import List, Dict, Any, Tuple, Union, Set # 导入类型提示

# 导入 Message Pydantic 模型，用于类型检查和访问消息属性
from app.api.models import Message # (新路径)

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# 定义 Gemini API 支持的图像 MIME 类型集合
SUPPORTED_IMAGE_MIME_TYPES: Set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

# 编译用于解析和验证图像 Data URI 的正则表达式
# 模式: data:<MIME 类型>;base64,<Base64 编码的数据>
# - `data:`: 固定前缀
# - `(` + `|`.join(...) + `)`: 捕获组 1，匹配 SUPPORTED_IMAGE_MIME_TYPES 中的任意一个
#   - `re.escape(m)`: 转义 MIME 类型字符串中的特殊字符
# - `;base64,`: 固定分隔符
# - `(.+)`: 捕获组 2，匹配 Base64 编码的数据部分 (至少一个字符)
DATA_URI_REGEX = re.compile(r"^data:(" + "|".join(re.escape(m) for m in SUPPORTED_IMAGE_MIME_TYPES) + r");base64,(.+)$")

def _process_text_content(
    content: str, # 纯文本内容
    role: str, # OpenAI 格式的角色 ('system', 'user', 'assistant')
    gemini_history: List[Dict[str, Any]], # 正在构建的 Gemini contents 列表
    is_system_phase: bool, # 当前是否正在处理系统指令阶段
    system_instruction_text: str, # 已累积的系统指令文本
    errors: List[str] # 用于收集错误的列表
) -> Tuple[bool, str]:
    """
    (内部辅助函数) 处理纯文本类型的消息内容。
    - 如果处于系统指令处理阶段且角色为 'system'，则累加文本到系统指令。
    - 否则，将文本内容添加到 Gemini contents 列表中，处理角色映射和消息合并。

    Args:
        content (str): 消息的文本内容。
        role (str): 消息的角色。
        gemini_history (List[Dict[str, Any]]): 当前已转换的 Gemini contents 列表。
        is_system_phase (bool): 是否处于系统指令处理阶段。
        system_instruction_text (str): 当前累积的系统指令文本。
        errors (List[str]): 用于记录错误的列表。

    Returns:
        Tuple[bool, str]:
            - 第一个元素 (bool): 更新后的 is_system_phase 状态。
            - 第二个元素 (str): 更新后的 system_instruction_text。
    """
    if is_system_phase and role == 'system': # 如果在系统指令阶段且角色是 system
        # 将当前系统消息内容追加到已有的系统指令文本后面
        if system_instruction_text: # 如果已有系统指令
            system_instruction_text += "\n" + content # 用换行符分隔追加
        else: # 如果是第一条系统指令
            system_instruction_text = content # 直接赋值
        return True, system_instruction_text # 保持在系统指令阶段，返回更新后的文本
    else: # 如果不是系统指令阶段，或者角色不是 system
        # 遇到非系统消息或非 system 角色的消息，则退出系统指令处理阶段
        is_system_phase = False

        # --- 映射 OpenAI 角色到 Gemini 角色 ---
        # Gemini API 只接受 'user' 和 'model' 两种角色
        if role in ['user', 'system']:  # 将 'system' (如果不是第一条) 也视为 'user'
            role_to_use = 'user'
        elif role == 'assistant': # OpenAI 的 'assistant' 对应 Gemini 的 'model'
            role_to_use = 'model'
        else: # 如果遇到无法识别的角色
            # 记录错误并跳过此消息
            errors.append(f"无效的角色 '{role}'") # 添加错误信息
            # 返回非系统指令阶段，系统指令文本不变
            return False, system_instruction_text

        # --- 合并连续相同角色的消息 ---
        # Gemini API 要求 'user' 和 'model' 角色交替出现
        # 如果当前消息的角色与 gemini_history 中最后一条消息的角色相同
        if gemini_history and gemini_history[-1]['role'] == role_to_use:
            # 将当前文本内容追加到上一条消息的 'parts' 列表中
            # 首先确保上一条消息的 'parts' 是一个列表
            if isinstance(gemini_history[-1].get('parts'), list):
                gemini_history[-1]['parts'].append({"text": content}) # 追加新的 text part
            else:
                # 如果 parts 不是列表（异常情况），则创建一个新的 parts 列表
                gemini_history[-1]['parts'] = [{"text": content}]
                logger.warning(f"发现非列表类型的 parts，已重新初始化。") # 记录警告
        else: # 如果角色不同，或者 gemini_history 为空
            # 添加一个新的消息条目到 gemini_history
            gemini_history.append(
                {"role": role_to_use, "parts": [{"text": content}]} # 创建新的 content 字典
            )

        # 返回非系统指令阶段，系统指令文本不变
        return False, system_instruction_text

def _process_multi_part_content(
    content: List[Dict[str, Any]], # OpenAI 格式的多部分内容列表
    role: str, # OpenAI 格式的角色
    gemini_history: List[Dict[str, Any]], # 正在构建的 Gemini contents 列表
    errors: List[str], # 用于收集错误的列表
    message_index: int # 当前消息在原始列表中的索引 (用于错误报告)
) -> bool:
    """
    (内部辅助函数) 处理包含多部分内容（例如文本和图像）的 OpenAI 消息。
    将 OpenAI 的多部分 content 列表转换为 Gemini 的 parts 列表。
    支持 text 和 image_url (Data URI 格式) 类型。
    处理角色映射和消息合并。

    Args:
        content (List[Dict[str, Any]]): OpenAI 格式的多部分内容列表。
        role (str): 消息的角色。
        gemini_history (List[Dict[str, Any]]): 当前已转换的 Gemini contents 列表。
        errors (List[str]): 用于记录错误的列表。
        message_index (int): 当前消息的索引，用于生成更清晰的错误信息。

    Returns:
        bool: 如果处理过程中发生错误，返回 True；否则返回 False。
    """
    parts = []  # 初始化用于存储转换后的 Gemini 'parts' 的列表
    has_error_in_item = False # 标记当前消息的 content 列表处理中是否出现错误

    # 遍历 OpenAI content 列表中的每个部分 (item)
    for item_index, item in enumerate(content):
        item_type = item.get('type') # 获取部分的类型 ('text' 或 'image_url')

        # --- 特殊处理：兼容某些客户端可能发送的无类型文本部分 ---
        # 检查 item 是否为字典，是否包含 'text' 键，且值是字符串，并且没有 'type' 键
        if item_type is None and isinstance(item, dict) and 'text' in item and isinstance(item.get('text'), str):
            logger.debug(f"消息 {message_index} 项目 {item_index}: 检测到无类型的文本部分，直接处理。") # 记录调试信息
            parts.append({"text": item['text']}) # 直接添加文本 part
            continue # 处理下一个项目
        # --- 特殊处理结束 ---

        if item_type == 'text': # --- 处理文本部分 ---
            # 直接添加 text part，使用 get 获取文本内容，提供默认空字符串以防万一
            parts.append({"text": item.get('text', '')})
        elif item_type == 'image_url': # --- 处理图像 URL 部分 ---
            # 获取 image_url 字典
            image_url_dict = item.get('image_url', {})
            # 验证 image_url 是否为字典
            if not isinstance(image_url_dict, dict):
                 errors.append(f"消息 {message_index} 项目 {item_index}: 'image_url' 必须是字典，但得到 {type(image_url_dict)}") # 记录错误
                 has_error_in_item = True # 标记错误
                 continue # 跳过这个损坏的项目

            image_data = image_url_dict.get('url', '') # 获取图像的 URL (期望是 Data URI)
            # 使用预编译的正则表达式解析和验证 Data URI
            match = DATA_URI_REGEX.match(image_data)
            if match: # 如果 Data URI 格式有效且 MIME 类型受支持
                mime_type = match.group(1) # 提取 MIME 类型
                base64_data = match.group(2) # 提取 Base64 编码的数据
                # 创建 Gemini 的 inline_data part
                parts.append({
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64_data # Base64 数据字符串
                    }
                })
            else: # 如果 Data URI 格式无效或 MIME 类型不支持
                # 构造详细的错误消息
                error_msg = f"消息 {message_index} 项目 {item_index}: 无效或不支持的图像 Data URI。"
                if image_data.startswith('data:image/'): # 如果是图像 Data URI 但格式或类型错误
                     error_msg += f" MIME 类型必须是 {SUPPORTED_IMAGE_MIME_TYPES} 之一且格式正确。"
                else: # 如果根本不是 Data URI
                     error_msg += f" 仅接受 Base64 编码的 Data URI，支持的 MIME 类型为: {', '.join(SUPPORTED_IMAGE_MIME_TYPES)}。"
                errors.append(error_msg) # 添加错误信息到列表
                has_error_in_item = True # 标记错误
        else: # --- 处理不支持的内容类型 ---
            # 如果 item 的 type 不是 'text' 或 'image_url'
            errors.append(f"消息 {message_index} 项目 {item_index}: 不支持的内容类型 '{item_type}'") # 记录错误
            has_error_in_item = True # 标记错误

    # --- 处理转换后的 parts ---
    # 只有在成功解析出 parts 并且当前消息没有发生错误时才进行后续处理
    if parts and not has_error_in_item:
        # --- 合并多个文本 parts ---
        # Gemini API 可能对单个 content 中的多个 text part 处理不佳，尝试合并它们
        text_parts = [p['text'] for p in parts if 'text' in p and len(p) == 1] # 提取所有纯文本 part 的内容
        non_text_parts = [p for p in parts if 'text' not in p or len(p) > 1] # 保留所有非文本 part (如图像)

        if len(text_parts) > 1: # 如果存在多个文本 part
            merged_text = "\n".join(text_parts) # 使用换行符将它们合并成一个字符串
            logger.debug(f"消息 {message_index}: 检测到 {len(text_parts)} 个文本 parts，合并为一个。") # 记录合并操作
            # 构建新的 parts 列表：合并后的文本在前，非文本部分在后
            merged_parts = [{"text": merged_text}] + non_text_parts
            parts = merged_parts # 使用合并后的 parts 列表
        # --- 合并结束 ---

        # --- 映射角色 ---
        if role in ['user', 'system']: # OpenAI 'user'/'system' -> Gemini 'user'
            role_to_use = 'user'
        elif role == 'assistant': # OpenAI 'assistant' -> Gemini 'model'
            role_to_use = 'model'
        else: # 无效角色
            errors.append(f"消息 {message_index}: 无效的角色 '{role}'") # 记录错误
            return True # 返回 True 表示此消息处理出错

        # --- 合并连续相同角色的消息 ---
        if gemini_history and gemini_history[-1]['role'] == role_to_use: # 如果历史不为空且最后一条消息角色相同
            # 将当前消息的 parts 追加到上一条消息的 parts 列表中
            if isinstance(gemini_history[-1].get('parts'), list): # 确保上一条的 parts 是列表
                gemini_history[-1]['parts'].extend(parts) # 追加 parts
            else: # 处理异常情况
                gemini_history[-1]['parts'] = parts # 直接替换为新的 parts
                logger.warning(f"消息 {message_index}: 发现非列表类型的 parts，已重新初始化。") # 记录警告
        else: # 如果角色不同或历史为空
            # 添加新的消息条目到 gemini_history
            gemini_history.append(
                {"role": role_to_use, "parts": parts} # 创建新的 content 字典
            )
        return False # 返回 False 表示此消息处理成功
    elif not parts and not has_error_in_item: # 如果 parts 为空但没有错误 (例如，内容列表为空或所有项都无效但被跳过)
         logger.warning(f"消息 {message_index}: 内容列表为空或所有项目均无效，已跳过。") # 记录警告
         return False # 返回 False 表示此消息未产生错误（虽然也没添加内容）
    else: # 如果 has_error_in_item 为 True
        # 错误信息已记录在 errors 列表中，直接返回 True 表示此消息处理出错
        return True

def convert_messages(messages: List[Message], use_system_prompt=False) -> Union[Tuple[List[Dict[str, Any]], Dict[str, Any]], List[str]]:
    """
    将 OpenAI 格式的消息列表转换为 Gemini API 格式的 'contents' 列表和 system_instruction。

    处理逻辑：
    1. 遍历 OpenAI 消息列表。
    2. 如果 `use_system_prompt` 为 True，将第一个 'system' 角色的消息内容提取为系统指令。
    3. 处理后续消息：
       - 映射角色 ('user'/'system' -> 'user', 'assistant' -> 'model')。
       - 处理文本内容。
       - 处理多部分内容（文本和图像 Data URI）。
       - 合并连续相同角色的消息。
    4. 如果在转换过程中遇到任何错误，返回包含错误信息的列表。
    5. 如果转换成功，返回包含 Gemini 'contents' 列表和 'system_instruction' 字典的元组。

    Args:
        messages (List[Message]): OpenAI 格式的消息列表 (Pydantic 模型对象列表)。
        use_system_prompt (bool): 是否启用系统指令提取功能。默认为 False。

    Returns:
        Union[Tuple[List[Dict[str, Any]], Dict[str, Any]], List[str]]:
            - 成功时: 返回一个元组 `(gemini_history, system_instruction_dict)`。
              `gemini_history` 是转换后的 Gemini contents 列表。
              `system_instruction_dict` 是包含系统指令的字典 (如果提取到)，否则为空字典。
            - 失败时: 返回一个包含描述性错误信息的字符串列表。
    """
    gemini_history: List[Dict[str, Any]] = []  # 初始化 Gemini contents 列表
    errors: List[str] = []          # 初始化错误信息列表
    system_instruction_text = ""  # 初始化系统指令文本
    is_system_phase = use_system_prompt  # 根据参数设置初始是否处于系统指令处理阶段

    # 遍历输入的 OpenAI 消息列表
    for i, message in enumerate(messages):
        role = message.role # 获取角色
        content = message.content # 获取内容

        # 记录正在处理的消息（用于调试）
        logger.debug(f"正在处理消息 {i}: role={role}, content_type={type(content)}") # 记录调试日志

        # --- 根据内容类型调用不同的处理函数 ---
        if isinstance(content, str): # 如果内容是纯字符串
            # 调用处理纯文本内容的辅助函数
            is_system_phase, system_instruction_text = _process_text_content(
                content, role, gemini_history, is_system_phase, system_instruction_text, errors
            )
        elif isinstance(content, list): # 如果内容是列表 (表示多部分内容)
            # 遇到多部分内容时，强制退出系统指令处理阶段
            is_system_phase = False
            # 调用处理多部分内容的辅助函数
            has_error = _process_multi_part_content(
                content, role, gemini_history, errors, i
            )
            # 如果处理多部分内容时发生错误，跳过当前消息，继续处理下一条
            if has_error:
                continue
        else: # 如果内容类型既不是字符串也不是列表
            # 记录不支持的内容类型错误
            errors.append(f"消息 {i}: 不支持的内容类型 '{type(content)}'")


    # --- 处理转换结果 ---
    if errors: # 如果在转换过程中收集到了错误
        logger.error(f"消息转换失败: {'; '.join(errors)}") # 记录整体转换失败的错误日志
        return errors # 返回错误信息列表
    else: # 如果没有错误
        # 准备 system_instruction 字典
        system_instruction_dict = {} # 初始化为空字典
        if system_instruction_text: # 如果成功提取到了系统指令文本
            # Gemini API 要求 system_instruction 是一个包含 'parts' 列表的字典
            system_instruction_dict = {"parts": [{"text": system_instruction_text}]}

        # 返回转换成功的 Gemini contents 列表和 system_instruction 字典
        return gemini_history, system_instruction_dict
