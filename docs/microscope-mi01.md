# Mikroskop MI01 in Raum 3.007

Das Forschungsmikroskop in Raum **3.007** wird unter der neutralen Kennung
**MI01** dargestellt. Der vom Eigentümer genannte Gerätetyp bleibt als interner
Entwurfsbezug in `reference` der gemeinsamen Quelle hinterlegt. Er wird nicht
als sichtbare Gerätebezeichnung verwendet. Das konkrete Trägerstativ bleibt
zunächst unbekannt; Objektive, Kamera, Beleuchtung und optionale Funktionen
werden aus der Referenz nicht abgeleitet.

Das bisherige MI01-Darstellungsmodell bleibt vorläufig ein generisches
aufrechtes Forschungsmikroskop: Trinokularkopf mit zwei geneigten Okularen, Kamera mit
Kühlrippen und Kabel, sechs farblich gekennzeichnete Objektive, Kreuztisch mit
Objektträger, Kondensor, Durchlichtöffnung, Fluoreszenzgehäuse sowie Grob-/Fein-
und Tischverstellung. Die 148 Körper entstehen aus einer gemeinsamen Quelle.
Diese Darstellung bestätigt kein aufrechtes Stativ am tatsächlichen Gerät.

Geometrie, Abmessungen und Objektivabstände bleiben Modellannahmen; MI01 ist
kein geometrischer Nachbau des vorhandenen Geräts. Herstellerlogos oder
Hersteller-CAD-Dateien werden nicht verwendet. Gitter für strukturierte
Beleuchtung, optische Schnittfunktion und reale Ansteuerung sind nicht
implementiert. Die Bedienelemente sind statische Geometrie.

## Quelle und Aufstellung

- `model/microscope-mi01.shared.json` führt die unabhängige Gerätebeschreibung.
  `scripts/microscope_model.py` leitet daraus dieselben portablen Körper für
  FreeCAD, SolidCraft und das Gebäude ab. Änderungen erfolgen in dieser Quelle
  und werden erneut erzeugt; native Ausgaben sind keine zusätzlichen Quellen.
- `model/furnishings/microscopy-3007.json` referenziert das vorhandene
  Desktop-Rezept als 1.400 × 800 × 780 mm große Aufstellbank. Ihre Südwandbindung
  folgt `OG3` / `R3_007` / `W031`; die Raumkontur bleibt ausschließlich im
  Geschossmodell. Eine besondere Schwingungsisolierung wird nicht behauptet.
- `model/equipment/microscopy-3007.json` referenziert Gerät und Möblierung.
  Das Mikroskop steht mittig auf der Bank und blickt in den Raum. Das Gebäude
  bindet diese Referenz unter `sources.microscopy` ein. Das Gerät und die Bank
  behalten Maßstab 1 und werden auch in die native Gebäudefassung aufgenommen.
- Der Rundgang benennt den Blickpunkt **Mikroskop · 3.007**. Seine Kamera folgt
  derselben Aufstellung; die 17 Geräte in Labor 3.003 behalten ihre bestehende
  separate L01-Bindung.

Die Modellprüfung des generischen Darstellungsstands bestätigt 100 mm Abstand der Bank zur inneren Südwand,
mindestens 182 mm Randabstand des gesamten Mikroskops auf der Arbeitsfläche und
rund 419 mm Abstand zur konservativen vollständigen Schwenkscheibe von Tür
`D3_007`. Diese Werte betreffen die vorhandene unkalibrierte Gebäudegeometrie,
keine vermessenen Raumabstände oder reale Navigationsfreigabe.

## Erzeugen und prüfen

```sh
python3 scripts/build_microscope.py
python3 scripts/build_microscope.py --backend solidcraft
python3 -m unittest discover -s tests -p 'test_microscope.py' -v
python3 scripts/build_building_stack.py --backend freecad --no-render
```

Jedes CAD erzeugt das Mikroskop direkt aus der gemeinsamen Quelle. Der
zusätzliche Vergleich beider Backends benötigt keine fremde CAD-Datei als
Konstruktionsgrundlage. Ein einzelnes Backend ist über `--backend` auswählbar.
Die native Prüfung kontrolliert geschlossene Körper, optische Tischöffnungen,
Objektiv-/Tischabstände, vier aufliegende Füße, erneutes Öffnen der Datei sowie
bei gemeinsamem Aufbau Volumen, Schwerpunkte, Begrenzungen und STEP-Differenzen.
Neue Ausgaben liegen unter `cad/generated/`, `exports/generated/` und `renders/`.

## Historische Nachweise des generischen Darstellungsmodells

Die Revision `microscope-mi01-0580b0e09dd3-r2` bestand alle 148 Körpervergleiche;
die maximale STEP-Volumendifferenz betrug 0. Abstandsprüfungen verwenden
ausdrücklich die dargestellte statische Stellung. Verstellwege, Roboterzugriff,
Optik, mechanische Belastbarkeit und Gerätehardware sind nicht qualifiziert.
Dieser Nachweis gehört zur früheren generischen Quelle; er belegt keine
Hersteller-Geometrietreue. Die interne Referenzkorrektur ändert keine Körper oder Maße
und schreibt keine historischen Build-Berichte oder Medienprüfsummen um.

Die vollständige Gebäudefassung `building-stack-2f2288035a30-r2` wurde in
FreeCAD mit 2.541 geschlossenen Körpern, 509 Geometrieproben und 17 Höhenprüfungen
erzeugt und geprüft. Der neue Stand ergänzt die 148 Gerätekörper und fünf
Bankkörper. Ein vollständiger SolidCraft-Gebäudeaufbau wurde für diese Änderung
nicht erneut ausgeführt; der unabhängige SolidCraft-Nachweis betrifft MI01.
Der daraus erzeugte Rundgang liegt unter
`exports/building-walkthrough/building-walkthrough-718f9e83d2cf/index.html`;
Build-Berichte und native Dateien bleiben lokale, ignorierte Ableitungen.
Der zugehörige historische `browser-check.json` bestätigt den damaligen Blickpunkt, alle 148
Gerätekörper und ihre Auflage innerhalb der Bankfläche. Die bestehenden
Raum-, Tür-, Küchen- und Aufzugskontrollen bestehen denselben Browserlauf.
`browser-microscopy.png` dokumentiert die visuell geprüfte Raumansicht.
Für die korrigierte Gerätebezeichnung wurde kein neuer nativer Gebäude- oder
Browserexport erzeugt; bestehende Ausgaben behalten ihre ursprünglichen
Quellenpins und Bezeichnungen.
