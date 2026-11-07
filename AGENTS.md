# AGENTS.md

Diese Hinweise gelten für das Projekt SolidCraftBot.

## Leitidee: abstrakt beschreiben, automatisch ableiten

Die führende Konstruktion ist eine CAD-unabhängige, maschinenlesbare Beschreibung
der Konstruktionsabsicht. FreeCAD, SolidCraft und ROS 2/RViz sind daraus erzeugte
Fassungen. Dasselbe gilt für Arm, Stationen und spätere Mehrarmaufbauten.

Die gewünschte Entwicklungsschleife lautet:

**Idee und Anforderungen → gemeinsame Modellquelle und Protokoll → Generatoren
→ CAD/Visualisierung/Prüfung → Rückmeldung in die gemeinsame Quelle.**

- Änderungen zuerst in der passenden gemeinsamen Quelle formulieren. Maße,
  Bauteilrollen, Schnittstellen, Gelenke und Abläufe einmal beschreiben;
  zielprogrammspezifische Details gehören in die Adapter unter `scripts/`.
- Neue wiederkehrende Funktionen als portable, semantische Operationen
  ausdrücken, zum Beispiel Motoraufnahme, Lochbild oder Kaufteilinstanz.
  Bereits passende Operationen und gemeinsame Hilfsfunktionen wiederverwenden.
  Nicht für jedes CAD eine unabhängige Konstruktion derselben Funktion pflegen.
- Fehlt eine benötigte Operation, Quelle/Schema und betroffene Generatoren
  gemeinsam erweitern. Eine Planung oder ein Platzhalter ist noch keine
  implementierte Funktion; fehlende Zielunterstützung ausdrücklich melden.
- Native CAD-Bearbeitung ist für Inspektion und Entwurfsexperimente möglich.
  Dauerhafte Änderungen anschließend in Quelle oder Generator zurückführen
  und erneut ableiten. Eine automatische Rückübersetzung ist nicht eingerichtet.
  Erzeugte CAD-, Mesh- und URDF-Dateien nicht als zusätzliche führende Quellen
  von Hand weiterentwickeln.

## Redundanz vermeiden: Definition, Variante und Instanz trennen

- Jede Baugruppe besitzt genau eine führende Konstruktionsquelle. Aufstellungen
  referenzieren diese Quelle; sie enthalten nur Instanz-ID, Transformation,
  Zustand und ausdrücklich benannte Parameterüberschreibungen. Glieder,
  Gelenkrahmen, Lochbilder oder Bauteilgeometrie nicht für eine Szene kopieren.
- Varianten aus derselben Quelle ableiten. Nur unabhängige Parameter mit
  deklarierten Einheiten und gültigen Wertebereichen überschreiben; abhängige
  Maße und Gelenkanker gemeinsam neu auswerten. Unterstützte Instanzverträge
  stehen in `model/assembly-reference.schema.json`; keine unimplementierten
  Variantenfelder als verfügbar darstellen.
- Wiederholte Maßangaben durch Referenzen oder abgeleitete Ansichten ersetzen.
  Berechnete Montage- und Prüfdaten gehören in Berichte beziehungsweise eine
  eindeutig als abgeleitet markierte Bibliothek, nicht als zusätzliche
  Handkopien in Auswahl- oder Aufstellungsdateien.
- Gemeinsame Kinematik und semantische Operationen wiederverwenden. Ein
  zielprogrammspezifischer Adapter ist keine zweite Konstruktionsquelle.
- Native Ausgaben über geprüfte Build-Berichte auflösen. Revisionspfade und
  Datei-Prüfsummen gehören in diese Berichte, nicht in die Instanzdefinition.
  Quellen dürfen zur bewussten Revisionsbindung eine Quellprüfsumme tragen.
- Historische Quellen nur unter `model/history/` führen; alte Generatoren dürfen
  keine aktuellen Baugruppenausgaben überschreiben. Unabhängige Test-Fixtures
  und kuratierte README-Medien sind bewusst erhaltene Momentaufnahmen und
  werden nicht zur führenden Modellquelle.

