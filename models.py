from sqlalchemy import Column, DateTime, Integer, String, JSON, Boolean
from database import Base
from datetime import datetime



class UploadedImage(Base):
    __tablename__ = "uploaded_images"
    id = Column(Integer, primary_key=True, autoincrement=True)
    image_path = Column(String, nullable=False)  # Path to the uploaded image
    created_at = Column(DateTime, default=datetime.utcnow)  # Timestamp

class Graphics(Base):
    __tablename__ = "graphics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    Gtype = Column(String, nullable=False)
    branding = Column(JSON, nullable=False)
    position = Column(String, nullable=False)
    scoreboard_id = Column(Integer, nullable=False)  # New mandatory field
    url = Column(String, nullable=False)  # New field

class GameStats(Base):
    __tablename__ = "gamestats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stats = Column(JSON, nullable=False)

class CameraURLs(Base):
    __tablename__ = "cameraurls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    rtsp_url = Column(String, nullable=False)
    http_url = Column(String, nullable=False)
    Default = Column(Boolean, default=False)  # New field with default value




class StreamTargets(Base):
    __tablename__ = "stream_targets"
    id = Column(Integer, primary_key=True, index=True)
    sink = Column(String, nullable=False)
    stream_type = Column(String, nullable=False)
   