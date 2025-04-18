# -*- coding: utf-8 -*-
"""
处理 Web UI 相关的路由，例如状态页面和未来的管理界面。
"""
import logging
# import pytz # 已移除，不再需要
from datetime import datetime, timezone # 导入时区
# from collections import Counter # 已移除，不再需要
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status, Response # Keep Response
# 导入 Response, Request, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse # Keep existing imports
from fastapi.templating import Jinja2Templates
# 导入安全类型和新依赖项
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # 虽然 verify_jwt_token 在 auth.py，但类型提示可能需要
from typing import Optional, Annotated, Dict, Any # Annotated 用于表单依赖, Dict, Any 用于 JWT

import uuid # 用于生成新的 Key
from pydantic import BaseModel, Field # 用于 API 请求体验证
# 相对导入
from .. import config # 导入根配置
from ..config import (
    PROTECT_STATUS_PAGE,
    PASSWORD,
    # ... (其他可能需要的配置)
    __version__,
    # Import config values directly needed by render_status_page
    REPORT_LOG_LEVEL_STR,
    USAGE_REPORT_INTERVAL_MINUTES,
    DISABLE_SAFETY_FILTERING,
    MAX_REQUESTS_PER_MINUTE,
    MAX_REQUESTS_PER_DAY_PER_IP
)
# from ..core.utils import key_manager_instance as key_manager # 移除，如果不再需要 Key Manager
# Import the specific count variable from key_management
# from ..core.key_management import INVALID_KEY_COUNT_AT_STARTUP # 移除，如果不再需要
# from ..core.tracking import ( # 移除，如果不再需要
#     daily_rpd_totals, daily_totals_lock,
#     ip_daily_counts, ip_counts_lock,
#     ip_daily_input_token_counts, ip_input_token_counts_lock
# )
# 导入上下文存储
from ..core import context_store
from ..core import db_utils # 导入数据库工具函数和 IS_MEMORY_DB
# 导入新的安全和认证模块
from ..core.security import create_access_token
from .auth import verify_jwt_token # 导入新的 JWT 验证依赖
# CSRF 保护相关导入已移除


logger = logging.getLogger('my_logger')
router = APIRouter(tags=["Web UI"]) # 添加标签

# 设置模板目录
templates = Jinja2Templates(directory="app/web/templates")

# --- 旧的 Session 认证依赖 (已移除) ---
# async def require_login(request: Request): ... (代码已删除)

# --- 根路径 (现在是登录页面) ---
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_get(request: Request): # Removed CsrfProtect dependency
    """显示状态页面或登录表单"""
    # user_session = request.session.get("user", {}) # 安全地获取 session (Session 已移除)
    # is_authenticated = user_session.get("authenticated", False) # (Session 已移除)
    login_required = bool(PASSWORD) # 检查是否全局设置了密码
    # show_details = not PROTECT_STATUS_PAGE or is_authenticated # (Session 已移除)
    # 假设存在 login.html 模板用于显示登录表单

    # --- CSRF code removed ---
    # csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "login_required": login_required,
            # "csrf_token": csrf_token # Removed CSRF token
        }
    )
    # --- CSRF code removed ---
    # csrf_protect.set_csrf_cookie(signed_token, response)

    return response

# --- 旧的 POST / 路由 (已移除) ---
# @router.post("/", ...) ... (代码已删除)

# --- 旧的 render_status_page 辅助函数 (已移除) ---
# async def render_status_page(...): ... (代码已删除)

# --- 新的登录处理路由 ---
@router.post("/login", include_in_schema=False)
async def login_for_access_token(
    request: Request, # 添加 request 参数用于 CSRF 验证
    password: str = Form(...)
    # csrf_protect: CsrfProtect = Depends() # Removed CsrfProtect dependency
):
    """处理 Web UI 登录请求，验证密码并返回 JWT"""
    # --- CSRF validation removed ---
    # try:
    #     await csrf_protect.validate_csrf(request)
    # except CsrfProtectException as e:
    #     logger.warning(f"CSRF validation failed during login: {e.message}")
    #     raise HTTPException(status_code=e.status_code, detail=e.message)
    # --- CSRF validation removed ---

    if not PASSWORD:
        logger.error("尝试登录，但 Web UI 密码 (PASSWORD) 未设置。")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Web UI 登录未启用 (密码未设置)",
        )

    if password == PASSWORD:
        # 密码正确，创建 JWT
        # 注意：JWT payload 可以包含任何你需要的信息，这里只放一个简单的标识
        # 在实际应用中，可能会包含 user_id, role 等
        access_token_data = {"sub": "web_ui_user"} # 'sub' (subject) 是 JWT 标准字段
        try:
            access_token = create_access_token(data=access_token_data)
            logger.info("Web UI 登录成功，已签发 JWT。")
            return JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
        except ValueError as e: # 捕获 create_access_token 中 SECRET_KEY 未设置的错误
             logger.error(f"无法创建 JWT: {e}")
             raise HTTPException(
                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                 detail="无法生成认证令牌 (内部错误)",
             )
        except Exception as e: # 捕获其他可能的 JWT 创建错误
             logger.error(f"创建 JWT 时发生未知错误: {e}", exc_info=True)
             raise HTTPException(
                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                 detail="生成认证令牌时出错",
             )
    else:
        # 密码错误
        logger.warning("Web UI 登录失败：密码错误。")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码错误",
            headers={"WWW-Authenticate": "Bearer"}, # 虽然这里不是直接用 Bearer，但登录失败返回 401 是惯例
        )


