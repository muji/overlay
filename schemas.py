from pydantic import BaseModel

from datetime import datetime
from typing import Dict, Any


class UploadedImageCreate(BaseModel):
    image_path: str
    created_at: datetime

class UploadedImageResponse(BaseModel):
    id: int
    image_path: str
    created_at: datetime

    
class GraphicsCreate(BaseModel):
    Gtype: str
    branding: Dict[str, Any]
    position: str
    scoreboard_id: int  # New mandatory field
    url: str  # Add this field

class GraphicsResponse(BaseModel):
    id: int
    Gtype: str
    branding: Dict[str, Any]
    position: str
    scoreboard_id: int  # New mandatory field
    url: str  # Add this field

class GameStatsCreate(BaseModel):
    stats: Dict[str, Any]

class GameStatsResponse(BaseModel):
    id: int
    stats: Dict[str, Any]

class CameraURLsCreate(BaseModel):
    rtsp_url: str
    http_url: str
    Default: bool = False  # New field with default value

class CameraURLsResponse(BaseModel):
    id: int
    rtsp_url: str
    http_url: str
    Default: bool  # New field

# schemas.py


class StreamTargetBase(BaseModel):
    sink: str
    stream_type: str

class StreamTargetUpdate(StreamTargetBase):
    pass

class StreamTargetResponse(StreamTargetBase):
    id: int

    class Config:
        orm_mode = True
