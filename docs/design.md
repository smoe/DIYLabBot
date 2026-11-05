# Mechanischer Aufbau des Laborarms

Die [L01-Aufstellungsstudie](lab-layout-l01.md) kombiniert drei Instanzen dieses
Arms mit CF01, TR01, T01 und vorhandener Kassettentechnik. Die eigene gemeinsame
Layoutquelle speichert Platzierungen und Prüfbereiche. Beide CAD-Ziele erhalten
dieselben statischen, aus den nativen Ursprungsmodellen abgeleiteten Körper;
die ursprünglichen Gelenkmodelle bleiben die Grundlage für Bewegungsentwicklung.

Die [Transfersequenz L01](lab-transfer-l01.md) setzt ArmC und CF01 zusätzlich mit
nativen vorgeschriebenen Gelenkbewegungen aus denselben Ankern und Achsen um.
Ein einzelnes Gefäß und eine angenommene Greiferhülle folgen dem gemeinsamen
Ablauf; die übrigen beiden Arme stehen auf der rechten Mittelbank.

## Konzept A01

Die ergänzende [mobile Armbasis MB01](mobile-base-mb01.md) referenziert diesen Arm
aus einer eigenen gemeinsamen Quelle. Ein manueller Rolluntersatz, drei
einziehbare Stützen und ein eigener Griff sollen das Freigeben der Laborbank
ermöglichen. Die sechs Armachsen bleiben unverändert. Die Basis darf nach
Verlagerung näherungsweise stehen; die Feinanfahrt bezieht sich auf die aktuell
beobachtete Spitze und das Gefäß. Ein Präzisionsdock ist optional. Konstruktive
Stabilität, echte Kameraregelung und Lastverteilung sind weiterhin nachzuweisen.

Das Modell besteht aus sieben starren Baugruppen, verbunden durch sechs
Drehgelenke. Die Grundplatte ist fixiert. Der Arm endet an einem freien Flansch;
eine Pipettenaufnahme ist nicht enthalten.

| Achse | Baugruppen | Funktion |
|---|---|---|
| J1 | L0 Base → L1 Turret | Sockeldrehung |
| J2 | L1 Turret → L2 UpperArm | Schulter |
| J3 | L2 UpperArm → L3 Elbow | Ellenbogen |
| J4 | L3 Elbow → L4 ForearmRoll | Rotation des distalen Unterarms |
| J5 | L4 ForearmRoll → L5 WristPitch | Neigung im Handgelenk |
| J6 | L5 WristPitch → L6 BareFlange | Rotation des freien Flansches |

## Startmaße

| Größe | Konzeptmaß |
|---|---:|
| Grundplatte | 180 × 160 × 12 mm |
| Schulterachse über Grundplattenunterseite | 150 mm |
| Schulter–Ellenbogen | 200 mm |
| Ellenbogen–Handgelenkachse J5 | 175 mm |
| Dicke der Oberarm-Seitenplatten | 6 mm |
| Flanschaußendurchmesser | 50 mm |
| Flanschdicke | 8 mm |

Diese Maße definieren den Bauraum des Konzepts. Sie sind noch keine auf
Lastfall, Lagerpassung oder Steifigkeitsziel abgestimmten Fertigungsmaße.
Das Lochbild am freien Flansch ist ein Konzeptdetail ohne erklärte Normschnittstelle.

## Tragende Struktur

Gefräste Aluminiumseitenplatten und Querverbände bilden den Oberarm.
Gabeln und beidseitige Lagerstellen sind an Schulter und Handgelenk vorgesehen.
Die Rohrform des distalen Unterarms schafft einen kompakten Querschnitt.

Im früheren A01 war der Ellenbogenantrieb als Motorbauraum näher zur Schulter und als
Riemenübertragungsbauraum am Oberarm dargestellt. Übersetzung, Riemenbreite,
Vorspannung, Lagerlasten und Abdeckung waren nicht ausgelegt.
Die übrigen Motor- und Getriebekörper waren ebenfalls vereinfachte Bauräume;
die folgende Servo-Revision ersetzt diese Antriebsdarstellung.

Die aktuelle Bestückung verwendet X4-P36-36-E-L für J1/J3,
X6-P20-60-E für J2 und X2-P28-7-E für J4/J5/J6. Hersteller-STEPs
und Zeichnungen liegen in der [Referenzbibliothek](../cad/vendor/myactuator/README.md).
Die aktuelle Revision baut sie geometrisch mit getrenntem Gehäuse und Ausgang
sowie zwölf eigenen Motorplatten ein. J3 verwendet darin ein direktes Modul;
der entfernte Riemenbauraum ist entfernt. Die Präzisionsanforderung ist nicht
qualifiziert; Massen, Steifigkeit und Passungen brauchen einen Nachweis.
Die X6-Zeichnung und das CAD stimmen nach Korrektur unserer Zuordnung überein:
Gehäuse 10 × M3 auf Ø72,5 mm plus zwei Zentrierhülsen; Ausgang 12 × M4 auf Ø44 mm.
Die Platten sind entsprechend korrigiert. Die [X6-Passungs- und Schraubenauslegung](x6-fits-fasteners.md)
führt Rundbohrung/Langloch und versenkte Schraubenstapel einschließlich der
noch zu bestätigenden Gehäusegewindetiefe. Der [X6-Bericht](x6-interface-resolution.md)
und der [Integrationsbericht](servo-integration.md) beschreiben die offenen Passungen,
Freiräume und die um 40 mm verlängerte distale J6-Anordnung. Vorgehen steht im
[Integrationsplan](vendor-cad-plan.md), Last-/Präzisionsnachweis in der
[Antriebsauswahl](actuator-selection.md).

