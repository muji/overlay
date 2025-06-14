import gi
import threading

gi.require_version('Gst', '1.0')
from gi.repository import Gst

class AudioPipeline:
    def __init__(self):
        Gst.init(None)
        self.pipeline = Gst.Pipeline.new("audio-mixer")
        self.create_elements()
        self.link_elements()

    def create_element(self, factory, name):
        element = Gst.ElementFactory.make(factory, name)
        if not element:
            raise RuntimeError(f"Failed to create element {factory} ({name})")
        return element

    def get_available_mic(self):
        return "plughw:CARD=rockchipes8388,DEV=0"

    def create_elements(self):
        # Microphone path
        self.mic_src = self.create_element("alsasrc", "mic_src")
        self.mic_src.set_property("device", self.get_available_mic())

        self.mic_convert = self.create_element("audioconvert", "mic_convert")
        self.mic_resample = self.create_element("audioresample", "mic_resample")
        self.mic_gate = self.create_element("ladspa-gate-1410-so-gate", "mic_gate")
        self.mic_amplify = self.create_element("volume", "mic_amplify")
        self.mic_queue = self.create_element("queue", "mic_queue")
        self.mic_panorama = self.create_element("audiopanorama", "mic_panorama")

        # UDP Opus input
        self.udp_src = self.create_element("udpsrc", "udp_src")
        self.udp_src.set_property("port", 5001)
        self.udp_src.set_property("caps", Gst.Caps.from_string(
            "application/x-rtp, media=audio, encoding-name=OPUS, payload=96"))

        self.rtp_depay = self.create_element("rtpopusdepay", "rtp_depay")
        self.opus_dec = self.create_element("opusdec", "opus_dec")
        self.udp_convert = self.create_element("audioconvert", "udp_convert")
        self.udp_resample = self.create_element("audioresample", "udp_resample")
        self.udp_queue = self.create_element("queue", "udp_queue")
        self.udp_volume = self.create_element("volume", "udp_volume")
        self.udp_panorama = self.create_element("audiopanorama", "udp_panorama")

        # Mixer
        self.mixer = self.create_element("audiomixer", "mixer")

        # AAC + ADTS stream output
        self.aac_enc = self.create_element("voaacenc", "aac_enc")
        self.aac_parse = self.create_element("aacparse", "aac_parse")
        self.caps_filter = self.create_element("capsfilter", "caps")
        self.caps_filter.set_property("caps", Gst.Caps.from_string(
            "audio/mpeg, mpegversion=4, stream-format=adts"))

        self.udp_sink = self.create_element("udpsink", "udp_sink")
        self.udp_sink.set_property("host", "192.168.100.99")  # Or your Wowza server IP
        self.udp_sink.set_property("port", 5000)
        self.udp_sink.set_property("sync", False)
        self.udp_sink.set_property("async", False)

        elements = [
            self.mic_src, self.mic_convert, self.mic_resample, self.mic_gate,
            self.mic_amplify, self.mic_queue, self.mic_panorama,
            self.udp_src, self.rtp_depay, self.opus_dec, self.udp_convert,
            self.udp_resample, self.udp_queue, self.udp_volume, self.udp_panorama,
            self.mixer, self.aac_enc, self.aac_parse, self.caps_filter, self.udp_sink
        ]

        for elem in elements:
            self.pipeline.add(elem)

        self.set_initial_properties()

    def set_initial_properties(self):
        self.mic_gate.set_property("threshold", -40.0)
        self.mic_gate.set_property("attack", 10.0)
        self.mic_gate.set_property("decay", 200.0)
        self.mic_gate.set_property("hold", 100.0)
        self.mic_amplify.set_property("volume", 3.0)
        self.udp_volume.set_property("volume", 0.5)

    def link_elements(self):
        # Microphone path
        self.mic_src.link(self.mic_convert)
        self.mic_convert.link(self.mic_resample)
        self.mic_resample.link(self.mic_gate)
        self.mic_gate.link(self.mic_amplify)
        self.mic_amplify.link(self.mic_queue)
        self.mic_queue.link(self.mic_panorama)
        self.mic_panorama.link(self.mixer)

        # UDP Opus path
        self.udp_src.link(self.rtp_depay)
        self.rtp_depay.link(self.opus_dec)
        self.opus_dec.link(self.udp_convert)
        self.udp_convert.link(self.udp_resample)
        self.udp_resample.link(self.udp_queue)
        self.udp_queue.link(self.udp_volume)
        self.udp_volume.link(self.udp_panorama)
        self.udp_panorama.link(self.mixer)

        # Mixer to ADTS AAC
        self.mixer.link(self.aac_enc)
        self.aac_enc.link(self.aac_parse)
        self.aac_parse.link(self.caps_filter)
        self.caps_filter.link(self.udp_sink)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)

    # Public controls
    def set_mic_gain(self, value: float):
        self.mic_amplify.set_property("volume", value)

    def mute_mic(self, mute: bool):
        self.mic_amplify.set_property("mute", mute)

    def set_gate_threshold(self, value: float):
        self.mic_gate.set_property("threshold", value)

    def set_mic_panorama(self, value: float):
        self.mic_panorama.set_property("panorama", value)

    def set_udp_volume(self, value: float):
        self.udp_volume.set_property("volume", value)

    def mute_udp(self, mute: bool):
        self.udp_volume.set_property("mute", mute)

    def set_udp_panorama(self, value: float):
        self.udp_panorama.set_property("panorama", value)