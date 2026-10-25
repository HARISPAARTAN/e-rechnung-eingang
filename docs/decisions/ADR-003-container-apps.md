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
  rund 1,6 GiB). Die Liveness-Probe braucht eine Fehlerschwelle über 1, weil die Daemon-Abfrage in `/health` nach
  2 s abbricht und bei einer schweren Validierung einzeln scheitern kann.
- Überwachung im Container: tini ist PID 1, das Startskript überwacht Java und uvicorn. Stirbt einer der beiden
  Prozesse (auch Java bei Speichermangel über `-XX:+ExitOnOutOfMemoryError`), beendet es den anderen und den
  Container mit einem Fehlercode, damit die Plattform ihn neu startet.
- Anfragegröße: Schlüssel und `Content-Length` werden vor dem Lesen des Inhalts geprüft, gestreamte Uploads werden
  mitgezählt und über 10 MiB mit 413 abgebrochen. Eine Grenze am Ingress ist damit nicht nötig.

### Umsetzung in Meilenstein 2 (2026-10-25)

- Probes (`deploy/containerapp.bicep`, alle HTTP `GET /health` auf Port 8080; Azure wertet 200 bis 399 als Erfolg, das
  503 eines ausgefallenen Daemons gilt also als Fehlschlag):
  - Startup: 10 s Anfangsverzögerung, Periode 5 s, Timeout 3 s, Fehlerschwelle 36, also bis zu rund 190 s Zeit für
    Container und Daemon-Start, bevor die Revision als gescheitert gilt.
  - Liveness: Periode 30 s, Timeout 5 s, Fehlerschwelle 3. Erst drei Fehlschläge in Folge (rund 90 s) starten den
    Container neu; ein einzelnes langsames `/health` bei einer schweren Validierung bleibt folgenlos.
  - Readiness: Periode 10 s, Timeout 5 s, Fehlerschwelle 3. Ein Replikat ohne laufenden Daemon bekommt keinen Verkehr.
- Ressourcen: 1 vCPU und 2 GiB, Replikate min 0 und max 1 (kein Zustand im Container, eine Replik reicht für die
  Demo-Last und hält den Verbrauch klein).
- Image-Registry: GHCR statt Azure Container Registry. Das Paket
  `ghcr.io/harispaartan/e-rechnung-eingang` ist öffentlich, Azure zieht es ohne hinterlegte Zugangsdaten; eine ACR
  würde Grundkosten erzeugen und ein Pull-Secret verlangen. Das Image enthält keine Geheimnisse (der Schlüssel kommt als
  Container-App-Secret `api-key`). Fallback bei Pull-Problemen: `az containerapp registry set` mit einem GitHub-Token
  mit `read:packages`.
- Der Schlüssel liegt nur als Container-App-Secret und, für den Smoke-Test, als GitHub-Umgebungs-Secret
  `ERE_API_KEY`; die Bereitstellung aus GitHub läuft über OIDC (Federated Credentials auf die Umgebung `production`,
  Contributor nur auf die Ressourcengruppe), es gibt kein gespeichertes Azure-Passwort. Entra vergleicht das Subject
  exakt und unterstützt keine Platzhalter; GitHub stellte es beim ersten Deploy mit numerischen IDs aus
  (`repo:HARISPAARTAN@<Owner-ID>/e-rechnung-eingang@<Repo-ID>:environment:production`, Fehler `AADSTS700213`). Darum gibt es
  zwei Credentials, `github-production` (Namen) und `github-production-ids` (IDs); `deploy/github-oidc.sh` legt beide an.
- Gemessen (2026-10-25): Kaltstart 22,6 s, warmes `/health` 0,1 s, Image-Pull 5 s; die Probes lieferten 200, kein
  `ProbeFailed`. Zahlen und Kontingentrechnung stehen im Runbook und in der README.
- Übergroße Uploads: Der Dienst antwortet 413 und entscheidet an der angegebenen `Content-Length`. Beobachtet (ein
  Windows-Rechner, ein Runner-Lauf): der Ingress trennt danach die Verbindung, und ein Client, der den ganzen Körper vor
  dem Lesen schreibt (`httpx` unter Windows), sieht einen Abbruch statt der Antwort. Der Smoke-Test entscheidet deshalb
  mit einer Anfrage ohne Körper und `Content-Length` von 11 MiB (erwartet 413, sollte auf jedem System gelten), prüft mit 9 MiB (muss in den Timeout laufen), dass
  das 413 von der Größe abhängt, und wertet den echten Upload nur als abgelehnt bei 413 oder bei einem Abbruch
  (`WriteError`, `ReadError`, `RemoteProtocolError`) in unter 5 s, wenn danach ein gültiges UBL noch 200 und
  `gueltig: true` ergibt. Ein Timeout oder `ConnectError` ist ein Fehler.
- OIDC-Skript: Idempotenz nach Name und Subject; weicht das Subject eines vorhandenen Credentials ab (Repository
  umbenannt oder neu angelegt), bricht das Skript mit beiden Werten ab, und das Credential wird von Hand gelöscht.
  `REPO` ist im Skript fest eingetragen.
