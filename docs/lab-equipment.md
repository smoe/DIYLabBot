# Analysenwaage und Kaltlagerung

Die Gerätebibliothek enthält eine generische Analysenwaage mit Windschutz,
einen Laborkühlschrank mit direkt zugänglichen Ebenen, einen generischen
−20-°C-Gefrierschrank mit Kunststoffschubladen und ein manuell bedientes
Keller-Tiefkühllager nach dem CryoCube F440n. Türen, Windschutz und Schubladen
besitzen native Gelenke. Die Bibliothek ergänzt Gerätetypen; die Aufstellungen
in L01 und auf den Referenzbänken bleiben davon unabhängig.

Die [L01-Aufstellung](lab-layout-l01.md) referenziert inzwischen Waage,
Kühlschrank und −20-°C-Schrank. Die dortige Gefrierschrankinstanz verwendet
90° als Öffnungs- und Zugangswinkel, damit die Tür am Fensterarbeitstisch
vorbeikommt. Der Katalogstandard bleibt bei 110°. Das manuelle Kellerlager
ist in L01 nicht aufgestellt; ein Kellerraum ist weiterhin nicht modelliert.

Führende Quelle ist [lab-equipment.shared.json](../model/lab-equipment.shared.json),
Vertrag [lab-equipment.schema.json](../model/lab-equipment.schema.json).
[lab_equipment.py](../scripts/lab_equipment.py) leitet beide Familienrezepte,
Parameterabhängigkeiten, Körper, Gelenke und Zugangsbezüge einmal ab.
FreeCAD und SolidCraft bauen ihre Geometrie unabhängig daraus auf. Ein CAD
ist keine notwendige Build-Abhängigkeit des anderen; STEP wird zusätzlich
zum Vergleich verwendet.

## Auswahl und Maßgrundlagen

| Profil | Ausführung | Außenmaße B × T × H, geschlossen |
|---|---|---|
| `analytical_balance` | Ø90-mm-Wägeteller, seitlich verschiebbarer Windschutz, aufklappbares Oberteil | 240 × 340 mm Grundfläche; generische, angenommene Maße |
| `fridge_4c` | +4 °C als Planungswert, vier Einlegeböden plus Bodenebene | 597 × 654 × 1684 mm |
| `freezer_minus20` | −20 °C als Planungswert, sechs hohle Kunststoffschubladen | 600 × 650 × 1700 mm, generische Maße |
| `cellar_ult_f440n` | manuelles Kellerlager, fünf Fächer mit getrennten Innentüren | 955 × 898 × 1950 mm als Gesamthülle |

