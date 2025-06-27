from collections import defaultdict
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List
from srt import RTSPtoSRTStreamer

import datetime
from fastapi import Query
from sqlalchemy import text



from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware import Middleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
import uvicorn
from fastapi.responses import RedirectResponse
import os
import crud, schemas
from fastapi.responses import JSONResponse

from typing import List, Optional

import asyncio
from starlette.concurrency import run_in_threadpool




from recording_session import start_slow_motion_worker, start_resource_monitor, start_shared_audio_provider
from audio_mixer import AudioMixer



@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    start_slow_motion_worker()
    start_resource_monitor()

from recording_session import CRecordingSession


from db_recordings import get_chunk_path_by_id, get_chunk_info_by_id
from schemas import (
    UploadedImageResponse,
    GraphicsCreate, GraphicsResponse, GameStatsCreate, GameStatsResponse,
    CameraURLsCreate, CameraURLsResponse
)
from crud import (
    create_graphics, create_uploaded_image, get_graphics, update_graphics, delete_graphics,
    create_gamestats, get_gamestats, update_gamestats, delete_gamestats,
    create_cameraurls, get_cameraurls, update_cameraurls, delete_cameraurls,
    get_all_graphics, get_all_cameraurls, set_default_camera, get_all_uploaded_images,
    delete_all_uploaded_images
)
from exceptions import NotFoundException
from models import Base
from database import engine, SessionLocal
from logging_config import logger
from srt import RTSPtoSRTStreamer


from db_recordings import init_db

# ✅ Initialize database only if missing
if not os.path.exists("recordings.db"):
    print("📁 recordings.db not found. Initializing...")
init_db()

# Initialize directories
# Constants
UPLOAD_DIR = Path("/var/www/html/public/assets/uploads")
RECORDINGS_DIR = UPLOAD_DIR
HLS_DIR = "hls_output"
BASE_URL = "http://103.217.176.16:8080"
#BASE_URL = "http://192.168.8.47:8080"
MAX_RECORDING_AGE = 12 * 3600
MAX_STORAGE_SIZE = 10 * 1024**3
# Create required folders
os.makedirs(UPLOAD_DIR, exist_ok=True)

for cam in range(1, 5):
    cam_path = UPLOAD_DIR / f"CAM{cam}"
    os.makedirs(cam_path, exist_ok=True)
    subprocess.run(["chmod", "755", str(cam_path)])

os.makedirs(UPLOAD_DIR, exist_ok=True)


# Add this cleanup function before the lifespan manager
def cleanup_old_recordings():
    """Background task to delete old recordings and manage storage"""
    while True:
        try:
            now = time.time()
            total_size = 0
            all_files = []
            recordings_dir_str = str(RECORDINGS_DIR)  # Convert to string once

            # 1. Process recordings directory
            for root, dirs, files in os.walk(RECORDINGS_DIR):
                for file in files:
                    file_path = Path(root) / file
                    stat = file_path.stat()
                    all_files.append((file_path, stat.st_mtime, stat.st_size))
                    total_size += stat.st_size

           

            # 3. Delete old files (both recordings and HLS segments)
            deleted_size = 0
            sorted_files = sorted(all_files, key=lambda x: x[1])  # Oldest first

            for file_path, mtime, size in sorted_files:
                try:
                    file_path_str = str(file_path)  # Convert to string for comparison

                    # Check age-based deletion
                    age = now - mtime
                    if age > MAX_RECORDING_AGE:
                        if file_path.exists():
                            file_path.unlink()
                            logger.info(f"Deleted old file: {file_path}")
                            # Only update DB for original recordings
                            if file_path_str.startswith(recordings_dir_str):
                                from db_recordings import delete_chunk_by_path
                                delete_chunk_by_path(file_path_str)
                            total_size -= size
                            deleted_size += size

                    # Check size-based deletion
                    if total_size > MAX_STORAGE_SIZE:
                        if file_path.exists():
                            file_path.unlink()
                            logger.info(f"Deleted oversized file: {file_path}")
                            if file_path_str.startswith(recordings_dir_str):
                                from db_recordings import delete_chunk_by_path
                                delete_chunk_by_path(file_path_str)
                            total_size -= size
                            deleted_size += size

                    # Stop if under limit
                    if total_size <= MAX_STORAGE_SIZE:
                        break

                except Exception as e:
                    logger.error(f"Error deleting {file_path}: {e}")


        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        
        # Run every hour
        time.sleep(3600)
   


