# The planning API (FastAPI + PuLP). The web app in web/ deploys separately.
#   docker build -t fpl-api .
#   docker run -p 8000:8000 fpl-api
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    FPL_DB=/data/fpl_agent.db

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY fpl_agent ./fpl_agent

# Shared FPL data lives here. Mount a volume to keep it across restarts;
# without one, a restart re-fetches it in the background (a minute or two).
RUN useradd --create-home app && mkdir /data && chown app /data
USER app

EXPOSE 8000
# Hosts like Render and Cloud Run set PORT; the default is 8000.
CMD ["sh", "-c", "exec uvicorn fpl_agent.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