## Zielarchitektur für Arbeitsumgebungen

Das Vier-Ebenen-Zielmodell steht in [ARCHITECTURE.md](ARCHITECTURE.md):
Arbeitsumgebung → referenzierte Möbeltypen und deren Möblierung → Geräteausstattung.
Für L01 sind Raumgeometrie, Möbelkatalog und Möblierung bereits getrennte Quellen;
`model/lab-room-l01.shared.json` bindet ihre Revisionen als Komposition. Die
bestehenden Körper-IDs, Bezugssysteme und Gerätepositionen sind zu erhalten.
Gebäudekonturen nicht in Möbeltypen und Möbelrezepte nicht in Aufstellungen
kopieren. Flur-/Mehrraumtopologie und allgemeine Gerätebindungen an Möbelrahmen
sind nächste Schritte, noch keine implementierten Funktionen. Vor entsprechenden
Änderungen auch `ARCHITECTURE.md` lesen.

Synthetische Minimalumgebungen sind ebenfalls Teil des Zielmodells: unbegrenzter
Raum, eine Referenzbank und kompakte Geräteaufstellung für Kommunikations- und
Ablauftests. Unbegrenzt, unbekannt und nur zur Darstellung begrenzt unterscheiden;
keine riesigen Ersatzräume konstruieren. Geräte- und Protokollquellen zwischen
realen und synthetischen Aufstellungen wiederverwenden. Mocks, Testzeit,
Netzwerkkommunikation und Hardwareausführung getrennt nachweisen. Die README-
Interaktion Arm/CF01/Rack ist der erste vorgesehene Ableitungsfall; dieses Profil
ist noch nicht als Generator oder Laufzeit implementiert.

## Gemeinsame Quellen und Generatoren

| Baugruppe | Führende Quelle | Aufbau |
|---|---|---|
| Laborarm | `model/robot.json` | `python scripts/build_models.py --ros2` |
| Deckelstation C01 | `model/tube-station-c01.shared.json` | `python scripts/build_tube_station.py` |
| Spitzenabwurf T01 | `model/tip-collector-t01.shared.json` | `python scripts/build_tip_collector.py` |

Die Stationsgeneratoren erzeugen derzeit FreeCAD und SolidCraft; eine
ROS-Integration der Stationen ist damit noch nicht implementiert.
Komponentendaten liegen ergänzend in `model/actuator-selection.json` und
`cad/vendor/`. Die ausgewählten Servos sind über `vendor_component` und
`mount_plate` geometrisch integriert. Die X6-Lochbildzuordnung ist in
`model/x6-mounting-interface.json` geklärt: Gehäuse 10 × M3 plus zwei
Zentrierhülsen, Ausgang 12 × M4. Dieselbe Quelle enthält nun eine Ø5-H7-Bohrung,
ein radiales Entlastungslangloch und versenkte M3×10/M4×6-Schraubenstapel.
M3×10 setzt eine bestätigte nutzbare Gewindetiefe voraus; Musterprüfung und
mechanische Qualifikation stehen aus (siehe `docs/x6-fits-fasteners.md`,
`docs/x6-interface-resolution.md` und `docs/servo-integration.md`).
X2/X4 führen Passungen und Schraubenstapel analog in
`model/x2-mounting-interface.json` und `model/x4-mounting-interface.json`.
Eigene Rund-/Entlastungsstifte sitzen mit Pressschäften in den Platten und
greifen in vorhandene Herstellerbohrungen. X4: M3×8 ISO 4762; X2: M3×6/M3×8
DIN 7984 mit reduzierter Kopfbelastbarkeit. Siehe `docs/x2-x4-fits-fasteners.md`.
Aktuelle Modellpfade aus den jeweiligen
Build-Berichten beziehungsweise README beziehen, nicht aus alten Dateikopien.

Die gemeinsame Beschreibung umfasst nach Bedarf:

- Parameter und Abhängigkeiten mit Einheiten, starre Baugruppen, stabile IDs,
  benannte Schnittstellen und Koordinatenrahmen.
