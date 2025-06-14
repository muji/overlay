import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import threading
import time
from datetime import datetime
import os

Gst.init(None)

class AudioRecorder:
    def __init__(self, output_dir="/var/www/html/public/assets/uploads/audio", device="mixed_output.monitor"):
        self.output_dir = output_dir
        self.device = device
        os.makedirs(self.output_dir, exist_ok=True)
        self.pipeline = None
        self.thread = None
        self.loop = None
        self.filename = None

    def start(self):
        self.filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S.m4a")
        full_path = os.path.join(self.output_dir, self.filename)

        pipeline_str = (
            f'pulsesrc device="{self.device}" ! '
            f'audioconvert ! audioresample ! voaacenc ! '
            f'mp4mux faststart=true ! filesink location="{full_path}" async=false'
        )

        self.pipeline = Gst.parse_launch(pipeline_str)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"🎙️ Audio recording started: {full_path}")

    def _run(self):
        self.loop = GLib.MainLoop()

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop.run()

        self.pipeline.set_state(Gst.State.NULL)

    def _on_bus_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            print("📥 EOS received. Finalizing audio file.")
            self.loop.quit()
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"❌ GStreamer Error: {err}, Debug: {debug}")
            self.loop.quit()

    def stop(self):
        if self.pipeline:
            print("📤 Sending EOS to audio pipeline...")
            self.pipeline.send_event(Gst.Event.new_eos())





import time


if __name__ == "__main__":
    print("🔧 Starting test audio recording...")

    recorder = AudioRecorder()
    recorder.start()

    print("⏳ Recording for 10 seconds...")
    time.sleep(10)

    print("🛑 Stopping recorder...")
    recorder.stop()

    print("✅ Test completed. Check output folder.")