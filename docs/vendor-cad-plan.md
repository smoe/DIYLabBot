# Herstellerkomponenten im gemeinsamen Modell

Stand: 28. Oktober 2026. Ziel ist, gekaufte Servomodule einmal zu registrieren
und daraus FreeCAD, SolidCraft und eine leichte ROS-2-Darstellung abzuleiten.
Unsere konstruktive Arbeit liegt vor allem in Motorplatten, Lagerung, Gliedern,
Kabelhaltern und ihren Schnittstellen.

## Verfügbare Dateien und aktueller Umfang

Für X2-P28-7-E, X4-P36-36-E-L und X6-P20-60-E sind originale STEP-Dateien und
zugehörige PDF-Zeichnungen/Parameterblätter aus den
[Herstellerpaketen](https://www.myactuator.com/downloads-xseries) gespeichert.
Der [lokale Bibliotheksindex](../cad/vendor/myactuator/README.md) enthält die
Dateipfade; das Manifest hält Quelle, Revision, Originalnamen und SHA-256 fest.
Jede der drei Größen wird nur einmal gespeichert und für mehrere Gelenke instanziert.

Die STEP-Dateien sind Außenmodelle, keine parametrische Fertigungshistorie.
Beim X4 enthält die Originaldatei auch offene Schalen und zwei ungültige,
mikroskopisch kleine Volumenkörper. Die abgeleitete Referenz erhält die Schalen
und lässt ausschließlich diese beiden dokumentierten Artefakte weg. Die
Originaldatei bleibt unverändert. Wiederöffnung, Gültigkeit und Außenabmessungen
werden im [Geometriebericht](../cad/vendor/myactuator/geometry-check.json) geprüft.
Diese Prüfung erlaubt die Verwendung als Bauraum-/Montagereferenz; sie bestätigt
keine Toleranzen, Schraubverbindungen oder Fertigungsmaße.

Die Bibliothek und die [Gelenkzuordnungen](../model/actuator-selection.json)
sind inzwischen geometrisch integriert: `vendor_component` und `mount_plate`
in `model/robot.json` erzeugen beide CADs und sechs RViz-Gehäusequader.
Die bisherigen Antriebsplatzhalter sind ersetzt. Der aktuelle Stand, die
X6-Lochbildklärung und die Prüfungen stehen im
[Integrationsbericht](servo-integration.md). Die nachfolgenden Abschnitte
beschreiben die Architektur; Last-, Präzisions- und Fertigungsfreigabe stehen aus.

## Drei Darstellungen derselben Komponente

| Verwendung | Darstellung | Was erhalten bleiben muss |
|---|---|---|
| SolidCraft und FreeCAD | Hersteller-STEP als Referenz; später optional vereinfachte Hülle | Befestigungsflächen, Zentrierung, Ausgang, Stecker, Kabelausgang und nötiger Freiraum |
| RViz | Ein einfacher Quader je Servogehäuse | Richtige Größe, Pose und Zuordnung zum tragenden Glied; Farbe zur Orientierung |
| Kollisionsprüfung | Konservative Hülle plus gesonderte Freiräume | Gehäuse, Vorsprünge, Stecker, Montagezugang und bewegte Leitungen |

„Box for the optics“ wird als vereinfachte **optische Darstellung des Servos**
in RViz umgesetzt. Sie enthält keine Optikbaugruppe. Der Arm selbst bleibt dort
als leichte Gliedgeometrie sichtbar; die Servogeometrie darf nicht zusätzlich im
alten Gliedmesh enthalten bleiben und damit doppelt dargestellt werden.

Die gespeicherten `conservative-box.step`-Dateien umschließen die gesamte
Herstellergeometrie in deren ursprünglichen Achsen. Ihre Abmessungen sind in mm;
sie enthalten **noch keinen** Zuschlag für Steckerbetätigung, Kabelbewegung,
Wärme oder Werkzeugzugang. Sie sind Ausgangsdaten für RViz und Bauraumplanung,
keine fertige Kollisionshülle der eingebauten Achse. Nach Registrierung am Arm
werden deren Pose und Maße nach m/rad in URDF übernommen.

Für flüssige CAD-Bedienung kleine Gewinde, Gravuren und interne Details erst in
einer zweiten, abgeleiteten Repräsentation vereinfachen. Schnittstellen und
Außenkontur anhand des Originals prüfen und jeden Vereinfachungsschritt
nachvollziehbar speichern. Getriebezähne müssen wir nicht nachkonstruieren.
Die Massen kommen aus der dokumentierten Stückliste; Materialdichte und Trägheit
werden nicht aus dem Volumen eines vereinfachten Hersteller-Außenmodells geraten.
Gazebo benötigt später eigene, geprüfte Massen-, Trägheits- und Antriebsdaten.

## Schnittstellen statt nachgebauter Motoren

Pro Baugröße werden zwei getrennte mechanische Schnittstellen registriert:
die stationäre Gehäusebefestigung und der rotierende Ausgang. Die gemeinsame
Beschreibung erhält dafür:

- Gehäuse-Montagerahmen, Ausgangsflanschrahmen und eine definierte positive
  Drehachse +Z; Transformationen als starre Matrizen mit Längen in mm.
- Mechanische Nullstellung, Drehsinn und Winkelversatz zum Gebernullpunkt.
- Lochbilder, Gewinde, Einschraubtiefen, Zentrierbund/-bohrung und Bezugsflächen
  mit Quellenangabe zur jeweiligen Zeichnungsrevision.
- Kabel-/Steckerrahmen, Auszugsrichtung, Zugentlastung sowie Einbau- und
  Wartungsfreiräume.
- Kennzeichnung, welche Herstellerkörper zum Gehäuse und welche zum Ausgang
  gehören, oder bewusst eine vereinfachte Ausgangsdarstellung.

Dateiursprung und längste Bounding-Box-Achse reichen dafür nicht. Die drei
gelieferten STEP-Modelle verwenden unterschiedliche Achslagen. Die Matrizen
und Lochbilder werden aus Zeichnungen und CAD registriert. Die aktuelle
Registrierung ist umgesetzt; die X6-Maßpfeilzuordnung ist geklärt und korrigiert.
Der Abgleich mit Musterteilen steht aus. Unbekannte Passungen und Gebernullpunkte bleiben
ausdrücklich `null`. Keine Bohrplatte aus geschätzten Bildschirmmaßen erzeugen.

Motorplatten werden anschließend als eigene parametrische Konstruktionen
abgeleitet: Dicke, Kontur, Schraub-/Zentrierstellen, Lageraufnahme und Kabelhalter
bleiben unsere Parameter. Eine definierte Zentrierung beziehungsweise Passstifte
bestimmen die Lage; Schrauben liefern die Klemmung. Passung, Plattensteifigkeit,
Schraubeneingriff und Lagerlasten werden gerechnet oder gemessen, bevor eine
Fertigungsfreigabe entsteht.

## Folgen für die sechs Gelenke

| Gelenk | Gehäuse am bisherigen Elternlink | Rotierender Ausgang am Kindlink | Nächste konstruktive Frage |
|---|---|---|---|
| J1 | L0_Base | L1_Turret | X4-Aufnahme, Basislagerung und Leitungsdurchgang |
| J2 | L1_Turret | L2_UpperArm | X6-Motorplatten, Gegenlager, Haltesicherung und Schwerkraftlast |
| J3 | L2_UpperArm | L3_Elbow | Integrierten X4 am Ellenbogen gegen bisherige entfernte Motor-/Riemenlösung abwägen |
| J4 | L3_Elbow | L4_ForearmRoll | X2-Durchmesser, Ausgangskopplung und Kabelweg |
| J5 | L4_ForearmRoll | L5_WristPitch | X2-Gabel, Gegenlager und enger Bewegungsfreiraum |
| J6 | L5_WristPitch | L6_BareFlange | X2-Ausgang auf den allgemeinen freien Flansch adaptieren |

Ein Hersteller-Außenmodell darf nicht vollständig mit dem Kindlink rotieren:
das Gehäuse bleibt am Elternlink, nur der Ausgang dreht relativ dazu. Auch ein
in SolidCraft als starre Gruppe importiertes STEP braucht diese ausdrücklich
geprüfte Aufteilung. Fehlt sie, verwenden wir eine Gehäusereferenz mit eigener
vereinfachter Ausgangsscheibe statt einer falschen Animation.

Beim Ellenbogen ist die Bestückung keine bloße Dateiersetzung. Das Konzept
zeigt derzeit einen schulternahen Motor mit Riemenübertragung. Ein integriertes
X4 am Gelenk verändert Masse, Schwerkraftmoment, Steifigkeit und Kabelposition.
Direktmontage und entfernte Übertragung zunächst vergleichen; bei einer weiteren
Übertragung reicht ein Geber vor dem Riemen nicht als Messung der tatsächlichen
Ellenbogenlage. Alte Motor-, Getriebe- und Lagerbauräume erst entfernen, wenn die
neue Last- und Schnittstellenaufteilung feststeht. Zusätzliche Getriebe nicht
versehentlich zu den bereits integrierten Getrieben addieren.

## Umsetzung in der Entwicklungsschleife

1. **Bibliothek und Nachweise — umgesetzt.** Drei Herstellerpakete,
   unveränderte Originale, Referenzgeometrie, vereinfachte Teilgeometrien,
   Quader und Importberichte sind gespeichert.
2. **Schnittstellen und ein Prüfglied — teilweise umgesetzt.** Gehäuse-/
   Ausgangsrahmen und nominale Lochbilder sind registriert; die X6-Zuordnung
   ist geklärt. Vor Fertigung Passungen und eine Schulter-/Ellenbogenaufnahme am Prüfstand
   qualifizieren. Last-, Spiel-, Steifigkeits-, Temperatur- und Regelungsversuche
   nach dem [Auswahldokument](actuator-selection.md) bestimmen die Freigabe.
3. **Gemeinsames Schema — umgesetzt.** Semantische Operationen `vendor_component`
   und `mount_plate` sind implementiert. Komponenten-ID und Bibliotheksrevision,
   Gehäuse-/Ausgangszuordnung und explizite Transformationen ersetzen CAD-
   spezifische Flächenindizes. Ungeklärte Schnittstellen bleiben gekennzeichnete
   Konzeptgeometrie ohne Fertigungsfreigabe.
4. **Beide CAD-Adapter — umgesetzt.** FreeCAD liest die registrierte STEP-Geometrie
   mit `Part` und instanziiert sie getrennt von nativen Plattenfeatures.
   SolidCraft 0.25.1 bietet `file.insert_step` mit starrer `matrix` und eigener
   Komponente; importierte Gruppen bleiben zunächst starr. Die Anbindung an
   Elternlink und Ausgang wird durch den Adapter hergestellt. Diese Befehle
   sind verfügbar; der gemeinsame Komponentenadapter ist inzwischen implementiert.
5. **Armrevision — erzeugt und in Stichproben geprüft.** Neue Motorplatten und
   Komponenten sind eingebaut; gemeinsame Parameter führen Geometrie und Anker.
   Beide CADs werden in Standpose und Einzelbewegungen geprüft, FreeCAD außerdem
   an Protokollstichproben. Bewegungsraum, Kabel und Kollisionen
   brauchen weitere Prüfungen über die Standpose hinaus. Jede Ausgabe erhält
   eine neue Revision; geöffnete Konstruktionen vorher auf Speicherstand prüfen.
6. **RViz erzeugt; Hardwareanbindung offen.** Der ROS-Exporter trennt Strukturmeshes und
   Servo-Rollen, exportiert Servo-Quader und getrennte Kollisionshüllen und
   prüft Einheiten, Lage und einmalige Darstellung. Gemessene Antriebszustände
   ersetzen später Mock-Rückmeldungen. Hersteller-Nenndrehzahl und -moment
   werden nicht direkt als zulässige Arm-Grenzwerte übernommen.
7. **Mehrarmbetrieb.** Dieselbe Komponentenbibliothek für weitere Instanzen
   nutzen. Armpräfixe, Stationskalibrierung, Ressourcenreservierung und
   Interarm-Kollisionen ergänzen; gemeinsame Protokolle nach gemessener
   Zykluszeit und Qualität optimieren.

Damit bleibt die schnelle Schleife erhalten: Protokoll oder Geometrie in der
gemeinsamen Quelle ändern, passende Darstellungen automatisch erzeugen,
prüfen und das Ergebnis auf einen bestimmten Modell- und Komponentenstand
zurückführen. Die Zahl der Schraubenflächen im Hersteller-STEP beeinflusst
die Protokollentwicklung nicht.
