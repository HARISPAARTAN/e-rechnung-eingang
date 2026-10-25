# syntax=docker/dockerfile:1
# Base, uv and Temurin images pinned by digest (multi-arch index, resolved 2026-10-25 with docker buildx imagetools inspect).
# python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962
FROM python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS base

# --- KoSIT validator jar and XRechnung configuration, pinned by SHA-256 (must equal config.toml; tests/unit/test_pins.py)
FROM base AS validator
ARG VALIDATOR_VERSION=1.6.3
ARG VALIDATOR_SHA256=799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9
ARG CONFIG_RELEASE=2026-08-31
ARG XRECHNUNG_VERSION=3.0.2
ARG CONFIG_SHA256=2530cd107c414511c5d0462ec10f886910395abfca820db82e83d70bf01221a8
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/validator/config && cd /opt/validator \
 && curl -fsSL -o validator.jar "https://github.com/itplr-kosit/validator/releases/download/v${VALIDATOR_VERSION}/validator-${VALIDATOR_VERSION}-standalone.jar" \
 && echo "${VALIDATOR_SHA256}  validator.jar" | sha256sum -c - \
 && curl -fsSL -o config.zip "https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v${CONFIG_RELEASE}/xrechnung-${XRECHNUNG_VERSION}-validator-configuration-${CONFIG_RELEASE}.zip" \
 && echo "${CONFIG_SHA256}  config.zip" | sha256sum -c - \
 && unzip -q config.zip -d config && rm config.zip \
 && if [ ! -f config/scenarios.xml ]; then d=$(find config -mindepth 1 -maxdepth 1 -type d | head -n 1); mv "$d"/* config/ && rmdir "$d"; fi \
 && test -f config/scenarios.xml

# --- Python dependencies from uv.lock (the set the tests ran), then the project itself, both non-editable
FROM base AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11.8@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable
COPY src ./src
COPY config.toml README.md ./
RUN uv sync --frozen --no-dev --no-editable

# --- Runtime: Temurin 21 JRE, tini, the venv, config.toml and the XPath maps under ERE_ROOT
FROM base
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=eclipse-temurin:21-jre@sha256:227118764cccd3c3294617061aaa93a08309c63a395eefa83e6b35032992ea99 /opt/java/openjdk /opt/java/openjdk
COPY --from=validator /opt/validator /opt/validator
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY config.toml README.md ./
COPY src ./src
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod 0755 /app/docker/entrypoint.sh && useradd -r -u 10001 erechnung
USER erechnung

ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:/app/.venv/bin:$PATH \
    ERE_ROOT=/app \
    ERE_VALIDATOR_PORT=8081 \
    PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD curl -fs --max-time 4 http://127.0.0.1:8080/health | grep -q '"status":"ok"' || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