- Gelenktypen, Anker, Achsen, Nullstellungen, Grenzwerte und Referenzposen.
- Kaufteilreferenzen mit Revision/Prüfsumme, Montagebeziehungen und eigenen
  parametrischen Anschlussplatten.
- Bewegungs- und Laborprotokolle mit Zuständen, Vorbedingungen, Rückmeldungen
  und Fehlerfällen; dieselben IDs verbinden Ablauf und 3D-Prüfung.
- Nicht sichtbare Anforderungen wie Versorgung, Positionsrückmeldung,
  Kabelführung, Biegeradius, Freiraum, Lasten und Kalibrierbeziehungen.

Unbekannte Werte als offen beziehungsweise `null` führen. Geplante
Schemaerweiterungen nicht als bereits unterstützte Felder ausgeben. Das feste
Sechsachsen-Roboterschema nicht für anders aufgebaute Stationen zweckentfremden.

## Darstellung passend zur Aufgabe

| Ziel | Aufgabe und Detailgrad |
|---|---|
| FreeCAD | Native parametrische Geometrie und Bewegungsdarstellung; Herstellergeometrie für Kaufteile wiederverwenden |
| SolidCraft | Dieselbe Konstruktion und Gelenkstruktur durch den SolidCraft-Adapter erzeugen |
| ROS 2/RViz | Gemeinsame Rahmen, Gelenke, Zustände und Protokolle; leichte Visualisierung und gesonderte Kollisionsgeometrie |
| Gazebo, bei späterem Bedarf | Physik-/Sensorsimulation mit begründeten Massen, Trägheiten, Antriebs- und Kontaktannahmen |

RViz visualisiert Zustände und Sensordaten; es berechnet keine mechanische
Physik. Der aktuelle ROS-Aufbau verwendet Mock-Hardware. ROS-Laufzeit,
Hardwareanbindung und Gazebo nur dann als geprüft bezeichnen, wenn sie
tatsächlich ausgeführt und validiert wurden.

Die Abstraktion soll unnötige Detailarbeit vermeiden: Fasen, Gewinde oder
einzelne Getriebezähne nur modellieren, wenn Fertigung, Kontakt, Passung oder
die konkrete Untersuchung sie benötigen. Für Kinematik können Übersetzung,
Schnittstellen und Bauraum genügen. Vereinfachungen und ihre Prüfgrenzen
dokumentieren; relevante Anschlüsse, Freiräume und Kabelanforderungen erhalten.

Herstellergeometrie unverändert archivieren; Vereinfachungen separat und
nachvollziehbar ableiten. Eigene Motorplatten bleiben editierbare Konstruktionen.
Servos in RViz als einfache Quader vorsehen, ohne dieselbe Servogeometrie noch
einmal im Gliedmesh darzustellen. Gehäuse dem tragenden Elternlink, rotierenden
Ausgang dem Kindlink zuordnen. Montageframes und Lochbilder aus Zeichnungen
registrieren; CAD-Flächenindizes oder geschätzte Außenmaße sind keine stabile
mechanische Schnittstelle. Eine vereinfachte Hülle liefert keine reale Masse
oder Trägheit.

## Projektgrenzen

- Sechs Drehachsen sind eine feste Eigentümeranforderung.
- Zunächst einen Arm entwickeln; bis zu drei Arme an einer Station vorsehen.
- Die austauschbare Pipettenaufnahme bleibt zunächst außerhalb des CAD-Umfangs.
  Das Modell endet an einem allgemeinen Flansch.
- Budgetziel des ersten begrenzten Prototyps: 3.000–5.000 EUR.
- Vorhandene Pipetten, Messgeräte, 3D-Drucker und Universitätswerkstatt berücksichtigen.
- Projektdateien unter diesem Projektordner halten.

## Vor Änderungen lesen

