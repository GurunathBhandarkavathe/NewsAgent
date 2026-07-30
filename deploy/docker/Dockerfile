FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml requirements.txt README.md /app/
COPY src /app/src

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["newsagent", "production"]
