from src.utils.jwt_utils import decode_token
from fastapi import  HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from src.utils.db import PGDB
db = PGDB()
security = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    token = None
    
    if credentials:
        token = credentials.credentials
    elif "access_token" in request.cookies:
        token = request.cookies["access_token"]
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token - missing user_id")
    
    if isinstance(user_id, str) and not user_id.isdigit():
        user = db.get_user_by_username(user_id)
    else:
        user = db.get_user_by_id(int(user_id))
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user