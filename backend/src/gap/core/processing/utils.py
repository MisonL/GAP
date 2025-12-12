# -*- coding: utf-8 -*-
"""
请求处理相关的工具函数，包括 Token 估算、上下文截断、速率限制检查和计数更新、上下文保存等。
"""
import json  # 导入 JSON 处理模块
import logging  # 导入日志模块
import time  # 导入时间模块
from collections import Counter, defaultdict  # 导入集合类型
from typing import Any, Dict, List, Optional, Tuple  # 导入类型提示

from sqlalchemy.ext.asyncio import AsyncSession  # 导入 AsyncSession 类型

# 导入配置
from gap import config as app_config  # 导入应用配置
from gap.core.context import store as context_store_module  # 导入上下文存储模块
from gap.core.context.store import ContextStore

# 导入核心模块
from gap.core.database import utils as db_utils  # 导入数据库工具模块

# 导入跟踪相关的数据结构和常量
from gap.core.tracking import TPM_WINDOW_SECONDS  # 使用数据、锁及时间窗口常量
from gap.core.tracking import ip_input_token_counts_lock  # IP 每日输入 Token 计数及锁
from gap.core.tracking import (
    RPM_WINDOW_SECONDS,
    ip_daily_input_token_counts,
    usage_data,
    usage_lock,
)

# 导入日志记录器
logger = logging.getLogger("my_logger")  # 获取日志记录器实例

# --- Token 估算与上下文截断 (来自 token_utils.py) ---


def estimate_token_count(contents: List[Dict[str, Any]]) -> int:
    """
    估算 Gemini contents 列表的 Token 数量。
    使用简单的字符数估算方法 (1 个 token 大约等于 4 个字符)。
    注意：这是一个非常粗略的估算，实际 Token 数可能因模型和内容而异。

    Args:
        contents (List[Dict[str, Any]]): Gemini 格式的内容列表。

    Returns:
        int: 估算的 Token 数量。
    """
    if not contents:  # 检查列表是否为空
        return 0  # 如果为空，返回 0
    try:
        # 计算 JSON 序列化后的字符数
        # ensure_ascii=False 确保中文字符等非 ASCII 字符按实际字符数计算，而不是转义序列
        char_count = len(
            json.dumps(contents, ensure_ascii=False)
        )  # 序列化为 JSON 字符串并获取长度
        # 使用 1 token ≈ 4 chars 的简化规则进行估算
        return char_count // 4  # 返回估算的 Token 数
    except TypeError as e:
        # 捕获并记录序列化过程中可能发生的类型错误
        logger.error(
            f"序列化 contents 进行 Token 估算时出错: {e}", exc_info=True
        )  # 记录错误日志
        return 0  # 如果序列化失败，返回 0


