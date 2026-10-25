# ADR-001: KoSIT-Validator als Prüfinstanz

- Datum: 2026-10-25
- Status: angenommen

## Kontext

Eingehende E-Rechnungen müssen gegen EN 16931 und die nationalen XRechnung-Regeln geprüft werden. Die Regeln liegen
als XSD und Schematron vor und ändern sich mit jedem Release der XRechnung-Konfiguration. Öffentliche Auftraggeber
prüfen mit dem Validator der Koordinierungsstelle für IT-Standards (KoSIT) und dessen XRechnung-Konfiguration.

## Entscheidung

Der offizielle KoSIT-Validator 1.6.3 mit der XRechnung-Konfiguration 3.0.2 (Release 2026-08-31) läuft als Daemon
neben der API im selben Container und wird über HTTP angesprochen. Jar und Konfiguration werden mit SHA-256 aus
`config.toml` geprüft. Alternativen wurden verworfen: Mustang (eigene Validierung, nicht die Regeln der KoSIT) und
eigenes Schematron (Pflegeaufwand, Abweichungen vom Referenzergebnis), weil die KoSIT-Regeln das sind, was öffentliche
Stellen anwenden.

## Folgen

- Das Prüfergebnis entspricht dem, was ein öffentlicher Rechnungsempfänger sieht, einschließlich HTML-Bericht.
- Das Image braucht eine Java-Laufzeit neben Python; der Daemon braucht beim Start einige Sekunden.
- Ein Versionswechsel der Konfiguration ist eine Änderung an `config.toml` und am `Dockerfile` (Version und Prüfsumme).
- Dokumente älterer XRechnung-Versionen (z. B. 2.1) finden kein Szenario und werden mit `KEIN-SZENARIO` beantwortet.
