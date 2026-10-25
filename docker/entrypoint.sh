#!/bin/sh
set -eu
java -Xmx512m -jar /opt/validator/validator.jar -s /opt/validator/config/scenarios.xml -r /opt/validator/config \
  -D -H 127.0.0.1 -P 8081 --disable-gui &
VALIDATOR_PID=$!
for i in $(seq 1 60); do
  if curl -fs http://127.0.0.1:8081/server/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fs http://127.0.0.1:8081/server/health >/dev/null || { echo "validator daemon did not start"; kill $VALIDATOR_PID; exit 1; }
exec uvicorn erechnung.api:app --host 0.0.0.0 --port 8080 --workers 1
