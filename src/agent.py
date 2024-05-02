import asyncio
import io
import json
import logging
import math
import os
import traceback
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
    AutoDisconnect,
    cli,
)
import cv2

SOURCE_VIDEO = os.getenv("SOURCE_VIDEO")
LIPSYNCED_VIDEO = os.getenv("LIPSYNCED_VIDEO")
LIPSYNC_SIGNAL_CHANNEL = os.getenv("LIPSYNC_SIGNAL_CHANNEL")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
WIDTH = 540
HEIGHT = 960
r = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)

AUDIO_SAMPLE_RATE = 24000
AUDIO_CHANNEL_NUMBERS = 1


async def capture_and_send_audio(audio_source, audio_file):
    with wave.open(audio_file, "rb") as wf:
        num_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        num_frames = wf.getnframes()
        pcm_data = wf.readframes(num_frames)
    # Convert PCM data to numpMymB-kUH1y array
    y = np.frombuffer(pcm_data, dtype=np.int16)
    audio_frame = AudioFrame(
        data=pcm_data,
        sample_rate=sample_rate,
        num_channels=num_channels,
        samples_per_channel=num_frames,
    )

    await audio_source.capture_frame(audio_frame)


def calculate_duration(raw_bytes_length, sample_rate):
    total_samples = raw_bytes_length // 2
    duration_seconds = total_samples / sample_rate
    return duration_seconds


async def capture_and_send_audio_from_binary(audio_source, audio_bytes):
    duration_seconds = calculate_duration(
        raw_bytes_length=len(audio_bytes), sample_rate=AUDIO_SAMPLE_RATE
    )
    samples_per_channel = int(AUDIO_SAMPLE_RATE * duration_seconds)
    audio_frame = AudioFrame(
        data=audio_bytes,
        sample_rate=AUDIO_SAMPLE_RATE,
        num_channels=AUDIO_CHANNEL_NUMBERS,
        samples_per_channel=samples_per_channel,
    )
    #
    await audio_source.capture_frame(audio_frame)
    return duration_seconds


async def entrypoint(job: JobContext):
    room = job.room
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

    async def _publish_audio():
        try:
            sub = r.pubsub()
            sub.subscribe(str(job.room.name))
            while True:
                msg = sub.get_message()
                if msg is not None:
                    data = msg["data"]
                    if isinstance(data, bytes):
                        durations = await capture_and_send_audio_from_binary(
                            audio_source, data
                        )
                        r.publish(
                            LIPSYNC_SIGNAL_CHANNEL.format(job.room.name),
                            json.dumps({"total_seconds": durations}),
                        )
                await asyncio.sleep(0.04)
        except:
            print(f"Error: {traceback.format_exc()}")

    async def _publish_frame():
        sub = r.pubsub()
        lipsync_channel = LIPSYNC_SIGNAL_CHANNEL.format(job.room.name)
        sub.subscribe(lipsync_channel)
        logging.info(f"Subscribed to {lipsync_channel}")
        video_source_capture = cv2.VideoCapture(SOURCE_VIDEO)
        video_synced_capture = cv2.VideoCapture(LIPSYNCED_VIDEO)
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
                logging.info(f">>>>>>>{msg}")
                if "data" in msg and isinstance(msg["data"], bytes):
                    data = json.loads(msg["data"])
                    logging.info(data)
                    if data.get("total_seconds"):
                        logging.info(msg)
                        total_seconds = data.get("total_seconds")
                        logging.info(f"Total seconds: {total_seconds}")
                        synced_frame_count = synced_frame_count + round(
                            total_seconds * 25
                        )
                        if total_seconds >= 0.1:
                            synced_frame_count = (
                                synced_frame_count if synced_frame_count >= 5 else 5
                            )
                        logging.info(f"synced_frame_count: {synced_frame_count}")
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
            # if synced_frame_count > 0 and audio_file is not None:
            #     logging.info(f">>>>>>>> PLAYING AUDIO")
            #     asyncio.create_task(capture_and_send_audio(audio_source, audio_file))
            #     audio_file = None
            video_source.capture_frame(frame)
            # logging.info(f"publish frame index: {frame_index}")
            await asyncio.sleep(0.04)

    await asyncio.gather(_publish_frame(), _publish_audio())


async def request_fnc(req: JobRequest) -> None:
    logging.info(f"request_fnc.room: {req.room}")
    logging.info(f"request_fnc.id: {req.id}")
    logging.info(f"request_fnc.job: {req.job}")
    await req.accept(entrypoint, auto_disconnect="ROOM_EMPTY")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(request_fnc=request_fnc, load_threshold=2.0))
