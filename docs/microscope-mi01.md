# Mikroskop MI01 in Raum 3.007

MI01 ist ein detailliertes aufrechtes Forschungsmikroskop als eigenständiges
Darstellungsmodell: Trinokularkopf mit zwei geneigten Okularen, Kamera mit
Kühlrippen und Kabel, sechs farblich gekennzeichnete Objektive, Kreuztisch mit
Objektträger, Kondensor, Durchlichtöffnung, Fluoreszenzgehäuse sowie Grob-/Fein-
und Tischverstellung. Die 148 Körper entstehen aus einer gemeinsamen Quelle.

Die [Nikon-ECLIPSE-Ni-Serie](https://www.microscope.healthcare.nikon.com/products/upright-microscopes/eclipse-ni-series)
dient als Referenz für die Geräteklasse und sichtbaren Baugruppen. MI01 ist
kein Nachbau eines konkreten Herstellerartikels; Geometrie, Abmessungen und
Objektivabstände sind Modellannahmen. Es werden keine Herstellerlogos oder
Hersteller-CAD-Dateien verwendet. Optische Leistung und reale Ansteuerung sind
nicht implementiert. Die Bedienelemente sind hier statische Geometrie.

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
- Der Rundgang ergänzt den Blickpunkt **Mikroskop · 3.007**. Seine Kamera folgt
  derselben Aufstellung; die 17 Geräte in Labor 3.003 behalten ihre bestehende
  separate L01-Bindung.

Die Modellprüfung bestätigt 100 mm Abstand der Bank zur inneren Südwand,
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

Die Revision `microscope-mi01-0580b0e09dd3-r2` besteht alle 148 Körpervergleiche;
die maximale STEP-Volumendifferenz beträgt 0. Abstandsprüfungen verwenden
ausdrücklich die dargestellte statische Stellung. Verstellwege, Roboterzugriff,
Optik, mechanische Belastbarkeit und Gerätehardware sind nicht qualifiziert.

Die vollständige Gebäudefassung `building-stack-2f2288035a30-r2` wurde in
FreeCAD mit 2.541 geschlossenen Körpern, 509 Geometrieproben und 17 Höhenprüfungen
erzeugt und geprüft. Der neue Stand ergänzt die 148 Gerätekörper und fünf
Bankkörper. Ein vollständiger SolidCraft-Gebäudeaufbau wurde für diese Änderung
nicht erneut ausgeführt; der unabhängige SolidCraft-Nachweis betrifft MI01.
Der daraus erzeugte Rundgang liegt unter
`exports/building-walkthrough/building-walkthrough-718f9e83d2cf/index.html`;
Build-Berichte und native Dateien bleiben lokale, ignorierte Ableitungen.
Der zugehörige `browser-check.json` bestätigt den neuen Blickpunkt, alle 148
Gerätekörper und ihre Auflage innerhalb der Bankfläche. Die bestehenden
Raum-, Tür-, Küchen- und Aufzugskontrollen bestehen denselben Browserlauf.
`browser-microscopy.png` dokumentiert die visuell geprüfte Raumansicht.