README.md sowie docs/requirements.md, docs/design.md und docs/development-plan.md.
Für Änderungen an Quelle oder Generatoren außerdem `docs/shared-model.md` lesen;
für ROS `docs/ros2.md`, für Kaufteile `docs/vendor-cad-plan.md` und die
Dokumentation der jeweils betroffenen Baugruppe.

## Arbeitsablauf und Rückmeldung

1. Anforderungen und maßgebliche Quelle bestimmen; betroffene Schnittstellen,
   Generatoren und Prüfungen identifizieren.
2. Konstruktionsabsicht in der Quelle ändern, benötigte Adapter ergänzen und
   die betroffenen Zielmodelle neu erzeugen. Unterstützte Ausgaben gemeinsam
   aktuell halten. Fehlende Backends oder bewusst ausgelassene Inhalte benennen.
3. Geometrie, Gelenkrahmen und relevante Protokollstellungen vergleichen.
   Parametervarianten müssen Geometrie und Anker zusammen verändern. Fehler
   mit Baugruppen-/Gelenk-/Protokoll-ID auf die Quelle zurückführen.
4. Quellstand, Generatorstand, Ausgaben und Prüfgrenzen im Build-Bericht
   zuordnen. Neue Revisionen erzeugen, damit geöffnete oder historisch geprüfte
   Konstruktionen nachvollziehbar bleiben.
5. Dokumentation und Einstiegspfade aktualisieren. Im Ergebnis sagen, was sich
   tatsächlich geändert hat, welche Fassungen erzeugt wurden, was geprüft ist
   und welche Teile weiterhin Platzhalter sind.

Für den Arm ist der gemeinsame Einstieg `python scripts/build_models.py --ros2`.
Bei Änderungen an Generatoren oder Modellverträgen die passenden Prüfungen
ausführen; die vorhandene Offline-Suite startet mit
`python -m unittest discover -s tests -v`. Reine Dokumentationsänderungen
benötigen keinen CAD-Neuaufbau. Ein erfolgreicher Dateiexport allein gilt nicht
als bestandene Geometrie-, Bewegungs- oder Funktionsprüfung.

## CAD und Validierung

- SolidCraft-MCP für die Ausführung des SolidCraft-Adapters und Modellinspektion
  bevorzugen. Der reproduzierbare CLI-Aufbau ist ein vorhandener Ausführungsweg;
  beide müssen dieselbe gemeinsame Quelle verwenden.
- Längen in mm; Gelenkwinkel und Grenzwerte mit expliziten Einheiten dokumentieren.
  ROS-Ausgaben ausdrücklich in m/rad umrechnen; Zeiten in s führen.
- Vor Ersetzen einer offenen Konstruktion deren Änderungen und Speicherort prüfen.
- Konzept-Bauräume nicht als ausgewählte oder berechnete Kaufteile ausgeben.
- Bei Änderung der Gliedlängen Geometrie und Gelenkanker aus denselben Parametern
  ableiten und neu prüfen. Im historischen, direkt erstellten A01-Konzept sind
  die Elternkoordinatensysteme fest; eine isolierte native Maßänderung gleicht
  diese nicht automatisch ab.
- Nach geometrischen Änderungen Gelenklösung und betroffene Stellungen prüfen.
  Standpose und vollständigen Bewegungsraum im Prüfbericht unterscheiden.
- Überlappende Konstruktionskörper innerhalb einer starren Baugruppe sind im
  Konzept dokumentiert; daraus folgen keine geprüften Passungen.
- Tragfähigkeit, Steifigkeit, Präzision, Dosierleistung und Sicherheit anhand
  geeigneter Messungen oder Berechnungen belegen, bevor sie zugesichert werden.

## Renderings und Dokumentation

Der Eigentümer hat am 28. Oktober 2026 Modellrenderings und deren Speicherung
für dieses Projekt ausdrücklich freigegeben. Für Modellansichten bevorzugt
SolidCraft `source: model` verwenden.

Anforderungen, Konstruktionsentscheidungen und Grenzen zusammen mit dem CAD
aktualisieren. Exportdateien und Renderings dem zugehörigen Modellstand zuordnen.