async def truncate_context(  # 改为 async 函数，因为内部可能调用 async 函数 (如 estimate_token_count 未来可能改为调用 API)
    contents: List[Dict[str, Any]],
    model_name: str,
    dynamic_max_tokens_limit: Optional[
        int
    ] = None,  # 新增可选参数，表示基于 Key 实时容量的动态限制
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    根据模型限制和可选的动态限制截断对话历史 (contents)。
    采用从开头成对移除消息（通常是 user/model 对）的策略，
    直到估算的 Token 数量满足限制要求。

    Args:
        contents (List[Dict[str, Any]]): 完整的对话历史列表 (Gemini 格式)。
        model_name (str): 当前请求使用的模型名称，用于查找其 Token 限制。
        dynamic_max_tokens_limit (Optional[int]): 可选的动态 Token 限制，
            通常基于 API Key 的实时可用容量。如果提供，将使用此限制与模型静态限制中的较小值。

    Returns:
        Tuple[List[Dict[str, Any]], bool]:
            - 第一个元素是截断后的对话历史列表。
            - 第二个元素是一个布尔值，指示截断后是否仍然超限
              (True 表示超限，False 表示未超限或无需截断)。
              如果返回 True，调用者通常不应保存此上下文，因为它可能仍然过长。
    """
    if not contents:  # 检查输入列表是否为空
        return [], False  # 如果为空，直接返回空列表和 False (未超限)

    # --- 确定最大 Token 限制 ---
    # 1. 获取配置中的默认值和安全边际
    # 使用 getattr 提供默认值，增加配置的灵活性
    default_max_tokens = getattr(
        app_config, "DEFAULT_MAX_CONTEXT_TOKENS", 30000
    )  # 获取默认最大上下文 Token 数，默认为 30000
    safety_margin = getattr(
        app_config, "CONTEXT_TOKEN_SAFETY_MARGIN", 200
    )  # 获取 Token 安全边际，默认为 200

    # 2. 获取模型的静态输入 Token 限制
    model_limits = getattr(app_config, "MODEL_LIMITS", {})  # 从配置加载模型限制字典
    limit_info = model_limits.get(model_name)  # 查找当前模型的限制信息
    static_max_tokens = default_max_tokens  # 默认使用全局默认值
    if (
        limit_info
        and isinstance(limit_info, dict)
        and limit_info.get("input_token_limit")
    ):  # 检查是否存在有效的模型特定限制
        try:
            limit_value = limit_info["input_token_limit"]  # 获取模型限制值
            if limit_value is not None:  # 确保值不是 JSON null
                static_max_tokens = int(limit_value)  # 转换为整数
            else:
                # 如果模型限制值为 null，记录警告并使用默认值
                logger.warning(
                    f"模型 '{model_name}' 的 input_token_limit 值为 null，使用默认值 {default_max_tokens}"
                )  # 记录警告：模型限制值为 null
        except (ValueError, TypeError):
            # 如果模型限制值无效（无法转换为整数），记录警告并使用默认值
            logger.warning(
                f"模型 '{model_name}' 的 input_token_limit 值无效 ('{limit_info.get('input_token_limit')}')，使用默认值 {default_max_tokens}"
            )  # 记录警告：模型限制值无效
    else:
        # 如果模型或其限制未定义，记录警告并使用默认值
        logger.warning(
            f"模型 '{model_name}' 或其 input_token_limit 未在 model_limits.json 中定义，使用默认值 {default_max_tokens}"
        )  # 记录警告：模型限制未定义

    # 3. 结合动态限制确定最终使用的最大 Token 限制
    actual_max_tokens = static_max_tokens  # 默认使用模型的静态限制
    if (
        dynamic_max_tokens_limit is not None and dynamic_max_tokens_limit >= 0
    ):  # 如果提供了有效的动态限制（非 None 且非负）
        # 取静态限制和动态限制中的较小者作为实际限制
        actual_max_tokens = min(static_max_tokens, dynamic_max_tokens_limit)
        # 记录日志，说明使用了哪个限制
        logger.debug(
            f"使用动态限制 {dynamic_max_tokens_limit} 和静态限制 {static_max_tokens}，最终最大 Token 限制为 {actual_max_tokens}"
        )  # 记录使用的限制值

    # 4. 计算截断阈值（实际限制减去安全边际）
    # 确保阈值不小于 0
    truncation_threshold = max(
        0, actual_max_tokens - safety_margin
    )  # 计算最终的截断目标 Token 数

    # --- 执行截断 ---
    # 估算当前内容的 Token 数量
    estimated_tokens = estimate_token_count(contents)  # 调用 Token 估算函数

    # 判断是否需要截断
    if estimated_tokens > truncation_threshold:  # 如果估算 Token 数超过了阈值
        logger.info(
            f"上下文估算 Token ({estimated_tokens}) 超出阈值 ({truncation_threshold} for model {model_name}, actual max tokens {actual_max_tokens})，开始截断..."
        )  # 记录开始截断的日志
        # 创建内容的副本进行操作，避免修改原始列表
        truncated_contents = list(contents)  # 复制列表
        # 循环移除消息对，直到满足 Token 限制或无法再移除
        while (
            estimate_token_count(truncated_contents) > truncation_threshold
            and len(truncated_contents) >= 2
        ):
            # 从列表开头移除两个元素（假设是 user/model 对）
            removed_first = truncated_contents.pop(0)  # 移除第一个元素 (通常是 user)
            removed_second = truncated_contents.pop(0)  # 移除第二个元素 (通常是 model)
            # 记录被移除的消息的角色，用于调试
            logger.debug(
                f"移除旧消息对: roles={removed_first.get('role')}, {removed_second.get('role')}"
            )  # 记录移除的消息角色

        # 重新估算截断后的 Token 数量
        final_estimated_tokens = estimate_token_count(
            truncated_contents
        )  # 估算最终 Token 数

        # 检查截断后是否仍然超限
        if final_estimated_tokens > truncation_threshold:  # 如果截断后仍然超过阈值
            # 这种情况可能发生在即使只剩下一条消息，其 Token 数也超过阈值
            logger.error(
                f"截断后上下文估算 Token ({final_estimated_tokens}) 仍然超过阈值 ({truncation_threshold})。本次交互的上下文不应被保存。"
            )  # 记录错误：截断后仍超限
            # 返回截断后的内容，并标记为超限 (True)
            return truncated_contents, True
        else:
            # 截断成功，且最终 Token 数在阈值内
            logger.info(
                f"上下文截断完成，剩余消息数: {len(truncated_contents)}, 最终估算 Token: {final_estimated_tokens}"
            )  # 记录截断成功信息
            # 返回截断后的内容，并标记为未超限 (False)
            return truncated_contents, False
    else:
        # 如果原始 Token 数未超过阈值，无需截断
        return contents, False  # 返回原始内容，并标记为未超限 (False)


# --- 速率限制检查与计数更新 (来自 rate_limit_utils.py) ---


def check_rate_limits_and_update_counts(
    api_key: str, model_name: str, limits: Optional[Dict[str, Any]]
) -> bool:
    """
    检查给定 API Key 和模型的速率限制 (RPD, TPD_Input, RPM, TPM_Input)。
    此函数在选择 Key *之前* 调用，用于预检查 Key 是否已达到已知限制。
    如果未达到限制，则更新 RPM 和 RPD 计数（假设本次请求会发生），并返回 True。
    如果达到任何限制，则记录警告并返回 False，表示不应选择此 Key。

    Args:
        api_key (str): 当前尝试使用的 API Key。
        model_name (str): 请求的模型名称。
        limits (Optional[Dict[str, Any]]): 从配置中获取的该模型的限制字典。

    Returns:
        bool: 如果根据已知计数判断可以继续进行 API 调用则返回 True，否则返回 False。
    """
    if not limits:  # 检查是否有该模型的限制配置
        logger.warning(
            f"模型 '{model_name}' 不在 model_limits.json 中，跳过本地速率限制检查。"
        )  # 记录警告：模型不在限制配置中
        return True  # 没有限制信息，默认允许调用

    now = time.time()  # 获取当前时间戳，用于 RPM 和 TPM 检查
    perform_api_call = True  # 初始化标志：假设可以执行 API 调用

    with usage_lock:  # 获取使用数据锁，保证对共享数据 usage_data 的访问是线程安全的
        # 使用 setdefault 确保 key 和 model 的条目存在于 usage_data 中，避免 KeyError
        # 如果键不存在，会使用 defaultdict 的默认工厂（这里是另一个 defaultdict）创建新条目
        key_usage = usage_data.setdefault(
            api_key, defaultdict(lambda: defaultdict(int))
        )[
            model_name
        ]  # 获取或创建 Key 和模型的用法数据字典

        # --- 检查并更新 RPM (每分钟请求数) ---
        rpm_limit = limits.get("rpm")  # 从模型限制中获取 RPM 限制值
        if rpm_limit is not None:  # 如果配置了 RPM 限制
            current_rpm_count = key_usage.get(
                "rpm_count", 0
            )  # 获取当前 RPM 计数，默认为 0
            rpm_timestamp = key_usage.get(
                "rpm_timestamp", 0
            )  # 获取上次 RPM 窗口开始时间戳，默认为 0

            if (
                now - rpm_timestamp >= RPM_WINDOW_SECONDS
            ):  # 检查当前时间是否已经超过了 RPM 窗口时长
                # RPM 窗口已过期，重置计数并将当前请求计为 1
                key_usage["rpm_count"] = 1  # 新窗口的第一个请求
                key_usage["rpm_timestamp"] = now  # 更新窗口开始时间戳为当前时间
                logger.debug(
                    f"RPM 窗口过期，重置计数并增加 (Key: {api_key[:8]}, Model: {model_name}): 新 RPM=1"
                )  # 记录 RPM 窗口过期和重置
            else:
                # RPM 窗口未过期，检查加上当前这个预期的请求是否会超限
                if current_rpm_count + 1 > rpm_limit:  # 如果当前计数加 1 超过限制
                    logger.warning(
                        f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPM 达到限制 ({current_rpm_count}/{rpm_limit})。跳过此 Key。"
                    )  # 记录 RPM 超限警告
                    perform_api_call = False  # 设置标志为 False，表示不能选择此 Key
                else:
                    # 未达到限制，预先增加计数（假设此 Key 会被选中并使用）
                    key_usage["rpm_count"] = current_rpm_count + 1  # RPM 计数加 1
                    # 时间戳保持不变，因为仍在当前窗口内
                    logger.debug(
                        f"RPM 计数增加 (Key: {api_key[:8]}, Model: {model_name}): 新 RPM={key_usage['rpm_count']}"
                    )  # 记录 RPM 计数增加

        # --- 检查并更新 RPD (每日请求数) ---
        # 仅在之前的检查（RPM）通过时才进行 RPD 检查
        if perform_api_call:
            rpd_limit = limits.get("rpd")  # 获取 RPD 限制值
            if rpd_limit is not None:  # 如果配置了 RPD 限制
                current_rpd_count = key_usage.get(
                    "rpd_count", 0
                )  # 获取当前 RPD 计数，默认为 0
                # RPD 是每日计数，不需要时间窗口检查，直接判断是否超限
                if current_rpd_count + 1 > rpd_limit:  # 如果当前计数加 1 超过限制
                    logger.warning(
                        f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): RPD 达到限制 ({current_rpd_count}/{rpd_limit})。跳过此 Key。"
                    )  # 记录 RPD 超限警告
                    perform_api_call = False  # 设置标志为 False
                else:
                    # 未达到限制，预先增加计数
                    key_usage["rpd_count"] = current_rpd_count + 1  # RPD 计数加 1
                    logger.debug(
                        f"RPD 计数增加 (Key: {api_key[:8]}, Model: {model_name}): 新 RPD={key_usage['rpd_count']}"
                    )  # 记录 RPD 计数增加

        # --- 检查 TPD_Input (每日输入 Token 数) ---
        # 仅检查，不在此处增加计数，因为此时还不知道实际的输入 Token 数。
        # 计数更新在 API 调用成功后的 update_token_counts 函数中进行。
        if perform_api_call:
            tpd_input_limit = limits.get("tpd_input")  # 获取 TPD_Input 限制值
            if (
                tpd_input_limit is not None
                and key_usage.get("tpd_input_count", 0) >= tpd_input_limit
            ):  # 如果设置了限制且当前计数已达到或超过限制
                logger.warning(
                    f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPD_Input 达到限制 ({key_usage.get('tpd_input_count', 0)}/{tpd_input_limit})。跳过此 Key。"
                )  # 记录 TPD_Input 超限警告
                perform_api_call = False  # 设置标志为 False

        # --- 检查 TPM_Input (每分钟输入 Token 数) ---
        # 同样仅检查，不在此处增加计数。
        if perform_api_call:
            tpm_input_limit = limits.get("tpm_input")  # 获取 TPM_Input 限制值
            if tpm_input_limit is not None:  # 如果设置了 TPM_Input 限制
                # 检查是否仍在当前 TPM 窗口内
                if now - key_usage.get("tpm_input_timestamp", 0) < TPM_WINDOW_SECONDS:
                    # 如果在窗口内，检查当前 Token 计数是否已达到或超过限制
                    if key_usage.get("tpm_input_count", 0) >= tpm_input_limit:
                        logger.warning(
                            f"速率限制预检查失败 (Key: {api_key[:8]}, Model: {model_name}): TPM_Input 达到限制 ({key_usage.get('tpm_input_count', 0)}/{tpm_input_limit})。跳过此 Key。"
                        )  # 记录 TPM_Input 超限警告
                        perform_api_call = False  # 设置标志为 False
                # 注意：这里没有 else 块来在窗口过期时重置 TPM_Input 计数/时间戳，
                # 因为 update_token_counts 函数会处理 TPM_Input 的重置和增加。

        # 如果所有检查都通过，更新此 Key 的最后请求时间戳（用于 Key 选择策略）
        if perform_api_call:
            key_usage["last_request_timestamp"] = now  # 更新最后请求时间戳

    return perform_api_call  # 返回最终的检查结果


def update_token_counts(
    api_key: str,
    model_name: str,
    limits: Optional[Dict[str, Any]],
    prompt_tokens: Optional[int],
    client_ip: str,
    today_date_str_pt: str,
) -> None:
    """
    在 API 调用成功 *之后* 更新给定 API Key 和模型的 TPD_Input 和 TPM_Input 计数。
    同时记录基于 IP 的每日输入 Token 消耗。

    Args:
        api_key (str): 当前成功使用的 API Key。
        model_name (str): 请求的模型名称。
        limits (Optional[Dict[str, Any]]): 从配置中获取的该模型的限制字典。
        prompt_tokens (Optional[int]): 从 API 响应中获取的实际输入 Token 数量。
        client_ip (str): 客户端 IP 地址。
        today_date_str_pt (str): 当前的太平洋时区日期字符串 (YYYY-MM-DD)，用于 IP 每日计数。
    """
    # 检查输入有效性：需要有效的限制信息和大于 0 的 prompt_tokens
    if not limits or not prompt_tokens or prompt_tokens <= 0:
        if limits and (
            not prompt_tokens or prompt_tokens <= 0
        ):  # 如果有限制但 prompt_tokens 无效
            logger.warning(
                f"Token 计数更新跳过 (Key: {api_key[:8]}, Model: {model_name}): 无效的 prompt_tokens ({prompt_tokens})。"
            )  # 记录警告：无效的 prompt_tokens
        # 如果没有限制信息或 prompt_tokens 无效，则不执行更新
        return  # 直接返回

    with usage_lock:  # 获取使用数据锁，保证线程安全
        # 确保 key 和 model 的条目存在
        key_usage = usage_data.setdefault(
            api_key, defaultdict(lambda: defaultdict(int))
        )[
            model_name
        ]  # 获取或创建 Key 和模型的用法数据字典

        # --- 更新 TPD_Input (每日输入 Token 数) ---
        # 直接累加本次请求的 prompt_tokens
        key_usage["tpd_input_count"] = (
            key_usage.get("tpd_input_count", 0) + prompt_tokens
        )  # 累加 TPD_Input 计数

        # --- 更新 TPM_Input (每分钟输入 Token 数) ---
        tpm_input_limit = limits.get("tpm_input")  # 获取 TPM_Input 限制值
        if tpm_input_limit is not None:  # 只有在配置了 TPM 限制时才更新
            now_tpm = time.time()  # 获取当前时间戳
            # 检查 TPM 窗口是否已过期
            if now_tpm - key_usage.get("tpm_input_timestamp", 0) >= TPM_WINDOW_SECONDS:
                # 窗口已过期，重置计数为当前请求的 Token 数，并更新时间戳
                key_usage["tpm_input_count"] = (
                    prompt_tokens  # 新窗口的第一个请求的 Token 数
                )
                key_usage["tpm_input_timestamp"] = now_tpm  # 更新窗口开始时间戳
            else:
                # 窗口未过期，累加 Token 数
                key_usage["tpm_input_count"] = (
                    key_usage.get("tpm_input_count", 0) + prompt_tokens
                )  # 累加 TPM_Input 计数
            # 记录详细的 Token 更新日志
            logger.debug(
                f"输入 Token 计数更新 (Key: {api_key[:8]}, Model: {model_name}): Added TPD_Input={prompt_tokens}, TPM_Input={key_usage['tpm_input_count']}"
            )  # 记录 Token 计数更新详情

    # --- 记录 IP 输入 Token 消耗 (独立于 Key 的限制) ---
    # 使用单独的锁来保护 IP 计数数据
    with ip_input_token_counts_lock:  # 获取 IP 输入 token 计数锁
        # 使用 setdefault 确保日期条目存在，并使用 Counter 方便地增加 IP 计数
        # 结构: { 'YYYY-MM-DD': Counter({'ip1': count1, 'ip2': count2}) }
        ip_daily_input_token_counts.setdefault(today_date_str_pt, Counter())[
            client_ip
        ] += prompt_tokens  # 增加指定 IP 在当天的输入 Token 计数


# --- 上下文保存逻辑 (来自 utils.py 原始版本) ---
async def save_context_after_success(
    proxy_key: str,
    contents_to_send: List[Dict[str, Any]],
    model_reply_content: str,
    model_name: str,
    enable_context: bool,
    final_tool_calls: Optional[List[Dict[str, Any]]] = None,
    db: AsyncSession | None = None,
    context_store: Optional[ContextStore] = None,
):
    """
    在 API 调用成功后保存上下文（如果启用）。

    Args:
        proxy_key (str): 用于存储上下文的键 (通常是 user_id)。
        contents_to_send (List[Dict[str, Any]]): 发送给模型的最终内容列表 (包含历史)。
        model_reply_content (str): 模型返回的文本回复。
        model_name (str): 使用的模型名称。
        enable_context (bool): 是否启用上下文保存功能。
        final_tool_calls (Optional[List[Dict[str, Any]]]): 模型返回的工具调用信息（目前暂未处理）。
    """
    if not enable_context:  # 如果未启用上下文保存
        logger.debug(
            f"Key {proxy_key[:8]}... 的上下文补全已禁用，跳过上下文保存。"
        )  # 记录跳过信息
        return  # 直接返回

    # 记录准备保存上下文的日志，并指明当前的数据库模式
    logger.debug(
        f"准备为 Key '{proxy_key[:8]}...' 保存上下文 (内存模式: {db_utils.IS_MEMORY_DB})"
    )  # 记录准备保存日志

    # 构造模型的回复部分，格式应符合 Gemini contents 结构
    model_reply_part = {"role": "model", "parts": [{"text": model_reply_content}]}
    if final_tool_calls:  # 如果存在工具调用信息
        # TODO: 处理工具调用的上下文保存。
        # Gemini API 的工具调用响应格式与 OpenAI 不同，通常包含 functionCall 和 functionResponse。
        # 需要确定如何将这些信息整合到对话历史中以便后续使用。
        # 目前仅记录警告，表示暂未处理。
        logger.warning(
            "上下文保存：暂未处理工具调用 (tool_calls) 的保存。"
        )  # 记录警告：未处理工具调用
        pass  # 暂时忽略工具调用

    # 将模型的回复追加到发送给模型的内容之后，形成完整的对话历史用于保存
    final_contents_to_save = contents_to_send + [
        model_reply_part
    ]  # 组合最终要保存的内容

    # --- 对最终要保存的内容进行截断 ---
    # 保存上下文时，通常只使用模型的静态限制进行截断，
    # 因为保存的目的是维护历史记录，而不是适配某个 Key 的实时容量。
    # 注意：这里调用了 truncate_context 函数，它会根据 model_name 查找静态限制。
    # 第二个返回参数 still_over_limit_final 指示即使截断后是否仍然超限。
    truncated_contents_to_save, still_over_limit_final = await truncate_context(
        final_contents_to_save, model_name
    )  # 对最终内容进行截断

    if not still_over_limit_final:  # 如果截断后内容没有超限
        if db is None and (context_store is None or context_store.storage_mode == "database"):
            logger.warning(
                f"保存上下文时未提供数据库会话 (Key: {proxy_key[:8]}...)，已跳过保存。"
            )
            return
        try:
            # 优先使用 ContextStore 实例，以统一 memory/database 行为
            if context_store is not None:
                if context_store.storage_mode == "memory":
                    await context_store.store_context(
                        user_id=proxy_key,
                        context_key=proxy_key,
                        context_value=truncated_contents_to_save,
                        ttl_seconds=None,
                        db=None,
                    )
                else:
                    await context_store.store_context(
                        user_id=proxy_key,
                        context_key=proxy_key,
                        context_value=truncated_contents_to_save,
                        ttl_seconds=None,
                        db=db,
                    )
            else:
                # 回退到旧的直接保存到数据库的路径
                if db is None:
                    logger.warning(
                        f"保存上下文时未提供数据库会话且未配置 ContextStore (Key: {proxy_key[:8]}...)，已跳过保存。"
                    )
                    return
                await context_store_module.save_context(
                    proxy_key, truncated_contents_to_save, db=db
                )
            logger.info(
                f"上下文保存成功 for Key {proxy_key[:8]}..."
            )  # 记录保存成功日志
        except Exception as e:
            # 捕获并记录保存过程中可能发生的任何异常
            logger.error(
                f"保存上下文失败 (Key: {proxy_key[:8]}...): {str(e)}", exc_info=True
            )  # 记录保存失败错误
    else:
        # 如果截断后仍然超限，记录错误，不进行保存
        logger.error(
            f"上下文在添加回复并再次截断后仍然超限 (Key: {proxy_key[:8]}...). 上下文未保存。"
        )  # 记录错误：截断后仍超限


# --- 工具调用处理 (来自 tool_call_utils.py) ---
def process_tool_calls(gemini_tool_calls: Any) -> Optional[List[Dict[str, Any]]]:
    """
    将 Gemini 返回的 functionCall 列表转换为 OpenAI 兼容的 tool_calls 格式。
    Gemini: [{'functionCall': {'name': 'func_name', 'args': {...}}}]
    OpenAI: [{'id': 'call_...', 'type': 'function', 'function': {'name': 'func_name', 'arguments': '{...}'}}]
    """
    if not isinstance(gemini_tool_calls, list):  # 检查输入是否为列表
        logger.warning(
            f"期望 gemini_tool_calls 是列表，但得到 {type(gemini_tool_calls)}"
        )  # 记录警告
        return None  # 返回 None

    openai_tool_calls = []  # 初始化 OpenAI 格式工具调用列表
    # 遍历 Gemini 工具调用列表
    for i, call in enumerate(gemini_tool_calls):
        # 简化条件判断，逐步检查元素的格式和必要字段
        if not isinstance(call, dict):  # 检查元素是否为字典
            logger.warning(f"工具调用列表中的元素不是字典: {call}")  # 记录警告
            continue  # 跳过格式不正确的元素

        # 检查 'functionCall' 键是否存在且其值是字典
        function_call_data = call.get("functionCall")
        if not isinstance(function_call_data, dict):
            logger.warning(
                f"工具调用元素缺少有效的 'functionCall' 字典: {call}"
            )  # 记录警告
            continue  # 跳过格式不正确的元素

        # 检查 'name' 字段是否存在且有效
        func_name = function_call_data.get("name")
        if not isinstance(func_name, str) or not func_name:
            logger.warning(f"工具调用元素缺少有效的 'name' 字段: {call}")  # 记录警告
            continue  # 跳过格式不正确的元素

        # 检查 'args' 字段是否存在且是字典
        func_args = function_call_data.get("args")
        if not isinstance(func_args, dict):
            logger.warning(f"工具调用元素缺少有效的 'args' 字典: {call}")  # 记录警告
            continue  # 跳过格式不正确的元素

        try:
            # OpenAI 需要 arguments 是 JSON 字符串
            arguments_str = json.dumps(
                func_args, ensure_ascii=False
            )  # 将参数序列化为 JSON 字符串
        except TypeError as e:
            logger.error(
                f"序列化工具调用参数失败 (Name: {func_name}): {e}", exc_info=True
            )  # 记录序列化失败错误
            continue  # 跳过这个调用

        # 添加到 OpenAI 格式列表
        openai_tool_calls.append(
            {
                "id": f"call_{int(time.time()*1000)}_{i}",  # 生成唯一 ID (基于时间戳和索引)
                "type": "function",  # 类型固定为 function
                "function": {
                    "name": func_name,  # 函数名称
                    "arguments": arguments_str,  # 参数 JSON 字符串
                },
            }
        )

    return (
        openai_tool_calls if openai_tool_calls else None
    )  # 返回 OpenAI 格式列表或 None
