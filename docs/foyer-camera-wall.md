# Kamerawand im EG-Foyer

Die Außenwand des Aufzugs zum Foyer trägt neun Monitore im Raster 3×3.
Der Blickpunkt **Kamerawand · EG** im Gebäuderundgang führt dorthin.
Einen Monitor anklicken oder aus der Nähe mit der Leertaste auswählen:
Die Großansicht bietet die Kameraauswahl für diesen Platz. **Schließen**
oder Escape kehrt zum Rundgang zurück. Die Belegung gilt für diese Sitzung.

## Bilder und fehlende Quellen

Alle Bilder entstehen lokal aus dem Gebäudemodell. Es gibt keine realen
Videostreams, Aufzeichnungen oder Gerätebedienung. **Modellkamera /
synthetisches Livebild** bezeichnet die vorhandenen Arm-Kameramodelle.
**Virtuelle Übersicht – keine physische Kamera** bezeichnet einen vorhandenen
quellgebundenen Geräteblickpunkt. Nur Arm A besitzt die vorhandene
Demobewegung. Ein unbewegtes Modellbild bleibt ein gültiges aktuelles Bild.

Das Register folgt tatsächlich gebundenen Labor- und Robotikinstanzen,
einschließlich Basislabor-Abzügen und Mikroskop. Racks, Möbel, Büro und Küche
sind ausgenommen. Eine Gerätequelle allein ist keine aufgestellte Instanz.
Unklassifizierte Gerätetypen und fehlende Blickpunkte erscheinen als Lücken.

Aktuell sind **25 Ansichten verfügbar**: sechs Armkameras und 19 virtuelle
Geräteübersichten. Für CF01, Spitzensammelstation T01, Waage, Kühlschrank,
Wasserbad und TapeStation fehlen quellgebundene Blickpunkte. Diese sechs
Einträge zeigen kein erfundenes Bild. Der statische L01-TR01 hat **keine
Kamera modelliert**. Die 20 vorgesehenen BF01-Kameras stehen separat als
**Flotte nicht angebunden** zur Auswahl, ohne Bilder oder automatische
Belegung eines Monitors.

Bildalter ist verstrichene **Browserzeit** seit der Berechnung des Bildes.
Vorhandene Arm-Modellzeit wird separat angezeigt. Veraltete Bilder,
pausierte Anzeige, fehlende Quellen und Darstellungsfehler unterscheiden
sich von Gerätestörungen. **Keine Meldungsquelle angebunden** bedeutet
nicht „keine Störung“.

## Quellen und Geometrie

`model/equipment/foyer-monitor-wall.json` führt Aufstellung und lokale
Typableitung des vorhandenen Bürodisplays; der Katalog bleibt unverändert.
Der aufgelöste EG-Plan liefert W052 und die Foyerseite R0_019. Neun Instanzen
bestehen jeweils aus Gehäuse, Bildschirm und Halter. Dieselben 27 Körper
werden unabhängig in FreeCAD und SolidCraft erzeugt und bleiben gebäudefest.

Maßstab 1, 40 mm Zwischenräume, 1100 mm Gehäuseunterkante und 30 mm
Rückabstand sind Darstellungsannahmen. Die Typmaße ergeben 1700×1070 mm.
Wandlänge und Randabstände werden aus den gemeinsamen Quellen berechnet und
nativ gegengeprüft. Vermessung, Montagefestigkeit und Ergonomie fehlen.

`model/foyer-camera-wall.shared.json` ist die äußere Komposition. Sie pinnt
Rundgang und Flotte und führt die Assettyp-Richtlinie und Bildparameter.
Der Rundgang referenziert die Flotte nicht zurück. Das Register ist eine
Ableitung, kein zusätzlicher Gerätebestand. BF01-Einträge enthalten keine
Fahrzeugpose, Bilder oder Simulatorwahrheit. Ein späterer Leitstandsadapter
muss zugestellte Frames verwenden.

## Darstellung und Prüfung

Kamerapässe verwenden die vollständige Szene und dieselben
Objekttransformationen wie die Hauptansicht. Geschosswahl und Isolation
verändern ihre Bilder nicht. Nur native Bildschirmflächen erhalten Texturen;
in Kamerapässen bleiben sie ohne Bildtextur. Sichtverdeckung ist eine
Browserprüfung; L01-Geräte fehlen weiterhin im nativen Gebäude-CAD.
Konservative Körperhüllen begrenzen die Zeichnung auf den jeweiligen
Sichtkegel. Grenzkontakte bleiben erhalten; Geschosse oder verdeckende Wände
werden nicht pauschal entfernt. Bewegte Körper verwenden dieselbe
Objektmatrix wie im Renderer.

