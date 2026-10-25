# ADR-004: Keine KI-Extraktion

- Datum: 2026-10-25
- Status: angenommen

## Kontext

Für Rechnungsdaten werden oft KI-Dienste wie AI Builder (Rechnungsverarbeitung) eingesetzt. E-Rechnungen nach
EN 16931 sind aber strukturiertes XML (XRechnung direkt, ZUGFeRD als in das PDF/A-3 eingebettetes CII-XML); jedes Feld
hat einen festen Ort.

## Entscheidung

Die Felder werden deterministisch per XPath gelesen, getrennt nach UBL und CII (`src/erechnung/xpath/*.toml`).
AI Builder wird nicht verwendet: das Ergebnis ist nicht deterministisch, verbraucht Credits und ist für strukturiertes
XML unnötig.

## Folgen

- Gleiche Eingabe, gleiches Ergebnis; die Extraktion ist mit Unit-Tests vollständig prüfbar.
- Keine laufenden Kosten pro Rechnung.
- Papierrechnungen und reine Bild-PDFs ohne eingebettetes XML werden nicht ausgelesen (HTTP 422); OCR ist nicht Teil
  des Projekts.
