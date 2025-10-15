# 🪓 ChopChop – Video Splitter Web App

ChopChop is a **Dockerized full-stack web application** that lets users upload a video file and split it into multiple smaller parts.  
You can choose to split by **number of parts** or by **maximum file size**.  
After processing, the app bundles all split files into a `.zip` archive for download.

---

## 🚀 Features

- Upload any video file (e.g. `.mp4`, `.mkv`, `.mov`)
- Choose between:
  - Split by **count** (number of parts), or
  - Split by **size** (maximum MB per part)
- Automatic video splitting using **FFmpeg**
- Download a `.zip` file containing all parts
- Responsive web UI (FastAPI + Tailwind CSS)
- Dockerized for easy deployment

---

## 🧠 Tech Stack

**Frontend:**  
- FastAPI templates + Tailwind CSS  

**Backend:**  
- FastAPI (Python)
- FFmpeg for video processing
- Zipfile for bundling output

**Deployment:**  
- Docker + Docker Compose  
- Gunicorn with Uvicorn workers

---

## 📦 Installation & Setup

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/wyznel/ChopChop.git
cd ChopChop
docker compose up --build
```
### 2️⃣ Access
Once the container has started, go to:
```bash
http://localhost:8080
```
