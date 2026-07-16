from typing import Optional, Annotated
from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field, BeforeValidator, PlainSerializer, WithJsonSchema, AliasChoices

# Custom type for handling MongoDB ObjectId
PyObjectId = Annotated[
    str,
    BeforeValidator(lambda x: str(x) if isinstance(x, ObjectId) else x),
    PlainSerializer(lambda x: str(x), return_type=str),
    WithJsonSchema({"type": "string", "example": "507f1f77bcf86cd799439011"}),
]

class HostelDetails(BaseModel):
    room: str = Field(..., example="101")
    hostel_name: str = Field(..., example="A-Block")
    occupancy_status: str = Field("Resident", example="Resident")

class UserBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    role: str = Field("student", description="student, advisor, warden, hod, security, admin")
    roll_number: Optional[str] = None
    parent_email: Optional[EmailStr] = None
    hostel_details: Optional[HostelDetails] = None
    enrollment_status: str = "active"

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    roll_number: Optional[str] = None
    parent_email: Optional[EmailStr] = None
    hostel_details: Optional[HostelDetails] = None
    enrollment_status: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None

class UserInDB(UserBase):
    id: PyObjectId = Field(default=None, alias="_id")
    password_hash: str

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

class UserResponse(UserBase):
    id: PyObjectId = Field(default=None, validation_alias=AliasChoices("_id", "id"), serialization_alias="id")
    live_status: Optional[str] = None
    active_outpass_status: Optional[str] = None

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