Die [X2-/X4-Auslegung](x2-x4-fits-fasteners.md) ergänzt eigene gestufte
Rund-/Entlastungsstifte und nominelle Schraubenstapel: X4 M3×8 ISO 4762,
X2 M3×6/M3×8 DIN 7984 mit reduzierter Kopfbelastbarkeit. Die X2-Ausgangsplatten
haben Radius 15,7 mm und die festen Platten Radius 16,0 mm Mittelfreiraum.
Ellenbogen- und Handgelenk-Montageebenen liegen entlang derselben Gelenkachsen
3 bzw. 4 mm weiter außen; benachbarte Kupplungen enden an den freien
Plattenseiten. Maße, Retention, Montage und Last bleiben am Prüfglied zu bestätigen.

Für die nächste Auslegung sind die Werkzeugmasse einschließlich späterer
Adapter und Leitungen sowie die Massen aller bewegten Bauteile zu erfassen.
Die Schwerkraftmomente an J2 und J3, Beschleunigung, Prozesskräfte,
Wärmeentwicklung und Haltesicherung bestimmen die Antriebsauswahl.

## Modellprüfung

Am 27. Oktober 2026 wurden alle sechs Gelenke einzeln um 5° aus der Standpose
bewegt und zurückgesetzt. Der Solver meldete keine Fehler oder Konflikte.
Eine Überschneidungsprüfung der 38 Körper fand in der Standpose nach Korrekturen
keine Überschneidungen zwischen unterschiedlichen beweglichen Baugruppen.

Innerhalb einzelner starrer Baugruppen überlappen Konzeptkörper. Diese
Überlappungen sind im JSON-Prüfbericht aufgeführt. Sie stellen weder geprüfte
Passungen noch einen fertig konstruierten Montagezustand dar.

Am 28. Oktober 2026 wurden die Gelenke erneut gelöst und zwei Modellansichten
gerendert sowie visuell auf Bildausschnitt und Vollständigkeit geprüft.
Das ist keine optische oder mechanische Leistungsprüfung des realen Roboters.

Die gespeicherte Standpose lautet J1=20°, J2=35°, J3=65°, J4=0°, J5=80°, J6=15°.
Die Gelenkgrenzen im Modell sind vorläufige Demonstrationsgrenzen.
Der gesamte Bewegungsraum und die späteren Arbeitsbahnen sind noch zu prüfen.

## Parametergrenze des Konzepts

Die Gliedlängenparameter steuern die Geometrie. Die auf der Elternseite
gespeicherten Gelenkkoordinatensysteme sind im A01-Modell jedoch fest.
Nach Änderung von Oberarm- oder Unterarmlänge müssen die Gelenkanker neu
abgeglichen und die Kette erneut geprüft werden.

## Erste parallele FreeCAD-Fassung

Am 28. Oktober 2026 wurde eine FreeCAD-Begleitfassung aus dem A01-STEP-Export
und den zugehörigen SolidCraft-Gelenkrahmen aufgebaut. Alle 38 Körper sind
den sieben ursprünglichen starren Baugruppen zugeordnet. Die Grundplatte
bleibt fest; sechs native, durch Ausdrücke gesteuerte Drehtransformationen
bilden die serielle Vorwärtskinematik ab. Das FCStd-Modell enthält diese
Verknüpfungen dauerhaft. Ein Python-Makro ergänzt die Bedienung.

Die Geometrie ist als importierte Volumenkörper enthalten; die SolidCraft-
Konstruktionshistorie und native FreeCAD-Assembly-Solvergelenke sind nicht
übertragen. Diese erste Begleitfassung diente dem Erkunden der Achsbewegungen und wurde inzwischen auf Eigentümerwunsch gelöscht.
Bei dieser früheren Begleitfassung wurden Gliedlängen in SolidCraft geändert
und nach Abgleich der Gelenkanker erneut exportiert. Diese erste Übertragungsart
wird durch die nachfolgende gemeinsame Modellquelle ergänzt.

Geometrieprüfung und Wiederöffnung der gespeicherten FCStd-Datei bestanden.
24 Posen wurden gegen eine gesonderte Vorwärtsrechnung geprüft; sechs
Einzelbewegungen um jeweils +5° zusätzlich gegen den SolidCraft-Solver.
Alle zwölf Regler und sieben Animationsmodi wurden in der laufenden
FreeCAD-Oberfläche getestet. Die Standpose hat keine erkannten
Volumenüberschneidungen zwischen verschiedenen starren Baugruppen oberhalb
0,0001 mm³. Die vollständigen Achsbereiche und die Demonstrationsbahn sind
damit nicht als kollisionsfrei nachgewiesen.

Bedienung, Winkelgrenzen und Reproduktionsweg stehen in [freecad.md](freecad.md).
Die Prüfberichte und FreeCAD-Modellansichten enthalten die Zuordnung zum
Quellstand. Eingeblendete Referenzebenen und Koordinatensysteme wurden für
die gespeicherte Modellansicht ausgeblendet.

