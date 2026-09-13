FROM python:3.13-slim
ARG SOURCE_SHA=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SOURCE_SHA=${SOURCE_SHA}
# The entrypoint drops to the plus account before running migrations/API.
# libpq resolves its optional client certificate under the effective user's
# home, which must not remain the inaccessible root-account directory.
ENV HOME=/home/plus
WORKDIR /app/backend
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --uid 10001 --create-home plus
COPY backend/ ./
COPY app/build/web /app/web
RUN mkdir -p /data/photos && chown -R plus:plus /app /data
EXPOSE 8080
ENTRYPOINT ["python", "/app/backend/start_service.py"]
CMD ["uvicorn", "estimoto_plus.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--workers", "1"]
