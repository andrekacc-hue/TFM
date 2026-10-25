# Bot de Microsoft Teams (Microsoft 365 Agents SDK + aiohttp)
#   docker build -t teams-bot teams-bot
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/teams-bot

RUN useradd --create-home --uid 10001 app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=app app ./app
USER app

EXPOSE 3978
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:3978/health').status==200 else 1)"

CMD ["python", "-m", "app.main"]
