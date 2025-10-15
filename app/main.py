# app/main.py
import os
import uuid
import shutil
import json
import math
import time
import threading
import subprocess
from pathlib import Path
from zipfile import ZipFile
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/uploads"))
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Splitter")

# Serve frontend
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

# In-memory job store. For production use persistent store.
jobs = {}

class JobStatus(BaseModel):
    status: str
    message: Optional[str] = None
    total_parts: Optional[int] = None
    completed_parts: Optional[int] = None
    zip_path: Optional[str] = None

def run_cmd(cmd):
    """Run shell command, return (returncode, stdout, stderr)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err

def ffprobe_info(path: Path):
    """Return dict with duration (seconds, float) and size (bytes, int)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate",
        "-print_format", "json",
        str(path)
    ]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        # fallback using os.stat
        size = path.stat().st_size
        return {"duration": None, "size": size, "bit_rate": None}
    j = json.loads(out)
    fmt = j.get("format", {})
    duration = fmt.get("duration")
    size = fmt.get("size")
    bit_rate = fmt.get("bit_rate")
    return {
        "duration": float(duration) if duration else None,
        "size": int(size) if size else (path.stat().st_size),
        "bit_rate": int(bit_rate) if bit_rate else None
    }

def create_segments_by_duration(input_path: Path, output_dir: Path, seg_seconds: float, output_ext: str):
    """
    Use ffmpeg segment muxer to split into segments of seg_seconds.
    Uses -c copy to avoid re-encoding.
    """
    # Ensure output_dir exists
    output_dir.mkdir(parents=True, exist_ok=True)
    out_pattern = str(output_dir / f"part_%03d{output_ext}")
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c", "copy",
        "-map", "0",
        "-f", "segment",
        "-segment_time", str(seg_seconds),
        "-reset_timestamps", "1",
        out_pattern
    ]
    return run_cmd(cmd)

def package_zip(output_dir: Path, zip_path: Path):
    with ZipFile(zip_path, "w") as zf:
        for f in sorted(output_dir.iterdir()):
            if f.is_file():
                zf.write(f, arcname=f.name)
    return zip_path

def process_job(job_id: str, job_dir: Path, params: dict):
    jobs[job_id] = {"status": "processing", "message": "starting", "total_parts": None, "completed_parts": 0, "zip": None}
    try:
        input_file = job_dir / "input" / params["original_filename"]
        info = ffprobe_info(input_file)
        duration = info["duration"]
        size = info["size"]
        if duration is None or duration <= 0:
            jobs[job_id].update({"status": "error", "message": "Could not determine video duration."})
            return

        # Decide splitting strategy
        out_dir = job_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        # preserve extension
        output_ext = Path(params["original_filename"]).suffix or ".mp4"

        if params["mode"] == "count":
            count = int(params["count"])
            if count <= 0:
                raise ValueError("count must be positive")
            seg_seconds = duration / count
            jobs[job_id].update({"message": f"splitting into {count} parts (~{seg_seconds:.2f}s each)", "total_parts": count})
            rc, out, err = create_segments_by_duration(input_file, out_dir, seg_seconds, output_ext)
            if rc != 0:
                jobs[job_id].update({"status": "error", "message": f"ffmpeg failed: {err.splitlines()[-1] if err else 'unknown'}"})
                return

        else:  # size mode
            size_mb = float(params["size_mb"])
            if size_mb <= 0:
                raise ValueError("size_mb must be positive")
            target_bytes = int(size_mb * 1024 * 1024)

            # Attempt to use bit_rate to compute bytes per second
            bit_rate = info.get("bit_rate")
            if bit_rate:
                bytes_per_sec = bit_rate / 8.0
            else:
                # fallback: filesize/duration
                bytes_per_sec = size / duration

            if bytes_per_sec <= 0:
                jobs[job_id].update({"status": "error", "message": "Could not determine bytes-per-second for size estimation."})
                return

            seg_seconds = max(1.0, target_bytes / bytes_per_sec)
            estimated_parts = math.ceil(duration / seg_seconds)
            jobs[job_id].update({"message": f"splitting approx {estimated_parts} parts (~{seg_seconds:.2f}s each)", "total_parts": estimated_parts})
            rc, out, err = create_segments_by_duration(input_file, out_dir, seg_seconds, output_ext)
            if rc != 0:
                jobs[job_id].update({"status": "error", "message": f"ffmpeg failed: {err.splitlines()[-1] if err else 'unknown'}"})
                return

        # Count produced files
        produced = sorted([p for p in out_dir.iterdir() if p.is_file()])
        jobs[job_id].update({"completed_parts": len(produced), "total_parts": len(produced)})

        # Create ZIP
        zip_path = job_dir / f"{job_id}.zip"
        package_zip(out_dir, zip_path)
        jobs[job_id].update({"status": "finished", "message": "done", "zip": str(zip_path)})
    except Exception as e:
        jobs[job_id].update({"status": "error", "message": str(e)})
    finally:
        # Note: we do NOT auto-delete here immediately to allow download.
        return

@app.post("/upload")
async def upload(file: UploadFile = File(...),
                 mode: str = Form(...),  # 'count' or 'size'
                 count: Optional[int] = Form(None),
                 size_mb: Optional[float] = Form(None)):
    """
    Accepts multipart upload:
    - mode: 'count' or 'size'
    - count: int (if mode == 'count')
    - size_mb: float (if mode == 'size')
    """
    # minimal validation
    if mode not in ("count", "size"):
        return JSONResponse({"error": "mode must be 'count' or 'size'"}, status_code=400)

    if mode == "count" and (count is None or count <= 0):
        return JSONResponse({"error": "count must be provided and > 0 for mode 'count'."}, status_code=400)

    if mode == "size" and (size_mb is None or size_mb <= 0):
        return JSONResponse({"error": "size_mb must be provided and > 0 for mode 'size'."}, status_code=400)

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_ROOT / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # save uploaded file
    file_path = input_dir / file.filename
    with open(file_path, "wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)

    params = {
        "mode": mode,
        "count": count,
        "size_mb": size_mb,
        "original_filename": file.filename
    }

    # launch processing in background thread
    t = threading.Thread(target=process_job, args=(job_id, job_dir, params), daemon=True)
    t.start()

    jobs[job_id] = {"status": "queued", "message": "queued", "total_parts": None, "completed_parts": 0, "zip": None}
    return {"job_id": job_id}

@app.get("/status/{job_id}")
def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return job

@app.get("/download/{job_id}")
def download(job_id: str, background_tasks: BackgroundTasks):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    if job.get("status") != "finished":
        return JSONResponse({"error": "job not finished yet"}, status_code=400)
    zip_path = Path(job.get("zip"))
    if not zip_path.exists():
        return JSONResponse({"error": "zip not found"}, status_code=404)

    # after sending file, schedule cleanup
    def cleanup():
        try:
            parent = zip_path.parent
            # remove job folder
            shutil.rmtree(parent)
            jobs.pop(job_id, None)
        except Exception:
            pass

    background_tasks.add_task(cleanup)
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")