##############################################################################################################################3
# Modify the lifespan manager to start recordings and cleanup
# Cleanup logic remains same (unchanged)

   
@asynccontextmanager
async def lifespan(app: FastAPI):
   
    app.state.streamer = RTSPtoSRTStreamer()
  
    app.state.mixer = AudioMixer()
    app.state.mixer.start()

 
    print("🔊 Starting shared UDP audio provider pipeline...")
    start_shared_audio_provider()  # Only runs once, even if called again!
     
    print("📱 SRT Streamer initialized")
    if not os.path.exists("recordings.db"):
        print("📁 recordings.db not found, initializing...")
    init_db()
    start_slow_motion_worker()
    #start_resource_monitor()


    

    db = SessionLocal()
    try:
        cameras = get_all_cameraurls(db)
        app.state.recording_sessions = {}
        for camera in cameras:
            try:
                token = str(uuid.uuid4())
                session = CRecordingSession(
                    token, camera.id, camera.rtsp_url
                )
                session.start()
                app.state.recording_sessions[camera.id] = session
                logger.info(f"Started recording for camera {camera.id}: {camera.rtsp_url}")
            except Exception as e:
                logger.error(f"Failed to start recording for camera {camera.id}: {e}")        


    finally:
        db.close()

    cleanup_thread = threading.Thread(target=cleanup_old_recordings, daemon=True)
    cleanup_thread.start()

    yield

    print("Cleaning up components...")
   
    for session in app.state.recording_sessions.values():
        session.stop()
    if app.state.streamer.is_streaming():
        app.state.streamer.stop_stream()
    if app.state.mixer:
      app.state.mixer.stop()    


  

app = FastAPI(
    redirect_slashes=False,
    lifespan=lifespan,
    middleware=[
        Middleware(GZipMiddleware),
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]
)











# Database setup
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



# ==================== Recording Endpoints ====================


# Add new Pydantic models
class RecordingItemResponse(BaseModel):
    id: str
    url: str

class RecordingChunk(BaseModel):
    chunk_path: str
    slow_chunk_path: Optional[str]
    start_time: str
    end_time: str
    status: str
    camera_no: int

class GetRecordingResponse(BaseModel):
    token: str
    camera_no: int
    session_start: str
    chunks: List[RecordingChunk]


class RecordingItem(BaseModel):
    token: str
    chunk_path: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    status: str
    camera_no: int

class ActiveRecordingStatus(BaseModel):
    token: str
    camera_no: int
    session_start: datetime.datetime
    chunks: List[RecordingItem]


class VolumeRequest(BaseModel):
    volume: float    

sessions = {}


#####################################



@app.get("/get-recording", response_model=dict)
async def get_recording(offset: int = Query(0)):
    """Get recording file URLs (normal and slow motion) per camera based on offset."""
    try:
        if offset > 0:
            return {
                "start": "N/A",
                "end": "N/A",
                "recordings": []
            }

        raw_recordings = CRecordingSession.get_all_recordings()

        parsed_recordings = []
        for rec in raw_recordings:
            try:
                if len(rec) < 7:
                    continue

                start_time = datetime.datetime.fromisoformat(rec[2]) if rec[2] else None
                end_time = datetime.datetime.fromisoformat(rec[3]) if rec[3] else None
                camera_no = int(rec[5]) if rec[5] is not None else None
                if camera_no not in {1, 2, 3, 4}:
                    continue

                parsed_recordings.append({
                    "start_time": start_time,
                    "end_time": end_time,
                    "status": rec[4],
                    "camera_no": camera_no,
                    "chunk_path": rec[1],
                    "slow_chunk_path": rec[6]
                })
            except (ValueError, TypeError):
                continue

        # Organize per camera
        camera_chunks = defaultdict(list)
        for rec in parsed_recordings:
            camera_chunks[rec["camera_no"]].append(rec)

        # Sort latest first
        for cam in camera_chunks:
            camera_chunks[cam].sort(key=lambda x: x["start_time"], reverse=True)

        index = abs(offset)  # Correct handling of offset for recent-to-older

        selected_chunks = []
        for camera_id in [1, 2, 3, 4]:
            chunks = camera_chunks.get(camera_id, [])
            if len(chunks) > index:
                selected_chunks.append(chunks[index])

        # Extract time range from the selected chunks
        valid_starts = [c["start_time"] for c in selected_chunks if c.get("start_time")]
        valid_ends = [c["end_time"] for c in selected_chunks if c.get("end_time")]

        start_str = min(valid_starts).strftime("%H:%M") if valid_starts else "N/A"
        end_str = max(valid_ends).strftime("%H:%M") if valid_ends else "N/A"


        
        def abs_to_url(path):
            if path and os.path.exists(path):
                rel = str(Path(path).relative_to("/var/www/html"))
                return f"{BASE_URL}/{rel}"
            return None






        recordings = []
        for chunk in selected_chunks:
            try:
                cam_id = str(chunk["camera_no"])
                recordings.append({
                    "id": cam_id,
                    "url": abs_to_url(chunk["chunk_path"]),
                    "slow_url": abs_to_url(chunk.get("slow_chunk_path"))
                })
            except Exception as err:
                logger.warning(f"⚠️ Failed to parse recording for cam {chunk.get('camera_no')}: {err}")
                continue

        return {
            "start": start_str,
            "end": end_str,
            "recordings": recordings
        }

    except Exception as e:
        logger.error(f"❌ Error in get_recording: {str(e)}")
        return {
            "start": "N/A",
            "end": "N/A",
            "recordings": []
        }

  

