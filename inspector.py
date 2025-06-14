import gi
import time
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

class StreamSwitcher:
    def __init__(self):
        Gst.init(None)

        # Define the GStreamer pipeline with input-selector
        
        self.pipeline = Gst.parse_launch(
            '''
                input-selector name=selector 
                    rtspsrc location=rtsp://192.168.8.50:554/11 is-live=1 latency=500 name=src1 ! \
                    rtph264depay ! h264parse config-interval=1 ! mppvideodec ! videoconvert ! \
                    queue max-size-buffers=2 max-size-bytes=0 leaky=downstream ! \
                    mpph264enc bps=4000000 gop=60 qp-min=18 qp-max=42 rc-mode=1 ! h264parse config-interval=-1 ! \
                    rtph264pay pt=96 ! selector.sink_0 

                    rtspsrc location=rtsp://192.168.8.51:1024/12 is-live=1 latency=500 name=src2 ! \
                    rtph264depay ! h264parse config-interval=1 ! mppvideodec ! videoconvert ! \
                    queue max-size-buffers=2 max-size-bytes=0 leaky=downstream ! \
                    mpph264enc bps=4000000 gop=60 qp-min=18 qp-max=42 rc-mode=1 ! h264parse config-interval=-1 ! \
                    rtph264pay pt=96 ! selector.sink_1 

                selector.src ! queue ! udpsink host=103.217.176.16 port=5010 sync=true async=false
            '''
        )

        self.selector = self.pipeline.get_by_name('selector')

    def switch_to_source(self, source_index):
        """Switch between RTSP sources."""
        pad_name = f'sink_{source_index}'
        pad = self.selector.get_static_pad(pad_name)
        if pad:
            print(f"Switching to source {pad_name}")
            self.selector.set_property('active-pad', pad)

    def run(self):
        """Run the GStreamer pipeline with automatic source switching."""
        self.pipeline.set_state(Gst.State.PLAYING)
        try:
            source_index = 0
            while True:
                self.switch_to_source(source_index)
                source_index = 1 - source_index
                time.sleep(35)
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            print("Pipeline stopped gracefully.")



if __name__ == "__main__":
    switcher = StreamSwitcher()
    switcher.run()
