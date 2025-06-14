import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import FastAPI, Depends, HTTPException
from ..constants import JWT_SECRET_KEY
from datetime import datetime, UTC
# Secret key used for encoding and decoding (must be the same as used in token generation)

def validate_jwt_token(token: str) -> bool:
    try:
        decoded_payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_signature": False}  # Note: Signature is not verified
        )
        decoded_payload["status"] = False
        decoded_payload["token"] = token
        # Optional: Check if token is expired manually
        now = datetime.now(UTC).timestamp()
        if decoded_payload.get('exp') and decoded_payload['exp'] < now:
            return decoded_payload
        decoded_payload["status"] = True
        return decoded_payload
    except (ExpiredSignatureError, InvalidTokenError, Exception):
        return {"status":None}

security = HTTPBearer()

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    if not validate_jwt_token(token)["status"]:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return validate_jwt_token(token)