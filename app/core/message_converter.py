# -*- coding: utf-8 -*-
"""
将 OpenAI 格式的消息列表转换为 Gemini API 格式的 'contents' 列表。
包括对文本和图像（Data URI）的处理。
"""
import re
import logging
from typing import List, Dict, Any, Tuple, Union, Set

# 尝试从父级 api.models 导入 Message，如果失败则尝试同级（以防结构变化）
try:
    from ..api.models import Message
except ImportError:
    from app.api.models import Message # Fallback if run directly or structure changes

logger = logging.getLogger('my_logger')

# 定义 Gemini 支持的图片 MIME 类型
SUPPORTED_IMAGE_MIME_TYPES: Set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

# 编译用于解析和验证 Data URI 的正则表达式
# 匹配 data:image/<mime>;base64,<data>
# <mime> 必须是 SUPPORTED_IMAGE_MIME_TYPES 中的一个
# 捕获组 1: mime_type, 捕获组 2: base64_data
DATA_URI_REGEX = re.compile(r"^data:(" + "|".join(re.escape(m) for m in SUPPORTED_IMAGE_MIME_TYPES) + r");base64,(.+)$")

def convert_messages(messages: List[Message], use_system_prompt=False) -> Union[Tuple[List[Dict[str, Any]], Dict[str, Any]], List[str]]:
    """
    将 OpenAI 格式的消息列表转换为 Gemini API 格式的 'contents' 列表和 system_instruction。

    Args:
        messages (List[Message]): OpenAI 格式的消息列表 (包含 role 和 content)。
        use_system_prompt (bool): 是否将第一个 'system' 角色的消息视为系统指令 (Gemini v1beta 支持)。

    Returns:
        Union[Tuple[List[Dict[str, Any]], Dict[str, Any]], List[str]]:
            - 成功: 返回包含转换后的 contents 列表和 system_instruction 字典的元组。
                    system_instruction 可能为空字典 {}。
            - 失败: 返回包含错误信息的字符串列表。
    """
    gemini_history: List[Dict[str, Any]] = []  # 存储转换后的 Gemini 消息历史
    errors: List[str] = []          # 存储转换过程中的错误信息
    system_instruction_text = ""  # 存储提取的系统指令文本
    is_system_phase = use_system_prompt  # 标记是否处于处理系统指令的阶段

    # 遍历输入的 OpenAI 消息列表
    for i, message in enumerate(messages):
        role = message.role      # 获取消息角色
        content = message.content  # 获取消息内容

        # 记录正在处理的消息（用于调试）
        logger.debug(f"正在处理消息 {i}: role={role}, content_type={type(content)}")

        # 处理纯文本内容
        if isinstance(content, str):
            # 如果启用了系统指令处理且当前角色是 'system'
            if is_system_phase and role == 'system':
                # 将系统消息内容累加到 system_instruction_text
                if system_instruction_text:
                    system_instruction_text += "\n" + content
                else:
                    system_instruction_text = content
                continue # 系统指令不加入 gemini_history
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
                    errors.append(f"消息 {i}: 无效的角色 '{role}'")
                    continue

                # 合并连续相同角色的消息
                if gemini_history and gemini_history[-1]['role'] == role_to_use:
                    # 确保 parts 是列表
                    if isinstance(gemini_history[-1].get('parts'), list):
                        gemini_history[-1]['parts'].append({"text": content})
                    else:
                        # 如果 parts 不是列表（理论上不应发生），则创建新的 parts 列表
                        gemini_history[-1]['parts'] = [{"text": content}]
                        logger.warning(f"消息 {i}: 发现非列表类型的 parts，已重新初始化。")
                else:
                    # 添加新的消息条目
                    gemini_history.append(
                        {"role": role_to_use, "parts": [{"text": content}]})

        # 处理包含多部分的内容（例如文本和图像）
        elif isinstance(content, list):
            # 遇到多部分内容时，退出系统指令处理阶段
            is_system_phase = False
            parts = []  # 存储转换后的 Gemini 'parts' 列表
            has_error_in_item = False # 标记当前多部分消息是否有错误

            # 遍历内容列表中的每个项目
            for item_index, item in enumerate(content):
                item_type = item.get('type')
                if item_type == 'text':
                    # 添加文本部分
                    parts.append({"text": item.get('text', '')}) # 使用 get 提供默认值
                elif item_type == 'image_url':
                    # 处理图像 URL
                    image_url_dict = item.get('image_url', {})
                    if not isinstance(image_url_dict, dict):
                         errors.append(f"消息 {i} 项目 {item_index}: 'image_url' 必须是字典，但得到 {type(image_url_dict)}")
                         has_error_in_item = True
                         continue # 跳过这个损坏的项目

                    image_data = image_url_dict.get('url', '')
                    # 使用正则表达式解析和验证 Data URI
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
                        error_msg = f"消息 {i} 项目 {item_index}: 无效或不支持的图像 Data URI。"
                        if image_data.startswith('data:image/'):
                             error_msg += f" MIME 类型必须是 {SUPPORTED_IMAGE_MIME_TYPES} 之一且格式正确。"
                        else:
                             error_msg += f" 仅接受 Base64 编码的 Data URI，支持的 MIME 类型为: {', '.join(SUPPORTED_IMAGE_MIME_TYPES)}。"
                        errors.append(error_msg)
                        has_error_in_item = True
                else:
                    # 如果内容类型不受支持，记录错误
                    errors.append(f"消息 {i} 项目 {item_index}: 不支持的内容类型 '{item_type}'")
                    has_error_in_item = True

            # 如果成功解析出 parts 且当前多部分消息没有错误
            if parts and not has_error_in_item:
                # 映射角色
                if role in ['user', 'system']:
                    role_to_use = 'user'
                elif role == 'assistant':
                    role_to_use = 'model'
                else:
                    errors.append(f"消息 {i}: 无效的角色 '{role}'")
                    continue # 跳过此消息

                # 合并连续相同角色的消息
                if gemini_history and gemini_history[-1]['role'] == role_to_use:
                     # 确保 parts 是列表
                    if isinstance(gemini_history[-1].get('parts'), list):
                        gemini_history[-1]['parts'].extend(parts)
                    else:
                        gemini_history[-1]['parts'] = parts
                        logger.warning(f"消息 {i}: 发现非列表类型的 parts，已重新初始化。")
                else:
                    # 添加新的消息条目
                    gemini_history.append(
                        {"role": role_to_use, "parts": parts})
            elif not parts and not has_error_in_item:
                 logger.warning(f"消息 {i}: 内容列表为空或所有项目均无效，已跳过。")
            # 如果有错误，错误信息已记录在 errors 列表中

        else:
            errors.append(f"消息 {i}: 不支持的内容类型 '{type(content)}'")


    # 如果转换过程中有错误，返回错误列表
    if errors:
        logger.error(f"消息转换失败: {'; '.join(errors)}")
        return errors
    else:
        # 准备 system_instruction 字典
        system_instruction_dict = {}
        if system_instruction_text:
            # Gemini 要求 system_instruction 是一个包含 'parts' 列表的字典
            system_instruction_dict = {"parts": [{"text": system_instruction_text}]}

        # 返回转换后的消息历史和系统指令
        return gemini_history, system_instruction_dict