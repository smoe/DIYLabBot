# Wiederverwendbares Laborglas

Die Bibliothek enthält hohle Bechergläser mit Ausguss, durchgängige Glastrichter,
Messzylinder mit Sechskantfuß und Flaschen mit getrenntem Schraubdeckel beziehungsweise Glasstopfen. Sie dient
der Konstruktion und geometrischen Ablaufplanung. Alle Größenvarianten entstehen
aus denselben vier portablen Familienrezepten. Optionale Markerbeschriftungen
gehören zur einzelnen Gefäßinstanz.

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
Eine Ausnahme ist die dokumentierte Höhe des neuen 5-ml-Messzylinders:
[BRAND/BLAUBRAND Z324310](https://www.sigmaaldrich.com/US/en/product/sigma/z324310)
besitzt laut Herstellerbeschreibung 5 ml Nennvolumen, 115 mm Gesamthöhe,
0,1-ml-Unterteilung, einen Ausguss und einen sechseckigen Glasfuß. Die ursprünglich
angefragte deutsche URL ließ sich nicht abrufen; die geprüfte US-Produktseite ist
unter `verified_url` dokumentiert. Nicht dokumentierte Durchmesser, Fußmaße und
der erste Skalenwert bleiben ausdrücklich unbekannt. Die CAD-Nachbildung erhält
keine metrologische Klassifizierung oder Kalibrierung des Herstellerartikels.

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
| Glasflasche mit Glasstopfen | `stopper_bottle_100`, `stopper_bottle_250`, `stopper_bottle_500` | 100, 250 und 500 ml Nennvolumen |
| Messzylinder mit Sechskantfuß | `measuring_cylinder_5`, `measuring_cylinder_10`, `measuring_cylinder_25`, `measuring_cylinder_50` | 5, 10, 25 und 50 ml Nennvolumen |

Das Quellformat `solidcraftbot.lab-glassware/2` trennt Familienrezepte, benannte
Größen unter `families.<family>.sizes`, gemeinsame Verschlüsse und Artikelreferenzen.
Jede Körpergröße beschreibt Nennvolumen und unabhängige Maßüberschreibungen
einmal. Schraub- und Stopfenflaschen referenzieren dieselben Körpergrößen;
Artikel enthalten keine kopierten Maßtabellen. Weitere Größen werden als explizite
Parameterstände ergänzt, nicht durch Skalieren fertiger CAD-Körper.

`closures.screw_cap_standard` und `closures.glass_stopper_standard` führen jeweils
eine gemeinsame Hals-/Verschlussgeometrie. Die 100-, 250- und 500-ml-Flaschen
verwenden pro Verschlussart identische Halsmaße, Deckel beziehungsweise Stopfen.
Eine größere Flasche oder geänderte Körperwand skaliert den Verschluss nicht mit.
Maßüberschreibungen von Gefäßinstanzen dürfen Hals-/Verschlussparameter nicht
ändern. Neue Hals- oder Verschlussgrößen benötigen eine ausdrücklich neue
gemeinsame Verschlussdefinition. Diese generischen Schnittstellen beanspruchen
keine GL-Gewinde- oder Normschliffkompatibilität.

## Zustände und nutzbare Bezüge

Becher, Trichter und Messzylinder haben die Konfiguration `open`. Bei Flaschen gibt es
`closed` und `open`. Der Verschluss ist ein eigener Körper in einer eigenen
Gruppe; im offenen Zustand liegt er neben dem Gefäß auf derselben Bezugsebene.
Das sind statische Konfigurationen. Es gibt kein erfundenes Bewegungs- oder
Schraubgelenk und keine ausgeführte Entfernung des Verschlusses.

- Alle Artikel führen einen Mundrahmen mit freiem Durchmesser und
  `accessible`. `accessible_mouth(spec, p)` weist geschlossene Flaschen zurück.
- Becher, Messzylinder und Flaschen führen Bodenauflage, Körpergreifachse und eine aus
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
mit **1 ml = 1000 mm³** aus. Bei Becher und Messzylinder endet der ausgewertete freie Zylinder
unterhalb der Ausgusswurzel; zusätzliche Ausgussräume und Überlauf werden nicht
mitgerechnet. Bei Flaschen wird der Innenraum bis zum Mund ausgewertet, bevor
ein Stopfen dessen oberen Teil belegt. Beim Trichter ist dies ein durchgängiger
Strömungsraum, kein zurückgehaltenes Flüssigkeitsvolumen. Eine Füllmengenabfrage
ist kein tatsächlicher Inhalt und erzeugt keine Inventarbuchung.

## Optionale Beschriftung mit Marker

`label` ist ein optionaler Instanzparameter, der Handschrift mit einem
wasserfesten Marker darstellt: frei gesetzter Text, Tintenfarbe und gewünschte
Schrifthöhe beziehungsweise Strichbreite. Der Artikelname im Katalog bleibt
eine davon getrennte Bezeichnung. Ein und derselbe Becher kann so als mehrere
Instanzen mit unterschiedlichen Probenbeschriftungen auftreten.

```python
import lab_glassware as glass

spec = glass.materialize(glass.load(), "beaker_250",
    label={"text": "DNA 01\n5 µl", "color": "#18242b", "height_mm": 5})
```

`scripts/marker_label.py` übersetzt portable Stiftpfade einmalig in schmale,
an die zylindrische oder konische Außenfläche angepasste Striche. Beide nativen
CADs erhalten dieselbe Darstellung; eine installierte Schriftart ist nicht nötig.
Groß-/Kleinschreibung bleibt erhalten. Unterstützt sind lateinische Buchstaben
einschließlich deutscher Umlaute/ß, Ziffern, µ und die dokumentierten üblichen
Satzzeichen. Bis zu drei Zeilen sind möglich. Längere Texte werden innerhalb
der freien Beschriftungszone verkleinert oder bei fehlendem Platz zurückgewiesen.
Der Bericht nennt die tatsächlich verwendete Schrifthöhe und Strichbreite.

Die Körperrolle `marker_ink` kennzeichnet reine Darstellungsannotation. Die
Stiftbreite ist eine visuelle Linienbreite, keine gemessene Schichtdicke.
Gefäßvolumen, Öffnungsbezüge und Verschlüsse ändern sich durch Text oder Farbe
nicht. Beschriftung ist kein Scan, Identitätsnachweis oder Inventareintrag.
Textänderungen werden durch erneute Ableitung übernommen; native Einzelstriche
bilden keine zweite führende Textquelle.

## Aufbauen und referenzieren

```sh
python3 scripts/build_lab_glassware.py
python3 scripts/build_lab_glassware.py --item beaker_250
python3 scripts/build_lab_glassware.py --item beaker_250 --label 'DNA 01' --label-color '#154985'
python3 scripts/build_lab_glassware.py --item measuring_cylinder_5 --label QC
python3 scripts/build_lab_glassware.py --backend freecad
python3 scripts/build_lab_glassware.py --backend solidcraft
python3 -m unittest discover -s tests -p 'test_lab_glassware.py' -v
python3 scripts/validate_assembly_schemas.py  # optionales Entwicklungspaket jsonschema
```

Jeder Lauf schreibt eine neue Revision unter `cad/generated/`,
`exports/generated/` und `renders/`. Aktuelle Modellpfade, Prüfsummen und die
native Übersicht löst der lokale
[Build-Bericht](../cad/lab-glassware/shared-build-report.json) auf. Der vollständige
Aufbau enthält 21 Artikel-/Zustandsfälle, eine Maßvariante des 250-ml-Bechers,
vier Beschriftungsfälle für die vier Familien und
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

`lab_glassware.resolve_reference(ref, label={"text": "Buffer A"})` materialisiert die passende Quelle mit optionaler Instanzbeschriftung;
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

Der Messzylinderfuß wird gegen das analytische Volumen eines sechseckigen Prismas
geprüft. Verschlussprofile, lokale Körpermaße, Schwerpunkt und Volumen werden
über alle Flaschengrößen und beide Zustände verglichen. Markerstriche dürfen nicht
in den freien Innenraum hineinragen; das Glas bleibt dieselbe ursprüngliche
Geometrie. Optische Lesbarkeit wird zusätzlich am nativen Modellrender geprüft.

Der Ausguss ist eine vereinfachte offene Rinne. Die Schraubdeckelhülle besitzt
kein Helixgewinde; der Stopfen keine qualifizierte Schliffpassung. Flüssigkeitsfluss,
Benetzung, Dichtigkeit, Glasfestigkeit, Heizen und robotische Handhabung werden
nicht simuliert oder qualifiziert. Die Modelle führen keine realen Proben oder
Füllstände und sind nicht an den manuellen Laborrunner angebunden.
