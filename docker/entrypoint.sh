#!/bin/bash
# Runs under tini (PID 1). Starts the KoSIT daemon and the API and supervises both: when either process exits, the
# other is stopped and the container exits non-zero, so the platform restarts it instead of serving 502s.
set -u

: "${ERE_VALIDATOR_PORT:?ERE_VALIDATOR_PORT must be set (Dockerfile ENV)}"
HEALTH_URL="http://127.0.0.1:${ERE_VALIDATOR_PORT}/server/health"

# Fail fast on configuration errors (e.g. ERE_API_KEY missing) before the JVM starts.
python -c "import erechnung.api as api; api.app" || { echo "configuration error, not starting" >&2; exit 1; }

java -XX:+ExitOnOutOfMemoryError -Xmx1g -jar /opt/validator/validator.jar \
  -s /opt/validator/config/scenarios.xml -r /opt/validator/config \
  -D -H 127.0.0.1 -P "${ERE_VALIDATOR_PORT}" --disable-gui &
VALIDATOR_PID=$!

ready=0
for _ in $(seq 1 120); do
  if ! kill -0 "$VALIDATOR_PID" 2>/dev/null; then
    wait "$VALIDATOR_PID"
    echo "validator daemon exited during startup (code $?)" >&2
    exit 1
  fi
  if curl -fs --max-time 2 "$HEALTH_URL" 2>/dev/null | grep -q UP; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "validator daemon did not become healthy" >&2
  kill "$VALIDATOR_PID" 2>/dev/null
  exit 1
fi

uvicorn erechnung.api:app --host 0.0.0.0 --port 8080 --workers 1 &
API_PID=$!

stop() {
  kill -TERM "$API_PID" "$VALIDATOR_PID" 2>/dev/null
  wait "$API_PID" "$VALIDATOR_PID" 2>/dev/null
  exit 143
}
trap stop TERM INT

wait -n "$API_PID" "$VALIDATOR_PID"
code=$?
if ! kill -0 "$VALIDATOR_PID" 2>/dev/null; then
  echo "validator daemon exited (code $code); stopping the API" >&2
else
  echo "API exited (code $code); stopping the validator daemon" >&2
fi
kill -TERM "$API_PID" "$VALIDATOR_PID" 2>/dev/null
wait "$API_PID" "$VALIDATOR_PID" 2>/dev/null
[ "$code" -eq 0 ] && code=1
exit "$code"
