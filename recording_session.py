# recording_session.py
import os
import threading
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import suppress
import random

import gi
import logging


from db_recordings import (
    add_session, update_session_end_time,
    get_all_recordings, get_active_sessions, get_session_chunks,
    update_chunk_slow_path, add_chunk, update_chunk_end_time,
)


from ffmpeg_post_process import SlowMoWorker

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

Gst.init(None)
Gst.SECOND = 1_000_000_000

logger = logging.getLogger("recording_session")

slowmo_workers = []





AUDIO_CHANNEL_NAME = "gameaudio"
_audio_provider_pipeline = None

def start_shared_audio_provider():
    global _audio_provider_pipeline
    if '_audio_provider_pipeline' in globals() and _audio_provider_pipeline:
        return _audio_provider_pipeline  # Already started

    pipeline = Gst.parse_launch(
        'udpsrc port=5450 buffer-size=262144 caps="audio/mpeg,stream-format=adts,channels=2,rate=44100,mpegversion=4" ! '
        'aacparse ! queue ! avdec_aac ! audioconvert ! audioresample ! queue ! interaudiosink channel=gameaudio sync=false'
    )
    pipeline.set_state(Gst.State.PLAYING)
    _audio_provider_pipeline = pipeline
    print(f"[INFO] Shared audio provider pipeline started on UDP:5450 to interaudiosink:gameaudio")
    return pipeline





def start_slow_motion_worker():
    global slowmo_workers
    if not slowmo_workers:
        slowmo_workers = [SlowMoWorker() for _ in range(4)]  # 4 parallel workers
        for worker in slowmo_workers:
            worker.start()
        logger.info(f"🚀 SlowMoWorkers started: {len(slowmo_workers)} threads")


def stop_slow_motion_worker():
    global slowmo_workers
    for worker in slowmo_workers:
        worker.stop()
    slowmo_workers.clear()
    logger.info("🛑 SlowMoWorkers stopped")


def start_resource_monitor():
    def monitor():
        import psutil
        while True:
            ram = psutil.virtual_memory().percent
            cpu = psutil.cpu_percent(interval=1)
            logger.info(f"📊 RAM Usage: {ram}% | CPU: {cpu}%")
            time.sleep(30)
    threading.Thread(target=monitor, daemon=True).start()



def is_file_stable(file_path, min_duration=2.0):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of",
            "default=noprint_wrappers=1:nokey=1", str(file_path)
        ], capture_output=True, text=True)
        duration = float(result.stdout.strip())
        if duration < min_duration:
            logger.warning(f"⚠️ Skipping slow motion: video too short ({duration:.2f}s)")
            return False
        return True
    except Exception as e:
        logger.warning(f"Failed to probe file {file_path}: {e}")
        return False

class CRecordingSession:
    def __init__(self, token, camera_no, rtsp_url, output_dir="/var/www/html/public/assets/uploads"):
        self.token = token
        self.camera_no = camera_no
        self.rtsp_url = rtsp_url
        self.output_dir = Path(output_dir)
        self.pipeline = None
        self.loop = None
        self.thread = None
        self.running = False
        self.chunk_dir = ''
        add_session(token, camera_no, datetime.now())

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()
        logger.info(f"🎥 Recording thread started for camera {self.camera_no}")

    def _record_loop(self):
        try:
            self._run_pipeline()
        except Exception as e:
            logger.error(f"🔁 Record loop crashed: {e}")

    def ensure_folder_exists(self):
        folder = self.output_dir / f"CAM{self.camera_no}" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        self.chunk_dir = str(folder)
        return self.chunk_dir

