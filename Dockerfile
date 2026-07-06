# syntax=docker/dockerfile:1

FROM node:20-bookworm-slim AS frontend-builder
ARG NPM_REGISTRY=
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ARG PIP_INDEX_URL=
ARG PIP_TRUSTED_HOST=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PACKAGING_FRONTEND_DIST=/app/frontend-dist

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --upgrade pip \
    && if [ -n "$PIP_INDEX_URL" ]; then \
        python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" ${PIP_TRUSTED_HOST:+--trusted-host "$PIP_TRUSTED_HOST"} -r /app/backend/requirements.txt; \
    else \
        python -m pip install --no-cache-dir -r /app/backend/requirements.txt; \
    fi

COPY backend/app /app/backend/app
COPY --from=frontend-builder /app/frontend/dist /app/frontend-dist

WORKDIR /app/backend
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]