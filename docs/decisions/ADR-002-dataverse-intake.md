# ADR-002: Dataverse-Tabelle als Rechnungseingang

- Datum: 2026-10-25
- Status: angenommen

## Kontext

Rechnungen kommen in der Praxis meist per E-Mail an ein Sammelpostfach. Der Eingangs-Workflow (Meilenstein 3) läuft
im kostenlosen Power Apps Developer Plan. Dieser Plan enthält kein Exchange Online, ein Postfach-Trigger steht also
nicht zur Verfügung.

## Entscheidung

Der Eingang ist eine Dataverse-Tabelle mit einer Dateispalte. Eine neue Zeile mit Datei startet den Power-Automate-Flow,
der den Prüfdienst aufruft, das Ergebnis in die Zeile schreibt und die Freigabe anstößt. Im produktiven Betrieb würde
ein freigegebenes Postfach (Shared Mailbox) die Zeilen anlegen; der restliche Ablauf bleibt gleich.

## Folgen

- Der Workflow ist ohne Exchange-Lizenz vorführbar und testbar.
- Der Postfach-Anschluss ist ein zusätzlicher, kleiner Flow vor der Tabelle, kein Umbau.
- Dateigrößen und Speicher richten sich nach den Grenzen der Dataverse-Dateispalte.