Die [verlinkte Waagenkategorie](https://www.sigmaaldrich.com/DE/de/products/labware/laboratory-equipment/laboratory-balances)
wählt keinen konkreten Artikel aus. Das Modell folgt der gewünschten Bauform
**Analysenwaage mit Windschutz**. Kapazität, Ablesbarkeit und Messwert sind
unbekannt (`null`). Das dunkle Display zeigt keinen erfundenen Messwert.

Der Kühlschrank orientiert sich am
[Liebherr SRFvg 3501](https://www.liebherr.com/de-de/p/srfvg-3501-2451577).
Das [Herstellerdatenblatt](https://assets-cdn.liebherr.com/assets/api/954b8562-8914-4137-b8d4-d10cb2b6fed5/Original/)
nennt die Außenmaße, 460 × 423 × 1460 mm Innenraum, 261 l Nettovolumen und
vier verstellbare Ablageflächen. Zusammen mit dem Boden werden fünf Ebenen
modelliert. Ihre Höhen und die Mechanik sind angenommen. Alle fünf Ebenen
sind bei geöffneter Außentür von vorne zugänglich.

Der [Artikel EPF440400035](https://www.sigmaaldrich.com/CA/en/product/sigma/epf440400035)
gehört zum **CryoCube F440n**. Die
[Herstellerfamilie](https://www.eppendorf.com/ca-en/Products/Cold-Storage/ULT-Freezers/CryoCube-F440-Series-p-PF-996668)
führt 440 l, fünf Innentüren und eine Gesamthülle von 955 × 898 × 1950 mm.
Die [Betriebsanleitung, Seiten 62–63](https://www.eppendorf.com/product-media/doc/en/1025273/Freezers_Operating-manual_CryoCube-F440-series.pdf)
nennt dagegen 876 mm Gehäusebreite und einen seitlichen Überstand von 68 mm;
diese Angaben werden nicht als identisch zur Gesamthülle ausgegeben.
Der Innenraum beträgt 616 × 600 × 1265 mm, die Fachhöhen sind
245,5 / 242 / 242 / 242 / 245,5 mm. Diese Maße werden übernommen;
die genaue Zuordnung der äußeren Gehäuse-/Griffkonturen und die Scharniere
bleiben vereinfacht. Die elektrische Variante und Seriennummer der Geräte
im Keller sind unbekannt. −80 °C ist ein Planungswert, keine Beobachtung.

Der −20-°C-Schrank ist ein eigenes generisches Modell. Die Kunststoffbehälter
sind oben offen und besitzen Boden und Wände; die Front ist kein bloßer
aufgesetzter Schubladenumriss. Aktuell ist jeweils die vierte Schublade
herausgezogen. Werden alle Schubladen gleichzeitig ausgezogen, verdecken
obere Behälter den vertikalen Zugang zu den unteren; die Zugangsmetadaten
berücksichtigen dies.

## Zustände und Parameter

```python
import lab_equipment as equipment

catalog = equipment.load()
spec = equipment.materialize(catalog, "freezer_minus20",
    overrides={"width": 640, "inner_width": 490})
p = equipment.parameters(spec)
values = equipment.pose(spec, p, "access")
frames = equipment.interfaces(spec, p, values)
```

`closed`, `access` und `all_open` sind vollständig definierte Gelenkstellungen.
`access` öffnet die Außentür und eine mittlere Innentür beziehungsweise
Schublade. Beim Kühlschrank ist damit das gesamte Regal offen; bei der
Waage sind beide Seitenpaneele verschoben und das Oberteil aufgeklappt.
Individuelle Stellungen werden als vollständige Abbildung von Gelenk-ID
auf Grad beziehungsweise Millimeter an `validate_pose` übergeben.
Innentüren und Schubladen dürfen in diesem Vertrag erst bewegt werden,
wenn die Außentür mindestens den deklarierten Zugangswinkel erreicht hat.

Nur unabhängige Parameter innerhalb ihrer Grenzen lassen sich überschreiben.
Türbreite, Schubladenmaße und Scharnieranker werden erneut berechnet.
Eine höhere Waagenbasis verschiebt Wägeteller und oberen Scharnieranker
gemeinsam. Die geprüften Varianten sind ein um 40 mm verbreiterter
Gefrierschrank und eine um 10 mm erhöhte Waagenbasis.

Die Schnittstellen führen die Wägetellerfläche beziehungsweise die
einzelnen Lagerplätze mit Zugangsart und Zustand. Schubladenbezüge
folgen dem ausgezogenen Behälter. Solltemperaturen sind von den unbekannten
Isttemperaturen getrennt. `manual_only` bleibt am Kellergerät und seinen
Fächern erhalten. Es gibt keine automatische Auslagerung oder Inventarbuchung.

## Native Modelle und Prüfung

```bash
python3 scripts/build_lab_equipment.py
python3 scripts/build_lab_equipment.py --profile analytical_balance
python3 scripts/build_lab_equipment.py --backend freecad
python3 scripts/build_lab_equipment.py --backend solidcraft
python3 -m unittest discover -s tests -p 'test_lab_equipment.py' -v
```

Der vollständige Aufbau erzeugt vier Geräte, zwei Maßvarianten und eine
abgeleitete gemeinsame Ansicht der drei Schränke. Jeder Schrank dieser Ansicht
entsteht aus dem Geräteprofil in seiner Zugangsstellung; das Bild ist keine
vermessene Kelleraufstellung und keine neue Raumquelle.

Aktuelle native Pfade und Prüfsummen stehen im lokalen Bericht
`cad/lab-equipment/shared-build-report.json`. Die Revisionen unter
`cad/generated/`, `exports/generated/` und `renders/` werden neu angelegt.
Der Bericht pinnt Quelle, Generatoren, CAD-Dateien und Bilder. FreeCAD und
SolidCraft werden in offener und geschlossener Stellung über Körpervolumen,
Schwerpunkte und Begrenzungen verglichen; zusätzlich wird die STEP-Geometrie
mit nativer FreeCAD-Geometrie per Volumendifferenz verglichen.

Die native Prüfung umfasst gültige Einzelkörper, Wiederöffnen der FreeCAD-Datei,
diskrete Gelenkstellungen, Schwerpunktsbewegung und Überschneidungen zwischen
beweglichen Gruppen. Geometrische Sonden prüfen die freie Telleroberseite,
den Frontzugang jedes Regalfachs und den vertikalen Zugriff auf Schubladen.
Die Kunststoffbehälter werden zusätzlich auf tatsächlich freie Innenräume
geprüft. Die Testdatei kontrolliert vorhandene native Nachweise einschließlich
ihrer Prüfsummen; ohne vollständigen lokalen Aufbau wird dieser Teil als
übersprungen ausgewiesen.

In FreeCAD stehen die beweglichen Positionen unter `Controller`, die Maße
unter `ModelParameters`. In SolidCraft sind es native Gelenke und Parameter.
Direkte CAD-Experimente können auch unzulässige Kombinationen einstellen;
die API-Zustandsprüfung ist keine native Verriegelung. Gespeicherte
Zugangsmetadaten sind der geprüfte Buildstand. Nach Maß- oder Zustandsänderungen
werden sie aus der gemeinsamen Quelle neu erzeugt.

Die Prüfung umfasst die genannten Geometrien und Stichproben. Wägen, Kühlleistung,
reale Temperaturen, Robotik, Traglasten, Türdichtungen und Gerätesicherheit
sind damit nicht ausgeführt oder qualifiziert. ROS- und Netzwerkadapter
sind für diese Geräte nicht implementiert.
