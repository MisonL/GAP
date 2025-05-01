# app/api/token_utils.py
"""
Token 估算与上下文截断相关的辅助函数。
"""
import json # 导入 json 模块
import logging # 导入 logging 模块
from typing import Tuple, List, Dict, Any # 导入类型提示

# 导入配置以获取默认值和模型限制
# 注意：这里需要将相对导入改为绝对导入
from app import config as app_config # 导入 app_config 模块

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- Token 估算与上下文截断 ---

def estimate_token_count(contents: List[Dict[str, Any]]) -> int:
    """
    估算 Gemini contents 列表的 Token 数量。
    使用简单的字符数估算方法 (1 个 token 大约等于 4 个字符)。
    """
    if not contents:
        return 0
    try:
        # 计算 JSON 序列化后的字符数 (ensure_ascii=False 保证中文字符正确计数)
        char_count = len(json.dumps(contents, ensure_ascii=False)) # 序列化并获取字符数
        # 除以 4 作为 Token 估算值
        return char_count // 4 # 返回估算 Token 数
    except TypeError as e:
        logger.error(f"序列化 contents 进行 Token 估算时出错: {e}", exc_info=True) # 记录序列化错误
        return 0 # 如果序列化失败则返回 0

def truncate_context(
    contents: List[Dict[str, Any]],
    model_name: str
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    根据模型限制截断对话历史 (contents)。
    从开头成对移除消息，直到满足 Token 限制。
    从开头成对移除消息，直到满足 Token 限制。

    Args:
        contents: 完整的对话历史列表 (Gemini 格式)。
        model_name: 当前请求使用的模型名称。

    Returns:
        元组[List[Dict[str, Any]], bool]:
            - 截断后的对话历史列表。
            - 一个布尔值，指示截断后是否仍然超限（True 表示超限，False 表示未超限或无需截断）。
              如果为 True，调用者不应保存此上下文。
    """
    if not contents: # 如果内容为空
        return [], False # 返回空列表和 False

    # 从配置中获取默认最大上下文 Token 数和安全边际
    # 使用 getattr 安全地访问配置项，避免因配置项不存在而报错
    default_max_tokens = getattr(app_config, 'DEFAULT_MAX_CONTEXT_TOKENS', 30000) # 默认上下文 Token 上限
    safety_margin = getattr(app_config, 'CONTEXT_TOKEN_SAFETY_MARGIN', 200) # Token 安全边际

    # 1. 获取模型的输入 Token 限制 (input_token_limit)
    # model_limits 应该从 config 模块加载，确保它在应用启动时已加载
    model_limits = getattr(app_config, 'MODEL_LIMITS', {}) # 获取已加载的模型限制字典
    limit_info = model_limits.get(model_name) # 获取特定模型的限制信息
    max_tokens = default_max_tokens # 初始化最大 Token 数为默认值
    if limit_info and isinstance(limit_info, dict) and limit_info.get("input_token_limit"): # 如果找到限制信息且包含 input_token_limit
        try:
            limit_value = limit_info["input_token_limit"] # 获取限制值
            if limit_value is not None: # 确保值不是 None (JSON 中的 null)
                 max_tokens = int(limit_value) # 将限制值转换为整数
            else:
                 logger.warning(f"模型 '{model_name}' 的 input_token_limit 值为 null，使用默认值 {default_max_tokens}") # 模型 input_token_limit 值为 null
        except (ValueError, TypeError):
             logger.warning(f"模型 '{model_name}' 的 input_token_limit 值无效 ('{limit_info.get('input_token_limit')}')，使用默认值 {default_max_tokens}") # 模型 input_token_limit 值无效
    else:
        logger.warning(f"模型 '{model_name}' 或其 input_token_limit 未在 model_limits.json 中定义，使用默认值 {default_max_tokens}") # 模型或 input_token_limit 未在 model_limits.json 中定义

    truncation_threshold = max(0, max_tokens - safety_margin) # 计算截断阈值，确保不为负数

    # 2. 估算当前上下文的 Token 数量
    estimated_tokens = estimate_token_count(contents) # 估算 Token 数量

    # 3. 判断是否需要截断
    if estimated_tokens > truncation_threshold: # 如果估算 Token 数超过阈值
        logger.info(f"上下文估算 Token ({estimated_tokens}) 超出阈值 ({truncation_threshold} for model {model_name})，开始截断...") # 上下文估算 Token 超出阈值，开始截断
        # 创建上下文列表的副本进行修改，避免影响原始列表
        truncated_contents = list(contents) # 创建副本
        # 循环截断，直到 Token 数量满足阈值或无法再截断
        while estimate_token_count(truncated_contents) > truncation_threshold: # 当估算 Token 数仍超过阈值时
            # 检查是否至少有两条消息可以成对移除
            if len(truncated_contents) >= 2: # 如果消息数大于等于 2
                # 从列表开头移除两个元素 (通常是 user 和 model 的消息对)
                removed_first = truncated_contents.pop(0) # 移除第一个元素
                removed_second = truncated_contents.pop(0) # 移除第二个元素
                logger.debug(f"移除旧消息对: roles={removed_first.get('role')}, {removed_second.get('role')}") # 移除旧消息对
            elif len(truncated_contents) == 1: # 如果只剩下一条消息
                # 只剩下一条消息，但仍然超过 Token 限制
                logger.warning("截断过程中只剩一条消息，但其 Token 数量仍然超过阈值。") # 截断过程中只剩一条消息，但其 Token 数量仍然超过阈值
                break # 停止循环，将在下面检查最终状态
            else: # truncated_contents 列表已为空
                break # 无法再截断，跳出循环

        final_estimated_tokens = estimate_token_count(truncated_contents) # 估算截断后的最终 Token 数

        # 检查截断后的最终 Token 数量
        if final_estimated_tokens > truncation_threshold: # 如果最终 Token 数仍然超限
             # 即使经过截断（可能只剩下一条消息），最终 Token 数量仍然超过阈值
             logger.error(f"截断后上下文估算 Token ({final_estimated_tokens}) 仍然超过阈值 ({truncation_threshold})。本次交互的上下文不应被保存。") # 截断后上下文仍然超限
             # 返回截断后的结果，并标记为超限状态
             return truncated_contents, True # 返回截断后的内容和 True
        else:
            logger.info(f"上下文截断完成，剩余消息数: {len(truncated_contents)}, 最终估算 Token: {final_estimated_tokens}") # 上下文截断完成
            return truncated_contents, False # 截断成功，并且最终 Token 未超限
    else:
        return contents, False # 返回原始列表，标记为未超限