## Gemeinsame Modellquelle und abgeleitete Fassungen

Auf ausdrücklichen Wunsch des Eigentümers wurde die Entwicklungsrichtung auf
eine CAD-unabhängige Quelle umgestellt. `model/robot.json` beschreibt Parameter,
starre Glieder, Konstruktionsrezepte, Gelenkrahmen, Winkelgrenzen, eine
Flanschreferenz und ausführbare Bewegungssequenzen. Die Datei ist die führende
Quelle; die beiden CAD-Programme sind Ziele der Generatoren.

SolidCraft wird über seine dokumentierten Befehle erzeugt. Wenn die MCP-Verbindung
verfügbar ist, kann dieselbe Befehlsfolge darüber ausgeführt werden. Der
reproduzierbare lokale Aufbau verwendet die SolidCraft-CLI in einem eigenen
Prozess. FreeCAD erhält native Grundkörper, boolesche Features und Ausdrücke;
es importiert für unsere Struktur und Motorplatten keine STEP-Geometrie.
Die später ergänzten Kaufteilreferenzen für Servogehäuse und -ausgänge stammen
hingegen aus registrierten Hersteller-STEPs.

Die Gelenkrahmen beziehen sich auf die gemeinsame Nullstellung. Anker für
Ellenbogen, Unterarm und Handgelenk werden aus denselben Längenparametern wie
die Geometrie abgeleitet. Ein Test mit 220 statt 200 mm Oberarmlänge verschiebt
die Ellenbogen- und Handgelenkanker um die erwarteten 20 mm. In SolidCraft ist
für eine gemeinsame Maßänderung der Neuaufbau aus der Quelle vorgesehen;
ein isoliertes Ändern des nativen Längenparameters gleicht die dort numerisch
angelegten Gelenkanker weiterhin nicht automatisch ab.

Eine semantische `label`-Operation erzeugt die drei UMR-Buchstaben ohne lokale
Schriftartabhängigkeit. Die kräftigen Konturen werden als 0,8 mm hohe Prismen
auf der Oberarm-Seitenplatte dargestellt. Sie sind eine Kennzeichnung, keine
zusätzliche tragende Funktion. Diese ursprüngliche Ableitung umfasste 41 Körper;
die Servo-Integration umfasst jetzt 62 Endkörper.

Der aktuelle Vergleich prüft Körpervolumen und Schwerpunkte beider CADs.
Die gemeinsame Sequenz dreht J1 von 20° auf 25° und zurück, jeweils in 2 s.
Die FreeCAD-Prüfung untersucht 11 Posen mit BRep-Volumenüberschneidungen;
Zwischenräume zwischen den Abtastungen sind nicht kontinuierlich geprüft.
Die Ausführung des Aufbaus wurde mit SolidCraft 0.25.1 und FreeCAD 27.1.0dev geprüft.

Für ROS 2 werden daraus URDF, acht Visualisierungsmeshes einschließlich der
UMR-Kennzeichnung, konservative Kollisionsquader und Trajektoriendaten erzeugt.
Die Servo-Integration erzeugt sechs gesonderte RViz-Gehäusequader; die
Vendor-Oberflächen sind aus den Strukturmeshes ausgeschlossen.
Die Gelenkrahmen werden von mm/° nach m/rad überführt und gegen die gemeinsame
Vorwärtskinematik geprüft. Der freie Flansch erhält die Referenz `tool0` auf
seiner Stirnfläche bei `flange_z + 26 mm` in den aktuellen Konstruktionskoordinaten
(vor der Servo-Integration: `flange_z + 10 mm`).
Es ist kein kalibrierter Pipettenspitzen-TCP.

Der ROS-2-Start ist auf `mock_components/GenericSystem` vorbereitet. Eine
ROS-2-Laufzeitprüfung konnte auf diesem Rechner bisher nicht erfolgen.
Gazebo, physikalische Antriebe und Flüssigkeitssimulation sind nicht implementiert.
Details stehen in [shared-model.md](shared-model.md) und [ros2.md](ros2.md).

## Konzeptoption: gekühlter Gefäßplatz mit Deckelbetätigung

Der zusätzliche Wunsch nach Pipettieren auf Eis wird zunächst als eigenständige
Station neben dem Arm betrachtet. Der [separate Konzeptentwurf C01](tube-station-c01.md)
enthält jetzt native Modelle in SolidCraft und FreeCAD mit einem Gefäßplatz, zwei Deckelfingern,
Kühleinsatz und unselektierten Antriebs-/Rückhaltebauräumen. Der nachfolgende
Abschnitt beschreibt dessen Konzeptziel; Passungen, Kontaktmechanik und thermische
Leistung sind weiterhin nicht ausgelegt oder nachgewiesen.

Beide Fassungen werden aus `model/tube-station-c01.shared.json` erzeugt.
Körper, Ausschnitte, Gelenkrahmen und gekoppelte Parameter liegen in dieser
Quelle; der [Vergleichsbericht](../cad/tube-station-c01/shared-build-report.json)
prüft vier Geometriefälle und die native FreeCAD-Parameteränderung.

