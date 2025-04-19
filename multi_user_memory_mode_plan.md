# 实现计划：内存模式下支持多个中转用户 Key

**目标：** 在内存模式下，通过逗号分隔的 `PASSWORD` 环境变量支持多个中转用户key，并使上下文管理与这些用户key关联，同时确保不影响文件模式下的代理key管理功能。

**背景：**

*   当前项目在内存模式下使用单个 `PASSWORD` 环境变量作为 Web UI 登录密码和 API 访问的中转 Key。
*   文件数据库模式下已实现基于数据库存储的代理 Key 管理功能。
*   上下文管理 (`app/core/context_store.py`) 已经能够根据传入的 `proxy_key` 进行上下文的存取。
*   API 请求处理 (`app/api/request_processor.py`) 接收由认证依赖注入提供的 `proxy_key`，并将其传递给上下文存储函数。
*   API 认证 (`app/api/middleware.py`) 根据 `IS_MEMORY_DB` 变量区分内存模式和文件模式的验证逻辑。

**详细计划：**

1.  **修改 `app/config.py`：**
    *   在加载环境变量后，添加逻辑将 `PASSWORD` 变量的值按逗号分割，去除首尾空白，并将结果存储到一个新的列表变量 `WEB_UI_PASSWORDS` 中。
    *   如果 `PASSWORD` 环境变量未设置或为空，`WEB_UI_PASSWORDS` 将是一个空列表。

    ```python
    # app/config.py
    # ... 其他导入和配置 ...

    PASSWORD = os.environ.get("PASSWORD") # Web UI 密码 (强制设置)
    # 新增：解析 PASSWORD 环境变量为多个密码/Key列表
    WEB_UI_PASSWORDS: List[str] = [p.strip() for p in PASSWORD.split(',') if p.strip()] if PASSWORD else []

    # ... 其他配置 ...
    ```

2.  **修改 `app/web/routes.py`：**
    *   在 `/login` 路由的 `login_for_access_token` 函数中，获取用户通过表单提交的 `password`。
    *   修改验证逻辑，检查提交的 `password` 是否存在于 `config.WEB_UI_PASSWORDS` 列表中。
    *   如果存在，则认证成功，生成 JWT。JWT 的 payload 中的 `sub` 字段将设置为这个成功匹配的 `password`，作为用户的唯一标识符。
    *   如果不存在，则认证失败，返回 401 错误。

    ```python
    # app/web/routes.py
    # ... 其他导入 ...
    from .. import config # 导入 config

    # ... 其他路由 ...

    @router.post("/login", include_in_schema=False)
    async def login_for_access_token(
        request: Request,
        password: str = Form(...)
    ):
        """处理 Web UI 登录请求，验证密码并返回 JWT 访问令牌"""
        # 检查是否配置了任何密码
        if not config.WEB_UI_PASSWORDS:
            logger.error("尝试登录，但 Web UI 密码 (PASSWORD) 未设置或为空。")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, # 使用 503 表示服务未正确配置
                detail="Web UI 登录未启用 (密码未设置)",
            )

        # 检查提交的密码是否在配置的密码列表中
        if password in config.WEB_UI_PASSWORDS:
            # 密码正确，创建 JWT
            # 将成功匹配的密码作为用户标识符存储在 JWT 的 'sub' 字段中
            access_token_data = {"sub": password}
            try:
                access_token = create_access_token(data=access_token_data)
                logger.info(f"Web UI 登录成功，用户 Key: {password[:8]}... 已签发 JWT。")
                return JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
            except ValueError as e:
                 logger.error(f"无法创建 JWT: {e}")
                 raise HTTPException(
                     status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                     detail="无法生成认证令牌 (内部错误)",
                 )
            except Exception as e:
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
                headers={"WWW-Authenticate": "Bearer"},
            )

    # ... 其他路由 ...
    ```

