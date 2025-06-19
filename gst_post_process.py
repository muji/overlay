import os
import threading
import time
import queue
import subprocess
import logging
from db_recordings import update_chunk_slow_path
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

logger = logging.getLogger("gstreamer_post_process")

# 🔥 Limit 2 concurrent GStreamer encoding processes
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
                "gst-discoverer-1.0", path
            ], capture_output=True, text=True)
            if "No such file" in result.stderr or result.returncode != 0:
                logger.warning(f"❌ File not valid or not found: {path}")
                return False

            duration_line = next((line for line in result.stdout.splitlines() if "Duration:" in line), None)
            if duration_line:
                duration_str = duration_line.split("Duration:")[1].split()[0]
                h, m, s = duration_str.split(":")
                duration = int(h) * 3600 + int(m) * 60 + float(s)
                if duration < 2.0:
                    logger.warning(f"⚠️ Skipping slow motion: video too short ({duration:.2f}s)")
                    return False
                return True
            else:
                if os.path.getsize(path) < 1024:
                    logger.warning(f"⚠️ Skipping slow motion: file too small")
                    return False
                return True
        except Exception as e:
            logger.warning(f"❌ Failed to get video info: {e}")
            return False

    def generate_slow_motion(self, input_path, output_path):
        try:
            # Build the GStreamer pipeline as one string!
            gst_cmd = (
                f'gst-launch-1.0 -e '
                f'filesrc location="{input_path}" ! '
                f'qtdemux name=demux '
                f'demux.video_0 ! queue ! h264parse ! mppvideodec ! '
                f'videorate drop-only=false ! video/x-raw,framerate=6/1,width=1920,height=1080 ! '
                f'videorate ! video/x-raw,framerate=25/1 ! '
                f'mpph264enc ! h264parse ! mp4mux ! '
                f'filesink location="{output_path}"'
            )

            result = subprocess.run(gst_cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"❌ GStreamer slow-motion failed (code {result.returncode})")
                logger.error(f"stdout: {result.stdout}")
                logger.error(f"stderr: {result.stderr}")
                return False

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return self.validate_video(output_path)
            return False

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ GStreamer slow-motion failed (code {e.returncode})")
            logger.error(f"stdout: {e.stdout}")
            logger.error(f"stderr: {e.stderr}")
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
        return False    

    def validate_video(self, path):
        try:
            result = subprocess.run(
                ["gst-discoverer-1.0", path],
                capture_output=True, text=True
            )
            if result.returncode == 0 and "video" in result.stdout:
                return True
            else:
                logger.error(f"❌ Invalid output video: {path}")
                logger.error(f"stdout: {result.stdout}")
                logger.error(f"stderr: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Exception validating output video: {e}")
            return False

