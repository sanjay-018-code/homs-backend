from datetime import datetime
from typing import Optional, List
from bson import ObjectId
from pydantic import BaseModel, Field, AliasChoices
from app.models.user import PyObjectId

class HistoryItem(BaseModel):
    status: str
    updated_by: PyObjectId
    updated_by_name: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    comments: Optional[str] = None

class OutpassBase(BaseModel):
    destination: str = Field(..., min_length=3, max_length=100)
    reason: str = Field(..., min_length=5, max_length=500)
    out_date: datetime
    in_date: datetime

class OutpassCreate(OutpassBase):
    pass

class OutpassApprove(BaseModel):
    comments: Optional[str] = None

class OutpassReject(BaseModel):
    rejection_reason: str = Field(..., min_length=3, max_length=500)

class OutpassResponse(OutpassBase):
    id: PyObjectId = Field(default=None, validation_alias=AliasChoices("_id", "id"), serialization_alias="id")
    student_id: PyObjectId
    student_name: str
    roll_number: str
    room: Optional[str] = None
    hostel_name: Optional[str] = None
    status: str = "Pending"
    qr_token: Optional[str] = None
    rejection_reason: Optional[str] = None
    history: List[HistoryItem] = []
    exit_time: Optional[datetime] = None
    entry_time: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
