import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from datetime import datetime, UTC
# Secret key used for encoding and decoding (must be the same as used in token generation)
SECRET_KEY = "6a350ad10ff379270a10986757225cbc49209a7b53fef817e8c88084e2718af5"

def validate_jwt_token(token):
    try:
        decoded_payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_signature": False}  # Note: Signature is not verified
        )

        # Optional: Check if token is expired manually
        now = datetime.now(UTC).timestamp()
        print(decoded_payload)
        if decoded_payload.get('exp') and decoded_payload['exp'] < now:
            return False

        return True
    except (ExpiredSignatureError, InvalidTokenError, Exception):
        return False

# Example usage
if __name__ == "__main__":
    token = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiUk9MRV9DVVNUT01FUiIsImlkIjoiNjdiZTlkZTc3YTVkZTgzNGQ1YTY0MDQ2Iiwic3ViIjoiaGl0ZXNoZ2FyZzAyQGdtYWlsLmNvbSIsImlhdCI6MTc0NjI4MjU4MywiZXhwIjoxNzQ2ODg3MzgzfQ.SJOxRvnwezopyLWcYdO_O2lL0NUWcX8edWosfKiBgUA"  # Replace with a valid JWT token7
    print(validate_jwt_token(token))
