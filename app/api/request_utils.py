# -*- coding: utf-8 -*-
"""
API 请求处理相关的辅助函数。
"""
import pytz # 导入 pytz 模块
import json # 导入 json 模块
import logging # 导入 logging 模块
import time # 导入 time 模块
from datetime import datetime # 导入 datetime
from collections import Counter # 导入 Counter
from collections import defaultdict # 导入 defaultdict
from typing import Tuple, List, Dict, Any, Optional # 导入类型提示
from fastapi import Request # 导入 Request
# 导入配置以获取默认值和模型限制
from app import config as app_config # 导入 app_config 模块
from app.core.tracking import ip_daily_input_token_counts, ip_input_token_counts_lock # 导入 IP 每日输入 token 计数和锁
from app.core.tracking import usage_data, usage_lock, RPM_WINDOW_SECONDS, TPM_WINDOW_SECONDS # 导入使用数据、锁、RPM/TPM 窗口

# 从 token_utils 导入 token 相关的辅助函数
from app.api.token_utils import estimate_token_count, truncate_context # 导入 Token 辅助函数
# 从 tool_call_utils 导入工具调用处理函数
from app.api.tool_call_utils import process_tool_calls # 导入工具调用处理函数

logger = logging.getLogger('my_logger') # 获取日志记录器实例

def get_client_ip(request: Request) -> str:
    """
    从 FastAPI Request 对象中获取客户端 IP 地址。
    优先使用 X-Forwarded-For Header。
    """
    x_forwarded_for = request.headers.get("x-forwarded-for") # 获取 X-Forwarded-For Header
    if x_forwarded_for: # 如果存在 X-Forwarded-For
        # X-Forwarded-For 可能包含多个 IP，取第一个
        client_ip = x_forwarded_for.split(',')[0].strip() # 分割并获取第一个 IP
    else:
        # 回退到 request.client.host
        client_ip = request.client.host if request.client else "unknown_ip" # 获取客户端主机 IP # 如果 client 不存在，则为 "unknown_ip"
    return client_ip # 返回客户端 IP

def get_current_timestamps() -> Tuple[str, str]:
    """
    获取当前的 CST 时间字符串和 PT 日期字符串。

                         例如 ('2024-01-01 10:00:00 CST', '2023-12-31')
    """
    cst_tz = pytz.timezone('Asia/Shanghai') # 设置时区为亚洲/上海
    cst_now = datetime.now(cst_tz) # 获取当前 CST 时间
    cst_time_str = cst_now.strftime('%Y-%m-%d %H:%M:%S %Z') # 格式化 CST 时间字符串

    pt_tz = pytz.timezone('America/Los_Angeles') # 设置时区为美国/洛杉矶
    today_date_str_pt = datetime.now(pt_tz).strftime('%Y-%m-%d') # 格式化 PT 日期字符串

    return cst_time_str, today_date_str_pt # 返回时间戳元组