################################################################################################################    
    

    def _run_pipeline(self):
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline()

        # === Create video elements ===
        rtspsrc = Gst.ElementFactory.make("rtspsrc", "src")
        depay = Gst.ElementFactory.make("rtph264depay", "depay")
        parse = Gst.ElementFactory.make("h264parse", "parse")
        parse.set_property("config-interval", -1)

        # === Create audio elements (from mixer output via UDP multicast) ===
        udpsrc = Gst.ElementFactory.make("udpsrc", "udpsrc")
        udpsrc.set_property("address", "239.255.12.34")
        udpsrc.set_property("port", 5400)
        udpsrc.set_property("auto-multicast", True)
        # Set audio caps
        caps = Gst.Caps.from_string("audio/x-raw,format=S16LE,channels=2,rate=44100")
        udpsrc.set_property("caps", caps)

        audioconvert = Gst.ElementFactory.make("audioconvert", "audioconvert")
        audioresample = Gst.ElementFactory.make("audioresample", "audioresample")
        voaacenc = Gst.ElementFactory.make("voaacenc", "voaacenc")

        # === Output ===
        splitmuxsink = Gst.ElementFactory.make("splitmuxsink", "splitmuxsink")

        # === Validate all elements ===
        elements = {
            "rtspsrc": rtspsrc, "depay": depay, "parse": parse,
            "udpsrc": udpsrc, "audioconvert": audioconvert,
            "audioresample": audioresample, "voaacenc": voaacenc,
            "splitmuxsink": splitmuxsink
        }

        for name, elem in elements.items():
            if not elem:
                logger.error(f"❌ Failed to create element: {name}")
                return

        # === Configure elements ===
        rtspsrc.set_property("location", self.rtsp_url)
        rtspsrc.set_property("latency", 100)
        rtspsrc.connect("pad-added", self._on_pad_added)

        splitmuxsink.set_property("muxer-factory", "mp4mux")
        splitmuxsink.set_property("max-size-time", 60 * Gst.SECOND)
        splitmuxsink.connect("format-location-full", self._on_format_location)

        # === Add all to pipeline ===
        for elem in elements.values():
            self.pipeline.add(elem)

        # === Link audio chain ===
        if not udpsrc.link(audioconvert):
            logger.error("❌ udpsrc → audioconvert failed")
            return
        if not audioconvert.link(audioresample):
            logger.error("❌ audioconvert → audioresample failed")
            return
        if not audioresample.link(voaacenc):
            logger.error("❌ audioresample → voaacenc failed")
            return

        # === Link video chain ===
        if not depay.link(parse):
            logger.error("❌ depay → parse failed")
            return

        # === Link to splitmuxsink pads ===
        video_pad = splitmuxsink.get_request_pad("video")
        video_src = parse.get_static_pad("src")
        if not video_pad or not video_src:
            logger.error("❌ Missing video pad or parse src pad")
            return
        if video_src.link(video_pad) != Gst.PadLinkReturn.OK:
            logger.error("❌ Failed to link parse → splitmuxsink:video")
            return

        audio_pad = splitmuxsink.get_request_pad("audio_0")
        audio_src = voaacenc.get_static_pad("src")
        if not audio_pad or not audio_src:
            logger.error("❌ Missing audio pad or voaacenc src pad")
            return
        if audio_src.link(audio_pad) != Gst.PadLinkReturn.OK:
            logger.error("❌ Failed to link voaacenc → splitmuxsink:audio_0")
            return

        # === Bus and State ===
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        logger.info(f"🧪 Starting GStreamer pipeline for camera {self.camera_no}")
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            logger.error(f"❌ Failed to set pipeline to PLAYING for camera {self.camera_no}")
            return
        logger.info(f"✅ Pipeline PLAYING for camera {self.camera_no}")

        try:
            self.loop.run()
        except Exception as e:
            logger.error(f"GStreamer loop error: {e}")
        self.pipeline.set_state(Gst.State.NULL)
    
        


    


    def _on_pad_added(self, src, pad):
        depay = self.pipeline.get_by_name("depay")
        if not depay:
            logger.error("❌ depay not found")
            return

        sink_pad = depay.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            if pad.link(sink_pad) == Gst.PadLinkReturn.OK:
                logger.info(f"✅ Linked rtspsrc → depay for camera {self.camera_no}")
            else:
                logger.error("❌ Failed to link rtspsrc → depay")



    
 ################################################################################################   
        

    def _on_format_location(self, mux, fragment_id, _):
        try:
            folder = self.ensure_folder_exists()
            ts = int(time.time())
            file_path = Path(folder) / f"{ts}.mp4"
            add_chunk(self.token, str(file_path), datetime.now(), datetime.now() + timedelta(minutes=5))

            logger.info(f"📁 Started recording chunk: {file_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"❌ Format location error: {e}")
            return "/tmp/fallback.mp4"

    def _on_bus_message(self, bus, message):
        if message.type == Gst.MessageType.ELEMENT:
            s = message.get_structure()
            if s and s.get_name() == "splitmuxsink-fragment-closed":
                chunk_path = s.get_value("location")
                self._finalize_chunk(chunk_path)




    def _finalize_chunk(self, chunk_path):
        logger.info(f"Finalizing chunk: {chunk_path}")

        if not is_file_stable(chunk_path):
            logger.warning(f"Chunk not ready or too small to process: {chunk_path}")
            return

        # ✅ Update actual end time when chunk is finalized
        update_chunk_end_time(chunk_path, datetime.now())

        slow_path = str(chunk_path).replace(".mp4", "_slow.mp4")
        update_chunk_slow_path(chunk_path, slow_path)

       

        if slowmo_workers:
            logger.info(f"📤 Enqueuing for slow motion: {chunk_path}")
            random.choice(slowmo_workers).enqueue(chunk_path, slow_path, self.camera_no)





    def stop(self):
        if self.running:
            self.pipeline.send_event(Gst.Event.new_eos())
            self.running = False
            update_session_end_time(self.token, datetime.now())

    @classmethod
    def get_all_recordings(cls):
        return get_all_recordings()

    @classmethod
    def get_active_recordings(cls):
        active = []
        for s in get_active_sessions():
            token, cam, start = s
            chunks = get_session_chunks(token)
            active.append({"token": token, "camera_no": cam, "session_start": start, "chunks": chunks})
        return active