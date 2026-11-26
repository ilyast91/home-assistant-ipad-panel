FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PANEL_DROP_PRIVILEGES=1 PANEL_STATE_DIR=/data/panel-state
WORKDIR /app
COPY panel.py panel.html auth.py selection.py web.py ./
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2).close()"]
CMD ["python", "/app/panel.py"]
