# ffmpeg_post_process.py

import os
import threading
import time
import queue
import subprocess
import logging
from db_recordings import update_chunk_slow_path

logger = logging.getLogger("ffmpeg_post_process")

# 🔥 Limit 2 concurrent ffmpeg encoding processes
semaphore = threading.Semaphore(2)

class SlowMoWorker(threading.Thread):
    def __init__(self, max_retries=3):
        super().__init__(daemon=True)
        self.task_queue = queue.Queue()
        self.running = True
        self.max_retries = max_retries

    def enqueue(self, input_path, output_path, camera_no):
        self.task_queue.put((input_path, output_path, camera_no, 0))

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            try:
                input_path, output_path, camera_no, retry_count = self.task_queue.get(timeout=1)

                if not self.is_valid_file(input_path):
                    continue

                logger.info(f"🎞️ Processing slow motion: {input_path}")

                # 🛡️ Acquire a slot (only 2 can work at same time)
                with semaphore:
                    success = self.generate_slow_motion(input_path, output_path)

                if success:
                    update_chunk_slow_path(input_path, output_path)
                    logger.info(f"✅ Slow motion generated and recorded for {input_path}")
                elif retry_count < self.max_retries:
                    logger.warning(f"🔁 Retrying slow motion for {input_path} (attempt {retry_count + 1})")
                    self.task_queue.put((input_path, output_path, camera_no, retry_count + 1))
                else:
                    logger.error(f"❌ Slow motion generation failed after retries: {input_path}")

            except queue.Empty:
                time.sleep(0.5)
                continue

    def is_valid_file(self, path):
        try:
            result = subprocess.run([
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path
            ], capture_output=True, text=True)
            duration = float(result.stdout.strip())
            if duration < 2.0:
                logger.warning(f"⚠️ Skipping slow motion: video too short ({duration:.2f}s)")
                return False
            return True
        except Exception as e:
            logger.warning(f"❌ Failed to get video info: {e}")
            return False

    def generate_slow_motion(self, input_path, output_path):
        try:
            cmd = [
                "ffmpeg", "-y",
                "-v", "error",
                "-hwaccel", "rkmpp",  # Use Rockchip HW decoder
                "-i", input_path,
                "-filter_complex",
                "[0:v]setpts=2.0*PTS,fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2[v]",
                "-map", "[v]",
                "-c:v", "h264_rkmpp",  # Use Rockchip HW encoder
                "-profile:v", "main",
                "-level", "4.0",
                "-pix_fmt", "yuv420p",
                "-g", "60",
                "-bf", "2",
                "-threads", "2",  # 🧠 Light threading (save CPU for SRT streaming)
                "-movflags", "+faststart",
                "-an",  # no audio
                output_path
            ]

            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Post check
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return self.validate_video(output_path)
            return False

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Hardware encoding failed (code {e.returncode})")
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
        return False

    def validate_video(self, path):
        try:
            subprocess.run(
                ["ffprobe", "-v", "error", path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception:
            logger.error(f"❌ Invalid output video: {path}")
            return False
