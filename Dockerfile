FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV SHOPDESK_HOME=/workspace
WORKDIR /workspace
EXPOSE 8010
CMD ["uvicorn", "shopdesk.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
