FROM python:3.12-slim

ARG ROLE=em
ARG MODEL=vllm/default

ENV ROLE=${ROLE}
ENV MODEL=${MODEL}
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
COPY prompts/ ./prompts/
COPY schemas/ ./schemas/
COPY tools/ ./tools/

EXPOSE 8080

CMD ["python", "-m", "agent.main"]
