from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from bson import ObjectId
from app.core.database import get_database
from app.core.security import verify_password, create_access_token
from app.models.user import UserResponse
from app.routes.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    db = get_database()
    # Swagger UI sends email in the username field
    user_doc = await db.users.find_one({"email": form_data.username})
    if not user_doc or not verify_password(form_data.password, user_doc["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )
    
    if user_doc.get("enrollment_status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive or suspended"
        )

    access_token = create_access_token(subject=user_doc["_id"])
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user_doc["role"],
        "name": user_doc["name"]
    }

@router.post("/login-json")
async def login_json(data: dict):
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password required"
        )
        
    db = get_database()
    user_doc = await db.users.find_one({"email": email})
    if not user_doc or not verify_password(password, user_doc["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )
        
    if user_doc.get("enrollment_status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive or suspended"
        )

    access_token = create_access_token(subject=user_doc["_id"])
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user_doc["role"],
        "name": user_doc["name"]
    }

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user
