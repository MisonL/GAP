# -*- coding: utf-8 -*-
"""
处理 Web UI 相关的路由，例如状态页面和未来的管理界面。
"""
import logging
# import pytz # 已移除，不再需要
import asyncio # 导入 asyncio，虽然不直接用，但依赖的模块用了
from datetime import datetime, timezone # 导入时区
# from collections import Counter # 已移除，不再需要
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status, Response # 保留 Response 导入
# 导入 Response, Request, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse # 保留现有导入
from fastapi.templating import Jinja2Templates
# 导入安全相关的类型和新的依赖项
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
    # 导入 render_status_page (现已移除) 直接需要的配置值，部分可能仍用于模板
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
async def root_get(request: Request): # 移除了 CsrfProtect 依赖
    """显示登录表单页面"""
    # user_session = request.session.get("user", {}) # 安全地获取 session (旧的 Session 逻辑已移除)
    # is_authenticated = user_session.get("authenticated", False) # (旧的 Session 逻辑已移除)
    login_required = bool(PASSWORD) # 检查是否全局设置了密码
    # show_details = not PROTECT_STATUS_PAGE or is_authenticated # (Session 已移除)
    # 假设存在 login.html 模板用于显示登录表单

    # --- CSRF 相关代码已移除 ---
    # csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
    admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失
    response = templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "login_required": login_required,
            "admin_key_missing": admin_key_missing, # 添加到模板上下文
            # "csrf_token": csrf_token # 移除了 CSRF token
        }
    )
    # --- CSRF 相关代码已移除 ---
    # csrf_protect.set_csrf_cookie(signed_token, response)

    return response

# --- 旧的 POST / 路由 (已移除) ---
# @router.post("/", ...) ... (代码已删除)

# --- 旧的 render_status_page 辅助函数 (已移除) ---
# async def render_status_page(...): ... (代码已删除)

# --- 新的登录处理路由 ---
@router.post("/login", include_in_schema=False)
async def login_for_access_token(
    request: Request, # 添加 request 参数 (虽然 CSRF 移除了，但保留以备将来使用或获取请求信息)
    password: str = Form(...)
    # csrf_protect: CsrfProtect = Depends() # 移除了 CsrfProtect 依赖
):
    """处理 Web UI 登录请求，验证密码并返回 JWT 访问令牌"""
    # --- CSRF 验证已移除 ---
    # try:
    #     await csrf_protect.validate_csrf(request)
    # except CsrfProtectException as e:
    #     logger.warning(f"CSRF validation failed during login: {e.message}")
    #     raise HTTPException(status_code=e.status_code, detail=e.message)
    # --- CSRF 验证已移除 ---

    # 检查是否配置了任何密码
    if not config.WEB_UI_PASSWORDS:
        logger.error("尝试登录，但 Web UI 密码 (PASSWORD) 未设置或为空。")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, # 使用 503 表示服务未正确配置
            detail="Web UI 登录未启用 (密码未设置)",
        )

    # 检查是否为管理员 Key
    is_admin_login = False
    if config.ADMIN_API_KEY and password == config.ADMIN_API_KEY:
        is_admin_login = True
        logger.info(f"管理员 Key 登录尝试: {password[:8]}...")
        access_token_data = {"sub": password, "admin": True}
    # 检查提交的密码是否在配置的普通用户密码列表中
    elif password in config.WEB_UI_PASSWORDS:
        logger.info(f"普通用户 Key 登录尝试: {password[:8]}...")
        # 密码正确，创建 JWT (普通用户)
        # 将成功匹配的密码作为用户标识符存储在 JWT 的 'sub' 字段中
        access_token_data = {"sub": password} # 普通用户 JWT 不包含 admin 字段或为 False
    else:
        # 密码错误
        logger.warning("Web UI 登录失败：密码错误。")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 如果密码验证通过 (管理员或普通用户)
    try:
        access_token = create_access_token(data=access_token_data)
        login_type = "管理员" if is_admin_login else "普通用户"
        logger.info(f"Web UI {login_type}登录成功，用户 Key: {password[:8]}... 已签发 JWT。")
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
    description: Optional[str] = Field(None, description="新 Key 的描述 (可选)")
    expires_at: Optional[str] = Field(None, description="Key 过期时间 (ISO 格式, YYYY-MM-DDTHH:MM:SSZ 或 YYYY-MM-DDTHH:MM:SS+00:00)，留空或 null 表示永不过期")

