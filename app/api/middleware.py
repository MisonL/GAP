from fastapi import Request, HTTPException

# 从其他模块导入必要的组件
# 注意：移动后，相对导入路径需要调整
from ..config import PASSWORD # 从 config 导入 API 密钥 (PASSWORD)

async def verify_password(request: Request):
    """
    FastAPI 依赖项函数，用于验证 Authorization 头中的 Bearer 令牌
    是否与配置的 API 密钥 (PASSWORD) 匹配。
    """
    # 仅当在环境/配置中设置了 PASSWORD 时才强制执行密码检查
    if PASSWORD:
        auth_header = request.headers.get("Authorization")
        # 检查标头是否存在且以 "Bearer " 开头
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。" # 翻译
            )
        # 提取令牌部分
        try:
            token = auth_header.split(" ")[1]
        except IndexError:
             raise HTTPException(
                status_code=401,
                detail="未授权：'Bearer ' 后的令牌格式无效。" # 翻译
            )
        # 将提取的令牌与配置的密码进行比较
        if token != PASSWORD:
            raise HTTPException(status_code=401, detail="未授权：无效的令牌。") # 翻译

# 如果需要，以后可以在此处添加其他中间件函数或依赖项。