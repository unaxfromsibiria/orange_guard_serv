FROM    python:3.8.7-slim-buster
RUN     mkdir -p /app/ && mkdir -p ~/.cache && apt-get update && pip install -U pip
COPY    src /app
WORKDIR /app
RUN     pip install -r bot_guard/requirements.txt
RUN     apt-get clean && rm -r ~/.cache && find /app/ -name '*.json' -delete && du -h /app/*
CMD     ["python", "-m", "bot_guard.run"]