#################################


##################################

@app.get("/recordings", response_model=List[RecordingItem])
def get_all_recordings():
    try:
        return [
            dict(zip(('token', 'chunk_path', 'start_time', 'end_time', 'status', 'camera_no'), row))
            for row in CRecordingSession.get_all_recordings()
        ]
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/active_recordings", response_model=List[ActiveRecordingStatus])
def get_active_recordings():
    try:
        return [{
            'token': s['token'],
            'camera_no': s['camera_no'],
            'session_start': s['session_start'],
            'chunks': [dict(zip(('token', 'chunk_path', 'start_time', 'end_time', 'status', 'camera_no'), c)) 
                      for c in s['chunks']]
        } for s in CRecordingSession.get_active_recordings()]
    except Exception as e:
        raise HTTPException(500, str(e))

# ==================== Mixer Endpoints ====================

""" @app.post("/startMix")
def start_mixing():
    if app.state.mixer:
     app.state.mixer.start()
    return {"status": "Pipeline started"}

@app.post("/stopMix")
def stop_mixing():
    if app.state.mixer:
     app.state.mixer.stop()
    return {"status": "Pipeline stopped"} """

@app.post("/mixer_volume")
def set_udp_volume(request: VolumeRequest):
    if app.state.mixer:
        app.state.mixer.udp_vol.set_property("volume", request.volume) 
    return {"status": f"MIXER volume set to {request.volume}"}

@app.post("/mic_volume")
def set_mic_volume(request: VolumeRequest):
   # app.state.mixer.set_mic_volume(request.volume)
    if app.state.mixer:
        app.state.mixer.mic_vol.set_property("volume", request.volume) 

    return {"status": f"Mic volume set to {request.volume}"}


@app.get("/volume/mixer")
def get_udp_volume():
    if app.state.mixer:
        vol = app.state.mixer.get_current_udp_volume()
        return JSONResponse({"udp_volume": vol})
    return JSONResponse({"error": "Mixer app not ready"}, status_code=500)

@app.get("/volume/mic")
def get_mic_volume():
    if app.state.mixer:
        vol = app.state.mixer.get_current_mic_volume()
        return JSONResponse({"mic_volume": vol})
    return JSONResponse({"error": "Mixer app not ready"}, status_code=500)

# ==================== END Mixer Endpoints ====================

# StreamTargets CRUD Endpoints
@app.get("/streamtarget", response_model=schemas.StreamTargetResponse)
def read_stream_target(db: Session = Depends(get_db)):
    try:
        return crud.get_single_stream_target(db)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))



