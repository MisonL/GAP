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
    """
    if not isinstance(gemini_tool_calls, list):
        logger.warning(f"期望 gemini_tool_calls 是列表，但得到 {type(gemini_tool_calls)}")
        return None

    openai_tool_calls = [] # 初始化 OpenAI 格式工具调用列表
    # 遍历 Gemini 工具调用列表
    for i, call in enumerate(gemini_tool_calls):
        # 简化条件判断，逐步检查元素的格式和必要字段
        if not isinstance(call, dict):
            logger.warning(f"工具调用列表中的元素不是字典: {call}") # 记录警告
            continue # 跳过格式不正确的元素

        if 'name' not in call or not isinstance(call['name'], str) or not call['name']:
            logger.warning(f"工具调用元素缺少有效的 'name' 字段: {call}") # 记录警告
            continue # 跳过格式不正确的元素

        if 'args' not in call or not isinstance(call['args'], dict):
            logger.warning(f"工具调用元素缺少有效的 'args' 字段: {call}") # 记录警告
            continue # 跳过格式不正确的元素

        func_name = call['name'] # 获取函数名称
        func_args = call['args'] # 获取函数参数

        try:
            # OpenAI 需要 arguments 是 JSON 字符串
            arguments_str = json.dumps(func_args, ensure_ascii=False) # 将参数序列化为 JSON 字符串
        except TypeError as e:
            logger.error(f"序列化工具调用参数失败 (Name: {func_name}): {e}", exc_info=True) # 记录序列化失败错误
            continue # 跳过这个调用

        # 添加到 OpenAI 格式列表
        openai_tool_calls.append({
            "id": f"call_{int(time.time()*1000)}_{i}", # 生成唯一 ID
            "type": "function", # 类型为 function
            "function": {
                "name": func_name, # 函数名称
                "arguments": arguments_str, # 参数 JSON 字符串
            }
        })

    return openai_tool_calls if openai_tool_calls else None # 返回 OpenAI 格式列表或 None