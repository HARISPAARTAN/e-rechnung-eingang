FROM python:3.13-slim

ARG VALIDATOR_VERSION=1.6.3
ARG VALIDATOR_SHA256=799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9
ARG CONFIG_RELEASE=2026-08-31
ARG XRECHNUNG_VERSION=3.0.2
ARG CONFIG_SHA256=2530cd107c414511c5d0462ec10f886910395abfca820db82e83d70bf01221a8

RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/validator/config && cd /opt/validator \
 && curl -sSL -o validator.jar "https://github.com/itplr-kosit/validator/releases/download/v${VALIDATOR_VERSION}/validator-${VALIDATOR_VERSION}-standalone.jar" \
 && echo "${VALIDATOR_SHA256}  validator.jar" | sha256sum -c - \
 && curl -sSL -o config.zip "https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v${CONFIG_RELEASE}/xrechnung-${XRECHNUNG_VERSION}-validator-configuration-${CONFIG_RELEASE}.zip" \
 && echo "${CONFIG_SHA256}  config.zip" | sha256sum -c - \
 && unzip -q config.zip -d config && rm config.zip \
 && if [ ! -f config/scenarios.xml ]; then d=$(find config -mindepth 1 -maxdepth 1 -type d | head -n 1); mv "$d"/* config/ && rmdir "$d"; fi \
 && test -f config/scenarios.xml

WORKDIR /app
COPY pyproject.toml README.md config.toml ./
COPY src ./src
# editable install: load_settings() finds config.toml and src/erechnung/xpath relative to the source tree in /app
RUN pip install --no-cache-dir -e .
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh && useradd -r -u 10001 erechnung && chown -R erechnung /app /opt/validator
USER erechnung

ENV ERE_VALIDATOR_URL=http://127.0.0.1:8081 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD curl -fs http://127.0.0.1:8080/health | grep -q '"status":"ok"' || exit 1
ENTRYPOINT ["/app/docker/entrypoint.sh"]