# --- 管理界面路由 ---

@router.get("/manage", include_in_schema=False)
async def manage_redirect():
    """管理首页重定向到上下文管理"""
    return RedirectResponse(url="/manage/context", status_code=status.HTTP_303_SEE_OTHER)

# --- 代理 Key 管理 (已移除) ---
# @router.get("/manage/keys", ...) ... (代码已删除)
# @router.post("/manage/keys/add", ...) ... (代码已删除)
# @router.post("/manage/keys/toggle/{key}", ...) ... (代码已删除)
# @router.post("/manage/keys/delete/{key}", ...) ... (代码已删除)


# --- 代理 Key 管理 (已移除) ---
# @router.get("/manage/keys", ...) ... (代码已删除)
# @router.post("/manage/keys/add", ...) ... (代码已删除)
# @router.post("/manage/keys/toggle/{key}", ...) ... (代码已删除)
# @router.post("/manage/keys/delete/{key}", ...) ... (代码已删除)


# --- Pydantic Models for Key Management API ---

class AddKeyRequest(BaseModel):
    description: Optional[str] = Field(None, description="新 Key 的描述 (可选)") # 改为可选

class UpdateKeyRequest(BaseModel):
    description: Optional[str] = Field(None, description="新的描述 (可选)")
    is_active: Optional[bool] = Field(None, description="新的激活状态 (可选)")


# --- 代理 Key 管理 (仅文件模式) ---

# 辅助函数检查是否为文件模式，如果不是则抛出 404
async def require_file_db_mode():
    if db_utils.IS_MEMORY_DB:
        logger.debug("尝试访问 Key 管理功能，但当前为内存数据库模式。")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="代理 Key 管理仅在文件数据库模式下可用 (需设置 CONTEXT_DB_PATH)。"
        )

# 渲染 Key 管理页面的路由
@router.get(
    "/manage/keys",
    response_class=HTMLResponse,
    include_in_schema=False,
    # dependencies=[Depends(require_file_db_mode)] # Dependency removed
)
async def manage_keys_page(request: Request):
    """显示代理 Key 管理页面的 HTML 骨架，或在内存模式下显示提示信息。"""
    is_memory_mode = db_utils.IS_MEMORY_DB
    if is_memory_mode:
        logger.debug("渲染 Key 管理页面骨架 (内存模式提示)")
        return templates.TemplateResponse(
            "manage_keys.html",
            # Add 'now' to the context
            {"request": request, "is_memory_mode": True, "now": datetime.now(timezone.utc)}
        )
    else:
        logger.debug("渲染 Key 管理页面骨架 (文件模式)")
        # 页面骨架，实际数据通过 API 获取
        return templates.TemplateResponse(
            "manage_keys.html",
            # Add 'now' to the context
            {"request": request, "is_memory_mode": False, "now": datetime.now(timezone.utc)}
        )

