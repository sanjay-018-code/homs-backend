from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from bson import ObjectId
from app.core.config import settings
from app.core.database import get_database
from app.models.user import UserResponse

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserResponse:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    db = get_database()
    try:
        user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise credentials_exception
        
    if user_doc is None:
        raise credentials_exception
    
    if user_doc.get("enrollment_status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive or suspended"
        )
        
    return UserResponse(**user_doc)

class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role: {current_user.role}"
            )
        return current_user

# Database-level RBAC query enforcement helper
def get_role_based_outpass_filter(user: UserResponse) -> dict:
    """
    Enforces database-level query restriction to prevent API bypass/privilege escalation.
    Students: can only see their own requests.
    Advisors: see requests at 'Pending' or stages after they verified.
    Wardens: see requests at 'Advisor Approved' or stages after.
    HODs: see requests at 'Warden Approved' or 'Approved' or marked exits/entries.
    Security: see 'Approved' or 'Student Left' or 'Student Returned' requests.
    Admins: see all requests.
    """
    if user.role == "admin":
        return {}
    elif user.role == "student":
        return {"student_id": ObjectId(user.id)}
    elif user.role == "advisor":
        return {"status": {"$in": ["Pending", "Advisor Approved", "Warden Approved", "Approved", "Student Left", "Student Returned", "Rejected"]}}
    elif user.role == "warden":
        return {"status": {"$in": ["Advisor Approved", "Warden Approved", "Approved", "Student Left", "Student Returned", "Rejected"]}}
    elif user.role == "hod":
        return {"status": {"$in": ["Warden Approved", "Approved", "Student Left", "Student Returned", "Rejected"]}}
    elif user.role == "security":
        return {"status": {"$in": ["Approved", "Student Left", "Student Returned"]}}
    else:
        # Fallback block
        return {"_id": None}