3.  **修改 `app/api/middleware.py`：**
    *   在 `verify_proxy_key` 函数中，当 `IS_MEMORY_DB` 为 True (内存模式) 时：
        *   获取 Bearer 令牌。
        *   检查获取到的令牌是否存在于 `app_config.WEB_UI_PASSWORDS` 列表中。
        *   如果令牌在列表中，则认证成功，将该令牌存储到 `request.state.proxy_key` 中，并返回该令牌。
        *   如果令牌不在列表中，则认证失败，返回 401 错误。
    *   当 `IS_MEMORY_DB` 为 False (文件模式) 时，保持现有逻辑不变，继续调用 `context_store.is_valid_proxy_key(token)` 进行数据库验证。

    ```python
    # app/api/middleware.py
    # ... 其他导入 ...
    from .. import config as app_config # 导入 config
    from ..core.db_utils import IS_MEMORY_DB
    from ..core import context_store # 导入 context_store 以验证 Key (文件模式)

    # ... 其他函数 ...

    async def verify_proxy_key(request: Request) -> str:
        """
        FastAPI 依赖项函数，用于验证 API 请求的 Authorization 头。
        - 如果使用内存数据库 (IS_MEMORY_DB=True)，则验证 Bearer 令牌是否在配置的 WEB_UI_PASSWORDS 列表中。
        - 如果使用文件数据库 (IS_MEMORY_DB=False)，则验证 Bearer 令牌是否是数据库中有效的、活动的代理 Key。

        Returns:
            str: 验证通过的令牌 (PASSWORD 或 代理 Key)。

        Raises:
            HTTPException: 如果认证失败。
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            token = auth_header.split(" ")[1]
        except IndexError:
             raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权：'Bearer ' 后的令牌格式无效。",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if IS_MEMORY_DB:
            # --- 内存数据库模式：使用 WEB_UI_PASSWORDS 验证 ---
            if not app_config.WEB_UI_PASSWORDS:
                logger.error("API 认证失败(内存模式)：未设置 WEB_UI_PASSWORDS (PASSWORD 环境变量)。")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="服务配置错误：缺少 API 认证密码。",
                )
            # 检查提供的令牌是否在配置的密码列表中
            if token not in app_config.WEB_UI_PASSWORDS:
                logger.warning(f"API 认证失败(内存模式)：提供的令牌与配置的密码不匹配。")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未授权：无效的令牌。",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            logger.debug(f"API 认证成功 (内存模式，使用 Key: {token[:8]}...).")
            # 将验证通过的令牌（即用户提供的密码/key）存储在请求状态中
            request.state.proxy_key = token
            return token
        else:
            # --- 文件数据库模式：使用数据库中的代理 Key 验证 ---
            # 保持现有逻辑不变
            if not await context_store.is_valid_proxy_key(token): # is_valid_proxy_key 现在是 async 的
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="未授权：无效或非活动的代理 API Key。",
                )
            logger.debug(f"API 认证成功 (文件模式，使用代理 Key: {token[:8]}...)。")
            # 将有效的代理 Key 存储在 request state 中
            request.state.proxy_key = token
            return token
    ```

4.  **验证上下文管理逻辑 (`app/core/context_store.py`)：**
    *   确认 `save_context`, `load_context`, `delete_context_for_key`, `list_all_context_keys_info` 等函数已经接收 `proxy_key` 参数，并且在内部使用这个 `proxy_key` 来进行数据库操作（包括在内存模式下的 SQLite 数据库）。
    *   由于 SQLite 数据库本身支持基于 Key 的存取，并且 `contexts` 表通过 `proxy_key` 关联，现有结构在接收到不同的 `proxy_key` 时，会自动将上下文与对应的 Key 关联起来。这部分代码**不需要**进行大的结构性修改。

5.  **验证 API 请求处理逻辑 (`app/api/request_processor.py`)：**
    *   确认 `process_request` 函数已经接收由 `verify_proxy_key` 依赖注入提供的 `proxy_key` 参数。
    *   确认 `process_request` 函数在调用 `context_store.load_context` 和 `context_store.save_context` 时，使用了接收到的 `proxy_key` 参数。
    *   这部分代码**不需要**进行修改。

6.  **更新相关文档和提示信息：**
    *   在项目的 README 或其他文档中，明确说明在内存模式下，`PASSWORD` 环境变量可以配置多个逗号分隔的中转用户key，这些key同时用于 Web UI 登录和 API 认证。
    *   如果 Web UI 管理界面有相关提示，考虑更新以反映内存模式下用户key的来源是 `PASSWORD` 环境变量。

**Mermaid 图示 (更新):**

```mermaid
graph TD
    A[用户输入密码/Key登录] --> B{验证密码/Key};
    B -- 密码/Key 在 config.WEB_UI_PASSWORDS 列表中 --> C[认证成功];
    B -- 密码/Key 不在列表中 --> D[认证失败];
    C --> E[生成包含密码/Key的 JWT];
    E --> F[用户使用 JWT 访问 API];
    F --> G{验证 JWT};
    G -- 验证成功 --> H[从 JWT 提取用户Key];
    H --> I[使用用户Key调用 verify_proxy_key];
    I --> J{判断数据库模式};
    J -- 内存模式 (IS_MEMORY_DB=True) --> K{验证 Bearer Token 是否在 config.WEB_UI_PASSWORDS 列表中};
    J -- 文件模式 (IS_MEMORY_DB=False) --> L{调用 context_store.is_valid_proxy_key 验证 Key};
    K -- 验证通过 --> M[认证成功，proxy_key = Token];
    L -- 验证通过 --> M;
    K -- 验证失败 --> N[认证失败];
    L -- 验证失败 --> N;
    M --> O[将 proxy_key 传递给 process_request];
    O --> P[process_request 使用 proxy_key 存取上下文];
    P --> Q[内存模式下的 SQLite 数据库];
    P --> R[文件模式下的 SQLite 数据库];
    O --> S[处理 API 请求];
    S --> T[返回 API 响应];
    N --> U[拒绝访问];

    subgraph 内存模式下的上下文存储
        Q
    end
    subgraph 文件模式下的上下文存储
        R
    end