Auf der vorderen Behälteraußenwand sitzt jetzt dieselbe kräftige
UMR-Kennzeichnung wie am Arm. Drei dunkelblaue, 24 mm hohe und 0,8 mm erhabene
Buchstabenkörper werden aus den gemeinsamen, schriftartunabhängigen Konturen
erzeugt. Die Kennzeichnung gehört zur festen Stationsgruppe und ist in
SolidCraft und FreeCAD enthalten; damit umfasst die Stationsableitung 32 Körper.

Die Beladungsprüfung zeigt eine zusätzliche Grenze: C01 lässt nur 4 mm
Gefäßkörper unterhalb des Kragens frei und enthält keinen Greifer oder
Einsetz-/Entnahmeweg. Die vorhandenen Kollisionsstichproben beginnen mit bereits
eingesetztem Gefäß. Als noch nicht modellierte Korrektur wird ein außerhalb der
Deckelmechanik beladbarer, wärmeleitender Träger mit zugänglichen Greifflächen
und definierter Stationsaufnahme vorgeschlagen; siehe
[Beladungsbewertung](tube-station-c01.md#loading-review-c01-does-not-establish-automatic-tube-handling).

Ein austauschbarer, wärmeleitender Metalleinsatz soll das Gefäß passend zum
konkreten Artikel aufnehmen. Eine gesonderte Rückhaltung nahe dem oberen
Gefäßkragen nimmt Öffnungs- und Schließkräfte auf. Einsatz und Deckelmechanik
erhalten eine gemeinsame, feste Referenz am Stationsrahmen; schmelzendes Eis
darf die Gefäßpose nicht verändern. Der untere Einsatzbereich wird in einem
isolierten, entnehmbaren Eis-/Schmelzwasserbehälter gekühlt. Kondensat und
Schmelzwasser sind unterhalb von Öffnung, Antrieben und Elektronik aufzufangen.

Gefäßmund, Öffnungslasche und Scharnier bleiben für die Deckelfinger zugänglich.
Das Gefäß verbleibt beim Öffnen, Pipettieren und Schließen im Einsatz. Die
Betätigung kann über einen vom Roboter gedrückten Hebel oder lokale Antriebe
erfolgen; eine Antriebsauswahl ist damit nicht getroffen. Für verschiedene
Gefäßartikel sind Einsätze, Kontaktgeometrien und Bewegungen einzeln zu prüfen.
Auch die Betätigungskräfte müssen bei den vorgesehenen kalten Bedingungen
gemessen werden.

Für die optische Tropfensuche wird zunächst die schräge Sicht durch die Öffnung
untersucht. Die Metallaufnahme kann seitliche Sichtlinien verdecken; Ausschnitte
würden wiederum den Wärmekontakt vermindern. Kondensation am kalten Gefäß kann
die Bildauswertung beeinflussen. Insbesondere die Temperatur nahe der oberen
Innenwand ist getrennt von Block- und Bodentemperatur zu beurteilen.

Wärmeleitende Gefäßmodule auf einer Kältequelle sind ein bestehendes Prinzip,
etwa beim [Corning CoolRack M15](https://ecatalog.corning.com/life-sciences/b2b/US/en/General-Labware/Sample-Cooling-Systems-and-Accessories/CoolRack%C2%AE-for-Tubes/Corning%C2%AE-CoolRack%C2%AE-M-Microcentrifuge-Tube-Modules/p/432037).
Die dort angegebenen Leistungen gelten nicht als Nachweis des eigenen Konzepts.
[Eppendorf beschreibt Temperatureinflüsse auf Luftpolsterpipetten](https://www.eppendorf.com/us-en/lab-academy/topics-methods-technology/pipetting-dispensing/influence-of-physical-parameters-on-the-dispensed-volume-of-air-cushion-pipette).
Deshalb sind Volumenleistung und Wiederaufnahme unter den tatsächlichen kalten
Bedingungen gesondert zu messen. Eine spätere geregelte Kühlung bleibt eine
Ausbauoption; zunächst wird Wassereis betrachtet.

## Konzeptoption: zwei Armkameras und stationäre Laboransichten

Der Eigentümer wünscht seit dem 28. Oktober 2026 mehrere stationäre Kameras
sowie zwei Kameras am Arm. Seit Modellstand V02 enthält `model/robot.json`
zwei semantische `camera`-Operationen. FreeCAD, SolidCraft und RViz erhalten
daraus Kamerabauräume, provisorische Halter und durchsichtige Sichtkegel.
Kameraartikel, fertigungstaugliche Befestigungen und reale Sichtfelder sind
weiterhin nicht ausgewählt oder qualifiziert. Stationäre Kameras bleiben
außerhalb dieses Armaufbaus.

| Rolle | Vorläufiger Montagebereich | Bildaufgabe |
|---|---|---|
| C_tip, untere Armkamera | Vorläufig L6, auf der rotierenden Werkzeugseite von J6, seitlich am freien Flansch | Spitze, Gefäßöffnung und sichtbare Flüssigkeit bei der Feinanfahrt |
| C_scene, obere Armkamera | Vorläufig L1, erhöhter Halter neben dem Schulterturm; dreht nur mit J1 | Breiter Blick auf Racks, Gefäße und die nächste Arbeitszone |
| C_station_*, stationäre Kameras | Feste Labor-/Stationshalter, zum Beispiel von oben und schräg auf einzelne Arbeitsplätze | Stabiler Stationsbezug und ergänzende Sicht bei Verdeckung |

Der [visuelle Entwurf V01](../exports/vision/v01/camera-layout-v01.png) zeigt
die Nahkamera in Türkis, die Übersichtskamera am Schulterturm in Blau und zwei
beispielhafte stationäre Kameras in Orange. Grundlage ist ein nativer
SolidCraft-Modellrender des Armstands `5c49759cd210`; die beschriftete Ansicht
wurde anschließend mit ImageGen als Konzeptillustration erzeugt. Kameras,
Halter, Pipettenwerkzeug und Arbeitsplatzeinrichtung sind illustrative Ergänzungen,
keine neuen CAD-Baugruppen. Sichtkegel sind noch nicht geometrisch geprüft.
[Referenzbild, Generierungsangaben und Prüfgrenzen](../exports/vision/v01/provenance.json)
ordnen die Darstellung dem konkreten Modellstand zu; die Illustration kann von
der exakten CAD-Geometrie abweichen.

Die [native Modellansicht V02](../exports/vision/v02/model-iso.png) zeigt die
tatsächlich erzeugte Geometrie des Quellstands `fa7821d1ce02`, mit
[Renderzuordnung](../exports/vision/v02/model-render.json). Anders als die
historische Illustration V01 enthält der CAD-Aufbau weiterhin keine Pipette,
Gefäße oder stationären Kameras. Die Achse der Nahkamera ist auf einen rein
gedachten Spitzenpunkt 128 mm vor der Flanschstirnfläche ausgerichtet; nach
Werkzeugauswahl ist diese Annahme zu ersetzen und die Sicht erneut zu prüfen.

| Bauraum / Sichtkegel | C_tip | C_scene |
|---|---:|---:|
| Gehäuse, lokale Breite × Höhe × Tiefe | 24 × 22 × 26 mm | 28 × 24 × 28 mm |
| Objektivradius / Länge | 7 / 8 mm | 8 / 8 mm |
| Kegellänge / ferner Radius | 145 / 22 mm | 300 / 150 mm |
| Voller kreisförmiger Öffnungswinkel, daraus berechnet | ca. 17,255° | ca. 53,130° |
| Opazität des Sichtkegels | 0,18 | 0,10 |

Diese Maße sind frei gewählte Konzeptparameter, keine Kaufteil- oder Objektivdaten.
Die kreisförmigen Kegel vereinfachen reale rechteckige Bildfelder. Sie bleiben
sichtbar, auch wenn sie Armteile durchdringen: es erfolgt keine Verdeckungs-,
Brechungs- oder Tiefenschärferechnung. In FreeCAD und SolidCraft sind sie native
Kegel; RViz erhält getrennte eingefärbte Visualisierungsmeshes mit Alpha.
Die Rolle `viewing_cone` wird bei den physischen BRep-Kollisionsstichproben
und bei URDF-Kollisionskörpern ausgelassen. Kameragehäuse, Objektive und Halter
bleiben dagegen in diesen Geometrieprüfungen enthalten. Überlappungen innerhalb
eines starren Glieds sind weiterhin Konzeptdetails und keine geprüften Passungen.

Optische Rahmen `C_tip_optical` und `C_scene_optical` sind im nativen FreeCAD
gespeichert; ROS verwendet `c_tip_optical` und `c_scene_optical` als feste
Kindrahmen der zugehörigen Glieder. +Z blickt nach vorn, +X nach rechts und +Y
nach unten. Diese Frames sind Entwurfswerte, keine Kamerakalibrierung.
Die Kameraoperation führt eigene offene Anschlussdaten und den logischen
Gliederpfad. Der [Kamerabericht](../exports/generated/fa7821d1ce02/cameras-report.json)
nennt für C_tip J1 bis J6 und für C_scene nur J1 als benötigte Leitungsgrenzen;
Kabeltyp, Führung, Schnittstelle und zulässiges Bildalter bleiben offen.

Für C_tip zunächst einen seitlich versetzten, schrägen Blick auf das Spitzenende
und durch die Gefäßöffnung erproben. Eine starre Verbindung zum Werkzeug hält
deren geometrische Beziehung bei J6-Drehung konstant. Eine Kamera vor J6 ist
ebenfalls untersuchbar; dann muss die J6-Stellung in die Kamerabeziehung eingehen
und die Sicht bei Werkzeugdrehung gesondert geprüft werden. Die spätere
Pipettenaufnahme bleibt außerhalb des gegenwärtigen CAD-Umfangs.

Eine obere Kamera auf L2 neigt sich mit der Schulter und dem Oberarm; eine
Montage auf L1 vermeidet diese Nickbewegung, dreht aber mit J1. Keine dieser
Montagen garantiert in jeder Pose eine freie Gesamtansicht. Die stationären
Kameras ergänzen diese wechselnden Ansichten. C_tip und C_scene erfüllen
unterschiedliche Sehaufgaben und sind kein automatisch tiefenmessendes Stereopaar.

Objektiv, Arbeitsabstand, Sichtfeld und Schärfentiefe anhand echter Spitzen und
Gefäße bestimmen. Kontrollierbare Beleuchtung, feste Fokus-/Belichtungseinstellungen
und bei Aufnahmen während Bewegung bevorzugt ein Global-Shutter-Sensor sind
Auslegungskandidaten. Reflexionen, Brechung an gekrümmten Gefäßwänden, Deckel,
Metalleinsätze und Kondensat können das Ziel verdecken oder seine Bildlage
verändern. Pixelmaßstab und nominelle Sensorauflösung belegen keine erreichte
Positioniergenauigkeit.

Jede Kamera benötigt eine intrinsische Kalibrierung und eine bekannte Beziehung
zu ihrem Montageglied beziehungsweise zur Station. Bewegte Bilder müssen zur
Belichtungszeit mit gemessenen Gelenkstellungen zugeordnet werden. Bei späteren
Werkzeugwechseln ist die tatsächliche Spitzenlage zu prüfen; ein nomineller
Flansch-TCP reicht dafür nicht aus. Veraltete oder verdeckte Bilder dürfen keine
ungeprüfte Feinanfahrt auslösen; die zulässige Latenz und Reaktion sind festzulegen.

Masse, Schwerpunkt, Haltersteifigkeit und Kameraleitungen sind in die spätere
Auslegung aufzunehmen. Die getrennte Servo-Topologie reicht weiterhin bis L5;
die Kameraoperation vermerkt zusätzlich den Anschlussweg über J6.
Biegung, Verdrehung, Zugentlastung und Kollisionsfreiraum sind
über die benötigten Posen zu prüfen. Kamerabilder ersetzen weder den
Volumennachweis noch einen Nachweis der sicheren Roboterbewegung.

Fachliche Grundlagen: [Basler zu elektronischen Verschlüssen](https://assets-ctf.baslerweb.com/dg51pdwahxgw/7ntd9P0LbEeEmxKj6Q6J1h/cb845234f745dddab95f3ee64994dd7d/BAS1401_White_Paper_Rolling_Shutter.pdf),
[NI zu Sichtfeld, Arbeitsabstand und Schärfentiefe](https://www.ni.com/en/support/documentation/supplemental/06/ni-vision-image-acquisition-system-concepts.html)
und [Zivid zur Kamera-Roboter-Kalibrierung](https://support.zivid.com/en/v2.12/academy/applications/hand-eye/hand-eye-calibration-problem.html).
Diese Quellen begründen die Prüfaufgaben, keine Leistungszusage des Konzepts.

Der V02-Aufbau verglich alle 72 Endkörper beider CADs (einschließlich der zwei
nicht physischen Sichtkegel); größte Schwerpunktabweichung rund 0,00132 mm,
größte relative Volumenabweichung unter 0,019 %. Alle sechs SolidCraft-Gelenke
wurden um +5° und zurück bewegt. FreeCAD prüfte Standpose, sechs Einzelposen
und elf Protokollstichproben einschließlich Kamera-/Halterbauräumen ohne erkannte
Überschneidungen zwischen verschiedenen starren Gliedern. Kamera- und Kegelanker
wurden zusätzlich bei Änderungen der Oberarmlänge, des Kameraabstands und
der Kegellänge geprüft. 70 Offline-Tests bestanden. Vollständiger Bewegungsraum,
optische Sichtbarkeit, FreeCAD-GUI und laufendes ROS/RViz sind nicht damit geprüft.

## Noch offene Konstruktion

Die [Raumumgebung L01](lab-room-l01.md) besitzt eine eigene gemeinsame Quelle.
Eine parametrisierte, facettierte Fassadenwölbung verbindet die unterschiedlich
langen rechtwinkligen Seitenwände. Drei Randbänke, eine mittlere Doppelbank,
geschlossene Unterschrank-Bauräume und zwei flachere seitliche Oberschrankzeilen
folgen denselben Maßen in FreeCAD und SolidCraft. Oberschrankorte und alle Zahlen
sind vorläufig. Menschen, Fahrzeuge, Arme und Geräte werden erst nach Aufnahme
von Grundriss, Arbeitsplätzen und Freiräumen zugeordnet; Gänge sind geometrisch
offen, aber nicht als Betriebs- oder Fluchtwege qualifiziert.

Die Fensterbank besteht inzwischen aus zwei geraden Vierkant-Prismen mit
getrenntem Unterstauraum neben einer vertikalen Betonstütze. Deren ungefähr
300 × 500 mm Querschnitt übernimmt die Eigentümerangabe; die Stützenfront ist
mit den inneren Bankfronten gekoppelt. Heizungsabdeckungen füllen die variablen
Spalten zu den gekrümmten Fenstern und um die Stütze. Fassade und Verglasung
bleiben unabhängig von Stützenänderungen. Tragwerk, Heizleistung, Luftdurchlass
und reale Kleinteilrückhaltung sind nicht ausgelegt oder geprüft.

Ein gemeinsames schmales Regalbrett mit drei Stützen ergänzt die Rückenlinie
der beiden Mittelbänke. Länge und Stützenpositionen folgen der Insellänge und
parametrischen Endabständen; Breite und Höhen bleiben verstellbar. Das Brett
und die Stützen entstehen in beiden CADs aus derselben semantischen Operation.
Geprüft werden Zentrierung, geometrische Auflage und Freiraum über den Bänken;
Belastung, Befestigung und Ergonomie sind nicht qualifiziert. Das Brett liegt
nun auf 1,50 m; drei obere Stützen tragen zwei Schrank-Bauräume ab 1,75 m. Der
250 mm hohe Bereich dazwischen hat keine Rückwand. Geometrische Querproben
zwischen den Stützen prüfen seine Offenheit. Fensterseitige Unterschrank- und
Sockelkörper entfallen und werden durch offene Bein-Bauräume ersetzt.

[H03](tube-cam-h03.md) konkretisiert den motorlosen Stationsantrieb: Zwei
Kurvenscheiben auf einer gemeinsamen horizontalen Welle heben das Gefäß und
schließen über einen Keilkragen den Empfänger. Ein federbelasteter Bolzen
hält den Kragen beim Folgerrückzug. Sein Zug-/Vierteldrehverschluss erlaubt
ein vom Roboter betätigtes Offenhalten für den Rücklauf. Kurvenkonturen,
Winkelphasen, Verriegelungsfenster und zugehörige Rahmen entstehen aus derselben
Quelle. Nominale Kollisionsfreiheit ersetzt keine Feder-, Kontakt- oder Lastprüfung.

Der [Probentransport TR01](sample-transport-tr01.md) wird ausschließlich als
Bodenfahrzeug für Armstationen und Laborwechsel auf derselben Etage weitergeführt.
Tisch-/Spurwagen bleiben Historie; spurgenaue Fahrt ist keine Anforderung.
Zwei 140 × 104-mm-Kassettenplätze haben in allen drei Boden-Konfigurationen
denselben Bezug und dieselbe ungleich große Stiftanordnung. Plattennester und
24er-Gefäßeinsätze werden aus einer gemeinsamen Quelle in beiden CADs erzeugt.
Das Bodenfahrzeug ist ein statischer Bauraumentwurf mit erhöhtem Übergabedeck.
Der Arm soll Proben direkt vom geparkten Fahrzeug handhaben. Dazu sind je Station
Höhe, Parkpose, Werkzeugreichweite, lokale Probenreferenz und Haltefunktion zu
prüfen. Vision oder ein einfaches Dock sind Optionen; ein Präzisionsdock ist
nicht vorgeschrieben. Antrieb, Lenkung, Navigation, Abdeckungshandhabung und reale
Armübergabe sind noch nicht konstruiert.
H01 und C01 benötigen eigene Adapter.

Der [separate Gefäßträger H01](tube-carrier-h01.md) konkretisiert die vorgeschlagene
wechselbare Aufnahme: gemeinsamer Träger mit Greifflächen und asymmetrischem
Dockschlüssel, unterschiedliche konische/runde Gefäßeinsätze und ein Frontdock.
Vier Schieber beschreiben Einfahrt und Verriegelung in mm. Gemeinsame Quelle,
zwei native CAD-Adapter und Geometrie-/Positionsprüfungen folgen dem Ansatz des
Arms. H01 ist nicht in die bestehende Deckelstation C01 eingebaut; deren
Beladungsgrenze sowie die offene Auslegung von Kontakt, Kräften und Kühlung bleiben.

Für den neuen Wunsch nach freier Flüssigkeitssicht folgt [H02](tube-frame-h02.md):
schmale Führungs-/Sitzringe und zwei hintere Pfosten statt eines umschließenden
Körpers, durchgängige Bodenöffnungen und ein äußerer Bodenheber. Zwei geteilte
Empfangssitze schließen erst am angehobenen Gefäß; danach zieht der Heber zurück.
Eine obere Körperführung begrenzt das Kippen. Ein Öffnungs-/Lippenfreiraum,
Unterstützungszustände und vier Kamerasegmente ergänzen den Geometrievergleich.
Handhabungskontakte sind an Boden und äußerer unterer Wand vorgesehen. H02
enthält keine echte Kontakt-/Kraftsimulation, Deckelbetätigung oder C01-Anbindung.

Als eigenständiger Arbeitsplatz ist außerdem der [Spitzenabwurf T01](tip-collector-t01.md)
für die gewünschten 10-/200-/1000-µl-Pipetten angelegt. Drei farblich und mit
Volumenklassen markierte Gabelplatten besitzen vorläufig 4/6/9 mm breite Nuten.
Der feste Rahmen nimmt die Abziehreaktion auf; die Sammelbox kann darunter nach
vorne entnommen werden. Die Nut hält den Spitzenrand von oben, während die Pipette
nach oben herausgezogen wird. Artikelpassung, Verbindungsmittel, Kraftnachweis und
Roboterfreiräume sind noch nicht qualifiziert. Das Arm-Modell bleibt unverändert.

Der T01-Aufbau wird jetzt aus `model/tip-collector-t01.shared.json` in beiden CADs
erzeugt. Zum bisherigen Aufbau kommen drei kräftige UMR-Buchstabenkörper auf der
Front der Sammelbox hinzu: 24 mm hoch und 0,8 mm erhaben, derselbe Kontursatz wie
beim Arm. Sie gehören zur entnehmbaren Bin-Baugruppe. Quader, Bohrungen,
Abstreifprofile und Beschriftungen besitzen eine gemeinsame Beschreibung; native
FreeCAD-Features und SolidCraft-Features werden daraus getrennt aufgebaut.
Der [Vergleichsbericht](../cad/tip-collector-t01/shared-build-report.json) prüft
14 Körper in drei Maßfällen sowie native Parameteränderungen in beiden CADs.

Die Eigentümeranforderung für die Antriebe lautet jetzt Servos mit auslesbarer
Positionsrückmeldung. `services` in der gemeinsamen Quelle ordnet sie den
Motorbauräumen zu und beschreibt logische Leitungswege.
Die Ebene bleibt in der Bewegungsdarstellung unsichtbar. Topologieprüfungen sind
implementiert; räumliche Kabelführung, Biege-/Torsionsnachweise und tatsächliche
Sensorrückmeldung stehen aus. Siehe [servo-cables.md](servo-cables.md).

- Lageranordnung, Vorspannung, Wellen, Passungen und Befestigungen.
- Antriebsmomente, Übersetzungen, Regelung und Messung am Gelenkausgang.
- Steifigkeit, Umkehrspiel, Schwingungen und thermische Drift.
- Sichere Haltefunktion an schwerkraftbelasteten Gelenken.
- Leitungsführung durch Gelenke und Begrenzung von Kabelverdrehung.
- Kraftbegrenzte Feinanfahrt und optische Erfassung der tatsächlichen Spitze.
- Vollständige Kollisionsprüfung einschließlich Werkzeug und Umgebung.
- Reproduzierbarer Austausch des späteren Werkzeugmoduls.

Eine Tragfähigkeits-, Mikrometerpräzisions- oder Fertigungszusage ist aus
diesem Modellstand noch nicht abgeleitet.

## Zentrifugenstation CF01

Die neue [Entnahmeszene](centrifuge-cf01-robot-pickup.md) nutzt den vorhandenen
Sechsachsenarm mit einem provisorischen Parallelgreifer. Das Gefäß wechselt nach
Greifbestätigung starr zum Werkzeug, wird axial ausgezogen und aus dem
Deckelbereich zurückgenommen. Erst danach werden Heber und Deckel bewegt.
Lokale Armhalterung, Greifer und Bewegungszeiten sind Demonstrationsannahmen;
die vorhandene L01-Aufstellung bleibt unverändert.

Die aktuelle lokale CF01-Fassung montiert den Arm ohne Podest auf Bankhöhe.
Oberarm/Unterarm wachsen als Parameter-Variante derselben Quelle von 200/175
auf 280/250 mm. Ein bodengestütztes 12-Platz-Rack erhält große Führungsbohrungen
mit konischen Einläufen für das ungefähr 1-mm-Transportziel. Der Arm richtet
das entnommene Gefäß außerhalb der Zentrifuge auf, setzt es ab, bestätigt die
Unterstützung und öffnet erst dann die Finger. Adaptive native Kollisions-
stichproben umfassen auch die Zwischenbewegungen, den Deckel, die Bank und
das Rack. Die längeren Hebel erfordern weiterhin Last-/Steifigkeits- und
Antriebsnachweise; direkte Bankmontage allein qualifiziert keine Stabilität.

Die Mechanikrevision ersetzt den kombinierten Motorbauraum durch Spindelstator,
Rotorkern, Welle und Lagerhüllen. Eine elektrische Betriebsbremsung und ein
Widerstandsbauraum übernehmen die geplante Verzögerung; ein separater Sattel
mit zwei Schieberbelägen hält die Scheibe erst bei bestätigtem Stillstand.
Der Deckel erhält einen 60:1-Getriebemotor, durchgehende Scharnierwelle,
Lagerböcke, Ausgangskupplung, Motorhaltebremse und zwei angetriebene Stifte.
Die Hohlbasis wächst auf 400 × 380 × 150 mm. Acht Koordinaten und die
automatische Sequenz sind in beiden CADs umgesetzt; die Teile bleiben
unqualifizierte Konzepte. Der Rotorwerkstoff bleibt unselektiert.

Die präzisierte Stahlfassung verwendet vorläufig 22 mm radiale Kammerwand,
12 mm Boden und 20 mm Deckel. Vier Stützen verbinden den Kammerboden mit dem
unteren Gehäuseboden. Der untere Hohlraum enthält Motor-/Elektronikbauräume,
einen A/B/Z-Spindelgeber mit Halter und Signalweg; seitlich sind Netzmodul,
abnehmbares Kabel, Zugentlastung und PE-Anschluss dargestellt. Stahlgüte,
Schweiß-/Schraubverbindungen, Deckelantrieb, reale Elektrik und Geberauswahl
stehen aus. Die Materialfestlegung gilt nicht für den Rotor. Vollständige
Nachweise folgen nicht aus Wanddicke oder CAD-Materialzuordnung.

Der [CF01-Entwurf](centrifuge-cf01.md) ist eine eigenständige Station aus einer
gemeinsamen Quelle. Ein 12-Platz-Rotor wird bei geschlossenem Deckel mit höchstens
2 rpm indexiert, angehalten und gehalten. Danach öffnet der Deckel und ein
stationärer Heber hebt das vordere Gefäß um 16 mm entlang seiner 35° geneigten
Achse. Ziffern 01–12, ein Dreieck, ein Quadrat und feste Stationsmarkierungen
unterstützen die spätere Kamerakalibrierung. Die Heberdurchbrüche brauchen eine
eigens qualifizierte Rotorkonstruktion. CAD und lokale Mock-Steuerung sind kein
Festigkeits-, Greif-, Kamera- oder 16.000-×-g-Nachweis.
