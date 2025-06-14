import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)

class AudioMixer:
    def __init__(self):
        self.pipeline = None
        self.mic_vol = None
        self.udp_vol = None

    def build_pipeline(self):
        pipeline_description = """
            audiomixer name=mix ! tee name=tee \
                tee. ! queue ! audioconvert ! voaacenc bitrate=128000 ! aacparse ! \
                capsfilter caps="audio/mpeg,stream-format=adts" ! tee name=tee2 \
                    tee2. ! queue ! udpsink host=127.0.0.1 port=5450
                    tee2. ! queue ! udpsink host=127.0.0.1 port=5451
                    tee2. ! queue ! udpsink host=127.0.0.1 port=5452
                    tee2. ! queue ! udpsink host=127.0.0.1 port=5453
                    tee2. ! queue ! udpsink host=127.0.0.1 port=5454

            udpsrc port=5400 caps="audio/mpeg,stream-format=adts,channels=2,rate=44100,mpegversion=4" ! \
                aacparse ! avdec_aac ! audioconvert ! audioresample ! volume name=udp_vol ! queue ! mix.

            alsasrc device=plughw:0,0 ! audio/x-raw,rate=44100,channels=2 ! volume name=mic_vol ! queue ! mix.

            audiotestsrc wave=silence is-live=true ! audio/x-raw,rate=44100,channels=2 ! queue ! mix.
        """
        self.pipeline = Gst.parse_launch(pipeline_description)
        self.mic_vol = self.pipeline.get_by_name("mic_vol")
        self.udp_vol = self.pipeline.get_by_name("udp_vol")

    def start(self):
        if not self.pipeline:
            self.build_pipeline()
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)

    def set_udp_volume(self, volume):
        if self.udp_vol:
            self.udp_vol.set_property("volume", float(volume))

    def set_mic_volume(self, volume):
        if self.mic_vol:
            self.mic_vol.set_property("volume", float(volume))

    def get_current_udp_volume(self):
        if self.udp_vol:
            return self.udp_vol.get_property("volume")
        return None

    def get_current_mic_volume(self):
        if self.mic_vol:
            return self.mic_vol.get_property("volume")
        return None
