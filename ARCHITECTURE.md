# Architektur der Arbeitsumgebungen und Ausstattung

Die [Modellgalerie](docs/models/README.md) führt mit Bildern durch diese Ebenen
und verknüpft jede Ansicht mit den gemeinsamen Quellen und der Fachdokumentation.

Das Zielmodell trennt Arbeitsumgebung, Möbeltypen, Möblierung und
Geräteausstattung. Jede Konstruktion besitzt eine führende Quelle. Ein Standort
referenziert diese Quelle und beschreibt seine Instanzen mit Parametern,
Transformationen und benannten Bezugssystemen. CAD-Dateien bleiben Ableitungen.

FreeCAD und SolidCraft erzeugen ihre Geometrie unabhängig aus diesen Quellen.
Der Vergleich beider Ergebnisse ist eine zusätzliche Prüfung. Insbesondere
erzeugt der eigenständige CF01-SolidCraft-Adapter native Konstruktionsfeatures
und gemeinsame Protokollstellungen ohne FreeCAD-Dateien als Eingabe. Erhaltene
Hersteller-Gehäuseteile können unter einer gemeinsamen semantischen Geräte-ID
mehrere starre CAD-Körper bilden; ihre Zuordnung wird im Build-Bericht geführt.

## Projektweite Bewegungsvorgabe

Fließende Bewegung ist eine allgemeine Anforderung, auch bei leeren Fahrten
und Raumsondierung. Ein Wegpunkt erzeugt keine Pause. Eine notwendige
Wartebedingung benennt die erwartete Beobachtung beziehungsweise den Abschluss
eines anderen Vorgangs. Jeder neu entwickelte oder erneuerte
beladene Transport verbindet Griff und Ablage beziehungsweise Übergabe ohne
unnötige Zwischenhalte. Durchgangsziele, Freiraumereignisse und Stations-
quittungen werden von erforderlichen Prozess- und Schutzhalten getrennt.
Ein Sicherheitsstopp darf nicht zur Einhaltung dieser Bewegungsregel entfallen.

Die gemeinsamen PVA-Kurven und FK-Ableitungen unter
`solidcraftbot_ros/motion.py` und `scripts/sample_motion.py` bilden den vorhandenen
Rechenkern für die Sechsachs-Armbahnen. Grenzen und Kein-Halt-Kriterium werden
an der tatsächlichen Kurve und nach Export geprüft; die wissenschaftliche
Belastbarkeit der Proben bleibt eine gesonderte Qualifikationsaufgabe. Es gibt
keinen automatischen Glätter beliebiger Szenen und kein neues universelles
Transportschema. Weitere Programme müssen ihre unterstützten Quellen und
Adapter entsprechend erweitern und neu nachweisen.

Die aktuelle Drei-Proben-Entnahme erfüllt die numerischen synthetischen
Prüfkriterien für beladene und leere Fahrten. Die L01-Umstellung beschreibt
sechs durchgehende Bewegungsepisoden mit demselben PVA-/FK-Kern statt der
älteren linearen Wegpunktillustration. Ihr Heberrückzug läuft nach geprüfter
Gefäßfreigabe parallel zum Transport. FreeCAD wertet die tatsächlichen Kurven
aus; die native SolidCraft-Studie bleibt ausdrücklich eine diskrete lineare
Vorschau ohne PVA-Schnittstelle. Die Nachweise und Grenzen stehen in
[docs/lab-transfer-l01.md](docs/lab-transfer-l01.md).