# 获取 Key 数据的 API 端点
@router.get(
    "/api/manage/keys/data",
    dependencies=[Depends(verify_jwt_token), Depends(require_file_db_mode)] # 添加 JWT 和文件模式检查
)
async def get_manage_keys_data(token_payload: Dict[str, Any] = Depends(verify_jwt_token)):
    """获取代理 Key 管理页面所需的数据。"""
    logger.debug(f"用户 {token_payload.get('sub')} 请求 Key 管理数据")
    try:
        keys_data = db_utils.get_all_proxy_keys()
        # 转换 Row 对象为字典列表，并格式化日期
        result = []
        for row in keys_data:
            key_info = dict(row) # 将 sqlite3.Row 转换为字典
            # 确保 created_at 存在且是 datetime 对象或可解析的 ISO 字符串
            created_at_val = key_info.get('created_at')
            if isinstance(created_at_val, datetime):
                 key_info['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(created_at_val, str):
                 try:
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00')) # 处理 Z 时区
                     key_info['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError:
                     logger.warning(f"无法解析 Key {key_info.get('key')} 的 created_at 字符串: {created_at_val}")
                     # 保持原样或设为 None/空字符串
                     key_info['created_at'] = created_at_val # 保持原样

            result.append(key_info)

        return {"keys": result}
    except Exception as e:
        logger.error(f"获取 Key 管理数据时出错: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取 Key 数据失败")

# 添加新 Key 的 API 端点
@router.post(
    "/api/manage/keys/add",
    status_code=status.HTTP_201_CREATED, # Use 201 for successful creation
    dependencies=[Depends(verify_jwt_token), Depends(require_file_db_mode)] # 添加 JWT 和文件模式检查
)
async def add_new_key(
    key_data: AddKeyRequest, # 使用 Pydantic 模型接收数据
    token_payload: Dict[str, Any] = Depends(verify_jwt_token)
):
    """添加一个新的代理 Key (自动生成 UUID)。"""
    logger.debug(f"用户 {token_payload.get('sub')} 请求添加新 Key")
    new_key = str(uuid.uuid4())
    description = key_data.description # Pydantic 会处理 None

    success = db_utils.add_proxy_key(key=new_key, description=description)

    if success:
        logger.info(f"成功添加新 Key: {new_key[:8]}... (描述: {description})")
        # 返回新创建的 Key 信息可能更有用
        new_key_info = db_utils.get_proxy_key(new_key)
        if new_key_info:
             key_dict = dict(new_key_info)
             created_at_val = key_dict.get('created_at')
             if isinstance(created_at_val, datetime):
                 key_dict['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S')
             elif isinstance(created_at_val, str):
                 try:
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00'))
                     key_dict['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError: pass # 保持原样
             return {"message": "Key 添加成功", "key": key_dict}
        else:
             # 理论上不应发生，但作为回退
             logger.error(f"添加 Key {new_key[:8]}... 成功，但无法立即检索其信息。")
             return {"message": "Key 添加成功，但无法检索信息", "key_id": new_key}
    else:
        logger.error(f"添加新 Key 失败 (Key: {new_key[:8]}...)")
        # add_proxy_key 内部已记录 Key 可能重复的警告
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="添加 Key 失败")

# 更新 Key 的 API 端点
@router.put( # 使用 PUT 方法更新资源更符合 RESTful 风格
    "/api/manage/keys/update/{proxy_key}",
    dependencies=[Depends(verify_jwt_token), Depends(require_file_db_mode)] # 添加 JWT 和文件模式检查
)
async def update_existing_key(
    proxy_key: str,
    update_data: UpdateKeyRequest, # 使用 Pydantic 模型接收数据
    token_payload: Dict[str, Any] = Depends(verify_jwt_token)
):
    """更新指定代理 Key 的描述或状态。"""
    logger.debug(f"用户 {token_payload.get('sub')} 请求更新 Key: {proxy_key[:8]}...")

    if update_data.description is None and update_data.is_active is None:
         logger.warning(f"更新 Key {proxy_key[:8]}... 的请求未提供任何更新字段。")
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须提供 description 或 is_active 进行更新")

    success = db_utils.update_proxy_key(
        key=proxy_key,
        description=update_data.description,
        is_active=update_data.is_active
    )

    if success:
        logger.info(f"成功更新 Key: {proxy_key[:8]}...")
        updated_key_info = db_utils.get_proxy_key(proxy_key)
        if updated_key_info:
             key_dict = dict(updated_key_info)
             created_at_val = key_dict.get('created_at')
             if isinstance(created_at_val, datetime):
                 key_dict['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S')
             elif isinstance(created_at_val, str):
                 try:
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00'))
                     key_dict['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError: pass # 保持原样
             return {"message": "Key 更新成功", "key": key_dict}
        else:
             logger.warning(f"更新 Key {proxy_key[:8]}... 成功，但无法检索更新后的信息 (可能已被并发删除?)")
             return {"message": "Key 更新成功，但无法检索更新后的信息"}
    else:
        # update_proxy_key 内部已记录 Key 未找到或未改变的警告
        # 检查 Key 是否存在，以返回更具体的错误
        existing_key = db_utils.get_proxy_key(proxy_key)
        if not existing_key:
            logger.warning(f"尝试更新不存在的 Key: {proxy_key[:8]}...")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key '{proxy_key}' 不存在")
        else:
            logger.error(f"更新 Key {proxy_key[:8]}... 失败 (数据库错误或其他原因)")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新 Key 失败")


# 删除 Key 的 API 端点
@router.delete( # 使用 DELETE 方法删除资源
    "/api/manage/keys/delete/{proxy_key}",
    status_code=status.HTTP_204_NO_CONTENT, # 204 表示成功处理，无内容返回
    dependencies=[Depends(verify_jwt_token), Depends(require_file_db_mode)] # 添加 JWT 和文件模式检查
)
async def delete_existing_key(
    proxy_key: str,
    token_payload: Dict[str, Any] = Depends(verify_jwt_token)
):
    """删除指定的代理 Key (及其关联的上下文)。"""
    logger.debug(f"用户 {token_payload.get('sub')} 请求删除 Key: {proxy_key[:8]}...")

    success = db_utils.delete_proxy_key(key=proxy_key)

    if success:
        logger.info(f"成功删除 Key: {proxy_key[:8]}...")
        # No content to return for 204
        return None # FastAPI 会自动处理 204 响应
    else:
        # delete_proxy_key 内部已记录 Key 未找到的警告
        logger.warning(f"尝试删除不存在的 Key: {proxy_key[:8]}...")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Key '{proxy_key}' 不存在")


# --- 上下文管理 ---
# 移除 JWT 依赖，改为由前端 JS 获取数据时验证
# 添加 CsrfProtect 依赖
@router.get("/manage/context", response_class=HTMLResponse, include_in_schema=False) # 移除 JWT 验证依赖
async def manage_context_page(request: Request): # 移除 CsrfProtect 依赖
    """
    显示上下文管理页面的 HTML 骨架。
    实际数据将由前端 JavaScript 通过 /api/manage/context/data 获取。
    需要 JWT 认证。
    """
    # 不再需要在这里获取数据，只渲染模板
    # current_ttl_days = context_store.get_ttl_days()
    # contexts_info = context_store.list_all_context_keys_info()
    # # 转换 datetime 对象 ... (移除)
    context = {
        "request": request,
        # "current_ttl_days": current_ttl_days, # 数据由 API 提供
        # "contexts_info": contexts_info,      # 数据由 API 提供
        "now": datetime.now(timezone.utc) # 确保时区一致 (UTC) 且键名为 'now'
    }
    # CSRF 相关代码已移除

    response = templates.TemplateResponse("manage_context.html", context)

    # CSRF 相关代码已移除

    return response

# --- 新增：获取上下文数据的 API 端点 ---
@router.get("/api/manage/context/data", dependencies=[Depends(verify_jwt_token)])
async def get_manage_context_data(token_payload: Dict[str, Any] = Depends(verify_jwt_token)):
    """
    获取上下文管理页面所需的数据。
    需要有效的 JWT Bearer Token 认证。
    """
    logger.debug(f"用户 {token_payload.get('sub')} 请求上下文管理数据")
    try:
        current_ttl_days = context_store.get_ttl_days()
        contexts_info = context_store.list_all_context_keys_info()
        # 转换 datetime 对象为 ISO 格式字符串以便 JSON 序列化
        for ctx in contexts_info:
            if isinstance(ctx.get('last_used'), datetime):
                 ctx['last_used'] = ctx['last_used'].isoformat() # 转为 ISO 字符串

        return {
            "current_ttl_days": current_ttl_days,
            "contexts_info": contexts_info
        }
    except Exception as e:
        logger.error(f"获取上下文管理数据时出错: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取上下文数据失败")


# 使用新的 JWT 依赖项保护此路由
@router.post("/manage/context/update_ttl", response_class=RedirectResponse, dependencies=[Depends(verify_jwt_token)])
async def update_ttl(request: Request, ttl_days: int = Form(...), token_payload: Dict[str, Any] = Depends(verify_jwt_token)):
    """更新上下文 TTL 设置"""
    logger.debug(f"用户 {token_payload.get('sub')} 尝试更新 TTL 为 {ttl_days} 天")
    try:
        if ttl_days < 0: raise ValueError("TTL 不能为负数")
        context_store.set_ttl_days(ttl_days)
        # TODO: Flash 消息 (JWT 模式下通常不使用)
        logger.info(f"上下文 TTL 已更新为 {ttl_days} 天")
    except ValueError as e:
        # TODO: Flash 消息 (JWT 模式下通常不使用)
        logger.error(f"更新 TTL 失败: {e}")
    return RedirectResponse(url="/manage/context", status_code=status.HTTP_303_SEE_OTHER)

# 使用新的 JWT 依赖项保护此路由
@router.post("/manage/context/delete/{proxy_key}", response_class=RedirectResponse) # Removed dependency from decorator
async def delete_single_context(request: Request, proxy_key: str, token_payload: Dict[str, Any] = Depends(verify_jwt_token)): # Keep dependency here
    """删除指定 Key 的上下文"""
    logger.debug(f"用户 {token_payload.get('sub')} 尝试删除 Key {proxy_key[:8]}... 的上下文")
    success = context_store.delete_context_for_key(proxy_key)
    # TODO: Flash 消息 (如果需要的话，但 JWT 模式下 Flash 消息不常用)
    logger.info(f"删除 Key {proxy_key[:8]}... 的上下文 {'成功' if success else '失败'}")
    return RedirectResponse(url="/manage/context", status_code=status.HTTP_303_SEE_OTHER)