class UpdateKeyRequest(BaseModel):
    description: Optional[str] = Field(None, description="新的描述 (可选)")
    is_active: Optional[bool] = Field(None, description="新的激活状态 (可选)")
    expires_at: Optional[str] = Field(None, description="新的 Key 过期时间 (ISO 格式)，留空或 null 表示永不过期")


# --- 代理 Key 管理 (仅文件模式) ---

# 新增：辅助函数检查是否为管理员
async def require_admin_user(token_payload: Dict[str, Any] = Depends(verify_jwt_token)):
    """依赖项：检查当前用户是否为管理员。"""
    is_admin = token_payload.get("admin", False)
    if not is_admin:
        user_key = token_payload.get("sub", "未知用户")
        logger.warning(f"用户 {user_key[:8]}... 尝试访问管理员专属的 Key 管理 API，操作被拒绝。")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员有权限执行此操作。"
        )
    # 如果是管理员，可以继续，不需要返回值

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
    # dependencies=[Depends(require_file_db_mode)] # 依赖已移除 (改为在 API 端点检查)
)
async def manage_keys_page(request: Request):
    """显示代理 Key 管理页面的 HTML 骨架。如果处于内存数据库模式，则显示提示信息。"""
    is_memory_mode = db_utils.IS_MEMORY_DB
    if is_memory_mode:
        logger.debug("渲染 Key 管理页面骨架 (内存模式提示)")
        admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失
        return templates.TemplateResponse(
            "manage_keys.html",
            # 添加 'now' 到上下文，用于模板中可能的缓存控制或显示
            {"request": request, "is_memory_mode": True, "admin_key_missing": admin_key_missing, "now": datetime.now(timezone.utc)}
        )
    else:
        logger.debug("渲染 Key 管理页面骨架 (文件模式)")
        admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失
        # 仅渲染页面骨架，实际的 Key 数据将由前端通过 API 请求获取并填充
        return templates.TemplateResponse(
            "manage_keys.html",
            # 添加 'now' 到上下文
            {"request": request, "is_memory_mode": False, "admin_key_missing": admin_key_missing, "now": datetime.now(timezone.utc)}
        )

