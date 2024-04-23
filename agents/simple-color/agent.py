import asyncio
import json
import logging
import random

import redis
from dotenv import load_dotenv

load_dotenv()
from livekit import rtc
from livekit.agents import (
    JobContext,
    JobRequest,
    WorkerOptions,
    cli,
)
import cv2

WIDTH = 720
HEIGHT = 1280
r = redis.Redis(host="127.0.0.1", port=6378, decode_responses=True)
sub = r.pubsub()
sub.subscribe("loki")

async def entrypoint(job: JobContext):
    room = job.room
    source = rtc.VideoSource(WIDTH, HEIGHT)
    track = rtc.LocalVideoTrack.create_video_track("single-color", source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
    publication = await room.local_participant.publish_track(track, options)
    logging.info("published track", extra={"track_sid": publication.sid})

    async def _draw_color():
        video_source_capture = cv2.VideoCapture("/home/tuankq/workspaces/livekit-demo/server/agents/simple-color/C0492.mp4")
        video_synced_capture = cv2.VideoCapture("/home/tuankq/workspaces/livekit-demo/server/agents/simple-color/synced.mp4")
        # Get the total number of frames in the video
        total_frames = int(video_source_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        logging.info(f"Total frames in video: {total_frames}")
        synced_frame_count = 0
        while True:
            msg = sub.get_message()
            if msg is not None:
                if "data" in msg and isinstance(msg["data"], str):
                    logging.info(msg)
                    total_seconds = json.loads(msg["data"]).get("total_seconds")
                    logging.info(f"Total seconds: {total_seconds}")
                    synced_frame_count = int(total_seconds * 25)
            logging.info(f"synced_frame_count: {synced_frame_count}")
            if synced_frame_count > 0:
                ret, frame = video_synced_capture.read()
                synced_frame_count = synced_frame_count - 1
            else:
                ret, frame = video_source_capture.read()
            if not ret:
                logging.info("End of video reached. Jumping to start...")
                video_source_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = video_source_capture.read()
            argb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            argb_frame = argb_frame.tobytes()
            frame = rtc.VideoFrame(WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, argb_frame)
            source.capture_frame(frame)
            await asyncio.sleep(0.02)  # 100ms

    asyncio.create_task(_draw_color())


async def request_fnc(req: JobRequest) -> None:
    await req.accept(entrypoint)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(request_fnc=request_fnc))
