# One image per demo: build the 3D frontend with Node, then serve it and the API from Python.
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Public address, used at build time for canonical links, the sitemap and social cards.
ARG SITE_URL=""
ENV SITE_URL=${SITE_URL}
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /app/frontend/dist /app/frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist
RUN useradd --create-home app && chown -R app /app
USER app
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
