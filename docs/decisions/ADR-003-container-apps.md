# ADR-003: Ein Image auf Azure Container Apps

- Datum: 2026-10-25 (Gesundheitsprüfung und Grenzen überarbeitet mit v0.1.1)
- Status: angenommen

## Kontext

Der Prüfdienst besteht aus der Python-API und dem Java-Daemon des KoSIT-Validators. Er wird selten und stoßweise
aufgerufen (eine Anfrage pro eingehender Rechnung) und soll im Leerlauf nichts kosten.

## Entscheidung

Ein einziges Image enthält Python und Java (Temurin 21); der Daemon hört nur auf 127.0.0.1, nach außen ist nur die
API offen. Betrieb auf Azure Container Apps im Verbrauchstarif (Consumption) mit Skalierung auf null. Zugriff über den
Header `X-Api-Key`, der Schlüssel kommt als Umgebungsvariable `ERE_API_KEY` aus einem Secret. Fehlt der Schlüssel,
startet der Container nicht (fail closed); nur die lokale Entwicklung setzt ausdrücklich `ERE_AUTH_DISABLED=1`.
Der Kaltstart (Container plus Daemon-Start) wird in Kauf genommen.

## Folgen

- Keine Grundkosten im Leerlauf; die erste Anfrage nach einer Pause wartet auf den Kaltstart.
- API und Daemon skalieren gemeinsam; ein getrennter Validator-Dienst ist bei Bedarf später möglich.
- Gesundheit: Container Apps wertet den `HEALTHCHECK` des Dockerfiles nicht aus. Meilenstein 2 konfiguriert eine
  HTTP-Liveness- und eine HTTP-Readiness-Probe auf `/health`; `/health` antwortet 200 nur bei `"status":"ok"` und
  503, wenn der Daemon nicht antwortet. Ressourcen: 1 vCPU und 2 GiB je Replik (ein 9-MB-Dokument brauchte im Test
  rund 1,6 GiB).
- Überwachung im Container: tini ist PID 1, das Startskript überwacht Java und uvicorn. Stirbt einer der beiden
  Prozesse (auch Java bei Speichermangel über `-XX:+ExitOnOutOfMemoryError`), beendet es den anderen und den
  Container mit einem Fehlercode, damit die Plattform ihn neu startet.
- Anfragegröße: Schlüssel und `Content-Length` werden vor dem Lesen des Inhalts geprüft, gestreamte Uploads werden
  mitgezählt und über 10 MB mit 413 abgebrochen. Eine Grenze am Ingress ist damit nicht nötig.
