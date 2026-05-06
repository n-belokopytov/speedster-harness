FROM python:3.12-slim

ARG ROLE=em

ENV ROLE=${ROLE}
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY prompts/ ./prompts/
COPY schemas/ ./schemas/
COPY tools/ ./tools/

EXPOSE 8080

ENTRYPOINT ["sh", "-c", "chmod 600 /run/secrets/github_ssh_key 2>/dev/null; exec python -m agent.main"]
