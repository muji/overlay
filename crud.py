from sqlalchemy.orm import Session
from models import Graphics, GameStats, CameraURLs, StreamTargets
from exceptions import NotFoundException
# crud.py
from models import UploadedImage
from sqlalchemy.orm import Session
from logging_config import logger
from pathlib import Path  # Add this import
from sqlalchemy import text



from schemas import StreamTargetUpdate
from exceptions import NotFoundException


def get_all_graphics(db: Session):
    logger.info("Fetching all graphics records")
    return db.query(Graphics).all()
# Graphics CRUD
def create_graphics(db: Session, graphics: dict):
    db_graphics = Graphics(
        Gtype=graphics["Gtype"],
        branding=graphics["branding"],
        position=graphics["position"],
        scoreboard_id=graphics["scoreboard_id"],
        url=graphics["url"]  # Add this line
    )
    try:
        logger.info(f"Creating graphics: {graphics}")
        db_graphics = Graphics(**graphics)
        db.add(db_graphics)
        db.commit()
        db.refresh(db_graphics)
        logger.info(f"Graphics created successfully: {db_graphics.id}")
        return db_graphics
    except Exception as e:
        logger.error(f"Error creating graphics: {e}")
        db.rollback()
        raise e

def get_graphics(db: Session, graphics_id: str):
    logger.info(f"Fetching graphics with ID: {graphics_id}")
    graphics = db.query(Graphics).filter(Graphics.id == graphics_id).first()
    if not graphics:
        logger.warning(f"Graphics not found: {graphics_id}")
        raise NotFoundException("Graphics not found")
    return graphics

def update_graphics(db: Session, graphics_id: str, graphics: dict):
    logger.info(f"Updating graphics with ID: {graphics_id}")
    db_graphics = get_graphics(db, graphics_id)
    try:
        for key, value in graphics.items():
            setattr(db_graphics, key, value)
        db.commit()
        db.refresh(db_graphics)
        logger.info(f"Graphics updated successfully: {graphics_id}")
        return db_graphics
    except Exception as e:
        logger.error(f"Error updating graphics: {e}")
        db.rollback()
        raise e

def delete_graphics(db: Session, graphics_id: str):
    logger.info(f"Deleting graphics with ID: {graphics_id}")
    db_graphics = get_graphics(db, graphics_id)
    try:
        db.delete(db_graphics)
        db.commit()
        logger.info(f"Graphics deleted successfully: {graphics_id}")
    except Exception as e:
        logger.error(f"Error deleting graphics: {e}")
        db.rollback()
        raise e

# GameStats CRUD
def create_gamestats(db: Session, gamestats: dict):


    gamestats_exist = db.query(GameStats).filter(GameStats.id == 1).first()
    if gamestats_exist.id < 1:
        try:
            logger.info(f"Creating gamestats: {gamestats}")
            
            db_gamestats = GameStats(**gamestats)
            db.add(db_gamestats)
            db.commit()
            db.refresh(db_gamestats)
            logger.info(f"GameStats created successfully: {db_gamestats.id}")
            return db_gamestats
        except Exception as e:
            logger.error(f"Error creating gamestats: {e}")
            db.rollback()
            raise e
    else:

         logger.info(f"Updating gamestats with ID: {1}")
    db_gamestats = get_gamestats(db, 1)
    try:
        for key, value in gamestats.items():
            setattr(db_gamestats, key, value)
        db.commit()
        db.refresh(db_gamestats)
        logger.info(f"GameStats updated successfully: {1}")
        return db_gamestats
    except Exception as e:
        logger.error(f"Error updating gamestats: {e}")
        db.rollback()
        raise e


def get_gamestats(db: Session, gamestats_id: str):
    logger.info(f"Fetching gamestats with ID: {gamestats_id}")
    gamestats = db.query(GameStats).filter(GameStats.id == gamestats_id).first()
    if not gamestats:
        logger.warning(f"GameStats not found: {gamestats_id}")
        raise NotFoundException("GameStats not found")
    return gamestats

def update_gamestats(db: Session, gamestats_id: str, gamestats: dict):
    logger.info(f"Updating gamestats with ID: {gamestats_id}")
    db_gamestats = get_gamestats(db, 1)
    try:
        for key, value in gamestats.items():
            setattr(db_gamestats, key, value)
        db.commit()
        db.refresh(db_gamestats)
        logger.info(f"GameStats updated successfully: {gamestats_id}")
        return db_gamestats
    except Exception as e:
        logger.error(f"Error updating gamestats: {e}")
        db.rollback()
        raise e

def delete_gamestats(db: Session, gamestats_id: str):
    logger.info(f"Deleting gamestats with ID: {gamestats_id}")
    db_gamestats = get_gamestats(db, 1)
    try:
        db.delete(db_gamestats)
        db.commit()
        logger.info(f"GameStats deleted successfully: {gamestats_id}")
    except Exception as e:
        logger.error(f"Error deleting gamestats: {e}")
        db.rollback()
        raise e

