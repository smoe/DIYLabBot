# Küche im ersten Raum von 3.008

Die blaue Küchenzeile steht in `OG3` / `R3_008A`, dem ersten Raum vom Flur aus.
Die neue Ansicht **Küche 3.008** blickt vom Eingang schräg auf die Zeile.
Die Küche 1.008 und das Mikroskop in 3.007 bleiben eigenständige Aufstellungen.

Die private Eigentümeraufnahme vom 18. November 2026 zeigt blaue Fronten,
eine weiße Arbeitsfläche, weiße Fliesen, einen Kühlschrank unter der Platte,
eine Mikrowellennische, zwei obere Schranktüren, fünf Schubladen, Spüle und
Abtropffläche sowie einen Wasserkocher. Diese Merkmale sind modelliert.
Kleine Details sind Metallgriffe, Armatur, Abtropfrippen, Teller, Seifenspender
und Tuch. Das Foto wird nicht ins Repository übernommen.

## Gemeinsame Quellen

- `model/furniture/kitchenette.catalog.json` beschreibt das wiederverwendbare
  Küchenmöbel mit angenommenen Maßen; `scripts/kitchenette_model.py` leitet
  portable Körper einschließlich realer Spülenausschnitte ab.
- `model/furnishings/kitchen-3008.json` verankert eine Instanz an `W030`.
  Raumkontur und Wände stammen weiterhin aus der Gebäudekomposition.
- `model/equipment/kitchen-3008.json` referenziert Kühlschrank, Mikrowelle und
  Wasserkocher aus dem vorhandenen Sozialmöbelkatalog. Die Aufstellplätze
  werden aus den Möbelmaßen abgeleitet. Die Mikrowelle hat nur eine eigene
  Farbvariante, keine kopierte Geometrie.
- `scripts/building_kitchenette.py` bindet Möbel und Geräte mit Maßstab 1.
  Kühlschrank- und Mikrowellentür verwenden dieselben typweiten Browsergelenke
  wie die vorhandene Küche. Die Schrankfronten und Schubladen sind statisch.

Die Zeile ist nominell 1.560 × 620 mm groß, mit 870 mm Arbeitsflächenhöhe.
Diese Maße sind Annahmen zur vorhandenen unkalibrierten Raumgeometrie, kein
Aufmaß und keine Herstellerrekonstruktion.

## Raumtüren und Aufzug

Die Eigentümerklarstellung gilt ausschließlich für die Türen von 3.008:
`D3_008A` öffnet vom Flur nach `R3_008A`, `D3_008AB` weiter nach `R3_008B`,
jeweils Richtung Fenster, also zu kleinerem Gebäude-X. Beide sind fensterlose
Holztüren. Der nördliche Anschlag ist eine Darstellungsannahme, damit die
offene Eingangstür den Kühlschrankzugang freilässt. Die komplette 90°-Schwenk-
hülle einschließlich 60 mm Blattzugabe hat über 100 mm Abstand zur Küchenzeile.
Andere Raumtüren erhalten keine neue Öffnungsrichtung.

Die gleichzeitig gelieferten Kabinenbilder bestätigen die Aufzugseite ohne
Bedienpanel für KG und EG. Die Kabine behält beide Öffnungen, unabhängig von
der aktiven Schachtseite ihrer nativen EG-Referenzstellung. Edelstahloptik,
zwei Handlaufhöhen, dunkler Boden und horizontale K/E/1/2/3-Tasten ergänzen die
bestehende Kabine. Alle Einbauten fahren mit ihr mit. Die Browsersteuerung
öffnet nur die aktive Türseite am Ziel; `lift_operation_implemented` bleibt
`false`. Das Anzeigenfeld ist stilisiert, ohne eigene Live-Ziffer.

## Prüfung

```sh
python3 -m unittest discover -s tests -p 'test_kitchen_3008.py' -v
python3 scripts/build_building_stack.py --backend freecad --no-render
```

Die Quellprüfungen kontrollieren Raumzuordnung, Maßstab, Geräteauflagen,
Spülen-/Schrankmaße, kontinuierliche Raumtürhüllen und die beiden Kabinen-
öffnungen. Der Browsernachweis ergänzt die neue Raumansicht sowie Mausbedienung
von Raum-, Kühlschrank- und Mikrowellentüren. Native Geometrie, Browserbedienung
und reale Geräte-/Aufzugsausführung bleiben getrennte Nachweise.

Der native Gebäudestand `building-stack-08c6df5e4c15` besteht in FreeCAD mit
2.748 geschlossenen Körpern, 509 Geometrieproben und 18 Höhenprüfungen.
`kitchen-lift-native-check.json` im selben lokalen Exportverzeichnis ergänzt
elf bestandene Prüfungen: freie Spülenausschnitte, kollisionsfreier Sitz des
Beckens, beide Kabinenöffnungen und die vier Küchen-/Raumtüren in 3°-Schritten.
Dabei wurden 58 native Körperpaare genauer geschnitten, ohne Kollision.
Diese diskrete CAD-Prüfung ergänzt die durchgehende Quellhülle der Raumtüren;
sie ist kein kontinuierlicher Freigangsnachweis aller Gerätegelenke.

Der lokale Rundgang `building-walkthrough-8e393d682087` enthält 3.431 native
Körper einschließlich der bestehenden Laborausstattung. `browser-check.json`
und `mechanisms-browser-report.json` bestehen: sieben Ansichten, alle 139
Raumtüren, Mausbedienung der beiden Küchengeräte und der beiden Raumtüren von
3.008 sowie eine zeitlich ausgeführte Aufzugfahrt. Die Küchengeräte werden vom
öffentlichen Küchenblick aus durch Ziehen der Blickrichtung und Anklicken der
Griffe bedient; die generische Geräte-Prüfkamera liegt bei dieser engen
Aufstellung hinter dem geöffneten Eingangstürblatt. KG und EG öffnen nur die
Seite gegenüber dem Bedienpanel; während der Fahrt bleiben alle Türen zu.
Quellen- und Artefaktprüfsummen der nativen und Browserausgaben sind geprüft.

Die gezielten Küchen-, Gebäude- und Rundgangtests bestehen. In der älteren
synthetischen Verkehrs-Testfixture bleibt der bereits vorhandene fehlende
Eintrag `D3_002_003` offen; diese unabhängige Fixture wurde nicht geändert.
Der neue native Gebäudestand ist in FreeCAD geprüft, nicht zusätzlich in
SolidCraft. Ein realer Aufzugsbetrieb wurde nicht geprüft.
