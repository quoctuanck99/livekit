import asyncio
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

# change this color in dev mode and the agent will automatically update
# COLOR = bytes([0, 255, 255, 255])


# async def entrypoint(job: JobContext):
#     room = job.room
#     video_capture = cv2.VideoCapture("/Users/tuankq/Downloads/C0509.mp4")
#     source = rtc.VideoSource(WIDTH, HEIGHT)
#     while True:
#         ret, frame = video_capture.read()
#         if not ret:
#             break
#         # Resize the frame to match the desired width and height
#         frame = cv2.resize(frame, (WIDTH, HEIGHT))
#         # Convert the frame to RGB format
#         rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
#         # Convert the frame to bytes
#         byte_frame = rgb_frame.tobytes()
#         # Create a VideoFrame object
#         video_frame = rtc.VideoFrame(WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, byte_frame)
#         # Pass the frame to the VideoSource object
#         source.capture_frame(video_frame)
#         # Delay to control the frame rate (optional)
#         await asyncio.sleep(0.1)
#     video_capture.release()


async def entrypoint(job: JobContext):
    room = job.room
    source = rtc.VideoSource(WIDTH, HEIGHT)
    track = rtc.LocalVideoTrack.create_video_track("single-color", source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
    publication = await room.local_participant.publish_track(track, options)
    logging.info("published track", extra={"track_sid": publication.sid})

    async def _draw_color():
        video_capture = cv2.VideoCapture("/Users/tuankq/Downloads/C0509.mp4")

        while True:
            msg = sub.get_message()
            if msg:
                logging.info(msg)
            _, frame = video_capture.read()
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