# 获取 Key 数据的 API 端点
@router.get(
    "/api/manage/keys/data",
    # 添加管理员检查依赖
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)]
)
async def get_manage_keys_data(token_payload: Dict[str, Any] = Depends(verify_jwt_token)): # 仍然需要 token_payload 来记录日志
    """获取代理 Key 管理页面所需的数据 (仅管理员)。"""
    admin_key = token_payload.get('sub', '未知管理员')
    logger.debug(f"管理员 {admin_key[:8]}... 请求 Key 管理数据")
    try:
        keys_data = await db_utils.get_all_proxy_keys() # 添加 await
        # 转换 Row 对象为字典列表，并格式化日期
        result = []
        for row in keys_data:
            key_info = dict(row) # 将 sqlite3.Row 转换为字典

            # 格式化 created_at
            created_at_val = key_info.get('created_at')
            if isinstance(created_at_val, datetime):
                 key_info['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(created_at_val, str):
                 try:
                     # 尝试解析数据库返回的字符串（可能是 ISO 格式）
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00')) # 处理 Z 时区
                     key_info['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError:
                     logger.warning(f"无法解析 Key {key_info.get('key')} 的 created_at 字符串: {created_at_val}")
                     key_info['created_at'] = created_at_val # 保持原样

            # 处理 expires_at (保持 ISO 格式或 None)
            expires_at_val = key_info.get('expires_at')
            if isinstance(expires_at_val, datetime):
                # 如果数据库返回的是 datetime 对象，转为 ISO 格式
                key_info['expires_at'] = expires_at_val.replace(tzinfo=timezone.utc).isoformat()
            elif isinstance(expires_at_val, str):
                # 如果已经是字符串，确保是有效的 ISO 格式，否则记录警告
                try:
                    datetime.fromisoformat(expires_at_val.replace('Z', '+00:00'))
                    # 格式有效，保持原样
                    key_info['expires_at'] = expires_at_val
                except ValueError:
                    logger.warning(f"数据库返回的 Key {key_info.get('key')} 的 expires_at 字符串格式无效: {expires_at_val}")
                    key_info['expires_at'] = None # 视为无效或无过期时间
            else:
                # 其他情况（如 None）保持不变
                key_info['expires_at'] = expires_at_val # 应该是 None

            result.append(key_info)

        # 返回 is_admin 状态，前端需要
        is_admin_status = token_payload.get("admin", False) # 从 token 获取真实状态
        return {"keys": result, "is_admin": is_admin_status}
    except Exception as e:
        logger.error(f"管理员 {admin_key[:8]}... 获取 Key 管理数据时出错: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取 Key 数据失败")

# 添加新 Key 的 API 端点
@router.post(
    "/api/manage/keys/add",
    status_code=status.HTTP_201_CREATED, # 成功创建资源时返回 201 状态码
    # 添加管理员检查依赖
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)]
)
async def add_new_key(
    key_data: AddKeyRequest, # 使用更新后的 Pydantic 模型
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 仍然需要 token_payload 来记录日志
):
    """API 端点：添加一个新的代理 Key (Key 值由 UUID 自动生成) (仅管理员)。"""
    admin_key = token_payload.get('sub', '未知管理员')
    logger.debug(f"管理员 {admin_key[:8]}... 请求添加新 Key")
    new_key = str(uuid.uuid4())
    description = key_data.description # Pydantic 会处理 None
    expires_at = key_data.expires_at # 获取 expires_at

    # 验证 expires_at 格式 (如果提供)
    if expires_at:
        try:
            # 尝试解析以确保格式正确，但不存储 datetime 对象
            datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        except ValueError:
            logger.warning(f"管理员 {admin_key[:8]}... 提供的 expires_at 格式无效: {expires_at}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_at 格式无效，请使用 ISO 8601 格式 (例如 YYYY-MM-DDTHH:MM:SSZ)")

    # 调用数据库函数，传入 expires_at
    success = await db_utils.add_proxy_key(key=new_key, description=description, expires_at=expires_at) # 添加 await

    if success:
        logger.info(f"管理员 {admin_key[:8]}... 成功添加新 Key: {new_key[:8]}... (描述: {description}, 过期: {expires_at})")
        # 返回新创建的 Key 信息可能更有用
        new_key_info = await db_utils.get_proxy_key(new_key) # 添加 await
        if new_key_info:
             key_dict = dict(new_key_info)
             # 格式化 created_at
             created_at_val = key_dict.get('created_at')
             if isinstance(created_at_val, datetime):
                 key_dict['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S')
             elif isinstance(created_at_val, str):
                 try:
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00'))
                     key_dict['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError: pass # 保持原样

             # 处理 expires_at (保持 ISO 格式或 None)
             expires_at_val = key_dict.get('expires_at')
             if isinstance(expires_at_val, datetime):
                 key_dict['expires_at'] = expires_at_val.replace(tzinfo=timezone.utc).isoformat()
             # else: # 保持数据库返回的字符串或 None

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
    # 添加管理员检查依赖
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)]
)
async def update_existing_key(
    proxy_key: str,
    update_data: UpdateKeyRequest, # 使用更新后的 Pydantic 模型
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 仍然需要 token_payload 来记录日志
):
    """更新指定代理 Key 的描述、状态或过期时间 (仅管理员)。"""
    admin_key = token_payload.get('sub', '未知管理员')
    logger.debug(f"管理员 {admin_key[:8]}... 请求更新 Key: {proxy_key[:8]}...")

    # 检查是否提供了至少一个要更新的字段
    if update_data.description is None and update_data.is_active is None and update_data.expires_at is None:
         logger.warning(f"管理员 {admin_key[:8]}... 更新 Key {proxy_key[:8]}... 的请求未提供任何更新字段。")
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须提供 description, is_active 或 expires_at 进行更新")

    # 验证 expires_at 格式 (如果提供)
    expires_at_to_update = update_data.expires_at
    if expires_at_to_update is not None: # 注意：空字符串 "" 也需要验证和处理
        if expires_at_to_update == "":
            expires_at_to_update = None # 将空字符串视为清除过期时间
        else:
            try:
                datetime.fromisoformat(expires_at_to_update.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"管理员 {admin_key[:8]}... 提供的 expires_at 格式无效: {expires_at_to_update}")
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_at 格式无效，请使用 ISO 8601 格式 (例如 YYYY-MM-DDTHH:MM:SSZ) 或留空")

    success = await db_utils.update_proxy_key( # 添加 await
        key=proxy_key,
        description=update_data.description,
        is_active=update_data.is_active,
        expires_at=expires_at_to_update # 传递处理过的 expires_at
    )

    if success:
        logger.info(f"管理员 {admin_key[:8]}... 成功更新 Key: {proxy_key[:8]}...")
        updated_key_info = await db_utils.get_proxy_key(proxy_key) # 添加 await
        if updated_key_info:
             key_dict = dict(updated_key_info)
             # 格式化 created_at
             created_at_val = key_dict.get('created_at')
             if isinstance(created_at_val, datetime):
                 key_dict['created_at'] = created_at_val.strftime('%Y-%m-%d %H:%M:%S')
             elif isinstance(created_at_val, str):
                 try:
                     dt_obj = datetime.fromisoformat(created_at_val.replace('Z', '+00:00'))
                     key_dict['created_at'] = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                 except ValueError: pass # 保持原样

             # 处理 expires_at (保持 ISO 格式或 None)
             expires_at_val = key_dict.get('expires_at')
             if isinstance(expires_at_val, datetime):
                 key_dict['expires_at'] = expires_at_val.replace(tzinfo=timezone.utc).isoformat()
             # else: # 保持数据库返回的字符串或 None

             return {"message": "Key 更新成功", "key": key_dict}
        else:
             logger.warning(f"更新 Key {proxy_key[:8]}... 成功，但无法检索更新后的信息 (可能已被并发删除?)")
             return {"message": "Key 更新成功，但无法检索更新后的信息"}
    else:
        # update_proxy_key 内部已记录 Key 未找到或未改变的警告
        # 检查 Key 是否存在，以返回更具体的错误
        existing_key = await db_utils.get_proxy_key(proxy_key) # 添加 await
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
    # 添加管理员检查依赖
    dependencies=[Depends(require_file_db_mode), Depends(require_admin_user)]
)
async def delete_existing_key(
    proxy_key: str,
    token_payload: Dict[str, Any] = Depends(verify_jwt_token) # 仍然需要 token_payload 来记录日志
):
    """删除指定的代理 Key (及其关联的上下文) (仅管理员)。"""
    admin_key = token_payload.get('sub', '未知管理员')
    logger.debug(f"管理员 {admin_key[:8]}... 请求删除 Key: {proxy_key[:8]}...")

    success = await db_utils.delete_proxy_key(key=proxy_key) # 添加 await

    if success:
        logger.info(f"管理员 {admin_key[:8]}... 成功删除 Key: {proxy_key[:8]}...")
        # 204 状态码表示成功处理请求，但无需返回任何内容
        return None # FastAPI 会自动生成无内容的 204 响应
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
    # current_ttl_days = await context_store.get_ttl_days() # 改为 await
    # contexts_info = await context_store.list_all_context_keys_info() # 改为 await
    # # 转换 datetime 对象 ... (移除)
    admin_key_missing = not config.ADMIN_API_KEY # 检查管理员 Key 是否缺失
    context = {
        "request": request,
        # "current_ttl_days": current_ttl_days, # 数据由 API 提供
        # "contexts_info": contexts_info,      # 数据由 API 提供
        "admin_key_missing": admin_key_missing, # 添加到模板上下文
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
    user_key = token_payload.get("sub")
    is_admin = token_payload.get("admin", False)
    logger.debug(f"用户 {user_key[:8]}... (Admin: {is_admin}) 请求上下文管理数据")
    try:
        current_ttl_days = await context_store.get_ttl_days() # 添加 await
        # 调用改造后的函数，传入用户信息
        contexts_info = await context_store.list_all_context_keys_info(user_key=user_key, is_admin=is_admin) # 添加 await
        # 转换 datetime 对象为 ISO 格式字符串以便 JSON 序列化
        for ctx in contexts_info:
            if isinstance(ctx.get('last_used'), datetime):
                 ctx['last_used'] = ctx['last_used'].isoformat() # 转为 ISO 字符串
            elif isinstance(ctx.get('last_used'), str):
                 # 尝试解析并重新格式化，以防数据库返回的是字符串
                 try:
                     dt_obj = datetime.fromisoformat(ctx['last_used'].replace('Z', '+00:00'))
                     ctx['last_used'] = dt_obj.isoformat() # 保持 ISO 格式
                 except ValueError:
                     logger.warning(f"无法解析上下文 {ctx.get('proxy_key')} 的 last_used 字符串: {ctx['last_used']}")
                     # 保持原样或设为 None/空字符串
                     pass # 保持原样

        return {
            "current_ttl_days": current_ttl_days,
            "contexts_info": contexts_info,
            "is_admin": is_admin # 将管理员状态也返回给前端
        }
    except Exception as e:
        logger.error(f"获取上下文管理数据时出错: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取上下文数据失败")


# 使用新的 JWT 依赖项保护此路由
@router.post("/manage/context/update_ttl", response_class=RedirectResponse, dependencies=[Depends(verify_jwt_token)])
async def update_ttl(request: Request, ttl_days: int = Form(...), token_payload: Dict[str, Any] = Depends(verify_jwt_token)):
    """更新上下文 TTL 设置 (仅管理员)"""
    user_key = token_payload.get("sub")
    is_admin = token_payload.get("admin", False)
    logger.debug(f"用户 {user_key[:8]}... (Admin: {is_admin}) 尝试更新 TTL 为 {ttl_days} 天")

    if not is_admin:
        logger.warning(f"非管理员用户 {user_key[:8]}... 尝试更新 TTL，操作被拒绝。")
        # 对于 Web 表单提交，重定向可能不是最佳选择，但为了保持一致性，暂时保留
        # 或者可以返回一个错误页面/消息
        # raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可以更新 TTL")
        # 暂时还是重定向，前端可以通过 is_admin 状态禁用表单
        return RedirectResponse(url="/manage/context?error=permission_denied", status_code=status.HTTP_303_SEE_OTHER)

    try:
        if ttl_days < 0: raise ValueError("TTL 不能为负数")
        await context_store.set_ttl_days(ttl_days) # 添加 await
        logger.info(f"管理员 {user_key[:8]}... 已将上下文 TTL 更新为 {ttl_days} 天")
        # 可以在重定向 URL 中添加成功参数
        redirect_url = "/manage/context?success=ttl_updated"
    except ValueError as e:
        logger.error(f"管理员 {user_key[:8]}... 更新 TTL 失败: {e}")
        # 可以在重定向 URL 中添加错误参数
        redirect_url = f"/manage/context?error=update_failed&detail={e}"
    except Exception as e:
        logger.error(f"管理员 {user_key[:8]}... 更新 TTL 时发生意外错误: {e}", exc_info=True)
        redirect_url = "/manage/context?error=internal_error"

    # 操作完成后重定向回上下文管理页面
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

# 使用新的 JWT 依赖项保护此路由
@router.post("/manage/context/delete/{proxy_key}", response_class=RedirectResponse) # 从装饰器移除依赖 (已移到函数参数)
async def delete_single_context(request: Request, proxy_key: str, token_payload: Dict[str, Any] = Depends(verify_jwt_token)): # 在此处保留 JWT 验证依赖
    """删除指定代理 Key 关联的上下文记录 (管理员或 Key 所有者)"""
    user_key = token_payload.get("sub")
    is_admin = token_payload.get("admin", False)
    logger.debug(f"用户 {user_key[:8]}... (Admin: {is_admin}) 尝试删除 Key {proxy_key[:8]}... 的上下文")

    # 权限检查：必须是管理员，或者是该 Key 的所有者
    if not is_admin and user_key != proxy_key:
        logger.warning(f"用户 {user_key[:8]}... 尝试删除不属于自己的 Key {proxy_key[:8]}... 的上下文，操作被拒绝。")
        # raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除此上下文")
        return RedirectResponse(url="/manage/context?error=permission_denied", status_code=status.HTTP_303_SEE_OTHER)

    success = await context_store.delete_context_for_key(proxy_key) # 添加 await
    if success:
        logger.info(f"用户 {user_key[:8]}... 成功删除 Key {proxy_key[:8]}... 的上下文")
        redirect_url = "/manage/context?success=context_deleted"
    else:
        # delete_context_for_key 内部已记录 debug 日志
        logger.warning(f"用户 {user_key[:8]}... 尝试删除 Key {proxy_key[:8]}... 的上下文失败 (Key 可能不存在)")
        redirect_url = "/manage/context?error=delete_failed"

    # 操作完成后重定向回上下文管理页面
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)