Die historische CF01-Einzelbahn und statische Zweiarm-Prüfstellungen sind
kein solcher Bewegungsnachweis. Die alte nackte Arm-Demo
`base_sweep_return` in `model/robot.json` verwendet weiterhin `joint_linear`;
sie ist keine nach dieser Vorgabe freigegebene Sondierungsbahn. Ihre Migration
einschließlich der abhängigen Arm-/CAD-Revisionen ist gesonderte Folgearbeit.
Abstrakte manuelle Übergaben führen keine Roboterbahn aus. Notwendige Mess-,
Pipettier-, Inkubations- und Übernahmehalte bleiben Prozesszustände.
Die [Anforderungen](docs/requirements.md#fließender-probentransport) gelten vor
der Überführung dieser Altstände in aktuelle Transportprogramme.

## Vier Beschreibungsebenen

| Ebene | Verantwortung | Abgrenzung |
|---|---|---|
| Arbeitsumgebung | Geschosse, Labore, Flure, Raumkonturen, Wände, Stützen, Fenster, Öffnungen und feste Gebäudeanschlüsse | Keine Möbel- oder Geräteinstanzen |
| Möbeltypen | Wiederverwendbare parametrische Möbel und Zubehörtypen mit lokalen Montage- und Aufstellrahmen | Keine Standorte oder L01-Koordinaten |
| Möblierung | Konkrete Möbelinstanzen mit Typreferenz, Abmessungsbindungen und Aufstellung in einem Raum oder Flur | Keine kopierten Möbelrezepte |
| Geräteausstattung | Geräteinstanzen mit Referenz auf vorhandene Quellen, Zustand und Aufstellung auf Möbeln oder direkt im Raum | Keine zweite Arm-, Stations- oder Gerätebeschreibung |

Räume und Flure sollen später eine gemeinsame Umgebung bilden. Gemeinsam
verwendete Türen und Öffnungen werden dabei einmal beschrieben; die verbundenen
Bereiche referenzieren dieselbe Öffnungs-ID. Raumgeometrie und die Topologie der
Verbindungen sind getrennte Informationen. Die Mehrraum- und Flurtopologie ist
in diesem ersten Schritt noch nicht implementiert.

Ein optionales Anforderungsprofil kann später erwartete Möbel- und Gerätearten
benennen. Solche Anforderungen erzeugen noch keine tatsächlich aufgestellten
Gegenstände. Bewegliche Geräte behalten ihre Identität beim Raumwechsel;
Betriebspositionen werden später von der geplanten Aufstellung getrennt.

## Implementierter erster Schritt für L01

| Quelle | Inhalt |
|---|---|
| `model/lab-room-l01.shared.json` | Schlankes Kompositionsmanifest mit Revisionen der drei Quellen |
| `model/environments/l01.geometry.json` | Raumparameter, Fassade, Öffnungen, Verglasung und Betonstütze |
| `model/furniture/laboratory.catalog.json` | Neun Möbel- und Zubehörtypen mit lokalen Maßverträgen |
| `model/furnishings/l01.furnishings.json` | L01-Möbelinstanzen, Parameterbindungen und konkrete Aufstellungen |
| `model/lab-layout-l01.shared.json` | Referenzierte Geräteaufstellung einschließlich Waage, Kühlschrank und −20-°C-Schrank |

```mermaid
flowchart TD
    R[Raumgeometrie L01] --> C[L01 Komposition]
    T[Möbeltypen] --> M[Möblierung L01]
    R -->|Parameter und benannte Rahmen| M
    M --> C
    C --> G[Bestehendes Geräte Layout L01]
    Q[Arm und Stationsquellen] --> G
```

Die Raumschale ist über `room_geometry_model` unabhängig von Möbeln auswertbar.
Sie enthält neun Körper. `furniture_model` instanziiert Möbel aus dem Katalog;
`lab_room_model` kombiniert die drei Quellen für die bisherigen CAD-Adapter.
Die Einrichtung erhält die bisherigen Gebäude- und Möbelbezüge. Hohle
Schrankkorpusse ersetzen die früheren Stauraumhüllen; Türen und Hockersitze
ergänzen bewegliche Gruppen. Die sechs bisherigen festen Gruppen bleiben
erhalten. Der Standardraum umfasst jetzt 197 Körper und zusätzliche Bezüge.

Für die Kaltlagerung reserviert die Möblierung 640 mm am hinteren Ende der
linken Seitenbank; ihr Hängeschrank wird entsprechend gekürzt. Die rechte
Bank und ihr Hängeschrank behalten ihre Länge. Der Kühlschrank steht mit
dem Rücken an der rechten Seitenwand im freien Bereich hinter Tür B und
öffnet zum Gang. Die Gerätequelle
liefert ihre Maße einmalig. Das Layout leitet daraus benannte Maßansichten
für die Aufstellung ab und prüft die tatsächlichen Geräte gegen die
Möbelreservierungen. Die linke CF01-/ArmC-/TR01-/Rackgruppe wird über einen
gemeinsamen Versatz um 800 mm zum Eingang verschoben. Das manuelle
Kellerlager gehört nicht zu L01; ein Kellerraum wird nicht ergänzt.

Vorne links reserviert die Möblierung Platz für einen Nassplatz und den direkt
anschließenden Abzug. Die restliche linke Bank und die oberen offenen Regale
beginnen bei Y=2.800 mm. Der Nassplatz und die drei Hocker gehören zum
Möbelkatalog; Wasserbad und Abzug zur referenzierten Gerätebibliothek.
Unterschränke besitzen zwei Einlegeböden je Fach. Je zwei gegenläufig
angeschlagene Türen schließen ein gemeinsames Fach ohne Mittelsteg ein;
bei ungerader Türzahl endet die Bank mit einem Einzeltürfach.
`door_grouping: "single"` an einer Instanz trennt alle Türen in eigene Fächer.
Trennwände, Böden, Scharnierlagen und Zugangsproben entstehen gemeinsam
aus demselben Rezept, auch im Abzugunterbau. Die bisherigen
oberen Schrankinstanzen behalten ihre IDs, werden aber als offene Regale
erzeugt. Geschlossener Zustand, Öffnungsraum und tatsächliche Zugangsproben
werden getrennt ausgewiesen. Wasser, Abwasser und Abluft sind nicht angeschlossen.

Die Analysenwaage, beide Laborschränke, Wasserbad und Abzug entstehen in beiden CADs direkt
aus dem Gerätefamilienrezept. SolidCraft setzt diese Modelle und die bereits
geprüften nativen Armmodelle als platzierte Verknüpfungen ein. Die Aufstellung
bleibt eine statische Ansicht; Gerätestellungen werden zusätzlich diskret auf
Zugang und Überschneidungen geprüft. Diese Prüfung ist kein neues
Robotertransportprogramm.

Die Typen umfassen Stauraumbank, offene angepasste Bank, Regalbrett, Stütze,
offenes Regal, Nassplatz und Laborhocker sowie seitliche und mittige passgenaue Abdeckungen. Unterschiedliche
Bänke und Schränke verwenden dieselben Rezepte. Die Abdeckungen sind Zubehör
der Einrichtung, dessen Zuschnitt an Raumkontur und Banklage gebunden ist;
sie beschreiben keine Heizungsanlage. Die bisherige Darstellungsgruppe
`BuildingServices` bleibt zur Identitätswahrung erhalten.

Möbelabmessungen und Raummesswerte besitzen getrennte Parametertabellen ohne
überlappende Namen. Ein Möbeltyp kennt nur lokale Abmessungen. Die Möblierung
bindet diese beispielsweise an `bench_height` oder eine freie Länge zwischen
Raumgrenzen. Verankerungen wie die Bankanpassung an die Stützenfront verwenden
den benannten Raumrahmen `L01.ConcreteSupport`.

Möbelposen bestehen derzeit aus drei Koordinaten in mm und einer festen Drehung
um die vertikale Achse in Grad. Gedrehte Quader werden als Polygonprismen
abgeleitet; Möbelrahmen drehen mit. Die eingepassten Abdeckungen verwenden
explizit die Raumkontur und bleiben im Raumbezugssystem. Allgemeine räumliche
Montagebeziehungen mit Neigung sind in diesem Schritt nicht implementiert.

## Ableitung und Revisionen

Der Einstieg bleibt `python scripts/build_lab_room.py`. FreeCAD und SolidCraft
verarbeiten dieselben ausgewerteten Primitive. Symbolische Maßabhängigkeiten
bleiben bis zu den Adaptern erhalten, damit native Parameteränderungen auch
Geometrie und Bezugssysteme gemeinsam verändern.

Das Kompositionsmanifest bindet jede Teilquelle mit SHA-256. Persistente
Änderungen an Raum, Katalog oder Möblierung erfordern eine bewusste Übernahme
in dieses Manifest; anschließend wird die Raumreferenz des Geräte-Layouts
aktualisiert. Der Build-Bericht führt die drei Quellen, deren Schemas und
Generatoren auf. Ein alter Bericht gilt nicht für die neue Kompositionsrevision.

Die Verträge sind in `room-composition.schema.json`, `room-geometry.schema.json`,
`furniture-catalog.schema.json` und `furnishings.schema.json` beschrieben.
Zusätzlich zu den Schemas prüfen die Generatoren Referenzen, Einheiten,
Wertebereiche, eindeutige IDs, Ausdruckszyklen und geometrische Bedingungen.

## Erhalt und Prüfgrenzen

`tests/fixtures/l01-before-layer-split.json` hält die ausgewerteten Primitive,
Konstruktionsfolgen, Rahmen und Gerätepositionen des vorherigen Stands für fünf
Parametervarianten fest. Die Regression prüft auch die bisherigen Übergabeziele.
Historische Testdaten sind keine zweite führende Raum- oder Möbelquelle.

Der native Vergleich prüft beide CAD-Kerne, gespeicherte Modelle und die
vorhandenen nativen Parameteränderungen. Das belegt geometrische Übereinstimmung,
keine Fertigungsfreigabe oder sichere Laboraufstellung. Die bisherigen
Durchgangsformeln beschreiben das nominale L01-Arrangement; frei versetzte Möbel
benötigen neue räumliche Freiraumprüfungen. Die heutigen Durchgänge und Geräte-
Betriebsbereiche sind weiterhin nicht sicherheitstechnisch qualifiziert.

## Synthetische minimale Testumgebungen

Neben einem realitätsbezogenen Labor ist ein ausdrücklich synthetisches
Umgebungsprofil implementiert: ein unbegrenzter Raum ohne beschriebene Wände,
Fenster, Türen oder lange Verkehrswege. Eine einzige Bank beziehungsweise
Referenzarbeitsfläche liefert Orientierung, Maßstab und Aufstellrahmen. Dieses
Profil gehört zur selben Vier-Ebenen-Architektur und benötigt keinen künstlich
riesigen Laborgrundriss.

Unbegrenztheit muss ein eigener, eindeutiger Modus sein. `null` bleibt einem
unbekannten Wert vorbehalten; sehr große Raumabmessungen und nicht endliche
Zahlen sind kein Ersatz für diesen Modus. Ein unbeschriebener Boden oder eine
fehlende Wand erzeugt keinen CAD-Körper. Ein Ausschnitt, Kameraraster oder
optional gezeichneter Boden dient nur der Darstellung und begrenzt die
Testumgebung nicht.

| Ebene | Kompakte Testumgebung |
|---|---|
| Arbeitsumgebung | Synthetischer unbegrenzter Raum mit eindeutigem Weltbezug; keine Gebäudevermessung oder Raumkontur |
| Möbeltypen | Referenz auf eine Bank oder Arbeitsfläche über den gemeinsamen Möbelvertrag |
| Möblierung | Eine Bankinstanz mit benanntem Arbeitsflächenrahmen |
| Geräteausstattung | Dicht angeordnete Instanzen der zu prüfenden Geräte; dieselben Gerätequellen wie im realen Layout |

Die Bank ist eine Referenz für die Anordnung, keine Voraussetzung für die
Kommunikation. Geräte sollen für kurze Übergaben in einem gemeinsamen
Arbeitsbereich angeordnet werden. Ein in der Realität bodengebundenes Gerät
kann daneben stehen oder durch einen ausdrücklich gekennzeichneten Mock
vertreten sein; seine Konstruktion wird dafür nicht in ein Tischgerät geändert.
Ungeprüfte mechanische Erreichbarkeit oder abstrahierte Transportübergaben
bleiben kenntlich.

### Kommunikation und Testlauf getrennt beschreiben

`model/cf01-rack-batch.protocol.json` bindet die Umgebung und den vorhandenen
CF01-Befehlsvertrag an einen lokalen Mock-Testlauf. Die zwölf Proben haben stabile
IDs und eine explizite Zuordnung von Rack- zu Rotorplätzen. Die Rückgabe erfolgt
an den ursprünglichen Rackplatz, unabhängig von der gewählten Rotorplatzfolge.
Der Transporter ist ausschließlich die externe Vorbedingung „Rack bereitgestellt“.

`scripts/run_cf01_rack_batch.py` führt den vollständigen Ablauf mit den
vorhandenen CF01-Simulator- und Protokollklassen aus: beladen, starten, Lauf und
Abbremsen abwarten, entnehmen und zurückstellen. `--transport ros2` und
`--transport sila2` wählen die bereits vorhandenen lokalen Vertragsdecoder.
Es werden dabei keine Netzwerkserver oder Hardware angesprochen. Der separate
[CF01-SiLA-Netzwerk-Chargenrunner](docs/sila2-network.md) verwendet denselben
Simulator-/Protokollkern über tatsächliches TLS/gRPC; er bindet den gemeinsamen
CF01/NanoDrop/Qubit-Laborablauf noch nicht an das Netzwerk an. Roboterrückmeldungen
für Greifen, Freigeben und Absetzen sind ausdrücklich synthetische Eingaben;
der Chargenlauf führt weder Beladungs- noch Rückgabebahnen aus.
Der bestehende Bewegungsbaustein Rotorplatz 01 → Rackplatz 01 besitzt eine
eigene Zeitachse und wird vom Chargenrunner nicht aufgerufen.

Bei falscher Probenidentität, fehlender Bestätigung, Eigentümer-Timeout oder
unwuchtiger Testbeladung endet der Lauf ohne Erfolg. Bei einer unvollständigen
Übergabe bleiben die letzte vollständig bestätigte Buchführung und die
synthetische Ortsbeobachtung getrennt erhalten. `pending_handoff` nennt Probe,
Quelle, Ziel und eingegangene Quittungen. Während der Bearbeitung heißt die
Zuordnung `pending`; erst nach einem Fehler `unresolved`. Dies verhindert
eine behauptete eindeutige Zuordnung. Ein Greifereintrag in dieser Buchführung
ist bei ungeklärter Übergabe keine gesicherte Aussage über den physischen Ort. Der Erfolg
verlangt den abgeschlossenen Schleuderlauf, bestätigten Stillstand, einen leeren
Rotor und exakt dieselbe Rackreihenfolge wie am Anfang. Testmassen und
Qualifikationsgrenzen stehen nur im explizit fiktiven Testprofil; die reale
CF01-Quelle erhält dadurch keine Freigabe.

Für schnelle Tests sind insbesondere Befehlsreihenfolge, Besitzübergaben,
Bestätigungen, Zeitüberschreitungen, Fehlerantworten und Wiederanlauf relevant.
Lange Fahrwege entfallen in diesem Szenario. Simulierte Wartezeiten können in
einem expliziten Testzeitmodell vorgerückt werden; sie dürfen nicht durch
vorgegebene Erfolgsmeldungen ersetzt werden. Ein Ablauf soll auch bei fehlender
Bestätigung oder Kommunikationsausfall korrekt anhalten.

Ein geometrisch kurzer Weg allein prüft keine Kommunikation. Eine lokale
Mock-Schnittstelle ist kein Netzwerkserver; eine Animation ist kein Nachweis
von ROS-/SiLA-Interoperabilität, realer Latenz oder Hardwarefunktion. Die
bestehenden Programm- und Protokollgrenzen bleiben auch im synthetischen Raum
sichtbar. Die Testumgebung liefert keine Freigabe einer realen Laboraufstellung.

### README Interaktion als erster Referenzfall

Die im README gezeigte Entnahme aus CF01 mit Ablage im Rack ist der erste
implementierte Integrationsfall für dieses Profil. Raum und Referenzbank werden
aus der minimalen Umgebung und Möblierung abgeleitet. Arm und CF01
referenzieren weiterhin `model/robot.json` beziehungsweise
`model/centrifuge-cf01.shared.json`; die Entnahme-, Greifer- und Rackbeziehungen
bleiben an ihre vorhandene Szenenquelle und das CF01-Protokoll gebunden.
Es entsteht keine zweite Beschreibung dieser Geräte oder des Ablaufs.

Die Überführung erhält Bankoberfläche, Geräteposen,
Gelenkstellungen und Gefäßübergaben. Die Bankoberfläche liegt im
bisherigen Szenenbezug bei Z = 0; ein neuer Welt- oder Bankrahmen darf die
Darstellung nicht unbeabsichtigt verschieben. Anschließend kann dieselbe
Interaktion mit einer anderen Aufstellung, etwa in L01, verbunden werden.
Dort kommen die realen Wege und zusätzlichen räumlichen Randbedingungen hinzu.

Die Quelle `model/synthetic-cf01-workspace.shared.json` bindet die vier Ebenen:

| Quelle | Inhalt |
|---|---|
| `model/environments/synthetic-unbounded.json` | Unbegrenztheit ohne Raumschale oder Ersatzabmessungen |
| `model/furniture/reference-bench.catalog.json` | Referenzarbeitsfläche über das vorhandene Möbelrezept |
| `model/furnishings/cf01-reference-bench.json` | Eine Bankinstanz und ihr Arbeitsflächenrahmen |
| `model/equipment/cf01-workspace.json` | Referenzierte Geräte und lokale Posen am Bankrahmen |

Die Rackkonstruktion steht einmal in `model/guided-tube-rack.shared.json`.
Die Entnahmeszene referenziert die Umgebung; Bankgeometrie, Gerätepositionen und
Armvariante sind daraus abgeleitete Ansichten. Bankoberfläche, Geräteposen und
Bewegungsziele bleiben erhalten. Die bisherige Einzelentnahme nutzt unabhängig
interpolierte Roboter-, Stations- und Greiferkanäle: Nach der synthetischen
Freigabe von Arm und Gefäß bei 29,5 s fährt der Arm weiter, während Heber und
Deckel ihren Ablauf abschließen. Dadurch dauert der Baustein 47,5 s mit 191
Samples; die früheren 60 s mit 241 Samples bleiben in den historischen Medien
erhalten. Die eigene Bewegungszeitachse wird vom Chargenrunner nicht aufgerufen
und ist nicht an dessen Schleuderlauf gekoppelt. Ein ROS-Export übernimmt den
Armkanal für den vorhandenen Trajektorienclient. Integrierte Greifer- und
Stationssteuerung, ROS-Laufzeit und reale Sensor-/Qualitätsrückmeldungen sind ungeprüft.

Die historische interaktive README-Demo zeigt diesen Bewegungsausschnitt und zusätzlich die
Aufzeichnung des vollständigen lokalen Chargenprotokolls mit Rack-, Rotor- und
Greiferinventar. Die Aufzeichnung ist kein im Browser laufender Geräteadapter.
Das damalige kurze Video zeigt den Entnahmebaustein; die physische Beladung
aller zwölf Rotorplätze wird damit nicht als geprüft dargestellt.

Die aktuelle [geglättete Entnahme](docs/cf01-smooth-unloading.md) ergänzt mit
`model/cf01-unload-demo.motion.json` eine eigene, referenzierende Bewegungsquelle:
zwölf Gefäße nach dem synthetischen Spin, Sample01–03 in ursprünglicher
Rackreihenfolge zurück, neun verbleiben im Rotor. Ein gemeinsames kompiliertes
Programm liefert separate Arm-/Stations-/Greiferkanäle, Eigentümerereignisse
und C2-Quintiken mit Position, Geschwindigkeit und Beschleunigung für native
Prüfung, Browser und ROS-Armexport. Die gesamte beladene Fahrt vom bestätigten
Griff zur Rackankunft erhält einen IK-Durchlauf, einen Kurvenfit und eine
gemeinsame Zeitskalierung; axiale Entnahme und vertikale Ablage sind durch
krümmungsstetige Übergänge verbunden. Zwischen ihnen gibt es keinen Ruhepunkt.
Entnahme- und Freiraumbestätigung werden aus der tatsächlichen FK-Kurve
abgeleitet, statt dafür Haltezeiten einzufügen. Ruck bleibt begrenzt, kann an Knoten springen;
biologische Toleranzen sind unbekannt. Geometrie wird nur mit gültigen Quellen-
und Artefaktbindungen übernommen; die neue Bahn erhält eine eigene diskrete
native Prüfung einschließlich Nachbargeräten und belegter Rackplätze.
Konservative FK-Intervallhüllen werden adaptiv vom Profilstart mit vier bis
höchstens 256 Teilintervallen im jeweils begrenzenden Abschnitt verfeinert.
Tatsächliche Auswertungen steuern diese Auswahl; sie ersetzen keine obere
Grenze. Der Abbruchgrund und die verwendeten Auflösungen stehen im Bericht.
Auch leere Anfahrten und Rückzüge besitzen durchgehende verrundete Bahnen;
eine reine Präsentationspause entfällt. Die letzten 25 mm der Anfahrt bleiben
axial, die ersten 96 mm des Rückzugs senkrecht. Das aktuelle Programm umfasst
3.876 Armknoten und 99,674 s Animationszeit; der erste Griff bis zur bestätigten
Rackabstützung dauert unverändert 11,611 s. Gegenüber der ersten durchgehenden
Fassung mit 80,759 s dauert das Gesamtprogramm durch die nun ebenfalls
verrundeten leeren Fahrten bei unveränderten Grenzen länger. Daraus folgt kein
Geschwindigkeits- oder Optimalitätsnachweis.
Build und Provenienz binden diese Modellzeiten; sie sind kein Chargenrunner-
oder Hardwarebenchmark. Die
Prüfung ersetzt weder einen kontinuierlichen Kollisionsnachweis noch ROS-/
Hardwareausführung; eine neue native SolidCraft-Bewegungsstudie liegt nicht vor.

Für diesen Entnahmeausschnitt bleibt der Deckel zwischen den Proben offen.
`model/cf01-open-lid-index.protocol.json` pinnt dafür eine additive,
simulationsgebundene Erweiterung. Nur der ausdrücklich gewählte
`OpenLidIndexSimulator` kennt `index_open_lid`; er verwendet die vorhandenen
Stillstands-, Brems-, Sitz-, Heber- und Freiraumprädikate sowie die
Indexgrenze der Stationsquelle. Der Basisbefehl `index` und der Schleuderstart
verlangen weiter den geschlossenen, verriegelten Deckel. Der neue Befehl wird
nicht in Standardsimulator, MockProtocol, ROS-Interfaces oder SiLA registriert.
Der vorhandene Zwölferlauf liefert ausschließlich einen Identitäts- und
Reihenfolgenbeleg; die neue Stationsfolge wird separat im Opt-in-Simulator
abgespielt. Weder bisheriger Chargenrunner noch gemeinsamer Laborworkflow
führen diese Erweiterung aus. Die logische Replay-Uhr ist kein Watchdog-Nachweis;
Hardware-, Sicherheitsqualifikation und ein bedingter Abbruchzweig des
Armprogramms bleiben offen.

### Koordinatenverträge und spätere Migration

Im bestehenden `lab-layout/1` bezeichnet `host` eine unterstützende Fläche für
Aufstellungsprüfungen. `xyz` und `yaw_deg` beziehen sich auf das Labor-Weltsystem;
`host` transformiert diese Werte nicht. Im `equipment-layout/1` mit
`equipment_instance` benennt `host` dagegen den Elternrahmen; Position und
Drehung sind lokal zu diesem Rahmen. Die Schemas beschreiben beide Bedeutungen
an den jeweiligen Verträgen. Die L01- und CF01-Posen werden dadurch nicht geändert.

Eine spätere allgemeine Gerätebindung muss Unterstützungsfläche und
Koordinatenbezug in einem versionierten Vertrag ausdrücklich unterscheiden.
`host` darf dafür nicht global umgedeutet werden; bestehende Weltposen müssten
gezielt in lokale Posen überführt und geometrisch erneut geprüft werden.
Diese Migration und die gemeinsame CF01-/NanoDrop-Komposition sind separate
Aufgaben.

## Manuelle Aufgaben als eigene Ausführungsebene

Der [erste NanoDrop-Ablauf](docs/nanodrop-manual-workflow.md) ergänzt die räumlichen
Ebenen um einen lokalen, vollständig synthetischen Arbeitsablauf. Gerätetypen und
Fähigkeiten stehen in `model/nanodrop.catalog.json`; One und UltraC referenzieren
dasselbe Protokoll `model/nanodrop-manual.protocol.json` für Mikrovolumen-
Absorption. `model/nanodrop-manual.synthetic.json` bindet eine logische Geräte-
instanz, Rackinstanz und Proben an die vorhandenen Quellen für unbegrenzten Raum,
Referenzbank und Rack. Neue CAD-Geometrie oder Gerätepositionen entstehen nicht.
Der formale Profilvertrag steht in `model/nanodrop-manual.schema.json`.

Verantwortliche Person, physischer Gefäßort und reservierte Ressource sind
getrennte Informationen. Platzkennungen aus der gemeinsamen Rackquelle werden
zusammen mit der Rackinstanz verwendet. Entnahmen verbinden Originalprobe,
Quellgefäß, Aliquot, berichtetes Volumen und die Messungskennung. Eine gespeicherte
Messabsicht muss vor Wiederholung oder Wiederaufnahme ausdrücklich aufgelöst
werden. Unbekannte Restvolumina bleiben unbekannt; frühere Massenbestätigungen
sind nach Entnahmen überholt.

`scripts/manual_tasks.py` speichert Ereignisse, Zustandsansichten, exklusive
Ressourcen und unveränderte Importdateien transaktional in SQLite unter dem
ignorierten `exports/manual-workflows/`. Laufzeitdaten gehören nicht nach
`model/`. `scripts/manual_workflow.py` bündelt Profilbindung, Sitzung, Gewahrsam,
Gefäßreservierungen, Verbrauch, Wiederaufnahme und Importhülle. NanoDrop und Qubit
verwenden gerätespezifische Adapter auf diesem Kern; die gemeinsame CLI liegt in
`scripts/manual_workflow_cli.py`. Dateiimporte werden über eindeutige
laufbezogene Messungsnamen zugeordnet; fremde, fehlende oder doppelte Messungen
blockieren den Abschluss. Originalmeldungen und ausdrückliche Bewertungen bleiben
getrennt. Nach Neustart, widersprüchlicher Beobachtung oder Aufgabenfrist bleiben
Reservierungen bis zum bestätigten Abgleich bestehen. Rückgabe, Ergebnisfreigabe
und abschließende Arbeitsplatzfreigabe sind eigene Bedingungen.

Der Einstieg `python3 scripts/run_nanodrop_manual.py demo` erzeugt ausschließlich
synthetische Eingaben und eine synthetische CSV-Datei. Tests prüfen auch einen
harten Prozessabbruch mit anschließendem Neustart. Ein echter Geräteexport,
eine reale SOP, Scanner, Schutzfunktion, Hardware- oder Netzwerkkommunikation
sind nicht validiert. Netzwerkadapter und eine Fortsetzung in CF01 folgen
später; der bestehende CF01-Chargenrunner wird hierfür nicht erweitert.

### Synthetischer Qubit-4-Ablauf

Der [Qubit-4-Durchstich](docs/qubit-4-manual-workflow.md) verwendet einen eigenen
Gerätetypenkatalog und die führenden Quellen `model/qubit-4-manual.protocol.json`
sowie `model/qubit-4-manual.synthetic.json`. Der Profilvertrag steht in
`model/qubit-4-manual.schema.json`. Bestehende NanoDrop-Quellenpins, Rack- und
Raumdefinitionen bleiben erhalten. Ansatz- und Standardgefäße besitzen deklarierte
logische Plätze ohne erfundene Geometrie.

Die separaten [NanoDrop- und Qubit-Anschauungsmodelle](docs/instrument-concepts.md)
besitzen nun eigene gemeinsame Geometriequellen und zwei native CAD-Ableitungen.
Ihre Maße sind Annahmen. Die synthetische Geräteaufstellung referenziert sie nun
als Instanzen auf der Armseite der Referenzbank. Statische Referenz-TCP-Ziele
an beiden Messpunkten und native Annäherungsstellungen werden daraus geprüft;
Werkzeugauslegung, Bindungen der logischen Messabläufe an CAD-Gelenke und
verbindende Roboterwege zu den Messgeräten sind nicht implementiert.

Eine Ansatzabsicht identifiziert das ausgewählte leere Gefäß vor dem Transfer.
Die Bestätigung erzeugt einen Transferdatensatz; nur dort wird die Originalprobe
einmalig belastet. Die spätere Messung verbraucht nicht noch einmal dieselbe
Probe. Alle Gefäße sind Teil des Wiederaufnahmeinventars. Nicht durchgeführte
Ansatzversuche benötigen bestätigte Entsorgung und neue IDs für einen erneuten
Versuch. Originalgefäße müssen an ihre ursprünglichen Plätze zurückkehren.

Die synthetische Prozesszeit ist im Lauf gebunden und schreitet ausschließlich
durch Ereignisse voran. Derselbe Zeitbezug prüft Inkubation, Kalibrierungsablauf
und Aufgabenfrist. Eine Kalibrierung pro Lauf wird nach bestätigten Standards
ausdrücklich freigegeben und an Gerät, Assayrevision, Chargen und Messungs-IDs
gebunden. Jede Probenmessabsicht friert diesen Bezug als `workflow_record` ein.
Eine außerhalb des Ablaufs erfolgte Gerätekalibrierung wäre nicht erkennbar.

Der finale Dateiimport verlangt sowohl Proben- als auch Standardmessungen.
Berichtete Ansatz- und Originalkonzentrationen bleiben getrennt. Eine berichtete
Originalkonzentration verlangt Proben- und Gesamtvolumen derselben Zeile passend
zum bestätigten Ansatz; sonst bleibt der Import in Quarantäne. Fehlt die
Originalkonzentration, wird sie mit dokumentierter Formel und Einheitenumrechnung
aus dem bestätigten Ansatz abgeleitet. Fehlende Gefäße, ungeklärte Absichten,
ungültige Messungen oder nicht bestätigte Entsorgung verhindern die Freigabe.
Ein neues Laufprofil deklariert eigene Anfangsmengen; ein laufübergreifendes
Volumenbuch und echte Kalibrierkurven sind nicht implementiert.

### Integrierter synthetischer Gesamtlauf

Der [gemeinsame Ablauf](docs/synthetic-lab-workflow.md) verbindet zwölf Originale
in der festen Folge CF01 → NanoDrop → Qubit 4. Führend ist das Manifest
`model/synthetic-lab-workflow.manifest.json`; die Komposition und ihr Schema
binden Aufstellung, Geräteprotokolle, Parameter, Uhrmodus und Platzrollen.
Die alten drei beziehungsweise zwölf Proben umfassenden Einzeldemos sind
unabhängige Fixtures, keine zusätzlich zu synchronisierenden Bestände.

Ein Rootzustand enthält Inventar, Buchungen, Massenbestätigungen, Reservierungen
und die ereignisgesteuerte Prozesszeit. Unter `stages[stage_id]` stehen getrennte
Gerätezustände mit Messungen, Importen, Bewertungen, Akteuren und Fristen.
`scripts/lab_workflow_stages.py` bindet die gemeinsamen Geräteoperationen über
ausdrückliche Ansichten an Root und Stufe. Alte Laufartprüfungen werden nicht
durch Umschreiben von Formaten umgangen. Die Restmenge ist eine Projektion aus
Anfangsmenge und eindeutig zugeordneten bestätigten Entnahmen. Unsichere
Durchführungen bleiben gesperrt; die geplante Entnahme ist keine Obergrenze.

Der Gesamtlauf verwendet die bestehende Rackinstanz `Rack` und lokale Plätze
wie `Slot01`. Historische geometrische IDs bleiben abgeleitete Referenzen.
Die gemeinsame Bankfläche wird über `SYN.Bench.Worktop` gebunden; der logische
Arbeitsbereich bleibt `SYN.NanoDrop.WorkArea`. Daraus entsteht kein zusätzlicher
Racktransport. NanoDrop und Qubit besitzen zusätzlich referenzierte CAD-Positionen
auf der bestehenden Bank; die Gesamtansicht entsteht mit
`python3 scripts/build_synthetic_lab_scene.py`. Der Root hält Rack, Gefäße und Arbeitsfläche über die
Gerätewechsel; Station, Arm und Messgeräte sind zusätzliche Stufenressourcen.
Ort, Akteursverantwortung und Ressourcenbesitz sind getrennte Informationen.

Neue synthetische Massenbestätigungen sind an Gefäß und Inhaltsrevision gebunden.
Entnahmeabsichten und Verbrauch entwerten sie; CF01 bekommt nur aktuelle Werte.
Qubit verarbeitet zwölf Proben seriell, sodass Halterplätze nach bestätigter
Entsorgung wiederverwendbar sind. Die Messkammer ist kein Vorbereitungsplatz.
NanoDrop-Blank und Qubit-Kalibrierung bleiben gerätespezifische Voraussetzungen;
der Kalibrierungsbezug ist weiterhin `workflow_record`.

Der CF01-Runner verwendet dieselbe Ausführung mit optionalen synchronen
Checkpoint- und Uhr-Callbacks. Absicht, rohe Antwort, Roboterbeobachtung und
vollständige Übergabe werden getrennt gespeichert. Wiederholte Heartbeatdetails
werden gezählt; der vollständige CF01-Bericht liegt einmal als Originalartefakt
vor. Rootzustände enthalten die letzte kompakte Ansicht, keine wiederholte
vollständige CF01-Trace. Bei Speicherfehlern wird nicht normal weitergearbeitet.
Der Journal-Präfixpfad vergleicht aktuellen Datenbank-Tail und Revision unter
derselben Schreibtransaktion; Öffnen, Bericht und Endabschluss prüfen die
gesamte Kette. Auch die Artefakte früherer Stufen werden beim Abschluss geprüft.

Nach Neustart innerhalb CF01 bleibt der Versuch gehalten; ein neuer Simulator
ist keine Wiederaufnahme. Die erste Fassung setzt aktive Mock-Jobs nicht fort.
Ein vollständiger Abbruchabgleich bestätigt alle Gefäße, Rotorplätze, Greifer,
Stillstand, Parkbremse, geparkten Heber und freien Arbeitsbereich ausdrücklich
als `synthetic_operator_confirmation`. Der alte Versuch wird mit seinen offenen
Quittungen stillgelegt, nicht nachträglich erfolgreich gemacht. An bestätigten
Stufengrenzen ist die manuelle Fortsetzung nach Abgleich möglich.

Die Runtime liegt im bisherigen gemeinsamen SQLite-Store unter `exports/`.
Unabhängige Gesamtläufe übernehmen Bestände nicht automatisch. Reagenzvorräte,
Netzwerkimport in diesen Gesamtlauf, Hardware, echte Exporte, neue Geometrie,
Roboterbahnen und
qualifizierte Schutzfunktionen sind damit nicht implementiert oder nachgewiesen.

Der [Plan zur laufübergreifenden Bestandsführung](docs/stock-continuation.md)
beschreibt den nächsten Ausbau: einmalige Einführung oder geprüfte Übernahme
eines abgeschlossenen Laufs, fortgeschriebene Restmengen und Inhaltsrevisionen
sowie ein atomarer Root-/Stock-Schreibpfad mit exklusiver persistenter Lease,
Kopfvergleich und Fencing. Diese Verträge und Befehle sind noch nicht implementiert.

## Lesende NanoDrop-UltraC-Netzwerkschnittstelle

Der [UltraC-Netzwerkadapter](docs/nanodrop-ultra-network.md) trennt den einmalig
beschriebenen Hersteller-Lesevertrag in
`model/nanodrop-ultra-network.protocol.json`, ein kataloggebundenes synthetisches
Gerätemodell und dessen HTTP-Adapter. Derselbe Client verwendet die fünf
ausgewählten GET-Routen am Modellserver oder an einer expliziten Geräte-URL.
Der lokale Netzwerkverkehr ist geprüft; ein Originalgerät ist noch nicht qualifiziert.
FreeCAD und SolidCraft sind keine Laufzeitabhängigkeiten dieses Geräteverhaltens.

Requestpfade und Parametertypen folgen M024 01/25. Nicht dokumentierte
Antwortformen, Filter- und Paging-Regeln bleiben ausdrücklich synthetische
Modellentscheidungen. Originalantworten werden unverändert mit Prüfsumme
archiviert. Ein Abruf erzeugt weder Verbrauch noch Ergebnisfreigabe und ist noch
nicht in den manuellen oder gemeinsamen Laborablauf eingebunden. Ein fachlicher
Decoder benötigt zunächst echte versionierte Geräteantworten und einen expliziten
Identitätsvertrag; die Ultra-API wird nicht auf NanoDrop One übertragen.

## SiLA-Fähigkeiten und GENtle-Ressourcenbindung

**Status: Die hier beschriebene GENtle-Fähigkeits- und Ressourcenbindung ist
dokumentierte Zielarchitektur, noch nicht implementiert.** Dieser Vertrag
ergänzt die vier räumlichen Ebenen um eine Bindung für Gerätefähigkeiten und
ihre aktuelle Belegung; er führt selbst keine neuen Schemas, Endpoints, Dienste
oder Runtime-Daten ein. Davon getrennt ist ein
[TLS/gRPC-SiLA-Server für den CF01-Simulator](docs/sila2-network.md) implementiert.
Sein Netzwerk-Chargenrunner ist nicht mit den bisherigen lokalen
Vertragsdecodern oder dem gemeinsamen synthetischen Laborablauf gleichzusetzen.
Implementierung und aktueller Prüferfolg bleiben getrennte Aussagen; historische
Rebase-Ergebnisse und der Integrationsstand stehen in der verlinkten Dokumentation.
Hardwarebetrieb,
formale SiLA-Zertifizierung und LAN-Qualifikation sind nicht nachgewiesen.
Auch der getrennte UltraC-HTTP-Leseadapter ist kein SiLA-Adapter. Alle bisherigen
Sicherheits-, Metrologie-, biologischen und Fertigungsgrenzen gelten weiter.

Referenzen sind [SiLA 2](https://sila-standard.com/), die
[offiziellen Featuredefinitionen in `sila_base`](https://gitlab.com/SiLA2/sila_base)
und [GENtle](https://github.com/smoe/gentle_rs). Die folgende Aufgabenteilung ist
der künftige Integrationsvertrag, keine Zusage bereits vorhandener Schnittstellen
in einem der beiden Projekte.

### Verantwortlichkeiten und Identitäten

DIYLabBot führt stabile Labor-, Umgebungs- und Geräteinstanz-IDs, referenzierte
Gerätetypen und deren genaue Quellenrevisionen beziehungsweise Prüfsummen.
Aufstellung, Koordinatenrahmen und modellierte Geometrie bleiben in ihren
bestehenden Quellen. Hinzu kommen künftig die Inventarbindung einer Instanz an
eine SiLA-Serveridentität, deren angekündigte Featuredefinitionen oder ein
zeitlich gebundener Cache sowie lokale Betriebszustände und Richtlinien aus
einer Runtime-/Privatüberlagerung. Modellidentität und beobachteter Zustand
bleiben getrennt: CAD-Präsenz, Aussehen, Hersteller-/Modellname oder eine
Ontologieklasse belegen keine erreichbare, steuerbare Fähigkeit.

GENtle oder ein anderer Versuchsplaner besitzt die wissenschaftliche Versuchs-
und Protokollabsicht, Proben-/Materialsemantik, benötigte Fähigkeiten und
Randbedingungen. Dort liegen Kandidatenvergleich, Zuordnungsvorschau, Freigabe
und der Beleg für das tatsächlich verwendete Gerät. DIYLabBot dupliziert diese
Protokollsemantik nicht und entscheidet keinen biologischen Erfolg. Das vorhandene
operative Lauf-Inventar mit Gefäßidentität, Ort, Gewahrsam, belegtem Verbrauch und
Reservierungen bleibt erhalten; eine spätere GENtle-Bindung referenziert die
wissenschaftlichen Proben-/Materialkennungen, statt einen zweiten Bestand zu
erfinden oder bestehende synthetische IDs still umzuschreiben.

### SiLA-Featuredefinitionen als Ausführungsvertrag

SiLA 2 Feature Definition Language (FDL) ist das primäre operative Vokabular.
SiLA ist keine OWL-Ontologie. Optionale semantische Annotationen, etwa OBI-Terme
für Zentrifuge oder Zentrifugation, dienen der fachlichen Einordnung; sie ersetzen
kein implementiertes, angekündigtes SiLA-Feature und keinen Kompatibilitätsnachweis.

Der künftige Bindungsweg lautet:

1. Die Geräteinstanz löst eine private Endpoint-Konfiguration auf. Die dort
   beobachtete Identität der normativen `SiLAService`, insbesondere die stabile
   `ServerUUID`, muss mit der Inventarbindung übereinstimmen. Eine Netzwerkadresse
   oder ein Anzeigename ist keine stabile Geräteidentität; eine UUID allein ist
   kein Nachweis physischer Identität oder authentisierter Kommunikation.
2. `ImplementedFeatures` liefert die angekündigten Features;
   `GetFeatureDefinition` liefert für jedes benötigte Feature die genaue FDL.
   Maßgeblich sind vollständig qualifizierter Feature-Identifier (FQI), volle
   `FeatureVersion` und Digest der exakten Definitionsbytes. Der FQI enthält die
   Major-Version; beispielsweise ist `org.silastandard/core/LockController/v2`
   nicht mit einer vollständigen Versionsangabe `2.0` gleichzusetzen.
3. Definitionen werden mit SHA-256, Quelle/Revisionsbezug, beobachteter
   Serveridentität, Beobachtungszeit und Frischefrist gebunden. Befehle,
   Properties, Datentypen, Einheiten, Constraints und Ausführungsfehler bleiben
   aus genau dieser FDL erhalten. Zusätzlich wird die vom Server angekündigte
   Liste der von Metadata betroffenen Calls an den Snapshot gebunden. Ein
   gemeinsamer Anzeigename oder gleicher
   FQI bei geändertem Digest genügt nicht zur Wiederverwendung eines Matches.
4. GENtle vergleicht diese Evidenz mit seinen Anforderungen und stellt die
   Zuordnung zur Freigabe dar. Unerreichbare, veraltete, widersprüchliche oder
   unvollständige Angaben bleiben unbekannt, nicht verfügbar. Eine kompatible
   Ankündigung ist noch keine bestätigte Belegung und keine Ausführung.

Referenz für die Serveridentität ist die normative
[`SiLAService`-FDL, Featureversion 1.0](https://gitlab.com/SiLA2/sila_base/-/blob/58290aab68172dcab4ce52d74478b9b97910964f/feature_definitions/org/silastandard/core/SiLAService-v1_0.sila.xml).
Der FQI-Vergleich folgt den SiLA-Regeln einschließlich ignorierter Groß-/
Kleinschreibung; die vollständige Version und der Byte-Digest bleiben zusätzliche
Bindungen, siehe [Core-Spezifikation v1.1](https://sila-standard.com/wp-content/uploads/2022/03/SiLA-2-Part-A-Overview-Concepts-and-Core-Specification-v1.1.pdf).

### Getrennte künftige Datensätze

Die folgenden Rollen beschreiben benötigte künftige Verträge, keine heute
unterstützten Schemafelder oder implementierten Datenbanken:

| Datensatz | Inhalt und Eigentümergrenze |
|---|---|
| Geräteinstanz | Stabile DIYLabBot-ID, Labor-/Umgebungsbezug, Gerätetyp-/Quellenrevision und Vertrauensklasse `synthetic`, `simulator`, `physical` oder ausdrücklich unbekannt |
| SiLA-Endpointbindung | Geräteinstanz-ID, erwartete `ServerUUID` und private Referenz auf lokale Endpoint-Konfiguration; keine Zugangsdaten oder sensible Topologie in öffentlichen Dateien |
| Capability-Advertisement-Snapshot | Angekündigte FQIs und volle Versionen, exakte FDL-Digests, Herkunft, beobachtete Identität, Beobachtungszeit, Erreichbarkeit und Frische |
| Runtime-Allokation | Beobachtete Sperre, bestätigte lokale Zuordnung, Besitzer-/Sitzungsbezug und lokale Richtlinie in geschütztem Laufzeitspeicher beziehungsweise privater Überlagerung |
| Zuordnungs-/Belegreferenz | GENtle-Plan-/Freigabereferenz, tatsächlich gewählte Instanz, `ServerUUID` und verwendete Feature-Digests; nicht geheime Allokations-/Journalreferenz statt Locktoken |

Die eindeutige Instanz-/Server-/Endpointzuordnung ist eine DIYLabBot-Inventarregel,
keine Behauptung, dass jeder SiLA-Server ein einzelnes physisches Gerät darstellt;
SiLA-Server können auch Softwarerollen erfüllen.

Vorhandene `host`-, Raum-, Platzierungs- und CAD-Verträge erhalten dadurch keine
Endpoint-, Capability- oder Reservierungsbedeutung. Insbesondere bleiben die
oben unterschiedenen Welt-/Elternrahmen unverändert. Ohne konfigurierte
SiLA-Bindung bleibt das bisherige Modell- und Workflowverhalten unverändert.

### Aktuelle Belegung mit LockController

Erster vorgesehener Mechanismus für exklusive unmittelbare Nutzung ist der
offizielle **`LockController` v2 im Status Draft**, hier die
[FDL mit Featureversion 2.0](https://gitlab.com/SiLA2/sila_base/-/blob/58290aab68172dcab4ce52d74478b9b97910964f/feature_definitions/org/silastandard/core/LockController-v2_0.sila.xml)
aus `sila_base`-Revision `58290aab68172dcab4ce52d74478b9b97910964f`.
Das ist kein normatives, bereits qualifiziertes Reservierungssystem. Die
ausgewertete FDL-Revision muss im jeweiligen Snapshot gebunden bleiben;
ein späterer Entwurf wird nicht still als gleichwertig behandelt.

Der bereits implementierte CF01-Simulatorserver verwendet davon getrennt
[`LockController` v1.0, Status `Verified`](interfaces/sila2/standard/LockController-v1_0.sila.xml),
mit FQI `org.silastandard/core/LockController/v1`. Diese vorhandene Schnittstelle
implementiert weder den hier vorgesehenen v2-Draft-Vertrag noch die GENtle-Bindung;
Versionen und ihre Semantik werden nicht still gleichgesetzt.

- `IsLocked` ist eine beobachtbare, nicht lockgeschützte Zustandsauskunft,
  kein Eigentumsnachweis.
  Erst die bestätigte erfolgreiche `LockServer`-Anforderung entscheidet, welcher
  konkurrierende Client die Ressource erhalten hat. Eine frühere Beobachtung
  „frei“ reserviert nichts. `ServerAlreadyLocked` bedeutet Konkurrenz, keinen
  Geräteausfall; eine andere kompatible Instanz kann als Kandidat geprüft werden.
- Der Client setzt den geheimen `LockIdentifier`; der Server liefert keinen
  neuen Locktoken zurück. `UnlockServer` und die dokumentierten Fehler werden
  gegen genau diesen Vertrag behandelt. Lock-Identifier gehören ausschließlich
  in geschützten geheimen Laufzeitzustand, nie in Modellquellen, Berichte, Logs,
  öffentliche Fixtures oder GENtle-Belege. Eine Beleg-ID ist kein Lock-Identifier.
- Der Draft-Timeout in Sekunden begrenzt Inaktivität seit einem gültigen Request
  mit Lock-Identifier; `0` bedeutet kein Timeout. Das ist keine Buchungsfrist.
  Nicht jeder Call ist lockgeschützt; Schutzumfang und Metadata-Verwendung
  ergeben sich aus der exakten FDL und der vom Server angekündigten Liste
  betroffener Calls. Insbesondere darf späteres Polling eines laufenden
  Observable-Kommandos nicht pauschal als Lock-Verlängerung gelten.
- Fehlt das Feature, bleibt das Gerät auffindbar, seine exklusive
  Reservierbarkeit aber ununterstützt beziehungsweise unbekannt. Eine lokale
  SQLite-Reservierung darf diese fehlende Serverfähigkeit nicht ersetzen.
- Timeout, fehlende Quittung, Abbruch oder Neustart erfordern einen expliziten
  Besitz-/Zustandsabgleich. Lokale Belegung wird nicht allein wegen Servertimeout
  als frei erklärt; ein früherer Besitzer darf ohne erneute bestätigte
  Berechtigung keine weiteren Schritte ausführen. Unlock oder Timeout belegen
  weder das Ende eines laufenden Gerätebefehls noch sichere physische Zustände.
- Ein Lock belegt nur Allokation, nicht Ausführung, wissenschaftlichen Abschluss,
  Sicherheit oder biologische Gültigkeit. Zukunftsbuchungen, Warteschlangen und
  erwartete Freigabezeiten benötigen einen getrennten Schedulervertrag.

Die Trennung von verantwortlichem Akteur, physischem Ort, Ressourcenbesitz und
persistiertem Zustand aus den [manuellen Aufgaben](docs/manual-tasks.md) und dem
[synthetischen Gesamtlauf](docs/synthetic-lab-workflow.md) bleibt maßgeblich.
Deren lokale SQLite-Reservierungen sind keine vorhandenen SiLA-Serverlocks und
schützen keine unabhängig zugreifenden Netzwerkclients. Es entsteht keine zweite
Reservierungsführung in Geometriequellen; ein künftiger Adapter muss bestätigte
Serverallokation und lokale Laufzustände ausdrücklich aufeinander beziehen.

### Generische Features und öffentliche/private Grenze

IEGT ist die vorgesehene erste reale Laborumgebung, keine Grundlage für
Sonderlogik im Vertrag. Künftige Schemas, Featureprofile und Mappings bleiben
labor-, raum-, hersteller- und geräteinstanzunabhängig; weder TP, IEGT noch CF01
definieren deren Semantik. Zuerst ist ein geeignetes versioniertes Upstream-
Feature zu suchen und wiederzuverwenden. Fehlt ein ausreichend generisches
Feature, etwa für eine herstellerübergreifende Zentrifugationssteuerung, folgt
die kleinste neutrale, wiederverwendbare Definition unter projektkontrolliertem
Namespace mit expliziten Einheiten und Constraints. Lokal/Draft und normativ
Upstream bleiben unterscheidbar. Herstelleraliase sind kein Nachweis äquivalenter
Fähigkeiten; eine Upstream-Beitragsprüfung folgt erst nach Bewährung des gemeinsamen
Vertrags an mehreren Geräten.

Das öffentliche Repository darf synthetische Fixtures, bereinigte Instanz-IDs,
Gerätetypdefinitionen, Feature-Mappings und spätere Schemas enthalten. Reale
Endpoints, Zugangsdaten, sensible Netz-/Raummetadaten, Betriebszustand und lokale
Richtlinien gehören in eine private IEGT-Überlagerung. Beide Ebenen referenzieren
dieselben stabilen, nicht sensiblen IDs. Öffentliche Serialisierung braucht eine
ausdrückliche Feldfreigabe; bei unklarer Klassifikation oder privaten Feldern
wird der Export gesperrt, statt die Überlagerung ungefiltert auszugeben.

### Künftige Abnahmeszenarien

**Diese Kriterien sind noch zu implementieren und nicht als bestanden geprüft:**

1. Zwei generische Zentrifugen kündigen dasselbe benötigte SiLA-Feature an;
   ist eine gesperrt, kann die andere kompatible Instanz tatsächlich allokiert werden.
2. Fehlen beim freien Ersatz erforderliche RCF, Temperatur, Kapazität oder
   Gefäßkompatibilität, wird er nicht als äquivalenter Ersatz angeboten.
3. Unerreichbare, veraltete, widersprüchliche oder unvollständige Ankündigungen
   bleiben unbekannt und werden nicht als verfügbar dargestellt.
4. Ein Gerät ohne `LockController` ist auffindbar, aber nicht als exklusiv
   reservierbar ausgewiesen.
5. Zwei Clients konkurrieren um dasselbe Gerät; nur der bestätigt erfolgreiche
   Lockinhaber erhält die Zuordnung, nicht beide aufgrund einer früheren Freimeldung.
6. Timeout, Abbruch, Neustart und Freigabe bewahren einen eindeutigen bestätigten
   Besitzer oder ausdrücklich ungeklärten Zustand; sie erfinden keinen Laufabschluss.
7. Eine geänderte Featureversion oder Definitionsprüfsumme entwertet das
   bisherige Cache-Matching und verlangt erneuten Abgleich.
8. Doppelte Geräteinstanz-IDs, doppelte/widersprüchliche `ServerUUID`-Bindungen
   und ein Endpoint für zwei physische Geräte werden abgelehnt.
9. `synthetic`, `simulator`, `physical` und unbekannte Vertrauensklassen werden
   niemals still gegeneinander ausgetauscht.
10. Öffentliche Ausgaben enthalten weder Endpoint-Zugangsdaten noch Locktoken
    oder private IEGT-Netz-/Raumdetails; unklare Exporte werden gesperrt.
11. Ohne SiLA-Bindung bleiben Bytes und Semantik vorhandener Raum-, Möbel-,
    Geräteaufstellungs-, CAD- und synthetischer Workflowquellen unverändert.
12. Ein GENtle-Beleg referenziert die gewählte DIYLabBot-Instanz, `ServerUUID`
    und Featuredefinition-Digests, ohne DIYLabBot-Geometrie zu kopieren.

## Nächste Schritte

Die Geräteausstattung soll später an benannte Möbel- oder Raumrahmen gebunden
werden: Geschoss → Raum → Möbel → Arbeitsfläche → Gerät. Dann folgt ein Gerät
beispielsweise einer verschobenen Bank. Das bestehende Geräte-Layout verwendet
weiterhin seine bisherigen Aufstellungsformeln; dieser erste Schritt verlagert
keine Geräte und führt noch keinen allgemeinen Montagegraphen ein.

Danach können weitere Raumgeometrien, Flure und gemeinsame Türverbindungen
folgen. Neue Räume und Aufstellungen sollen den Möbelkatalog wiederverwenden,
ohne Möbel oder Geräte erneut zu konstruieren.

Der Referenzbanktyp liegt in einem eigenen Möbelkatalog, damit die unveränderte
L01-Komposition ihre bisherige Katalogrevision behält. Die gemeinsame
Möbelauswertung wird wiederverwendet.

Das weitergehende Zielmodell für manuelle Arbeitsschritte und Messgeräte steht
in [Manuelle Aufgaben und Messgeräte](docs/manual-tasks.md). Der synthetische
NanoDrop- und Qubit-Durchstich sowie der getrennte UltraC-Leseadapter sind oben
beschrieben; ihre Workflow-Netzwerkintegration und weitere Adapter bleiben
geplant. Messgerätetypen deklarieren Fähigkeiten im Katalog, Protokolle verlangen
Fähigkeiten statt Gerätetypen. Verantwortlichkeit und physischer Ort bleiben
getrennt; Aufgaben und Bestätigungen sind Laufzeitzustand außerhalb von `model/`.
Die bestehende CF01-Szene bleibt auf Arm, CF01 und Rack beschränkt;
Messgeräte verwenden eine eigene logische Bindung.


## Vorbereitung der RNA-/DNA-Extraktion

[docs/extraction-automation.md](docs/extraction-automation.md) beschreibt die
Vorbereitung für getrennte Säugerzellpellet-Aliquots mit RNeasy Protect Cell
Mini 74624 und DNeasy Blood & Tissue 69504. Katalog, abstrakte Prozessquelle
und synthetisches Vorbereitungsprofil stehen unter
`model/extraction-automation.*.json`. Der wirkungsfreie Preflight leitet daraus
Materialrollen, Fraktionsbezüge, Produktabstammung und offene Anforderungen ab.
Das Schema verwendet die vorhandenen Quellenreferenzen. Ein Providername ist
keine Gerätequalifikation; `execution_ready` bleibt ausdrücklich falsch.

Vor einer Laufzeitintegration müssen zurückbehaltene Extrakte, umgewandelte
Eingangsmaterialien und typisierte Verbräuche im gemeinsamen Lebenszyklus und
Ledger unterstützt werden. Die bestehende Entsorgungsbedingung für abgeleitete
Messgefäße und die reine µL-Originalentnahmebilanz reichen dafür nicht aus.
Es gibt hier keinen zweiten Bestand, kein Ausführungsjournal und keinen
Extraktionsadapter. CF01, NanoDrop- und Qubit-Verträge bleiben eigenständig;
Zentrifugeneignung und analytspezifische QC sind später ausdrücklich zu binden.


### Passive Kitstation K01

`model/extraction-kit-station.shared.json` referenziert denselben Kitkatalog
und ergänzt generische physische Artikelhüllen sowie zwei Kitmodule. Ein
Behälter-/Deckel-/Einsatzrezept erzeugt beide Module und drei statische Fälle.
FreeCAD und SolidCraft bauen direkt aus denselben portablen Operationen;
STEP ist nur ein optionaler Vergleich. Die Galerie zeigt einen kleinen
Belegungsplan, die [Stationsdokumentation](docs/extraction-kit-station.md)
die nativen Ansichten. Prototypmaße sind synthetisch, reale Maße bleiben offen.
Die Bereitstellung ist `planned_unobserved` und führt keinen zweiten Bestand.
Raumtemperaturbedingungen der verschlossenen Originalkomponenten sind von
Ansatz-/Öffnungsfristen und Probenlagerung getrennt. Die Station ist ein
Druckentwurf, keine qualifizierte Lager-, Greif- oder Extraktionsmaschine.
