ARG BASE_IMAGE='python:3.11-slim'
FROM $BASE_IMAGE AS base

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

FROM base as dependencies
RUN apt-get update && apt-get install gcc -y && apt-get install build-essential -y \
    && apt-get install ffmpeg libsm6 libxext6  -y
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /opt/app/

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

FROM dependencies as pip_packages
COPY ./requirements.txt ./
RUN cd /opt/app/agents/livekit-agents/ && pip install .
RUN pip install -r requirements.txt

FROM pip_packages as sources
COPY ./ ./

FROM sources as cleaning
RUN rm -rf /var/lib/apt/lists/*
