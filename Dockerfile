# mt4-executor engine - always-on, outbound-only container for ECS Fargate.
# ARM64 by default (cheaper Fargate); the MetaApi SDK is pure Python.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv for reproducible, locked installs.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

# Install locked dependencies first (cached layer), then the package.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Runs as: mt4-executor <CMD...>. Override CMD in the ECS task def to change
# symbols/timeframe. Engine starts PAUSED; resume from the site.
ENTRYPOINT ["uv", "run", "--no-dev", "mt4-executor"]
CMD ["engine", "--symbol", "EURUSD", "--timeframe", "1h", "--interval", "5"]
