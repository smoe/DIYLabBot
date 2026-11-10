# Wiederverwendbares Laborglas

Die Bibliothek enthält hohle Bechergläser mit Ausguss, durchgängige Glastrichter
und Flaschen mit getrenntem Schraubdeckel beziehungsweise Glasstopfen. Sie dient
der Konstruktion und geometrischen Ablaufplanung. Alle Größenvarianten entstehen
aus denselben drei portablen Familienrezepten.

Führende Quelle ist [lab-glassware.shared.json](../model/lab-glassware.shared.json),
Vertrag [lab-glassware.schema.json](../model/lab-glassware.schema.json).
`scripts/lab_glassware.py` wertet Parameter, Innenräume, Zustände und Zugangsbezüge
gemeinsam aus. FreeCAD und SolidCraft konstruieren ihre Geometrie unabhängig
aus dieser Ableitung. STEP dient ausschließlich dem zusätzlichen Vergleich.

## Vorbild und Maßstatus

Das verlinkte [Sigma-Aldrich-Becherglas Z740576](https://www.sigmaaldrich.com/DE/de/product/aldrich/z740576)
ist ein niedriges 250-ml-Becherglas aus Borosilikatglas mit Ausguss und flachem
Boden. Seine Referenzskala reicht von 25 bis 200 ml in 25-ml-Schritten.
Die am 10. November 2026 gelesene Produktbeschreibung enthält keine Außenmaße.
Diese belegten Angaben stehen getrennt unter `references`; `outer_dimensions_mm`
bleibt `null`. Die Skala wird als Herstellerangabe erhalten, nicht als kalibrierte
Messfunktion oder aufgedruckte CAD-Geometrie ausgegeben.

Durchmesser, Höhe und Wanddicke der Modelle sind ausdrücklich angenommene Maße.
Auch die anderen Größen und Flaschen sind generische Planungsmodelle ohne
Herstellerbindung. Es werden weder Herstellergeometrie noch Logos kopiert.
Gemessene Leermasse und Dichte sind unbekannt; aus der Darstellung wird keine
reale Masse abgeleitet. Der Werkstoffeintrag beschreibt die Glasgefäße; ein
Kunststoff oder eine Dichtung für die Schraubdeckelhülle ist nicht ausgewählt.

## Auswahl

| Familie | Artikel-IDs | Auswahl |
|---|---|---|
| Becherglas mit offenem Ausguss | `beaker_100`, `beaker_250`, `beaker_500` | 100, 250 und 500 ml Nennvolumen |
| Glastrichter mit offenem Ablaufrohr | `funnel_60`, `funnel_80` | 60 und 80 mm oberer Außendurchmesser |
| Glasflasche mit Schraubdeckel | `screw_bottle_100`, `screw_bottle_250`, `screw_bottle_500` | 100, 250 und 500 ml Nennvolumen |
| Glasflasche mit Glasstopfen | `stopper_bottle_250` | 250 ml Nennvolumen |

Ein Artikel enthält nur Familie, Nennvolumen, Verschlussart und ausdrücklich
überschriebene unabhängige Maße. Die Familienquelle enthält die Parameter mit
Einheiten und gültigen Bereichen; abhängige Radien und Höhen werden neu abgeleitet.
Eine geänderte Wanddicke ändert damit auch den freien Querschnitt.

## Zustände und nutzbare Bezüge

Becher und Trichter haben die Konfiguration `open`. Bei Flaschen gibt es
`closed` und `open`. Der Verschluss ist ein eigener Körper in einer eigenen
Gruppe; im offenen Zustand liegt er neben dem Gefäß auf derselben Bezugsebene.
Das sind statische Konfigurationen. Es gibt kein erfundenes Bewegungs- oder
Schraubgelenk und keine ausgeführte Entfernung des Verschlusses.

- Alle Artikel führen einen Mundrahmen mit freiem Durchmesser und
  `accessible`. `accessible_mouth(spec, p)` weist geschlossene Flaschen zurück.
- Becher und Flaschen führen Bodenauflage, Körpergreifachse und eine aus
  dem Nennvolumen berechnete Füllebene. Der Ausguss besitzt einen Richtungsbezug.
- Trichter führen getrennte Einlass-, Auslass- und Schaftgreifbezüge. Sie
  benötigen eine Halterung; ein freistehender Trichter ist nicht vorgesehen.
- Flaschen führen zusätzlich eine mit dem Verschlusszustand versetzte Greifachse.
  Die Mundposition bleibt beim Entfernen des Verschlusses erhalten.

Die Rahmen sind geometrische Planungsbezüge und keine kalibrierten Roboterziele.
Sie stehen im Build-Bericht und im FreeCAD-Modell. Nach nativen Maßexperimenten
Geometrie und Rahmen aus der gemeinsamen Quelle neu erzeugen.

Nennvolumen und geometrisch berechneter Innenraum bleiben getrennt.
`cavity_volume_ml` und `fill_height_mm` werten gerade Zylinder und Kegelstümpfe
mit **1 ml = 1000 mm³** aus. Beim Becher endet der ausgewertete freie Zylinder
unterhalb der Ausgusswurzel; zusätzliche Ausgussräume und Überlauf werden nicht
mitgerechnet. Bei Flaschen wird der Innenraum bis zum Mund ausgewertet, bevor
ein Stopfen dessen oberen Teil belegt. Beim Trichter ist dies ein durchgängiger
Strömungsraum, kein zurückgehaltenes Flüssigkeitsvolumen. Eine Füllmengenabfrage
ist kein tatsächlicher Inhalt und erzeugt keine Inventarbuchung.

## Aufbauen und referenzieren

```sh
python3 scripts/build_lab_glassware.py
python3 scripts/build_lab_glassware.py --item beaker_250
python3 scripts/build_lab_glassware.py --backend freecad
python3 scripts/build_lab_glassware.py --backend solidcraft
python3 -m unittest discover -s tests -p 'test_lab_glassware.py' -v
python3 scripts/validate_assembly_schemas.py  # optionales Entwicklungspaket jsonschema
```

Jeder Lauf schreibt eine neue Revision unter `cad/generated/`,
`exports/generated/` und `renders/`. Aktuelle Modellpfade, Prüfsummen und die
native Übersicht löst der lokale
[Build-Bericht](../cad/lab-glassware/shared-build-report.json) auf. Der vollständige
Aufbau enthält 13 Artikel-/Zustandsfälle, eine Maßvariante des 250-ml-Bechers und
eine aus Artikelreferenzen abgeleitete Übersicht. Diese Übersicht ist eine
Kontaktansicht der Bibliothek ohne Bank oder Halter und keine Laboraufstellung.

Ein gemeinsamer Baugruppenverweis wählt einen konkreten Berichtsfall:

```json
{
  "source": "model/lab-glassware.shared.json",
  "report": "cad/lab-glassware/shared-build-report.json",
  "case": "screw_bottle_250_open"
}
```

`lab_glassware.resolve_reference(ref)` materialisiert die passende Quelle;
`assembly_model.resolve_artifact(ref)` prüft die Quellbindung und löst die
geprüfte FreeCAD-Datei auf. Für Größe und Zustand derselben Baugruppe keine
Geometrie in eine Aufstellung kopieren. Die Bibliothek besitzt noch keine
automatische Einbindung in die vorhandenen L01-/Analytik-Layoutadapter oder
in ein ROS-/URDF-Gerätemodell.

## Geometrieprüfung und Grenzen

Der vollständige Aufbau vergleicht Körperzahl, Volumen, Schwerpunkt,
Begrenzungsquader und die symmetrische STEP-/BRep-Differenz beider CADs.
FreeCAD prüft den echten freien Innenraum gegen das Glas, die geschlossenen
Böden, freie Ausgusskanäle, den durchgängigen Trichterquerschnitt und die zur
Konfiguration passende Öffnungsblockierung. Verschlüsse dürfen das Glas nicht
durchdringen; abgelegte Verschlüsse stehen neben dem Gefäß auf der Bezugsebene.
Speichern und Wiederöffnen sowie gemeinsam veränderte Geometrie-/Mundbezüge
werden ebenfalls geprüft. Ein einzelnes Backend weist keinen CAD-Vergleich nach;
ein SolidCraft-Alleinlauf enthält die FreeCAD-BRep-Funktionsprüfungen nicht.

Der Ausguss ist eine vereinfachte offene Rinne. Die Schraubdeckelhülle besitzt
kein Helixgewinde; der Stopfen keine qualifizierte Schliffpassung. Flüssigkeitsfluss,
Benetzung, Dichtigkeit, Glasfestigkeit, Heizen und robotische Handhabung werden
nicht simuliert oder qualifiziert. Die Modelle führen keine realen Proben oder
Füllstände und sind nicht an den manuellen Laborrunner angebunden.
