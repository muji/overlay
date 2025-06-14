import gi
from audio_pipeline_core import AudioPipeline

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

class AudioMixerGUI:
    def __init__(self):
        self.pipeline = AudioPipeline()
        self.pipeline.start()

        self.window = Gtk.Window(title="Audio Mixer")
        self.window.set_default_size(500, 400)
        self.window.connect("destroy", self.on_window_destroy)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        self.window.add(main_box)

        self.create_mic_controls(main_box)
        self.create_udp_controls(main_box)

        self.window.show_all()

    def create_mic_controls(self, parent):
        frame = Gtk.Frame(label="Microphone")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        frame.add(box)
        parent.pack_start(frame, True, True, 0)

        self.mic_mute = Gtk.ToggleButton(label="Mute")
        self.mic_mute.connect("toggled", self.on_mic_mute_toggled)

        self.mic_gain_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.1, 10.0, 0.1)
        self.mic_gain_scale.set_value(3.0)
        self.mic_gain_scale.connect("value-changed", lambda s: self.pipeline.set_mic_gain(s.get_value()))

        self.mic_threshold_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -80.0, 0.0, 1.0)
        self.mic_threshold_scale.set_value(-40.0)
        self.mic_threshold_scale.connect("value-changed", lambda s: self.pipeline.set_gate_threshold(s.get_value()))

        self.mic_balance_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -1, 1, 0.1)
        self.mic_balance_scale.connect("value-changed", lambda s: self.pipeline.set_mic_panorama(s.get_value()))

        box.pack_start(self.mic_mute, False, False, 0)
        box.pack_start(Gtk.Label(label="Gain"), False, False, 0)
        box.pack_start(self.mic_gain_scale, True, True, 0)
        box.pack_start(Gtk.Label(label="Noise Gate Threshold"), False, False, 0)
        box.pack_start(self.mic_threshold_scale, True, True, 0)
        box.pack_start(Gtk.Label(label="Balance"), False, False, 0)
        box.pack_start(self.mic_balance_scale, True, True, 0)

    def on_mic_mute_toggled(self, button):
        is_muted = button.get_active()
        button.set_label("Unmute" if is_muted else "Mute")
        self.pipeline.mute_mic(is_muted)

    def create_udp_controls(self, parent):
        frame = Gtk.Frame(label="UDP Stream")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        frame.add(box)
        parent.pack_start(frame, True, True, 0)

        self.udp_mute = Gtk.ToggleButton(label="Mute")
        self.udp_mute.connect("toggled", lambda b: self.pipeline.mute_udp(b.get_active()))

        self.udp_volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.01)
        self.udp_volume_scale.set_value(0.5)
        self.udp_volume_scale.connect("value-changed", lambda s: self.pipeline.set_udp_volume(s.get_value()))

        self.udp_balance_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -1, 1, 0.1)
        self.udp_balance_scale.connect("value-changed", lambda s: self.pipeline.set_udp_panorama(s.get_value()))

        box.pack_start(self.udp_mute, False, False, 0)
        box.pack_start(Gtk.Label(label="Volume"), False, False, 0)
        box.pack_start(self.udp_volume_scale, True, True, 0)
        box.pack_start(Gtk.Label(label="Balance"), False, False, 0)
        box.pack_start(self.udp_balance_scale, True, True, 0)

    def on_window_destroy(self, widget):
        self.pipeline.stop()
        Gtk.main_quit()

if __name__ == '__main__':
    gui = AudioMixerGUI()
    Gtk.main()
