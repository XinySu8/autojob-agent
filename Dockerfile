FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY autojob ./autojob
RUN pip install --no-cache-dir .
# Mount your workspace (autojob.yaml + profile.md) at /workspace
WORKDIR /workspace
ENV AUTOJOB_CONFIG=/workspace
EXPOSE 8765
ENTRYPOINT ["autojob"]
CMD ["run"]
