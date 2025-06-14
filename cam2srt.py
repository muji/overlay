def create_pipeline(self):
    with self.pipeline_lock:
        if self.pipeline:
            return  # Reuse existing pipeline

        # Load stream target first
        self._load_stream_target()
        if not self.db_sink:
            logger.error("Cannot create pipeline - no stream target configured")
            return

        logger.info(f"Creating pipeline for {self.stream_type} stream to: {self.db_sink}")

        mux_type = "mpegtsmux" if self.stream_type == 'srt' else "flvmux"
        sink_element = "srtsink" if self.stream_type == 'srt' else "rtmpsink"

        # Create main elements
        self.mux = Gst.ElementFactory.make(mux_type, "mux")
        self.sink = Gst.ElementFactory.make(sink_element, "stream_output")

        # MPEG-TS specific configuration (FIXED)
        if mux_type == "mpegtsmux":
            self.mux.set_property("alignment", 7)  # Only valid property for mpegtsmux

        # Sink configuration
        if self.stream_type == 'srt':
            self.sink.set_property("uri", self.db_sink)
            self.sink.set_property("mode", "caller")
            self.sink.set_property("latency", 200)
            self.sink.set_property("sync", False)
            self.sink.set_property("async", False)
        else:
            self.sink.set_property("location", self.db_sink)

        # Initialize pipeline and source map
        self.source_pad_map.clear()
        self.pipeline = Gst.Pipeline.new("main-pipeline")
        self.input_selector = Gst.ElementFactory.make("input-selector", "selector")
        self.pipeline.add(self.input_selector)

        # Create audio test elements
        self.audiotestsrc = Gst.ElementFactory.make("audiotestsrc", "audio_test_source")
        self.audioconvert_audio = Gst.ElementFactory.make("audioconvert", "audio_convert")
        self.audiocaps = Gst.ElementFactory.make("capsfilter", "audio_caps")
        self.audioenc = Gst.ElementFactory.make("voaacenc", "aac_encoder")
        self.aacparse = Gst.ElementFactory.make("aacparse", "aac_parser")
        self.audioqueue = Gst.ElementFactory.make("queue", "audio_queue")

        # Configure audio elements
        if self.audiotestsrc:
            self.audiotestsrc.set_property("wave", 2)  # 2 = sine wave
            self.audiotestsrc.set_property("volume", 0.5)
        if self.audiocaps:
            self.audiocaps.set_property("caps", 
                Gst.Caps.from_string("audio/x-raw,channels=2,rate=48000"))
        if self.audioenc:
            self.audioenc.set_property("bitrate", 128000)

        # RTSP sources setup
        self.rtsp_sources_elements = []
        for idx, rtsp_uri in enumerate(self.rtsp_sources, start=1):
            source = Gst.ElementFactory.make("uridecodebin", f"source{idx}")
            if not source:
                logger.error(f"Failed to create source element for {rtsp_uri}")
                continue
            source.set_property("uri", rtsp_uri)
            source.connect("pad-added", self.on_pad_added, self.input_selector)
            self.pipeline.add(source)
            self.rtsp_sources_elements.append(source)

        # Video processing elements
        self.videoconvert = Gst.ElementFactory.make("videoconvert", "convert")
        self.queue_1 = Gst.ElementFactory.make("queue", "queue_1")
        self.videoscale = Gst.ElementFactory.make("videoscale", "scale")
        self.videorate = Gst.ElementFactory.make("videorate", "rate")
        self.capsfilter = Gst.ElementFactory.make("capsfilter", "caps")
        self.videoconvert2 = Gst.ElementFactory.make("videoconvert", "videoconvert2")
        self.queue2 = Gst.ElementFactory.make("queue", "queue2")
        self.gdkpixbufoverlay = Gst.ElementFactory.make("gdkpixbufoverlay", "overlay")
        self.videoconvert3 = Gst.ElementFactory.make("videoconvert", "videoconvert3")
        self.capsfilter_encoder = Gst.ElementFactory.make("capsfilter", "capsfilter_encoder")
        self.encoder = Gst.ElementFactory.make("mpph264enc", "encoder")
        self.parser = Gst.ElementFactory.make("h264parse", "parser")
        self.queue3 = Gst.ElementFactory.make("queue", "buffer_queue")

        # Video configuration
        self.capsfilter_encoder.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,format=I420,width=1920,height=1080,framerate=30/1")
        )
        self.videorate.set_property("drop-only", True)
        self.encoder.set_property("rc-mode", "cbr")
        self.encoder.set_property("bps", 4000000)
        self.encoder.set_property("gop", 60)
        self.encoder.set_property("profile", "main")
        self.encoder.set_property("level", 40)
        self.encoder.set_property("sei-mode", "one-seq")

        # List of all elements to add to pipeline
        required_elements = [
            # Video elements
            self.videoconvert, self.queue_1, self.videoscale, self.videorate, self.capsfilter,
            self.videoconvert2, self.queue2, self.gdkpixbufoverlay, self.videoconvert3,
            self.capsfilter_encoder, self.encoder, self.parser, self.queue3,
            
            # Audio elements
            self.audiotestsrc, self.audioconvert_audio, self.audiocaps,
            self.audioenc, self.aacparse, self.audioqueue,
            
            # Muxer and sink
            self.mux, self.sink
        ]

        # Add all elements to pipeline with validation
        for element in required_elements:
            if element:
                self.pipeline.add(element)
            else:
                missing_type = type(element).__name__ if element else "Unknown"
                logger.error(f"❌ Failed to create element: {missing_type}")
                sys.exit(1)

        # Link video elements
        self.input_selector.link(self.videoconvert)
        self.videoconvert.link(self.queue_1)
        self.queue_1.link(self.videoscale)
        self.videoscale.link(self.videorate)
        self.videorate.link(self.capsfilter)
        self.capsfilter.link(self.videoconvert2)
        self.videoconvert2.set_property("chroma-mode", 3)
        self.videoconvert2.link(self.queue2)
        self.queue2.link(self.gdkpixbufoverlay)
        self.gdkpixbufoverlay.link(self.videoconvert3)
        self.videoconvert3.link(self.capsfilter_encoder)
        self.capsfilter_encoder.link(self.encoder)
        self.encoder.link(self.parser)
        self.parser.link(self.queue3)
        self.queue3.link(self.mux)

        # Link audio elements
        self.audiotestsrc.link(self.audioconvert_audio)
        self.audioconvert_audio.link(self.audiocaps)
        self.audiocaps.link(self.audioenc)
        self.audioenc.link(self.aacparse)
        self.aacparse.link(self.audioqueue)
        self.audioqueue.link(self.mux)

        # Final link to sink
        self.mux.link(self.sink)

        self.start_graphics_check_thread()