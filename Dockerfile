# One image: the Angular app is built in a Node stage and served by the FastAPI server.
#
#   docker build -t ledger .
#   docker run -p 8000:8000 -e DEMO_MODE=true ledger        # synthetic data, no network needed
#   docker run -p 8000:8000 -v ledger-data:/app/data ledger  # live Yahoo Finance data
#
# Then open http://localhost:8000 (API docs at /api/docs).

FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY api/ api/
COPY src/ src/
COPY config/ config/
COPY scripts/ scripts/
COPY main.py ./
COPY --from=frontend /frontend/dist/frontend/browser frontend/dist/frontend/browser
RUN mkdir -p data logs && useradd --create-home --uid 1000 ledger && chown -R ledger /app
# The commit the image was built from (recorded with every registered model)
ARG GIT_COMMIT=""
ENV GIT_COMMIT=${GIT_COMMIT}
USER ledger
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
