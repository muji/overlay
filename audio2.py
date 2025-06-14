import gi
import sys

gi.require_version('Gst', '1.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gst, Gtk, GObject

Gst.init(None)

class AudioMixerApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Orange Pi AAC Audio Mixer")
        self.set_border_width(10)
        self.set_default_size(400, 150)

        # UI Layout
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.add(grid)

        # UDP Volume
        udp_label = Gtk.Label(label="UDP Source Volume")
        self.udp_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01)
        self.udp_scale.set_value(1.0)
        self.udp_scale.connect("value-changed", self.on_udp_volume_changed)
        grid.attach(udp_label, 0, 0, 1, 1)
        grid.attach(self.udp_scale, 1, 0, 2, 1)

        # Mic Volume
        mic_label = Gtk.Label(label="Mic Source Volume")
        self.mic_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01)
        self.mic_scale.set_value(1.0)
        self.mic_scale.connect("value-changed", self.on_mic_volume_changed)
        grid.attach(mic_label, 0, 1, 1, 1)
        grid.attach(self.mic_scale, 1, 1, 2, 1)

        # Start/Stop buttons
        self.start_button = Gtk.Button(label="Start Mixing")
        self.stop_button = Gtk.Button(label="Stop Mixing")
        self.start_button.connect("clicked", self.start_pipeline)
        self.stop_button.connect("clicked", self.stop_pipeline)
        grid.attach(self.start_button, 0, 2, 1, 1)
        grid.attach(self.stop_button, 1, 2, 1, 1)

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

    def start_pipeline(self, button):
        if not self.pipeline:
            self.build_pipeline()
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop_pipeline(self, button):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)

    def on_udp_volume_changed(self, scale):
        volume = scale.get_value()
        if self.udp_vol:
            self.udp_vol.set_property("volume", volume)

    def on_mic_volume_changed(self, scale):
        volume = scale.get_value()
        if self.mic_vol:
            self.mic_vol.set_property("volume", volume)

if __name__ == '__main__':
    app = AudioMixerApp()
    app.connect("destroy", Gtk.main_quit)
    app.show_all()
    Gtk.main()
