FROM python:3.9-slim as builder

RUN pip3 install poetry && poetry config virtualenvs.in-project true
WORKDIR /app
COPY lobbyboy/ /app/lobbyboy/
COPY poetry.lock .
COPY pyproject.toml .
RUN poetry install

FROM python:3.9-slim

WORKDIR /app
COPY --from=builder /app/.venv/ .venv/
CMD [ "/app/.venv/bin/lobbyboy", "-c", "data/config.toml" ]
