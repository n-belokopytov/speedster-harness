FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY speedster/ ./speedster/
COPY prompts/ ./prompts/
COPY schemas/ ./schemas/

ENTRYPOINT ["sh", "-c", "chmod 600 /run/secrets/github_ssh_key 2>/dev/null; exec speedster run --watch"]