@app.put("/streamtarget", response_model=schemas.StreamTargetResponse)
def update_stream_target(data: schemas.StreamTargetUpdate, db: Session = Depends(get_db)):
    try:
        logger.info(f"Updating stream target to {data.stream_type}: {data.sink}")
        
        # Store current state before making changes
        current_camera_id = None
        was_streaming = False
        
        if hasattr(app.state, 'streamer') and app.state.streamer is not None:
            # Get current camera ID if available
            if hasattr(app.state.streamer, 'current_source_index') and app.state.streamer.current_source_index is not None:
                current_camera_id = app.state.streamer.current_source_index + 1
                logger.info(f"Current active camera ID: {current_camera_id}")
                
                # Check if streaming is active
                try:
                    was_streaming = app.state.streamer.is_streaming()
                except Exception:
                    was_streaming = False
            
            # Stop the stream properly
            logger.info("Stopping current stream to release resources")
            try:
                app.state.streamer.stop_stream()
                time.sleep(1)  # Small delay to ensure resources are freed
            except Exception as e:
                logger.error(f"Error stopping stream: {str(e)}")
        
        # Update the target in database
        updated_target = crud.update_single_stream_target(db, data)
        logger.info(f"Updated stream target in database: {updated_target.stream_type} => {updated_target.sink}")
        
        # Re-initialize the streamer with new target
        app.state.streamer = RTSPtoSRTStreamer()
        logger.info("Created new streamer instance")
        
        # Only restart if we were streaming before
        if was_streaming and current_camera_id is not None:
            try:
                logger.info(f"Restarting stream with camera ID: {current_camera_id}")
                # Small delay to ensure resources are properly initialized
                time.sleep(1)
                app.state.streamer.switch_stream(current_camera_id)
                logger.info("Stream successfully restarted")
            except Exception as e:
                logger.error(f"Failed to restart stream: {str(e)}")
                # Continue even if restart fails
        
        return updated_target
    except Exception as e:
        logger.error(f"Error updating stream target: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update stream target: {str(e)}")

@app.delete("/uploaded-images/")
def delete_all_images_endpoint(db: Session = Depends(get_db)):
    try:
        return delete_all_uploaded_images(db, UPLOAD_DIR)
    except Exception as e:
        logger.error(f"Error deleting images: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/uploaded-images", response_model=list[UploadedImageResponse])
def get_all_uploaded_images_endpoint(db: Session = Depends(get_db)):
    try:
        images = get_all_uploaded_images(db)
        logger.info(f"Found {len(images)} uploaded images")
        return images
    except Exception as e:
        logger.error(f"Error retrieving images: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve images")

#########################
@app.post("/upload-image", response_model=UploadedImageResponse)
async def upload_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"{timestamp}.{file_extension}"
        file_path = UPLOAD_DIR / unique_filename

        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        # Construct CORRECT URL path
        #http://192.168.100.101:8080/public/assets/uploads/20250321_072826.jpeg
        image_url = f"{BASE_URL}/public/assets/uploads/{unique_filename}"  # Modified this line

        db_image = create_uploaded_image(db, image_path=image_url)
        return db_image
    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload image")

#/var/www/html/public/assets/uploads
################################################


@app.put("/cameraurls/{camera_id}/start-stream", response_model=CameraURLsResponse)
def set_start_camera_endpoint(camera_id: int, db: Session = Depends(get_db)):
    try:
        # First check if camera exists
        logger.info(f"Fetching cameraurls with ID: {camera_id}")
        camera = get_cameraurls(db, camera_id)
        if not camera:
            logger.error(f"Camera not found: {camera_id}")
            raise HTTPException(status_code=404, detail=f"Camera with ID {camera_id} not found")
        
        # Set default camera in database using proper text() wrapper
        try:
            logger.info(f"Setting camera ID {camera_id} as default in database")
            # Use text() to properly format SQL statements
            db.execute(text("UPDATE cameraurls SET \"Default\" = FALSE"))
            db.execute(text(f"UPDATE cameraurls SET \"Default\" = TRUE WHERE id = {camera_id}"))
            db.commit()
            db.refresh(camera)
        except Exception as db_error:
            logger.error(f"Database error: {db_error}")
            db.rollback()
            # Continue even if DB update fails
        
        # Switch the stream
        logger.info(f"Switching to camera ID: {camera_id}")
        
        # Defensive handling of streamer initialization and switch_stream call
        if not hasattr(app.state, 'streamer') or app.state.streamer is None:
            app.state.streamer = RTSPtoSRTStreamer()
            
        try:
            app.state.streamer.switch_stream(camera_id)
        except Exception as e:
            logger.error(f"Error switching stream: {e}")
            # Continue and return camera even if stream switch fails
        
        return camera
        
    except NotFoundException as e:
        logger.error(f"Error setting default camera: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in set_start_camera_endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/stop-stream")
def stop_stream():
    if not app.state.streamer.is_streaming():
        raise HTTPException(status_code=400, detail="No active stream to stop")
    
    app.state.streamer.stop_stream()
    return {"message": "Stream stopped successfully"}

@app.get("/stream-status")
def get_stream_status():
    if app.state.streamer.is_streaming():
        return {"status": "Stream is running"}
    return {"status": "Stream is not running"}




