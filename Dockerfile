FROM python:3.9-slim as builder

RUN apt update && apt install -y gcc libkrb5-dev
RUN pip3 install poetry && poetry config virtualenvs.in-project true
WORKDIR /app
COPY poetry.lock .
COPY pyproject.toml .
RUN poetry install --no-dev --no-root
COPY lobbyboy/ /app/lobbyboy/
RUN .venv/bin/pip install --no-deps .


FROM python:3.9-slim

WORKDIR /app
COPY --from=builder /app/.venv/ .venv/
COPY dev_datadir/ dev_datadir/
ENV PATH ".venv/bin:$PATH"
RUN lobbyboy-config-example > dev_datadir/config.toml
EXPOSE 12200
CMD [ "/app/.venv/bin/lobbyboy-server", "-c", "dev_datadir/config.toml" ]
