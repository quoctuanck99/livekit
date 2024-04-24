import asyncio
import json
import logging
import os
import wave

import numpy as np
import redis
from dotenv import load_dotenv
from livekit.rtc import AudioFrame

load_dotenv()
from livekit import rtc
from livekit.agents import (
    JobContext,
    JobRequest,
    WorkerOptions,
    cli,
)
import cv2

SOURCE_VIDEO = os.getenv("SOURCE_VIDEO")
LIPSYNCED_VIDEO = os.getenv("LIPSYNCED_VIDEO")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
WIDTH = 540
HEIGHT = 960
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)




async def capture_and_send_audio(audio_source, audio_file):
    with wave.open(audio_file, "rb") as wf:
        num_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        num_frames = wf.getnframes()
        pcm_data = wf.readframes(num_frames)
    # Convert PCM data to numpy array
    y = np.frombuffer(pcm_data, dtype=np.int16)
    audio_frame = AudioFrame(
        data=pcm_data,
        sample_rate=sample_rate,
        num_channels=num_channels,
        samples_per_channel=num_frames,
    )

    await audio_source.capture_frame(audio_frame)


async def entrypoint(job: JobContext):
    video_source_capture = cv2.VideoCapture(SOURCE_VIDEO)
    video_synced_capture = cv2.VideoCapture(LIPSYNCED_VIDEO)
    room = job.room
    sub = r.pubsub()
    sub.subscribe(job.room.name)
    logging.info(f"start room {room.name}")
    video_source = rtc.VideoSource(WIDTH, HEIGHT)
    video_track = rtc.LocalVideoTrack.create_video_track("single-color", video_source)
    video_options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
    video_publication = await room.local_participant.publish_track(
        video_track, video_options
    )

    audio_source = rtc.AudioSource(24000, 1)
    audio_track = rtc.LocalAudioTrack.create_audio_track("agent-mic", audio_source)
    audio_options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_UNKNOWN)
    audio_publication = await room.local_participant.publish_track(
        audio_track, audio_options
    )

    logging.info("video_publication", extra={"track_sid": video_publication.sid})
    logging.info("audio_publication", extra={"track_sid": audio_publication.sid})
    audio_file = None

    async def _draw_color():
        # Get the total number of frames in the video
        total_source_frames = int(video_source_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        total_synced_frames = int(video_synced_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        logging.info(f"Total frames in source: {total_source_frames}")
        logging.info(f"Total frames in synced: {total_synced_frames}")
        total_frames = min(total_source_frames, total_synced_frames)
        synced_frame_count = 0
        while True:
            msg = sub.get_message()
            if msg is not None:
                if "data" in msg and isinstance(msg["data"], str):
                    logging.info(msg)
                    data = json.loads(msg["data"])
                    total_seconds = data.get("total_seconds")
                    logging.info(f"Total seconds: {total_seconds}")
                    synced_frame_count = int(round(total_seconds)) * 25
                    logging.info(f"synced_frame_count: {synced_frame_count}")
                    audio_file = data.get("audio_file")
            src_ret, source_frame = video_source_capture.read()
            syn_ret, synced_frame = video_synced_capture.read()

            if not src_ret or not syn_ret:
                logging.info("End of video reached. Jumping to start...")
                video_source_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                video_synced_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                _, source_frame = video_source_capture.read()
                _, synced_frame = video_synced_capture.read()
            if synced_frame_count > 0:
                frame = synced_frame
                synced_frame_count = synced_frame_count - 1
            else:
                frame = source_frame
            argb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            argb_frame = argb_frame.tobytes()
            frame = rtc.VideoFrame(WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, argb_frame)
            if synced_frame_count > 0 and audio_file is not None:
                logging.info(f">>>>>>>> PLAYING AUDIO")
                asyncio.create_task(capture_and_send_audio(audio_source, audio_file))
                audio_file = None
            video_source.capture_frame(frame)
            await asyncio.sleep(0.04)

    asyncio.create_task(_draw_color())


async def request_fnc(req: JobRequest) -> None:
    await req.accept(entrypoint)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(request_fnc=request_fnc))
