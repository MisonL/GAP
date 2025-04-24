# -*- coding: utf-8 -*-
"""
将 OpenAI 格式的消息列表转换为 Gemini API 格式的 'contents' 列表。
包括对文本和图像（Data URI）的处理。
Converts a list of messages in OpenAI format to the 'contents' list in Gemini API format.
Includes handling for text and images (Data URI).
"""
import re # 导入 re 模块 (Import re module)
import logging # 导入 logging 模块 (Import logging module)
from typing import List, Dict, Any, Tuple, Union, Set # 导入类型提示 (Import type hints)

# 尝试从父级 api.models 导入 Message，如果失败则尝试同级（以防项目结构变化）
# Attempt to import Message from parent api.models, if failed, attempt from sibling (in case of project structure changes)
try:
    from ..api.models import Message # 尝试从父级导入 (Attempt to import from parent)
except ImportError:
    from app.api.models import Message # 如果直接运行此文件或项目结构更改，则回退导入路径 (Fallback import path if running this file directly or project structure changes)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# 定义 Gemini 支持的图片 MIME 类型
# Define supported image MIME types for Gemini
SUPPORTED_IMAGE_MIME_TYPES: Set[str] = { # 支持的图片 MIME 类型集合 (Set of supported image MIME types)
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

# 编译用于解析和验证 Data URI 的正则表达式
# Compile regular expression for parsing and validating Data URI
# 匹配 data:image/<mime>;base64,<data>
# Matches data:image/<mime>;base64,<data>
# <mime> 必须是 SUPPORTED_IMAGE_MIME_TYPES 中的一个
# <mime> must be one of SUPPORTED_IMAGE_MIME_TYPES
# 捕获组 1: mime_type, 捕获组 2: base64_data
# Capture group 1: mime_type, Capture group 2: base64_data
DATA_URI_REGEX = re.compile(r"^data:(" + "|".join(re.escape(m) for m in SUPPORTED_IMAGE_MIME_TYPES) + r");base64,(.+)$") # 编译 Data URI 正则表达式 (Compile Data URI regex)

def convert_messages(messages: List[Message], use_system_prompt=False) -> Union[Tuple[List[Dict[str, Any]], Dict[str, Any]], List[str]]:
    """
    将 OpenAI 格式的消息列表转换为 Gemini API 格式的 'contents' 列表和 system_instruction。
    Converts a list of messages in OpenAI format to the 'contents' list and system_instruction in Gemini API format.

    Args:
        messages (List[Message]): OpenAI 格式的消息列表 (包含 role 和 content)。List of messages in OpenAI format (containing role and content).
        use_system_prompt (bool): 是否将第一个 'system' 角色的消息视为系统指令 (Gemini v1beta 支持)。Whether to treat the first message with 'system' role as system instruction (supported by Gemini v1beta).

    Returns:
        Union[Tuple[List[Dict[str, Any]], Dict[str, Any]], List[str]]:
            - 成功: 返回包含转换后的 contents 列表和 system_instruction 字典的元组。
                    On success: Returns a tuple containing the converted contents list and system_instruction dictionary.
            - system_instruction 可能为空字典 {}。
                    system_instruction might be an empty dictionary {}.
            - 失败: 返回包含错误信息的字符串列表。
                    On failure: Returns a list of strings containing error messages.
    """
    gemini_history: List[Dict[str, Any]] = []  # 存储转换后的 Gemini 消息历史 (Stores the converted Gemini message history)
    errors: List[str] = []          # 存储转换过程中的错误信息 (Stores error messages during conversion)
    system_instruction_text = ""  # 存储提取的系统指令文本 (Stores the extracted system instruction text)
    is_system_phase = use_system_prompt  # 标记是否处于处理系统指令的阶段 (Flag indicating if currently processing system instructions)

    # 遍历输入的 OpenAI 消息列表
    # Iterate through the input OpenAI message list
    for i, message in enumerate(messages): # 遍历消息列表 (Iterate through message list)
        role = message.role      # 获取消息角色 (Get message role)
        content = message.content  # 获取消息内容 (Get message content)

        # 记录正在处理的消息（用于调试）
        # Log the message being processed (for debugging)
        logger.debug(f"正在处理消息 {i}: role={role}, content_type={type(content)}") # 记录处理消息信息 (Log message processing info)

        # 处理纯文本内容
        # Handle plain text content
        if isinstance(content, str): # 如果内容是字符串 (If content is a string)
            # 如果启用了系统指令处理且当前角色是 'system'
            # If system instruction handling is enabled and the current role is 'system'
            if is_system_phase and role == 'system': # 如果是系统指令阶段且角色是 system (If in system instruction phase and role is system)
                # 将系统消息内容累加到 system_instruction_text
                # Accumulate system message content to system_instruction_text
                if system_instruction_text: # 如果 system_instruction_text 不为空 (If system_instruction_text is not empty)
                    system_instruction_text += "\n" + content # 添加换行符和内容 (Add newline and content)
                else:
                    system_instruction_text = content # 直接赋值内容 (Assign content directly)
                continue # 系统指令不加入 gemini_history (System instructions are not added to gemini_history)
            else:
                # 一旦遇到非系统消息或未启用系统指令处理，则退出系统指令处理阶段
                # Once a non-system message is encountered or system instruction handling is not enabled, exit the system instruction processing phase
                is_system_phase = False # 退出系统指令阶段 (Exit system instruction phase)

                # 映射 OpenAI 角色到 Gemini 角色（'user' 或 'model'）
                # Map OpenAI roles to Gemini roles ('user' or 'model')
                if role in ['user', 'system']:  # 将 'system'（非首条）也视为 'user' (Treat 'system' (non-first) also as 'user')
                    role_to_use = 'user' # 使用 user 角色 (Use user role)
                elif role == 'assistant':
                    role_to_use = 'model' # 使用 model 角色 (Use model role)
                else:
                    # 如果角色无效，记录错误并跳过此消息
                    # If the role is invalid, log an error and skip this message
                    errors.append(f"消息 {i}: 无效的角色 '{role}'") # 添加错误信息 (Add error message)
                    continue # 跳过此消息 (Skip this message)

                # 合并连续相同角色的消息
                # Merge consecutive messages with the same role
                if gemini_history and gemini_history[-1]['role'] == role_to_use: # 如果历史记录不为空且最后一个消息角色相同 (If history is not empty and the last message has the same role)
                    # 确保 parts 是列表
                    # Ensure parts is a list
                    if isinstance(gemini_history[-1].get('parts'), list): # 如果 parts 是列表 (If parts is a list)
                        gemini_history[-1]['parts'].append({"text": content}) # 添加文本部分 (Append text part)
                    else:
                        # 如果 parts 不是列表（理论上不应发生），则创建新的 parts 列表
                        # If parts is not a list (should not happen in theory), create a new parts list
                        gemini_history[-1]['parts'] = [{"text": content}] # 创建新的 parts 列表 (Create new parts list)
                        logger.warning(f"消息 {i}: 发现非列表类型的 parts，已重新初始化。") # 记录警告 (Log warning)
                else:
                    # 添加新的消息条目
                    # Add a new message entry
                    gemini_history.append(
                        {"role": role_to_use, "parts": [{"text": content}]}) # 添加新的消息条目 (Append new message entry)

        # 处理包含多部分的内容（例如文本和图像）
        # Handle content containing multiple parts (e.g., text and images)
        elif isinstance(content, list): # 如果内容是列表 (If content is a list)
            # 遇到多部分内容时，退出系统指令处理阶段
            # When encountering multi-part content, exit the system instruction processing phase
            is_system_phase = False # 退出系统指令阶段 (Exit system instruction phase)
            parts = []  # 存储转换后的 Gemini 'parts' 列表 (Stores the converted Gemini 'parts' list)
            has_error_in_item = False # 标记当前多部分消息是否有错误 (Flag indicating if the current multi-part message has an error)

            # 遍历内容列表中的每个项目
            # Iterate through each item in the content list
            for item_index, item in enumerate(content): # 遍历内容列表 (Iterate through content list)
                item_type = item.get('type') # 获取项目类型 (Get item type)
                if item_type == 'text': # 如果项目类型是 text (If item type is text)
                    # 添加文本部分
                    # Add text part
                    parts.append({"text": item.get('text', '')}) # 使用 get 提供默认空字符串，防止 None (Use get to provide default empty string, preventing None) # 添加文本部分 (Append text part)
                elif item_type == 'image_url': # 如果项目类型是 image_url (If item type is image_url)
                    # 处理图像 URL
                    # Handle image URL
                    image_url_dict = item.get('image_url', {}) # 获取 image_url 字典 (Get image_url dictionary)
                    if not isinstance(image_url_dict, dict): # 如果 image_url 不是字典 (If image_url is not a dictionary)
                         errors.append(f"消息 {i} 项目 {item_index}: 'image_url' 必须是字典，但得到 {type(image_url_dict)}") # 添加错误信息 (Add error message)
                         has_error_in_item = True # 标记有错误 (Mark as having error)
                         continue # 跳过这个损坏的项目 (Skip this corrupted item)

                    image_data = image_url_dict.get('url', '') # 获取图像数据 URL (Get image data URL)
                    # 使用正则表达式解析和验证 Data URI
                    # Use regular expression to parse and validate Data URI
                    match = DATA_URI_REGEX.match(image_data) # 匹配 Data URI (Match Data URI)
                    if match: # 如果匹配成功 (If match is successful)
                        mime_type = match.group(1) # 获取 MIME 类型 (Get MIME type)
                        base64_data = match.group(2) # 获取 Base64 数据 (Get Base64 data)
                        # 添加内联图像数据部分
                        # Add inline image data part
                        parts.append({ # 添加内联图像数据部分 (Append inline image data part)
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_data
                            }
                        })
                    else:
                        # 如果 Data URI 格式无效或 MIME 类型不支持
                        # If Data URI format is invalid or MIME type is not supported
                        error_msg = f"消息 {i} 项目 {item_index}: 无效或不支持的图像 Data URI。" # 错误消息 (Error message)
                        if image_data.startswith('data:image/'): # 如果以 data:image/ 开头 (If starts with data:image/)
                             error_msg += f" MIME 类型必须是 {SUPPORTED_IMAGE_MIME_TYPES} 之一且格式正确。" # 添加 MIME 类型错误信息 (Add MIME type error message)
                        else:
                             error_msg += f" 仅接受 Base64 编码的 Data URI，支持的 MIME 类型为: {', '.join(SUPPORTED_IMAGE_MIME_TYPES)}。" # 添加 Data URI 格式错误信息 (Add Data URI format error message)
                        errors.append(error_msg) # 添加错误信息 (Add error message)
                        has_error_in_item = True # 标记有错误 (Mark as having error)
                else:
                    # 如果内容类型不受支持，记录错误
                    # If the content type is not supported, log an error
                    errors.append(f"消息 {i} 项目 {item_index}: 不支持的内容类型 '{item_type}'") # 添加错误信息 (Add error message)
                    has_error_in_item = True # 标记有错误 (Mark as having error)

            # 如果成功解析出 parts 且当前多部分消息没有错误
            # If parts are successfully parsed and the current multi-part message has no errors
            if parts and not has_error_in_item: # 如果有 parts 且没有错误 (If there are parts and no errors)
                # 映射角色
                # Map roles
                if role in ['user', 'system']: # 如果角色是 user 或 system (If role is user or system)
                    role_to_use = 'user' # 使用 user 角色 (Use user role)
                elif role == 'assistant': # 如果角色是 assistant (If role is assistant)
                    role_to_use = 'model' # 使用 model 角色 (Use model role)
                else:
                    errors.append(f"消息 {i}: 无效的角色 '{role}'") # 添加错误信息 (Add error message)
                    continue # 跳过此消息 (Skip this message)

                # 合并连续相同角色的消息
                # Merge consecutive messages with the same role
                if gemini_history and gemini_history[-1]['role'] == role_to_use: # 如果历史记录不为空且最后一个消息角色相同 (If history is not empty and the last message has the same role)
                     # 确保 parts 是列表
                    # Ensure parts is a list
                    if isinstance(gemini_history[-1].get('parts'), list): # 如果 parts 是列表 (If parts is a list)
                        gemini_history[-1]['parts'].extend(parts) # 扩展 parts 列表 (Extend parts list)
                    else:
                        gemini_history[-1]['parts'] = parts # 重新赋值 parts 列表 (Reassign parts list)
                        logger.warning(f"消息 {i}: 发现非列表类型的 parts，已重新初始化。") # 记录警告 (Log warning)
                else:
                    # 添加新的消息条目
                    # Add a new message entry
                    gemini_history.append(
                        {"role": role_to_use, "parts": parts}) # 添加新的消息条目 (Append new message entry)
            elif not parts and not has_error_in_item: # 如果没有 parts 且没有错误 (If there are no parts and no errors)
                 logger.warning(f"消息 {i}: 内容列表为空或所有项目均无效，已跳过。") # 记录警告 (Log warning)
            # 如果当前多部分消息有错误，错误信息已记录在 errors 列表中，无需额外操作
            # If the current multi-part message has errors, error messages are already logged in the errors list, no extra action needed

        else: # 如果内容类型不受支持 (If content type is not supported)
            errors.append(f"消息 {i}: 不支持的内容类型 '{type(content)}'") # 添加错误信息 (Add error message)


    # 如果转换过程中有错误，返回错误列表
    # If there are errors during conversion, return the list of errors
    if errors: # 如果有错误 (If there are errors)
        logger.error(f"消息转换失败: {'; '.join(errors)}") # 记录错误 (Log error)
        return errors # 返回错误列表 (Return list of errors)
    else:
        # 准备 system_instruction 字典
        # Prepare system_instruction dictionary
        system_instruction_dict = {} # 初始化 system_instruction 字典 (Initialize system_instruction dictionary)
        if system_instruction_text: # 如果有系统指令文本 (If there is system instruction text)
            # Gemini 要求 system_instruction 是一个包含 'parts' 列表的字典
            # Gemini requires system_instruction to be a dictionary containing a 'parts' list
            system_instruction_dict = {"parts": [{"text": system_instruction_text}]} # 构建 system_instruction 字典 (Build system_instruction dictionary)

        # 返回转换后的消息历史和系统指令
        # Return the converted message history and system instruction
        return gemini_history, system_instruction_dict # 返回转换结果 (Return conversion result)
