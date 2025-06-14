import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)

pipeline_str = """
    udpsrc port=5451 caps=audio/mpeg,stream-format=adts,channels=2,rate=44100,mpegversion=4 !
    aacparse !
    avdec_aac !
    audioconvert !
    audioresample !
    autoaudiosink
"""

pipeline = Gst.parse_launch(pipeline_str)
pipeline.set_state(Gst.State.PLAYING)

bus = pipeline.get_bus()
while True:
    msg = bus.timed_pop_filtered(1000000000, Gst.MessageType.ERROR | Gst.MessageType.EOS)
    if msg:
        print("MSG:", msg)
        break

pipeline.set_state(Gst.State.NULL)
