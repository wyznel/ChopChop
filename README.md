# Video Splitter Web App (Dockerized)

A simple FastAPI + ffmpeg web app to split videos into parts, zip them, and download.

## Features
- Split by number of parts (equal-duration parts)
- Split by maximum file size (MB) — estimated via bitrate/filesize
- Frontend UI (Tailwind, simple) that uploads, polls status, and provides ZIP download
- Dockerized (includes ffmpeg)
- Temp files stored under `/uploads/<job_id>`, cleaned after download

## Quickstart (local)

Requirements: Docker & docker-compose

1. Clone repo using ``git clone https://github.com/wyznel/ChopChop.git``
2. From project root run:
```bash
docker compose up --build
