# ADR-003: Ein Image auf Azure Container Apps

- Datum: 2026-10-25
- Status: angenommen

## Kontext

Der Prüfdienst besteht aus der Python-API und dem Java-Daemon des KoSIT-Validators. Er wird selten und stoßweise
aufgerufen (eine Anfrage pro eingehender Rechnung) und soll im Leerlauf nichts kosten.

## Entscheidung

Ein einziges Image enthält Python und Java; der Daemon hört nur auf 127.0.0.1, nach außen ist nur die API offen.
Betrieb auf Azure Container Apps im Verbrauchstarif (Consumption) mit Skalierung auf null. Zugriff über den Header
`X-Api-Key`, der Schlüssel kommt als Umgebungsvariable `ERE_API_KEY` aus einem Secret. Der Kaltstart (Container plus
Daemon-Start) wird in Kauf genommen.

## Folgen

- Keine Grundkosten im Leerlauf; die erste Anfrage nach einer Pause wartet auf den Kaltstart.
- API und Daemon skalieren gemeinsam; ein getrennter Validator-Dienst ist bei Bedarf später möglich.
- Der Health-Check gilt nur bei `"status":"ok"` als gesund, ein ausgefallener Daemon (`degraded`) macht den Container
  ungesund.
- Die harte Grenze für die Anfragegröße setzt der Ingress; die 10-MB-Grenze im Dienst schützt nur den Puffer.