@app.put("/graphics/{graphics_id}/position", response_model=GraphicsResponse)
def update_graphics_position(
    graphics_id: str, 
    position: str,  # Expect position string (e.g., 'tl', 'tr')
    db: Session = Depends(get_db)
):
    # Fetch existing graphics data
    existing = get_graphics(db, graphics_id)
    # Update only the position
    update_data = {"position": position}
    return update_graphics(db, graphics_id, update_data)    

# End of SRT part

# New endpoint to get all graphics
@app.get("/graphics", response_model=list[GraphicsResponse])
def get_all_graphics_endpoint(db: Session = Depends(get_db)):
    graphics = get_all_graphics(db)
    logger.info(f"Found {len(graphics)} graphics records")
    return graphics  # Returns an empty array if no records are found    

# Graphics Endpoints
@app.post("/graphics", response_model=GraphicsResponse)
def create_graphics_endpoint(graphics: GraphicsCreate, db: Session = Depends(get_db)):
    return create_graphics(db, graphics.model_dump())

@app.get("/graphics/{graphics_id}", response_model=GraphicsResponse)
def read_graphics(graphics_id: str, db: Session = Depends(get_db)):
    return get_graphics(db, graphics_id)

@app.put("/graphics/{graphics_id}", response_model=GraphicsResponse)
def update_graphics_endpoint(graphics_id: str, graphics: GraphicsCreate, db: Session = Depends(get_db)):
    return update_graphics(db, graphics_id, graphics.model_dump())

@app.delete("/graphics/{graphics_id}")
def delete_graphics_endpoint(graphics_id: str, db: Session = Depends(get_db)):
    delete_graphics(db, graphics_id)
    # remove overlay 
    return {"message": "Graphics deleted"}



@app.post("/gamestats", response_model=GameStatsResponse)
def create_gamestats_endpoint(gamestats: GameStatsCreate, db: Session = Depends(get_db)):
    return create_gamestats(db, gamestats.model_dump())



@app.get("/gamestats", response_model=GameStatsResponse)
def read_gamestats(db: Session = Depends(get_db)):
    return get_gamestats(db, 1)


@app.put("/gamestats", response_model=GameStatsResponse)
def update_gamestats_endpoint(gamestats: GameStatsCreate, db: Session = Depends(get_db)):
    return update_gamestats(db, 1, gamestats.model_dump())

@app.delete("/gamestats")
def delete_gamestats_endpoint( db: Session = Depends(get_db)):
    delete_gamestats(db, 1)
    return {"message": "GameStats deleted"}

# CameraURLs Endpoints

@app.get("/cameraurls", response_model=list[CameraURLsResponse])
def get_all_cameraurls_endpoint(db: Session = Depends(get_db)):
    cameraurls = get_all_cameraurls(db)
    logger.info(f"Found {len(cameraurls)} CameraURLs records")
    return cameraurls  # Returns an empty array if no records are found

@app.post("/cameraurls", response_model=CameraURLsResponse)
def create_cameraurls_endpoint(cameraurls: CameraURLsCreate, db: Session = Depends(get_db)):
    return create_cameraurls(db, cameraurls.model_dump())

@app.get("/cameraurls/{cameraurls_id}", response_model=CameraURLsResponse)
def read_cameraurls(cameraurls_id: str, db: Session = Depends(get_db)):
    return get_cameraurls(db, cameraurls_id)

@app.put("/cameraurls/{cameraurls_id}", response_model=CameraURLsResponse)
def update_cameraurls_endpoint(cameraurls_id: str, cameraurls: CameraURLsCreate, db: Session = Depends(get_db)):
    return update_cameraurls(db, cameraurls_id, cameraurls.model_dump())

@app.delete("/cameraurls/{cameraurls_id}")
def delete_cameraurls_endpoint(cameraurls_id: str, db: Session = Depends(get_db)):
    delete_cameraurls(db, cameraurls_id)
    return {"message": "CameraURLs deleted"}

@app.put("/cameraurls/{camera_id}/set-default", response_model=CameraURLsResponse)
def set_default_camera_endpoint(camera_id: int, db: Session = Depends(get_db)):
    try:
        cam = get_cameraurls(db, camera_id)
        # Access streamer from app state instead of global variable
        app.state.streamer.switch_stream(camera_id)
        return set_default_camera(db, camera_id)
    except NotFoundException as e:
        logger.error(f"Error setting default camera: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error setting default camera: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8300)    