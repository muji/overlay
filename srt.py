# srt.py (updated)
import os
import sys
import uuid
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import threading
import time
from playwright.sync_api import sync_playwright  # Use sync API
from pathlib import Path

from sqlalchemy import event
from models import Graphics
from sqlalchemy.orm import Session, object_session
import json
from database import SessionLocal  # Import the database session

import logging
from crud import get_all_cameraurls
from database import SessionLocal

from database import SessionLocal

from exceptions import NotFoundException

import crud




# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="overlay.log"
)
logger = logging.getLogger("overlay")



#BASE_URL = "http://192.168.8.47:8080"
BASE_URL =  "http://103.217.176.16:8080"

class RTSPtoSRTStreamer:
    def __init__(self, stream_targets_id: int = 1):  # Default to ID 1
        Gst.init(None)
        self.pipeline_lock = threading.Lock()
        self.stream_targets_id = stream_targets_id
        self.db_sink = None  # Will be set from database
        self.stream_type = None
        self.pipeline = None
        self.loop = None
        self.overlay = None
        self.overlay_postition = None
        self.thread = None
        self.screenshot_thread = None
        self.running = False
        self.overlay_running = False       
        self.snap_folder = Path("url_shots")
        self.input_selector = None  # Input selector element       
        self.url = ''
        self.height  =450
        self.width  =150
        self.loop = None          
        self.thread = None  # Thread for running the main loop
        
        self.srt_sink = None  # Will be set from database
        self.rtmp_sink = None  # Will be set from database
        self.sink = None 
        self.mux = None
        self.sink = None   
        self.source_pad_map = {}  # Stores mapping of RTSP source URI to input-selector sink pads
        if not self.check_gst_elements():
            logger.warning("Some GStreamer elements are missing, pipeline creation may fail")

        # Fetch RTSP URLs from the database
        db = SessionLocal()
        try:
            camera_urls = get_all_cameraurls(db)
            self.rtsp_sources = [url.rtsp_url for url in camera_urls]
            if not self.rtsp_sources:
                logger.warning("No RTSP URLs found in the database")
        except Exception as e:
            logger.error(f"Error fetching RTSP URLs: {e}")
            raise
        finally:
            db.close()

        self.current_source_index = 0
       


    def _load_stream_target(self):
        db = SessionLocal()
        try:
            target = crud.get_single_stream_target(db)
            self.db_sink = target.sink
            self.stream_type = target.stream_type
            logger.info(f"Loaded stream target (ID: {self.stream_targets_id}): {self.stream_type} => {self.db_sink}")
            
            # Validate sink format
            if "://" not in self.db_sink:
                logger.error(f"Invalid sink format: {self.db_sink}")
                raise ValueError("Sink must be in protocol://address format (e.g., srt://IP:PORT)")
                
        except Exception as e:
            logger.error(f"Critical error loading stream target: {str(e)}")
            raise





    ##############################################################################




    def create_pipeline(self):
        """Create the GStreamer pipeline for RTSP to SRT/RTMP conversion with overlay support.
        
        Returns:
            bool: True if pipeline created successfully, False otherwise
        """
        with self.pipeline_lock:
            try:
                if self.pipeline:
                    logger.info("Pipeline already exists, reusing")
                    return True  # Reuse existing pipeline

                self._load_stream_target()
                if not self.db_sink:
                    logger.error("Cannot create pipeline - no stream target configured")
                    return False

                logger.info(f"Creating pipeline for {self.stream_type} stream to: {self.db_sink}")

                mux_type = "mpegtsmux" if self.stream_type == 'srt' else "flvmux"
                sink_element = "srtsink" if self.stream_type == 'srt' else "rtmpsink"

                self.mux = Gst.ElementFactory.make(mux_type, "mux")
                self.sink = Gst.ElementFactory.make(sink_element, "stream_output")

                # Configure muxer based on stream type
                if mux_type == "mpegtsmux":
                    self.mux.set_property("alignment", 7)
                elif mux_type == "flvmux":
                    # IMPORTANT: Set streamable mode for RTMP live streaming
                    self.mux.set_property("streamable", True)

                # Configure sink based on stream type
                if self.stream_type == 'srt':
                    self.sink.set_property("uri", self.db_sink)
                    self.sink.set_property("mode", "caller")
                    self.sink.set_property("latency", 600)    # 600 ms latency
                    self.sink.set_property("sync", False)
                    self.sink.set_property("async", False)
                else:  # RTMP
                    self.sink.set_property("location", self.db_sink)
                    # IMPORTANT: Disable sync for RTMP streaming
                    self.sink.set_property("sync", False)

                # Initialize pipeline and basic elements
                self.source_pad_map.clear()
                self.pipeline = Gst.Pipeline.new("main-pipeline")
                self.input_selector = Gst.ElementFactory.make("input-selector", "selector")
                self.pipeline.add(self.input_selector)

                # Create RTSP source elements
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

                # --- Video Elements ---
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

                # --- Extra queues for buffering ---
                self.queue_video1 = Gst.ElementFactory.make("queue", "queue_video1")
                self.queue_video2 = Gst.ElementFactory.make("queue", "queue_video2")  # Before mux

                # --- Audio Elements ---
                self.udpsrc_audio = Gst.ElementFactory.make("udpsrc", "udpsrc_audio")
                self.audioconvert = Gst.ElementFactory.make("audioconvert", "audioconvert")
                self.audioresample = Gst.ElementFactory.make("audioresample", "audioresample")
                self.voaacenc = Gst.ElementFactory.make("voaacenc", "voaacenc")
                self.aacparse = Gst.ElementFactory.make("aacparse", "aacparse")
                self.audio_queue1 = Gst.ElementFactory.make("queue", "audio_queue1")
                self.audio_queue2 = Gst.ElementFactory.make("queue", "audio_queue2")  # Before mux

                # --- Set caps and encoder properties ---
                self.capsfilter_encoder.set_property(
                    "caps",
                    Gst.Caps.from_string("video/x-raw,format=I420,width=1920,height=1080,framerate=30/1")
                )
                self.videorate.set_property("drop-only", True)
                self.encoder.set_property("rc-mode", "cbr")
                self.encoder.set_property("bps", 4000000)
                self.encoder.set_property("gop", 60)
                self.encoder.set_property("profile", "main")
                self.encoder.set_property("level", 40)  # 4.0 for 1080p 30fps
                self.encoder.set_property("sei-mode", "one-seq")

                # AUDIO CHAIN: set UDP, voaacenc, buffering
                self.udpsrc_audio.set_property("address", "239.255.12.34")
                self.udpsrc_audio.set_property("port", 5400)
                self.udpsrc_audio.set_property("auto-multicast", True)
                self.udpsrc_audio.set_property("buffer-size", 2097152)  # 2MB buffer for UDP

                self.udpsrc_audio.set_property("caps", Gst.Caps.from_string(
                    "audio/x-raw,format=S16LE,channels=2,rate=44100"
                ))
                self.voaacenc.set_property("bitrate", 128000)

                # --- Deep buffering for all queues ---
                for q in [
                    self.queue_1, self.queue2, self.queue3,
                    self.queue_video1, self.queue_video2,
                    self.audio_queue1, self.audio_queue2
                ]:
                    q.set_property("max-size-buffers", 0)
                    q.set_property("max-size-bytes", 0)
                    q.set_property("max-size-time", 15 * 1000000000)  # 15 seconds (nanoseconds)

                # Collect all elements that need to be added to pipeline
                elements = [
                    self.videoconvert, self.queue_1, self.videoscale, self.videorate, self.capsfilter,
                    self.videoconvert2, self.queue2, self.gdkpixbufoverlay, self.videoconvert3,
                    self.capsfilter_encoder, self.encoder, self.parser, self.queue3,
                    self.queue_video1, self.queue_video2,
                    self.udpsrc_audio, self.audioconvert, self.audioresample, self.voaacenc,
                    self.aacparse, self.audio_queue1, self.audio_queue2,
                    self.mux, self.sink
                ]

                # Check if all elements were created successfully
                failure = False
                failed_elements = []
                for element in elements:
                    if not element:
                        failure = True
                        element_name = [name for name, obj in list(locals().items()) if obj is element]
                        failed_elements.append(str(element_name))

                if failure:
                    logger.error(f"Failed to create elements: {', '.join(failed_elements)}")
                    return False

                if not self.rtsp_sources_elements:
                    logger.error("No RTSP source elements were created")
                    return False

                # Add all elements to pipeline
                for element in elements:
                    self.pipeline.add(element)

                # --- VIDEO LINKING (add deep buffering before mux) ---
                try:
                    # Chain 1: Input selector to encoder
                    self.input_selector.link(self.videoconvert)
                    self.videoconvert.link(self.queue_1)
                    self.queue_1.link(self.videoscale)
                    self.videoscale.link(self.videorate)
                    self.videorate.link(self.capsfilter)
                    self.capsfilter.link(self.videoconvert2)
                    
                    # Configure videoconvert2 if needed (chroma mode)
                    if hasattr(self.videoconvert2.props, "chroma-mode"):
                        self.videoconvert2.set_property("chroma-mode", 3)
                    
                    # Continue the chain
                    self.videoconvert2.link(self.queue2)
                    self.queue2.link(self.gdkpixbufoverlay)
                    self.gdkpixbufoverlay.link(self.videoconvert3)
                    self.videoconvert3.link(self.capsfilter_encoder)
                    self.capsfilter_encoder.link(self.encoder)
                    self.encoder.link(self.parser)
                    self.parser.link(self.queue3)
                    self.queue3.link(self.queue_video1)
                    self.queue_video1.link(self.queue_video2)
                    
                    # Link to muxer (handle different muxer types)
                    if mux_type == "mpegtsmux":
                        video_pad = self.mux.get_request_pad("video_%u")
                        if video_pad:
                            self.queue_video2.get_static_pad("src").link(video_pad)
                        else:
                            logger.warning("mpegtsmux has no video_%u pad – linking generically")
                            self.queue_video2.link(self.mux)
                    else:  # flvmux
                        video_pad = self.mux.get_request_pad("video")
                        if video_pad:
                            self.queue_video2.get_static_pad("src").link(video_pad)
                        else:
                            logger.warning("flvmux has no video pad – using generic link")
                            self.queue_video2.link(self.mux)

                    # --- AUDIO LINKING (add deep buffering before mux) ---
                    self.udpsrc_audio.link(self.audioconvert)
                    self.audioconvert.link(self.audioresample)
                    self.audioresample.link(self.voaacenc)
                    self.voaacenc.link(self.aacparse)
                    self.aacparse.link(self.audio_queue1)
                    self.audio_queue1.link(self.audio_queue2)

                    # Link audio to muxer (handle different muxer types)
                    if mux_type == "mpegtsmux":
                        audio_pad = self.mux.get_request_pad("audio_%u")
                        if audio_pad:
                            self.audio_queue2.get_static_pad("src").link(audio_pad)
                        else:
                            logger.warning("mpegtsmux has no audio_%u pad – linking generically")
                            self.audio_queue2.link(self.mux)
                    else:  # flvmux
                        audio_pad = self.mux.get_request_pad("audio")
                        if audio_pad:
                            self.audio_queue2.get_static_pad("src").link(audio_pad)
                        else:
                            logger.warning("flvmux has no audio pad – using generic link")
                            self.audio_queue2.link(self.mux)

                    # Link muxer to sink
                    if not self.mux.link(self.sink):
                        logger.error(f"Failed to link {mux_type} to {sink_element}")
                        return False
                        
                except Exception as e:
                    logger.error(f"Error linking pipeline elements: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return False

                # Setup bus message monitoring
                bus = self.pipeline.get_bus()
                bus.add_signal_watch()
                bus.connect("message", self._on_message)

                # Start the graphics check thread if needed
                self.start_graphics_check_thread()

                logger.info("Pipeline created successfully")
                return True
                
            except Exception as e:
                logger.error(f"Exception creating pipeline: {e}")
                import traceback
                logger.error(traceback.format_exc())
                
                # Clean up any partially created pipeline
                if hasattr(self, 'pipeline') and self.pipeline:
                    self.pipeline.set_state(Gst.State.NULL)
                    self.pipeline = None
                    
                return False




    def check_gst_elements(self):
        """Check if all required GStreamer elements are available."""
        required_elements = [
            "uridecodebin", "input-selector", "mpegtsmux", "flvmux", 
            "srtsink", "rtmpsink", "videoconvert", "x264enc", "h264parse",
            "udpsrc", "audioconvert", "voaacenc", "aacparse", "queue"
        ]
        
        missing_elements = []
        for element in required_elements:
            if not Gst.ElementFactory.find(element):
                missing_elements.append(element)
        
        if missing_elements:
            logger.error(f"Missing GStreamer elements: {', '.join(missing_elements)}")
            logger.error("Please install the required GStreamer plugins")
            return False
        else:
            logger.info("All required GStreamer elements are available")
            return True



    def on_bus_message(self, bus, message):
        """Handle GStreamer bus messages with improved debugging."""
        t = message.type
        
        if t == Gst.MessageType.EOS:
            logger.info("End-of-stream received")
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old_state, new_state, pending_state = message.parse_state_changed()
                logger.info(f"Pipeline state changed: {old_state.value_nick} → {new_state.value_nick} [pending: {pending_state.value_nick}]")
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            element_name = message.src.get_name() if message.src else "unknown"
            logger.error(f"GStreamer Error from {element_name}: {err.message}")
            logger.error(f"Debug info: {debug}")
            
            # Additional debugging information for specific error types
            if "No such element" in str(err) or "not found" in str(err):
                logger.error("Missing GStreamer element. Make sure all required GStreamer plugins are installed.")
                # List missing plugins if available
                if hasattr(err, 'domain') and err.domain == "gst-missing-plugin-error-quark":
                    missing = err.message.split(":")[-1].strip()
                    logger.error(f"Missing plugin: {missing}")
                    
            elif "negotiation" in str(err) or "caps" in str(err):
                logger.error("Format negotiation error. Check caps compatibility between elements.")
                
            elif "resource" in str(err):
                logger.error("Resource error. Check if sources/sinks are accessible and protocols are supported.")
                
        elif t == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            element_name = message.src.get_name() if message.src else "unknown"
            # Filter out common latency warnings to reduce noise
            if "latency" not in str(err):
                logger.warning(f"GStreamer Warning from {element_name}: {err.message}")
                logger.warning(f"Debug info: {debug}")



    def on_pad_added(self, src, pad, selector):
            try:
                logger.info(f"🧩 on_pad_added called from {src.get_name()}")

                # Get the pad's current caps to determine media type
                pad_caps = pad.get_current_caps()
                if not pad_caps:
                    logger.warning(f"❌ No caps found for pad from {src.get_name()}")
                    return

                pad_structure = pad_caps.get_structure(0)
                media_type = pad_structure.get_name()
                caps_str = pad_structure.to_string()

                logger.info(f"📦 Pad caps: {caps_str}")

                # Only handle video pads
                if "video" not in media_type:
                    logger.warning(f"⛔ Ignoring non-video pad from {src.get_name()} with media type: {media_type}")
                    return

                # Get the RTSP URI from the uridecodebin element
                uri = src.get_property("uri")
                if not uri:
                    logger.error("❌ Could not get URI from source element")
                    return

                logger.info(f"🔗 Handling pad from source URI: {uri}")

                sink_pad = None
                try:
                    # Request a new pad from the input-selector
                    sink_pad = selector.get_request_pad("sink_%u")
                    if not sink_pad:
                        logger.error(f"❌ Failed to get sink pad for {uri}")
                        return

                    logger.info(f"✅ Requested sink pad {sink_pad.get_name()} for {uri}")

                    # Attempt to link the pads
                    link_result = pad.link(sink_pad)
                    if link_result != Gst.PadLinkReturn.OK:
                        logger.error(f"❌ Failed to link pads from {uri} to {sink_pad.get_name()}")
                        selector.release_request_pad(sink_pad)
                        return

                    # Store the mapping using URI as key
                    self.source_pad_map[uri] = sink_pad
                    logger.info(f"✅ Successfully linked {uri} to {sink_pad.get_name()}")

                    # If this is the current source, activate the pad
                    if uri == self.rtsp_sources[self.current_source_index]:
                        pipeline_state = self.pipeline.get_state(0).state
                        if pipeline_state == Gst.State.PLAYING:
                            selector.set_property("active-pad", sink_pad)
                            logger.info(f"🎬 Set active pad to {uri}")
                        else:
                            logger.warning("⏸️ Pipeline not in PLAYING state, deferring active pad selection")

                except Exception as e:
                    logger.error(f"⚠️ Exception while linking pads for {uri}: {str(e)}")
                    if sink_pad:
                        selector.release_request_pad(sink_pad)
                    raise

            except Exception as e:
                logger.error(f"⚠️ Critical error in on_pad_added: {str(e)}")
                raise

    #########################################################

    def stop_stream(self):
        """Stop the pipeline and release resources efficiently."""
        if not self.pipeline:
            return

        with self.pipeline_lock:
            try:
                # First stop the resource-intensive screenshot thread
                self.stop_screenshot_capture()
                logger.info("Stopping pipeline...")
                
                # Send EOS signal first for clean shutdown
                self.pipeline.send_event(Gst.Event.new_eos())
                
                # Give a short timeout for EOS to propagate (useful for embedded systems)
                timeout = 0.5  # seconds
                start_time = time.time()
                while time.time() - start_time < timeout:
                    msg = self.pipeline.get_bus().pop_filtered(
                        Gst.MessageType.EOS | Gst.MessageType.ERROR)
                    if msg:
                        break
                    time.sleep(0.05)
                    
                # Force state change to NULL (stops pipeline)
                self.pipeline.set_state(Gst.State.NULL)
                
                # For embedded systems, explicitly null out references to free memory
                # This helps prevent memory leaks on resource-constrained boards
                self.input_selector = None
                self.rtsp_sources_elements = []
                self.source_pad_map.clear()
                self.mux = None
                self.sink = None
                self.pipeline = None
                
                if self.loop:
                    self.loop.quit()
                    self.loop = None
                    
                # Force garbage collection on memory-constrained systems
                import gc
                gc.collect()
                    
                logger.info("Pipeline stopped and resources released")
                
            except Exception as e:
                logger.error(f"Error stopping pipeline: {e}")


  

#############################################################




    def switch_stream(self, cam_id):
        """
        Switch to a different camera source by ID.
        
        Args:
            cam_id (int): Camera ID (1-based index)
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Attempting to switch stream to camera ID: {cam_id}")
        
        try:
            # Validate camera ID and RTSP sources
            if not self.rtsp_sources:
                logger.error("No RTSP sources configured in the database!")
                return False
                
            # Validate and convert cam_id if needed
            try:
                cam_id = int(cam_id)
            except (ValueError, TypeError):
                logger.error(f"Invalid cam_id type: {type(cam_id)}. Expected integer.")
                return False
                
            if cam_id < 1 or cam_id > len(self.rtsp_sources):
                logger.error(f"Invalid cam_id: {cam_id}. Must be between 1 and {len(self.rtsp_sources)}")
                return False
            
            # Update the current source index (zero-based index)
            self.current_source_index = cam_id - 1
            source_uri = self.rtsp_sources[self.current_source_index]
            logger.info(f"Switching to camera ID: {cam_id}, URI: {source_uri}")
        
            # Create pipeline if it doesn't exist
            if not self.pipeline:
                logger.info("Pipeline doesn't exist, creating new pipeline")
                pipeline_created = self.create_pipeline()
                if not pipeline_created:
                    logger.error("Failed to create pipeline for stream switching")
                    return False
            
            # Start pipeline thread if not already running
            if not (self.thread and self.thread.is_alive()):
                logger.info("Starting pipeline thread")
                thread_started = self._start_pipeline_thread()
                if not thread_started:
                    logger.error("Failed to start pipeline thread")
                    return False
            
            # Ensure pipeline is in PLAYING state
            if self.pipeline.get_state(0)[1] != Gst.State.PLAYING:
                logger.info("Setting pipeline to PLAYING state")
                state_change = self.pipeline.set_state(Gst.State.PLAYING)
                if state_change == Gst.StateChangeReturn.FAILURE:
                    logger.error("Failed to set pipeline to PLAYING state")
                    return False
            
            # Wait for pad negotiation (with incremental backoff)
            initial_delay = 1.0  # Start with 1 second
            max_delay = 5.0      # Cap at 5 seconds
            current_delay = initial_delay
            total_wait = 0
            max_total_wait = 15.0  # Maximum total time to wait
            
            pad_found = False
            start_time = time.time()
            
            while time.time() - start_time < max_total_wait:
                # Check if our source pad is available
                if source_uri in self.source_pad_map:
                    new_pad = self.source_pad_map[source_uri]
                    
                    # Validate the pad before using it
                    if new_pad and new_pad.get_parent() == self.input_selector:
                        logger.info(f"Found valid pad for {source_uri}, switching streams")
                        
                        # Get current pipeline state to ensure we're in a good state to switch
                        state_result, state, pending = self.pipeline.get_state(0)
                        if state_result != Gst.StateChangeReturn.SUCCESS:
                            logger.warning(f"Pipeline state query returned: {state_result}")
                        
                        if state == Gst.State.PLAYING:
                            try:
                                # Set active pad (this is the actual stream switch)
                                self.input_selector.set_property("active-pad", new_pad)
                                logger.info(f"Successfully switched to camera {cam_id}")
                                
                                # Update default camera in database if needed
                                try:
                                    db = SessionLocal()
                                    crud.set_default_camera(db, cam_id)
                                    db.close()
                                except Exception as e:
                                    logger.warning(f"Failed to update default camera in database: {e}")
                                
                                pad_found = True
                                break
                            except Exception as e:
                                logger.error(f"Error setting active pad: {e}")
                                return False
                        else:
                            logger.warning(f"Pipeline not in PLAYING state, current state: {state}")
                
                # Wait and increase delay (backoff)
                time.sleep(current_delay)
                total_wait += current_delay
                current_delay = min(current_delay * 1.5, max_delay)  # Exponential backoff, capped
                logger.info(f"Waiting for pad from {source_uri}, elapsed wait: {total_wait:.1f}s")
            
            if not pad_found:
                logger.error(f"Failed to find valid pad for {source_uri} after {total_wait:.1f} seconds")
                
                # Fall back to first camera as a last resort
                if self.current_source_index != 0:  # If we're not already on camera 1
                    logger.info("Attempting to fall back to camera 1")
                    self.current_source_index = 0
                    fallback_uri = self.rtsp_sources[0]
                    
                    if fallback_uri in self.source_pad_map:
                        fallback_pad = self.source_pad_map[fallback_uri]
                        if fallback_pad and fallback_pad.get_parent() == self.input_selector:
                            self.input_selector.set_property("active-pad", fallback_pad)
                            logger.info("Successfully fell back to camera 1")
                            return True
                
                # If we get here, even the fallback failed
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error switching stream: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False  






##################################--------------Threads---------######################################

    def _run_pipeline(self):
        if not self.pipeline:
            logger.error("Cannot run pipeline - pipeline is None")
            return
            
        # Add message bus monitoring
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

        # Start state monitoring thread
        state_thread = threading.Thread(target=self._watch_pipeline_state, daemon=True)
        state_thread.start()
        
        # Run main loop
        if self.loop:
            self.loop.run()
        else:
            logger.error("Cannot run pipeline - GLib loop is None")
    
    def _watch_pipeline_state(self):
        """Monitor pipeline state transitions with timeout"""
        start_time = time.time()
        timeout = 10  # Seconds
        
        while self.running:
            if not self.pipeline:
                return
                
            state = self.pipeline.get_state(Gst.CLOCK_TIME_NONE)[1]
            if state == Gst.State.PLAYING:
                logger.info("Pipeline successfully started")
                return
                
            if time.time() - start_time > timeout:
                logger.error("Pipeline startup timed out after 10 seconds")
                self.stop_stream()
                return
                
            logger.info(f"Current pipeline state: {state.value_nick.upper()}")
            time.sleep(0.5)

    def _on_message(self, bus, message):
        mtype = message.type
        if mtype == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"GStreamer ERROR: {err.message}")
            logger.error(f"Debug info: {debug}")
        elif mtype == Gst.MessageType.STATE_CHANGED:
            old, new, pending = message.parse_state_changed()
            logger.info(f"State changed: {old.value_nick.upper()} -> {new.value_nick.upper()}")    


    def start_graphics_check_thread(self):
        """Start a background thread to check the Graphics table every second."""
        self.graphics_check_thread = threading.Thread(
            target=self._check_graphics_table, daemon=True
        )
        self.graphics_check_thread.start()
        print("Graphics table check thread started...")

###############################################################




    def _check_graphics_table(self):
        """Continuously check the Graphics table and manage overlay state."""
        while True:
            db = SessionLocal()
            try:
                graphics_records = db.query(Graphics).all()
                if graphics_records:
                    graphics = graphics_records[0]
                    current_position = graphics_records[0].position  # Get latest position
                    if  self.overlay_running==False:
                        self.overlay_position = current_position




                        branding_data = graphics.branding
                        scoreboard_id = graphics.scoreboard_id
                        if isinstance(branding_data, str):
                            try:
                                branding_data = json.loads(branding_data)

                            except json.JSONDecodeError as e:
                                        logger.warning(f"⚠️ Failed to parse branding JSON: {e}")
                                        branding_data = {}    
                           
                        sports_type = branding_data.get("sportsType", "default")
                        self.width = int(branding_data.get("width", "0").replace("px", "").strip())
                        self.height = int(branding_data.get("height", "0").replace("px", "").strip())

                        #BASE_URL = "http://103.217.176.16:8080"
                        #BASE_URL = "http://192.168.8.47:8080"
                        self.url = BASE_URL+f"/scorecards/{sports_type}/scorecard/{scoreboard_id}"
                        logger.info(f"🧩 Dynamic overlay URL set to: {self.url}")
                        self.add_overlay(self.url, self.snap_folder, self.overlay_position)
                        self.overlay_running = True
                    else:
                        # Check if position changed
                        if current_position != self.overlay_position:
                            self.overlay_position = current_position
                            self.update_overlay_position(current_position)  # Update dynamically
                else:
                    if self.overlay_running:
                        self.remove_overlay()
                        self.overlay_running = False
            except Exception as e:
                logger.error(f"Error checking Graphics table: {e}")
            finally:
                db.close()
            time.sleep(1)





 ######################################################################################################################################




    def _capture_screenshots(self, url, snap_folder):
        previous_image_path = None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--window-size=450,100"])
            page = browser.new_page(viewport={"width": self.width, "height": self.height})
            logger.info(f"🌐 Opening overlay URL in Playwright: {url}")   

            page.goto(url, wait_until="networkidle")

            # 🧼 Make background transparent
            page.evaluate("""
                    () => {
                        // Force transparency on all elements
                        document.querySelectorAll('*').forEach(el => {
                            el.style.background = 'transparent !important';
                            el.style.backgroundColor = 'transparent !important';
                        });
                        
                        // Remove shadows and borders that might cause artifacts
                        document.body.style.boxShadow = 'none';
                        document.body.style.border = 'none';
                    }
                """)

            logger.info("🔧 Injected transparent background for overlay rendering")






            try:
                while self.running:
                    try:
                        if previous_image_path and os.path.exists(previous_image_path):
                            os.remove(previous_image_path)

                        current_image_path = os.path.join(snap_folder, f"{uuid.uuid4()}.png")
                        page.screenshot(
                                            path=current_image_path,
                                            omit_background=True,  # Force transparent background
                                            type="png"  # Explicit PNG format
                                        )
                                                                
                        
                        logger.info(f"📸 Screenshot captured: {current_image_path}")

                        if self.pipeline:
                            state = self.pipeline.get_state(Gst.CLOCK_TIME_NONE)[1]
                            if state == Gst.State.PLAYING:
                                self.overlay = self.pipeline.get_by_name("overlay")
                                self.overlay.set_property("location", current_image_path)
                                self.overlay.set_property("alpha", 1)
                                logger.info(f"🖼️ Updated overlay with PNG: {current_image_path}")

                        previous_image_path = current_image_path
                        time.sleep(1)

                    except Exception as e:
                        logger.error(f"❌ Screenshot capture error: {e}")
                        time.sleep(2)

            finally:
                browser.close()  # ✅ Close before exiting playwright context


        
############################################################################################





    def _start_pipeline_thread(self):
        with self.pipeline_lock:
            if self.thread and self.thread.is_alive():
                return True  # Thread already running
        
            # Ensure pipeline exists
            if not self.pipeline:
                success = self.create_pipeline()
                if not success:
                    logger.error("Failed to create pipeline, cannot start thread")
                    return False
                
            # Start pipeline thread
            self.loop = GLib.MainLoop()
            self.thread = threading.Thread(target=self._run_pipeline, daemon=True)
            self.thread.start()
            
            # Set initial state to PLAYING
            self.pipeline.set_state(Gst.State.PLAYING)
            logger.info("Pipeline thread started with state transition")
            return True

      
################################################

    


    def update_overlay_position(self, position):
        """Update overlay position dynamically with a pause."""
        try:
            if not self.overlay_running or not self.overlay:
                return
            
            # Hide the overlay
            self.overlay.set_property('alpha', 0.0)
            logger.info("Overlay hidden. Waiting before repositioning...")
            
            # Start a thread to handle the delay and repositioning
            def delayed_reposition():
                # Wait for pipeline stabilization
                time.sleep(2)  # Reduced from 19 to 2 seconds for better UX
                video_width = 1920  # Should match pipeline capsfilter settings
                
                # Update position with new cases
                padding = 10
                if position == 'tl':  # Top-left
                    x = padding
                    y = padding
                elif position == 'tr':  # Top-right
                    x = video_width - self.width - padding
                    y = padding
                elif position == 'bl':  # Bottom-left
                    x = padding
                    y = -padding
                elif position == 'br':  # Bottom-right
                    x = video_width - self.width - padding
                    y = -padding
                elif position == 'tc':  # Top-center
                    x = (video_width - self.width) // 2
                    y = padding
                elif position == 'bc':  # Bottom-center
                    x = (video_width - self.width) // 2
                    y = -padding
                else:  # Default to top-left
                    x = padding
                    y = padding
                    logger.warning(f"Unknown position {position}, using default")
                
                # Apply new position
                self.overlay.set_property('offset-x', x)
                self.overlay.set_property('offset-y', y)
                
                # Smooth fade-in
                for alpha in [0.3, 0.6, 1.0]:
                    self.overlay.set_property('alpha', alpha)
                    time.sleep(0.2)
                
                logger.info(f"Overlay repositioned to {position}")

            threading.Thread(target=delayed_reposition, daemon=True).start()
            
        except Exception as e:
            logger.error(f"Failed to update overlay position: {e}")


    def add_overlay(self, url, output_folder, position):
        try:
            logger.info(f"Adding overlay for position: {position}")
            
            # Stop existing screenshot thread if running
            if self.screenshot_thread and self.screenshot_thread.is_alive():
                logger.info("Stopping existing screenshot thread")
                self.stop_screenshot_capture()

            # Start new screenshot thread
            self.running = True
            self.screenshot_thread = threading.Thread(
                target=self._capture_screenshots, 
                args=(url, output_folder), 
                daemon=True
            )
            self.screenshot_thread.start()
            logger.info("Screenshot capture started...")

            # Configure overlay position
            self.overlay = self.pipeline.get_by_name("overlay")
            padding = 10
            video_width = 1920  # Should match pipeline capsfilter settings

            position_config = {
                'tl': (padding, padding),
                'tr': (video_width - self.width - padding, padding),
                'bl': (padding, -padding),
                'br': (video_width - self.width - padding, -padding),
                'tc': ((video_width - self.width) // 2, padding),
                'bc': ((video_width - self.width) // 2, -padding)
            }

            if position in position_config:
                x_offset, y_offset = position_config[position]
                self.overlay.set_property('offset-x', x_offset)
                self.overlay.set_property('offset-y', y_offset)
                logger.info(f"Position set to {position} (X: {x_offset}, Y: {y_offset})")
            else:
                logger.warning(f"Unknown position {position}, defaulting to top-left")
                self.overlay.set_property('offset-x', padding)
                self.overlay.set_property('offset-y', padding)

        except Exception as e:
            logger.error(f"Failed to add overlay: {e}")



#############################################################
   
   

    def log_pipeline_elements(self):
        """Log the names of all elements in the pipeline."""
        if not self.pipeline:
            print("Pipeline is not running.")
            return
    
        elements = self.pipeline.iterate_elements()
        print("Pipeline elements:")
        for element in elements:
          print(f"Element name: {element.get_name()}")




  #######################################################################              
        

    def is_streaming(self):
        if self.pipeline:
            return self.pipeline.get_state(0)[1] == Gst.State.PLAYING
        return False

     ####################################################################### 


  

   

       



    #####################################################################################################################################



    def start_screenshot_capture(self, url, output_folder):
        """Start the screenshot capture thread."""
        if self.screenshot_thread and self.screenshot_thread.is_alive():
            print("Screenshot capture is already running")
            return

        self.running = True
        self.screenshot_thread = threading.Thread(
            target=self._capture_screenshots, args=(url, output_folder), daemon=True
        )
        self.screenshot_thread.start()
        print("Screenshot capture started...")

    def stop_screenshot_capture(self):
        """Stop the screenshot capture thread and clean up."""
        self.running = False
        if self.screenshot_thread:
            self.screenshot_thread.join()
            self.screenshot_thread = None



    
  ####################################################################### 

    def remove_overlay(self):
        try:
            logger.info("Removing overlay and cleaning files")
            self.stop_screenshot_capture()
            
            # Clean any remaining files in the folder
            for filename in os.listdir(self.snap_folder):
                file_path = os.path.join(self.snap_folder, filename)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error(f"Error cleaning file {file_path}: {e}")

            # Reset overlay properties
            if self.overlay:
                self.overlay.set_property("location", "")
                self.overlay.set_property("alpha", 0.0)
                
        except Exception as e:
            logger.error(f"Failed to remove overlay: {e}")

########################################################      ---  ***   The END     *** ---      #############################