# CameraURLs CRUD

def get_all_cameraurls(db: Session):
    logger.info("Fetching all CameraURLs records")
    return db.query(CameraURLs).all()

def create_cameraurls(db: Session, cameraurls: dict):
    try:
        logger.info(f"Creating cameraurls: {cameraurls}")
        db_cameraurls = CameraURLs(**cameraurls)
        db.add(db_cameraurls)
        db.commit()
        db.refresh(db_cameraurls)
        logger.info(f"CameraURLs created successfully: {db_cameraurls.id}")
        return db_cameraurls
    except Exception as e:
        logger.error(f"Error creating cameraurls: {e}")
        db.rollback()
        raise e

def get_cameraurls(db: Session, cameraurls_id: str):
    logger.info(f"Fetching cameraurls with ID: {cameraurls_id}")
    cameraurls = db.query(CameraURLs).filter(CameraURLs.id == cameraurls_id).first()
    if not cameraurls:
        logger.warning(f"CameraURLs not found: {cameraurls_id}")
        raise NotFoundException("CameraURLs not found")
    return cameraurls

def update_cameraurls(db: Session, cameraurls_id: str, cameraurls: dict):
    logger.info(f"Updating cameraurls with ID: {cameraurls_id}")
    db_cameraurls = get_cameraurls(db, cameraurls_id)
    try:
        for key, value in cameraurls.items():
            setattr(db_cameraurls, key, value)
        db.commit()
        db.refresh(db_cameraurls)
        logger.info(f"CameraURLs updated successfully: {cameraurls_id}")
        return db_cameraurls
    except Exception as e:
        logger.error(f"Error updating cameraurls: {e}")
        db.rollback()
        raise e

def delete_cameraurls(db: Session, cameraurls_id: str):
    logger.info(f"Deleting cameraurls with ID: {cameraurls_id}")
    db_cameraurls = get_cameraurls(db, cameraurls_id)
    try:
        db.delete(db_cameraurls)
        db.commit()
        logger.info(f"CameraURLs deleted successfully: {cameraurls_id}")
    except Exception as e:
        logger.error(f"Error deleting cameraurls: {e}")
        db.rollback()
        raise e
    


# crud.py



def set_default_camera(db: Session, camera_id: int):
    logger.info(f"Setting camera ID {camera_id} as default")

    # Fetch the camera to be set as default
    camera = db.query(CameraURLs).filter(CameraURLs.id == camera_id).first()
    if not camera:
        logger.warning(f"Camera with ID {camera_id} not found")
        raise NotFoundException("Camera not found")

    try:
        # Use text() to properly format SQL statements
        db.execute(text("UPDATE cameraurls SET \"Default\" = FALSE"))
        db.execute(text(f"UPDATE cameraurls SET \"Default\" = TRUE WHERE id = {camera_id}"))
        db.commit()
        db.refresh(camera)
        logger.info(f"Camera ID {camera_id} set as default")
        return camera
    except Exception as e:
        logger.error(f"Error setting default camera: {e}")
        db.rollback()
        raise e

def get_single_stream_target(db: Session):
    target = db.query(StreamTargets).first()
    if not target:
        raise NotFoundException("Stream target not found")
    return target

def update_single_stream_target(db: Session, update_data: StreamTargetUpdate):
    target = get_single_stream_target(db)
    target.sink = update_data.sink
    target.stream_type = update_data.stream_type
    db.commit()
    db.refresh(target)
    return target

# StreamTargets CRUD



def create_uploaded_image(db: Session, image_path: str):
    db_image = UploadedImage(image_path=image_path)
    db.add(db_image)
    db.commit()
    db.refresh(db_image)
    return db_image

def get_uploaded_image(db: Session, image_id: int):
    return db.query(UploadedImage).filter(UploadedImage.id == image_id).first()    


def get_all_uploaded_images(db: Session):
    logger.info("Fetching all uploaded images")
    return db.query(UploadedImage).all()

def delete_all_uploaded_images(db: Session, upload_dir: Path):  # Add Path type hint
    try:
        logger.info("Deleting all uploaded images and files")
        
        # Delete physical files
        for file_path in upload_dir.glob("*"):
            try:
                if file_path.is_file():
                    file_path.unlink()
                    logger.info(f"Deleted file: {file_path}")
            except Exception as e:
                logger.error(f"Error deleting file {file_path}: {e}")
                continue

        # Delete database records
        deleted_count = db.query(UploadedImage).delete()
        db.commit()
        logger.info(f"Deleted {deleted_count} database records")
        
        return {"message": f"Deleted {deleted_count} images and associated files"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error during cleanup: {e}")
        raise e