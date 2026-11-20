# Pipettenspitzen und 96er-Trays

Stand: 18. November 2026, `TSUP01`. **Concept; no manufacturing release.**
Die [gemeinsame Quelle](../model/tip-supply.shared.json) beschreibt drei konkrete
Referenzartikel, ihre belegten Nennmaße und ein Raster aus zwölf logischen
Achterstreifen. Ein Tray besitzt damit **96 Plätze, nicht 96 Achterstreifen**.
Die Quelle enthält keine erfundenen Box-, Wand-, Nippel- oder Massendaten.

## Artikel und Maßbelege

Ausgewählt sind ungefilterte **Eppendorf epT.I.P.S. Reloads, PCR clean**:

| Größenklasse | Artikelnummer | Länge laut Zeichnung | Länge laut Katalog | Oberer Außendurchmesser | Körper-Durchmesserangabe |
|---|---|---:|---:|---:|---:|
| 10 µl | 0030073754 | 34 mm | 34 mm | 6 mm | 4,2 mm |
| 200 µl | 0030073819 | 52,7 mm | 53 mm | 7,15 mm | 5 mm |
| 1000 µl | 0030073851 | 70,7 mm | 71 mm | 8,8 mm | 7,9 mm |

Artikelnummern, gerundete Kataloglängen und Verpackung mit zehn Trays zu je
96 Spitzen stammen aus dem [Eppendorf-Hauptkatalog](https://www.eppendorf.com/product-media/doc/en/11112106/General_Catalog_Main-Eppendorf-Catalog-UK-Version.pdf),
gedruckte Seite 38 beziehungsweise PDF-Seite 68. Es sind katalogisierte
Referenzartikel; Lagerbestand und Liefertermin wurden nicht geprüft.
Die [Hersteller-Maßzeichnung](https://www.eppendorf.com/product-media/doc/en/154459_Technical-Data/Eppendorf_Consumables_Technical-data_epTIPS_epTIPS-Technical-Drawing.pdf)
liefert die geometrischen Werte: Seite 1 oben links, Seite 3 oben rechts und
Seite 4 links. Einlass- und Auslassdurchmesser stehen ebenfalls in der Quelle.
Die jeweils benachbarten Dualfilter-Varianten werden nicht vermischt.

Die nominale 9-mm-Teilung folgt der [Herstellerbeschreibung des epT.I.P.S.-Systems](https://www.eppendorf.com/ph-en/Products/Lab-Consumables/Pipette-Tips/epTIPS-384-p-PF-539738),
Abschnitt „Tip spacing“. Sie beschreibt 8-/12-Kanalpipetten mit 9 mm
Konusabstand. Das ist kein toleriertes Aufmaß eines einzelnen Trays. Aus acht
Positionen ergeben sich 63 mm Achsspannweite, aus zwölf Positionen 99 mm;
beides sind **keine Außenabmessungen** des Streifens oder der Box.

Ein Achterstreifen bezeichnet hier eine logische Spalte. Die ausgewählten
Reloads sind nicht als herausnehmbare, verbundene Achterträger belegt;
`physical_carrier_confirmed` und ihre physischen Maße bleiben `null`.
Ebenso offen sind Tray-/Boxkonturen, Auflagehöhe, Bohrungen, Wanddicken,
vollständige Innen-/Außenprofile, Masse pro Spitze und Pipettennippel.
Eine einzelne OD-/ID-Paarung bestimmt keine einheitliche Wanddicke.

## Definition, Variante und Instanz

- [Schema](../model/tip-supply.schema.json) und gemeinsame Quelle führen die
  Definition einmalig. `tip_10_ul`, `tip_200_ul` und `tip_1000_ul` sind benannte
  Varianten derselben Quelle.
- Varianten überschreiben unabhängige Parameter über die vorhandene
  `assembly_model.parameter_variant`-Auswertung. Einheiten und Bereiche sind
  deklariert; die Bereiche begrenzen die dokumentierte Variantenfamilie und
  sind keine Fertigungstoleranzen. Abhängige Rastermaße werden neu berechnet.
- [Referenzierende Beispiele](../model/tip-supply.instances.json) verwenden
  den bestehenden [Instanzvertrag](../model/assembly-reference.schema.json):
  ID, Assetreferenz, Bezugssystem, `xyz`, `yaw_deg`, Variante und `pose`.
  Beliebige Maßüberschreibungen an einer Artikelinstanz werden abgewiesen;
  weitere Artikel benötigen belegte Variantenwerte.
- `pose` ist `full`, `partial` oder `empty`. Die separate Belegung zählt
  konkrete Platz-IDs von `A01` bis `H12` auf und verlangt einen Herkunftsbeleg.
  Zustandsangabe und belegte Plätze müssen übereinstimmen; Duplikate und
  unbekannte IDs werden abgewiesen. Die Beispiele enthalten 96, 88 und 0
  Spitzen und sind ausdrücklich synthetische Momentaufnahmen.

Der lokale Ursprung liegt im Zentrum der Spitzenöffnung an `A01`, X läuft
über die zwölf Spalten, Y über A–H und Z nach oben. Spitzen reichen nach −Z.
Die Boxunterseite und ihre Beziehung zu diesem Ursprung sind unbekannt.
Die Instanzen liegen in **unabhängigen Beispielbezugssystemen**, nicht
zusammen an derselben physischen Position. Es wurden weder L01 noch die
Extraktionsstation um ungemessene Platzierungen ergänzt. Spätere Aufstellungen
müssen diese Quelle referenzieren; Geometrie wird nicht in Szenen kopiert.

`tip_supply_model.py` leitet Platzrahmen und belegte Spitzenachsen aus denselben
Parametern ab. Diese Ausgabe ist eine Maß-/Topologiebeschreibung, kein fertiger
Volumenkörper. Native Spitzen-, Strip-, Tray- und Boxmodelle werden wegen der
fehlenden Maße in dieser Revision weder in FreeCAD noch in SolidCraft erzeugt.
Die Belegung ist keine Bestandsdatenbank und bucht keinen Spitzenverbrauch.

## T01-Passungsprüfung

`fit_to` referenziert den unveränderten Spitzenabwurf mit Quellprüfsumme und
ordnet die drei Varianten den vorhandenen Nuten S/M/L zu. T01-Geometrie,
4/6/9-mm-Nuten und sämtliche `fit_rule`-Werte bleiben unverändert. Der jetzige
T01-Vertrag besitzt keinen validierten Rückverweis auf eine Spitzendefinition;
diese Erweiterung bleibt als Folgearbeit erfasst. Die prüfbare Bindung läuft
vorerst von der Spitzenquelle zu T01.

Alle drei Passungszustände bleiben **`open`**. Für eine dimensionsbezogene
Prüfung benötigt der Auswerter sowohl die T01-Grenzen als auch belegte
Schaft-Maximal- und Kragen-Minimaldurchmesser, den Abstand zur Abwurfhülse
und den vertikalen Betriebsfreiraum. Er prüft die radiale Ungleichung,
Artikelgrenzen und den Freiraum für die Gabeldicke. Nennmaße ersetzen weder
Toleranzextrema noch die exponierte Schaftgeometrie im tatsächlichen Griffbereich.
Selbst ein bestandener dimensionsbezogener Vergleich wäre keine Kraft-,
Bewegungs-, Herstellungs- oder Betriebsqualifikation (`qualified: false`).

Der getrennte Nennmaßvergleich meldet für 1000 µl **8,8 mm oberes OD gegenüber
9 mm Nutbreite**: Ein solcher kreisförmiger Prüfkörper überlappt die Gabel
seitlich nicht. Das ist ein Hinweis gegen Rückhaltung an genau diesem
Querschnitt, keine Aussage über einen vollständig vermessenen Spitzenrand.
Die Körper-Durchmesserangabe der Zeichnung wird ebenfalls ausdrücklich nicht
als maximaler freiliegender Schaftdurchmesser umgedeutet.

Die optionale FreeCAD-Prüfung baut T01 aus seiner vorhandenen Quelle und
schneidet sechs zylindrische Nennmaß-Prüfkörper mit den Gabeln. Die Prüfhöhe
entspricht der Gabeldicke und behauptet keine bekannte Kragenhöhe. Geprüft
wird nur, ob der native Kontakt mit dem analytischen Nutbreitenvergleich
übereinstimmt. Ein bestandenes Prüfkörper-Ergebnis gibt keinen Tip-Fit frei.

## Tests und lokaler Bericht

```sh
python3 -m unittest discover -s tests -p 'test_tip_supply*.py' -v
python3 scripts/build_tip_supply.py
python3 scripts/build_tip_supply.py --check-freecad
SOLIDCRAFTBOT_TIP_SUPPLY_NATIVE_TESTS=1 python3 -m unittest discover -s tests -p 'test_tip_supply_native.py' -v
```

Der Schema-Test benötigt `jsonschema`; ohne dieses Paket wird er ausdrücklich
übersprungen. Die übrigen Quelltests benötigen kein CAD. Der optionale native
Test liest den jüngsten lokalen Bericht und prüft die aktuellen Quell- und
Artefaktprüfsummen sowie den begrenzten Prüfumfang. Ohne aktivierten Schalter
oder vorhandenen nativen Bericht wird er übersprungen; ein Skip ist kein
bestandener CAD-Nachweis.

Vor dem Build müssen die drei unveränderten Herstelleroriginale mit den
Dateinamen und SHA-256-Werten aus `sources` unter
`exports/tip-supply/evidence/` liegen; ein anderer Ordner ist mit
`--evidence-dir` möglich. Die URLs stehen in derselben Quelle. Geänderte
Herstellerdateien werden abgewiesen und müssen ausdrücklich neu geprüft und
revidiert werden, statt ihre Prüfsummen still anzupassen.

Jeder Build erzeugt einen neuen Ordner unter `exports/generated/tip-supply-*`.
`build-report.json` enthält die Artikel, Originalquellen und ihre Prüfsummen,
alle Nennmaße mit Einheiten, abgeleitete Rastermaße, offene Messwerte,
Belegungszahlen, T01-Ergebnisse sowie optionale native Messungen und
Artefaktprüfsummen. `passed` bezieht sich auf diesen benannten Prüfumfang;
der Bericht führt fehlende native Tip-/Boxgeometrie und offene Passung separat.
Originale, Berichte und native Prüfausgaben bleiben lokal und gitignored.

Prüflauf vom 18. November 2026: Alle zwölf CAD-freien Spitzentests einschließlich
JSON-Schema-Prüfung, die vier bestehenden T01-Quelltests und der aktivierte
native Berichtstest bestanden. FreeCAD prüfte 14 gültige T01-Körper und sechs
Nennmaßvergleiche; alle drei tatsächlichen Passungszustände blieben `open`.
Der bestehende Arm-Integrationstest und der Galerie-Check scheiterten separat
an bereits veralteten `robot.json`-Quellprüfsummen. Die betroffenen Armquellen,
Aufstellungen und historischen Galeriemedien wurden hier nicht verändert.

## Offene Aufgaben

1. T01-`fit_rule`, Toleranzen, Abwurfhülsenabstand und Abziehkraft belegen;
   die Nennmaßwarnung der 1000-µl-Variante zuerst klären.
2. Tray-/Boxmaße, Auflagen, Wandprofile und Massen beschaffen; einen tatsächlich
   herausnehmbaren Achterträger bei Bedarf anhand eines Artikels belegen.
3. Vollständige Spitzenprofile und anschließend native CAD-Ableitungen ergänzen.
4. Strip-Zugriff und Einzelspitzenaufnahme separat mit Bahn-/PVA-Prüfung entwickeln.
5. Pipettierwerkzeug, Nippel, Betätigung und Aufnahme entwickeln. Die
   Pipettierfunktion des Arms bleibt „noch zu entwickeln“.
