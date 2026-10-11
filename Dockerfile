# --- 1. build the React app ---------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build  # -> /autojob/static

# --- 2. Python app ------------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY autojob ./autojob
COPY --from=web /autojob/static ./autojob/static
RUN pip install --no-cache-dir ".[agent]"
# Mount a workspace (autojob.yaml + profile.md) at /workspace
WORKDIR /workspace
ENV AUTOJOB_CONFIG=/workspace
EXPOSE 8000
ENTRYPOINT ["autojob"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
