import traceback

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import JSONResponse

from src.api.base_models import UserLogin, TokenRefresh, TokenValidate
from src.utils.db import PGDB
from src.utils.jwt_utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from src.utils.utils import get_current_user

router = APIRouter()
db = PGDB()


@router.post(
    "/login/",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                        "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                        "token_type": "bearer",
                        "user": {
                            "id": 1,
                            "username": "alice",
                            "email": "alice@example.com",
                            "first_name": "Alice",
                            "last_name": "Anderson",
                        },
                    }
                }
            }
        },
        401: {"content": {"application/json": {"example": {"error": "Invalid credentials"}}}},
    },
)
def login_user(user: UserLogin):
    """Authenticate and receive JWT tokens.

    Accepts a username or email address in the `username` field.
    Returns an access token (500 min) and a refresh token (30 days).
    The access token is also set as an `access_token` httpOnly cookie for
    browser SSO flows (Farm Calendar). Use `Authorization: Bearer <access_token>`
    for all other authenticated requests.
    """
    try:
        if '@' in user.username:
            user_dict = {"email": user.username, "password": user.password}
        else:
            user_dict = {"username": user.username.strip(), "password": user.password}
        
        result = db.login_user(user_dict)
        access_token = create_access_token({
            "user_id": result["id"],
            "username": result["username"]
        })
        refresh_token = create_refresh_token({
            "user_id": result["id"],
            "username": result["username"]
        })
        
        response = JSONResponse(content={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": result["id"],
                "username": result["username"],
                "email": result["email"],
                "first_name": result["first_name"],
                "last_name": result["last_name"]
            }
        })
        
        # Cookie lifetime MUST match the access token's own expiry. The Farm
        # Calendar SSO entry (GET /api/farm-calendar/) authenticates via this
        # cookie, not the Bearer header. A shorter cookie (was 3600s/1h) expired
        # while the token (500min) was still valid, so the calendar link 401'd
        # mid-session even though the rest of the app kept working.
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax"
        )

        return response
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Login failed")

@router.post("/logout/")
def logout_user(refresh_token: TokenRefresh, current_user: dict = Depends(get_current_user)):
    """Invalidate the current session.

    Blacklists the provided refresh token so it cannot be used again.
    The access token remains valid until its natural expiry (500 min).
    Requires a valid `Authorization: Bearer` header.
    """
    try:
        payload = decode_token(refresh_token.refresh_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        db.blacklist_token(refresh_token.refresh_token)
        return {"message": "Successfully logged out"}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Logout failed")

@router.post(
    "/validate_token/",
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "valid": {"value": {"valid": True, "user_id": 1}},
                        "invalid": {"value": {"valid": False, "detail": "Invalid or expired token"}},
                    }
                }
            }
        }
    },
)
def validate_token(token_data: TokenValidate):
    """Check whether an access token is still valid.

    Returns `{"valid": true, "user_id": <id>}` or `{"valid": false, "detail": "..."}`.
    Does not require authentication — intended for service-to-service token checks.
    """
    try:
        payload = decode_token(token_data.token)
        if not payload:
            raise ValueError("Invalid or expired token")
        return {"valid": True, "user_id": payload.get("user_id")}
    except ValueError as e:
        return {"valid": False, "detail": str(e)}

@router.post(
    "/token/refresh/",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
                }
            }
        },
        401: {"content": {"application/json": {"example": {"error": "Invalid or expired token"}}}},
    },
)
def refresh_token(refresh_data: TokenRefresh):
    """Exchange a refresh token for a new access token.

    Also renews the `access_token` httpOnly cookie in lockstep, keeping the Farm
    Calendar SSO session alive. Returns 401 if the refresh token is expired or blacklisted.
    """
    try:
        payload = decode_token(refresh_data.refresh_token)
        if not payload:
            raise ValueError("Invalid or expired token")
        if db.is_token_blacklisted(refresh_data.refresh_token):
            raise ValueError("Token blacklisted")
        user_id = payload.get("user_id")
        # Carry username so the refreshed token still works for the Farm Calendar
        # SSO (which mints its FC token from the username). The refresh token
        # was issued with both claims at login.
        new_access_token = create_access_token({
            "user_id": user_id,
            "username": payload.get("username"),
        })
        # Renew the SSO cookie in lockstep with the token, so the calendar link
        # keeps working for the full refreshed lifetime (not just until the
        # original login cookie would have expired).
        response = JSONResponse(content={"access_token": new_access_token})
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax"
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Token refresh failed")

@router.get(
    "/me/",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "username": "alice",
                        "email": "alice@example.com",
                        "first_name": "Alice",
                        "last_name": "Anderson",
                        "is_admin": False,
                    }
                }
            }
        }
    },
)
def get_me(current_user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user
