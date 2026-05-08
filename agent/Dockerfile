FROM python:3.12-slim

ARG ROLE=em
ARG MODEL=default

ENV ROLE=${ROLE}
ENV MODEL=${MODEL}
ENV PYTHONUNBUFFERED=1
ENV PI_CONFIG_DIR=/root/.pi/agent

WORKDIR /app

# Install nodejs/npm for PI
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Install PI coding agent
RUN npm install -g @earendil-works/pi-coding-agent

COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY prompts/ ./prompts/
COPY schemas/ ./schemas/
COPY tools/ ./tools/

EXPOSE 8080

ENTRYPOINT ["sh", "-c", "chmod 600 /run/secrets/github_ssh_key 2>/dev/null; exec python -m agent.main"]
