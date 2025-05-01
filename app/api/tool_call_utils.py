# app/api/tool_call_utils.py
"""
工具调用处理相关的辅助函数。
"""
import json # 导入 json 模块
import logging # 导入 logging 模块
import time # 导入 time 模块
from typing import List, Dict, Any, Optional # 导入类型提示

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 辅助函数 (例如处理工具调用) ---

def process_tool_calls(gemini_tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
    """
    将 Gemini 返回的 functionCall 列表转换为 OpenAI 兼容的 tool_calls 格式。
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    将 Gemini 返回的 functionCall 列表转换为 OpenAI 兼容的 tool_calls 格式。
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    """
    if not isinstance(gemini_tool_calls, list):
        logger.warning(f"期望 gemini_tool_calls 是列表，但得到 {type(gemini_tool_calls)}")
        return None

    openai_tool_calls = [] # 初始化 OpenAI 格式工具调用列表
    for i, call in enumerate(gemini_tool_calls): # 遍历 Gemini 工具调用列表
        if not isinstance(call, dict): # 如果元素不是字典
             logger.warning(f"工具调用列表中的元素不是字典: {call}") # 工具调用列表中的元素不是字典
             continue # 跳过

        func_call = call # Gemini 直接返回 functionCall 字典

        if not isinstance(func_call, dict): # 如果 functionCall 不是字典
             logger.warning(f"functionCall 元素不是字典: {func_call}") # functionCall 元素不是字典
             continue # 跳过

        func_name = func_call.get('name') # 获取函数名称
        func_args = func_call.get('args') # 获取函数参数

        if not func_name or not isinstance(func_args, dict): # 如果缺少名称或参数不是字典
            logger.warning(f"functionCall 缺少 name 或 args 不是字典: {func_call}") # functionCall 缺少 name 或 args 不是字典
            continue # 跳过

        try:
            # OpenAI 需要 arguments 是 JSON 字符串
            arguments_str = json.dumps(func_args, ensure_ascii=False) # 将参数序列化为 JSON 字符串
        except TypeError as e:
            logger.error(f"序列化工具调用参数失败 (Name: {func_name}): {e}", exc_info=True) # 序列化工具调用参数失败
            continue # 跳过这个调用

        openai_tool_calls.append({ # 添加到 OpenAI 格式列表
            "id": f"call_{int(time.time()*1000)}_{i}", # 生成唯一 ID
            "type": "function", # 类型为 function
            "function": {
                "name": func_name, # 函数名称
                "arguments": arguments_str, # 参数 JSON 字符串
            }
        })

    return openai_tool_calls if openai_tool_calls else None # 返回 OpenAI 格式列表或 None