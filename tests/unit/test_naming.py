from datetime import date
from decimal import Decimal

from erechnung.extract import Felder
from erechnung.naming import archive_name, slug


def test_slug_maps_umlauts_and_cleans():
    assert slug("Nordstern Projektmanagement GmbH") == "nordstern-projektmanagement-gmbh"
    assert slug("Müller & Söhne, Straße 1 (Groß)") == "mueller-soehne-strasse-1-gross"
    assert slug("  --RE/2026//0042--  ") == "re-2026-0042"
    assert slug(None) == "unbekannt" and slug("") == "unbekannt"
    assert len(slug("x" * 100)) == 60


def test_slug_folds_accents():
    assert slug("Société Générale") == "societe-generale"
    assert slug("Çelik Ünal Señor") == "celik-uenal-senor"
    assert slug("Müller") == slug("Müller") == "mueller"  # composed and decomposed umlaut agree


def test_archive_name():
    f = Felder(rechnungsnummer="RE-2026-0042", rechnungsdatum=date(2026, 10, 1), verkaeufer_name="Nordstern Projektmanagement GmbH", brutto=Decimal("1190.00"))
    assert archive_name(f, "pdf") == "2026-10-01_nordstern-projektmanagement-gmbh_re-2026-0042.pdf"
    assert archive_name(Felder(), "xml") == "0000-00-00_unbekannt_unbekannt.xml"
