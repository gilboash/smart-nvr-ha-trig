FROM ultralytics/ultralytics:8.3.40

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.115.5 \
    "uvicorn[standard]==0.32.1" \
    pydantic==2.9.2 \
    pydantic-settings==2.6.1 \
    jinja2==3.1.4 \
    shapely==2.0.6 \
    python-multipart==0.0.17 \
    psutil==6.1.0 \
    bcrypt==4.2.1 \
    itsdangerous==2.2.0 \
    "transformers>=4.44" \
    Pillow>=10.0

COPY app ./app

ENV SNVR_HOST=0.0.0.0 \
    SNVR_PORT=7070 \
    SNVR_DB_PATH=/data/snvr.db \
    SNVR_SNAPSHOT_DIR=/data/snapshots \
    SNVR_MODEL_DIR=/models \
    OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|stimeout;5000000"

EXPOSE 7070

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7070"]