Startparameter: 320×180 Pixel, bis 1 Hz je Mosaikbild, bis 5 Hz für die
ausgewählte Ansicht. Szenendurchläufe werden verteilt und nur bei sichtbarer
Wand oder offener Großansicht angefordert. Ein fester Satz Bildpuffer wird
wiederverwendet. Gemessene Raten und Renderzeiten gehören zum Browserbericht;
die Sollrate ist kein Nachweis ihrer Einhaltung oder realer Sicherheit.
Die nächste Fälligkeit beginnt nach Abschluss eines Bildes. Auch bei einer
langsamen Großansicht erhalten die übrigen sichtbaren Monitore weitere Bilder.

Die ausdrücklich synthetischen Clip-Ebenen betragen bei Armkameras
0,5–5000 mm und bei virtuellen Übersichten 25–180000 mm. Sie sind keine
Sensorreichweiten. Der Kamerapuffer verwendet 24-Bit-Tiefe; ein fertig
komponiertes Bild bleibt auch bei durchsichtigen Modellflächen undurchsichtig.

```sh
python3 scripts/build_building_stack.py --backend freecad --no-render
python3 scripts/build_foyer_monitor_wall_native.py
python3 scripts/check_foyer_monitor_wall_native.py <building-report> <neues-pruefverzeichnis> --solidcraft-report <monitor-scope-report>
python3 scripts/build_building_walkthrough.py --no-rebuild
node tests/check_camera_monitor_math.cjs
node tests/check_foyer_camera_wall_browser.cjs <index.html> <playwright-module> <chrome>
```

Neue Nachweise liegen ausschließlich unter `exports/`. Aktive BF01-Pins sind
nachgeführt; ältere Navigationscaches und Freiraum-/Fahrtnachweise gelten nur
für ihre ursprüngliche Revision. Der Flottennachweis im geänderten Gebäude
bleibt **unproven**. Historische Medien und Provenienz bleiben erhalten.

Die zusätzliche native Prüfung verwendet das vollständige FreeCAD-Gebäude
und eine unabhängig aus den gemeinsamen Operationen erzeugte SolidCraft-
Nachbarschaft. Deren Auswahl erfolgt vor dem CAD-Aufbau über konservative
Quellhüllen mit 2 m Abstand zum Monitorarray. Ausgeschlossene Körper und ihre
Abstandsuntergrenzen werden protokolliert. Das ist kein vollständiger
SolidCraft-Gebäudevergleich. Geprüft werden statische Körper; Türschwenkräume,
reale Gangfreiheit, Montagefestigkeit und Sicherheitsqualifikation bleiben offen.

## Prüfstand dieser Erweiterung

123 unterschiedliche Python-Prüffälle bestehen ohne Skip. Zusätzlich bestehen
die Node-Prüfungen zu Kameramathematik und konservativem Sichtkegel sowie die
Kamerawand-Browserprüfung mit SwiftShader und Metal. Auswahl per Maus und
Leertaste, Großansicht, Armkamera-FK, unveränderte Referenzpixel, fehlende
Quellen, lokale Fehlerbehandlung, Seiten-Lebenszyklus und tatsächlich gezählte
GPU-Allokationen sind geprüft. Die bestehende Roboter-Browserprüfung besteht.

Im dreisekündigen Metal-Messfenster auf Apple M1 wurden etwa 0,7–1 Hz je
Mosaikbild und 4,3 Hz für die Großansicht beobachtet. SwiftShader erreicht
deutlich niedrigere Raten; diese stehen getrennt im Bericht. Es handelt sich
um eine kurze lokale Messung, nicht um eine garantierte Bildrate.

Die native Prüfung bestätigt neun Instanzen, 27 neue Körper und 158
CAD-Vergleiche. Beide Kerne finden 387 mm Mindestabstand zu anderen Körpern;
neun vorgesehene Halterkontakte an W052 werden getrennt geführt. Beide
Original-Buildberichte und ihre nativen Eingaben sind im Audit gepinnt.

Die zusätzliche Aufzug-Browserprüfung ist **nicht bestanden**: ihre
Schrittweiten-Assertion meldet etwa 134,4 mm statt weniger als 120 mm.
Derselbe Befund wurde auf einer verifizierten Kopie der unveränderten
Ausgangsversion reproduziert. Aufzugcode und Grenzwert wurden dafür nicht
geändert. Die vorhandenen Browserprüfungen wählen lediglich die Hauptkamera
über ihre eindeutige ID, da die Großansicht ein zweites Canvas ergänzt.
Dieser bestehende Befund bleibt eine separate Nacharbeit.
