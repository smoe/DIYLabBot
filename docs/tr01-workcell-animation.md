# TR01-Übergaben in L01

`model/tr01-l01-workcell.protocol.json` ergänzt die bestehende L01-Aufstellung als
separate synthetische Komposition. Sie referenziert Raumaufstellung, Fahrprofil,
Sechsachsarm, Greiferhülle und bestehende Bewegungsgrenzen. Die Grundaufstellung
bleibt eine eigenständig aufbaubare Dreiarm-Aufstellung.

Die zusätzliche Instanz ArmDNA verwendet dieselbe Armquelle. ArmA und sein
vorhandener Unterbau werden für diese Komposition um 120 mm zur Gangseite
versetzt. ArmB steht während der Übergaben in einer eigenen aufrechten
Parkstellung, damit er ArmA am QC-Rack nicht behindert. CFHandoffRack und TSHandoffRack sind Instanzen der bestehenden
TR01-Kassette, keine neuen Rackkonstruktionen. Das zusätzliche CF-Rack bringt
die Übergabe in Armreichweite; eine native CF01-Beladung wird damit nicht
vorgeführt. TapeStation und PC behalten ihre L01-Positionen.

## Verkehrs- und Übergabevertrag

Durchfahrten verwenden die aus der Raumquelle abgeleiteten Gangmitten. Die
Wartepositionen dort sind von den Andockpositionen getrennt. DNA und TapeStation
teilen den Arbeitsbereich LeftIsland: Eine Belegung durch Pipettieren sperrt
beide Annäherungen. Unbekannt gilt ebenfalls als gesperrt. Eine neue Beobachtung
entwertet die alte Freigabe. Weder Zeitablauf noch Signalton geben einen Bereich
frei. `scripts/bench_access.py` stellt diese reinen Zustandsübergänge für
persistierende Aufrufer bereit; es ist kein Sensor oder Sicherheitscontroller.

Die Vorschau verlangt ausdrücklich synthetische Bestätigungen für
Arbeitsplatzfreigabe, Griff/Identität, Ablage, Prozessabschluss und Abfahrt.
Während einer Andockfahrt führt eine neue Belegung zur angehaltenen Vorschau;
eine erneute Freigabe bleibt erforderlich. Dieser dargestellte Schutzstopp
ist keine geprüfte physische Bremsbahn. Die Zeitachse ist eine Vorschaufunktion,
kein Ausführungsjournal. Bestätigungen ersetzen keine realen Beobachtungen.

TR01 hält bei der eigentlichen Übergabe. Alle anderen Arme bleiben geparkt.
Die Abdeckung hat keinen konstruierten automatischen Öffner: Abnahme mit
anschließend freiem Armbereich sowie Wiederaufsetzen, Retention und Personen-
freigabe sind ausdrücklich manuelle Schritte. Diese Wartebedingungen besitzen
keine erfundene feste Dauer.

Ein repräsentatives Gefäß läuft DNA → CF-Übergaberack → QC-Rack → manuelle
TapeStation-Ablage → DNA. Es wird jeweils entladen und für die Weiterfahrt
wieder übernommen. Die menschliche Tragebewegung ist schematisch; ScreenTape-
Vorbereitung und Gerätebedienung sind nicht automatisiert. Eigentümerwechsel
verwenden erhaltene starre Anheftungen, damit das Gefäß nicht beim Greifen oder
Ablegen springt oder doppelt dargestellt wird. Übrige Rack-/Fahrzeuggefäße sind
Illustrationshüllen, keine zusätzliche Laufzeit-Probenbilanz.

## Bewegung und Nachweise

`tr01_workcell.py` verwendet die gemeinsame FK und C2-PVA-Mathematik. Der Greifer
bleibt aufrecht; die Gelenkgrenzen werden auch zwischen Knoten geprüft.
Durchgangspunkte der beladenen Bahn erzwingen keine Halte. Griff, bestätigte
Ablage und Armparkstellung begrenzen getrennte Bewegungen. Gelenk-, Werkzeug-,
Gefäß- und Orientierungsgrenzen stammen aus dem bestehenden synthetischen
CF01-Profil. Die Hüllpunkte werden aus der tatsächlichen Gefäßquelle abgeleitet. Für die dichten Racks wird die
Öffnung derselben Greiferinstanz explizit auf 11,2 mm begrenzt (Gefäßdurchmesser
10,8 mm, Kappendurchmesser 14 mm); eine reale Greifer- oder Passungsqualifikation folgt daraus nicht.

Die Zeitwahl sucht die kürzeste konservativ zulässige **gleichmäßige
Zeitdehnung dieser festgelegten PVA-Referenz** im angegebenen Raster. Sie hebt
keine Grenzen an. Globale Zeitoptimalität über andere Kurven oder lokale
Geschwindigkeitsprofile ist nicht nachgewiesen. „Schnellstmöglich“ darf hier
nur innerhalb dieser eingeschränkten Bahn-/Zeitfamilie gelesen werden.

Andockbewegungen sind geometrische starre Fahrzeugposen mit unabhängigem
Orientierungskanal. Die Drehung endet auf der Gangmitte vor der seitlichen
Annäherung. Ein physisch ausführbarer Lenk-/Antriebsregler ist nicht vorhanden.
Die Abfahrt kehrt dieselbe Posekurve exakt um, einschließlich Orientierung.

Aufbau mit der vorhandenen FreeCAD-Python-Umgebung:

```
python3 scripts/build_tr01_floor_motion.py --backend freecad
<FreeCAD-Python> scripts/build_tr01_workcell_freecad.py
<FreeCAD-Python> scripts/check_tr01_handoffs_freecad.py
python3 scripts/render_tr01_workcell.py <absoluter-Vorschaupfad.html>
```

Der erste Schritt gehört zum bestehenden Fahrprofil. Die ergänzte native
Komposition und Berichte liegen lokal unter `cad/tr01-workcell/` bzw.
`exports/tr01-workcell/`. Die FreeCAD-Umgebung muss wie bei den bestehenden
Adaptern eingerichtet sein. Der Renderer speichert nur eine abgeleitete
Vorschau; das Bewegungsprogramm bleibt im Build-Bericht auflösbar.

Die Fahrzeugprüfung zertifiziert native BRep-Abstände mit konservativen
Intervallhüllen einschließlich voller Abdeckung und Beladung. Die separate
Armprüfung ist eine diskrete native Kollisionsprüfung gegen Nachbargeräte,
Gefäße, andere geparkte Arme und das offen angedockte Fahrzeug. Sie ist kein
kontinuierlicher Selbstkollisions-, Menschen- oder Sicherheitsnachweis.
Die neue Komposition hat bisher keinen eigenen SolidCraft-Aufbau. Die
ursprünglichen CAD-Quellen und deren historische Vergleiche bleiben erhalten;
deren Nachweise werden nicht auf die neue Komposition übertragen.

## Geprüfter Stand am 12. November 2026

Die ergänzte FreeCAD-Welt enthält 974 feste Hinderniskörper. Vier Durchfahrten
und vier Andockkurven bestehen den konservativen Intervallnachweis; die
kleinste zertifizierte Untergrenze liegt bei 15,01 mm. Rückfahrten verwenden
dieselbe geometrische Kurve in umgekehrter Zeitrichtung. Die Durchfahrten
bleiben einschließlich einer 330-mm-Fahrzeughülle außerhalb der reservierten
Arbeitsflächen, auch zwischen den Kurvenknoten.

18 Armbewegungen bestehen die getrennte diskrete native Prüfung mit insgesamt
21.348 Prüfstellungen. Dabei werden die vollständigen Gefäße einschließlich
Kappen und die Nachbargefäße berücksichtigt. Die geschlossene Greiferhülle wird
zusätzlich gegen das eigene mitgeführte Gefäß geprüft: Die Kappe darf nicht
von Fingern oder Greiferkörper durchdrungen werden. Die Greifpunkte liegen
unterhalb der Kappe; DNA verwendet eine angepasste Greiferorientierung.
Die Anzeige der Greiferöffnung bleibt ein schematischer Zustand, kein
qualifizierter Greiferantrieb.

Der Offline-Wiedergabetest durchläuft acht Eigentümerübergaben und 34
Bestätigungsschranken, prüft Belegungssperre, erneute Belegung und den
sprungfreien Gefäßwechsel. JavaScript-FK und gemeinsame Python-FK stimmen
bis auf weniger als 1e-9 mm numerisch überein. Zwei abgeleitete Kameraansichten
wurden offline kontrolliert; eine Browserdarstellung wurde nicht inspiziert.
26 gezielte Python-Tests bestehen; eine optionale JSON-Schema-Prüfung ist
mangels `jsonschema` übersprungen. Die Galerieprüfung besteht. Die vollständige
Offline-Suite wurde nicht erneut ausgeführt. FreeCAD, diskrete Armprüfung,
Browserlogik, Netzwerk und Hardware sind getrennte Nachweiskategorien.

## Automatischer Demomodus und Tageslichtdarstellung

„Demo automatisch“ startet die vollständige Fahrt von vorn und spielt alle
acht Übergaben sowie 34 Bestätigungsschranken ohne einzelne Klicks ab. Die
Freigaben stammen aus einer ausdrücklich synthetischen, vorgegebenen
Anzeigefolge. Es werden keine Sensorantworten behauptet und weder der
Transportaufgabenrunner noch ein Hardware- oder Sicherheitsvertrag verändert.
Kurze Anzeigefenster lassen die Sperrzustände erkennen; sie gehören nicht zu
den geprüften Bewegungszeiten oder zu realen Prozess- und Bestätigungszeiten.

Bench-Umrisse und eine beschriftete Zustandszeile bleiben sichtbar: ungeklärt
oder belegt bedeutet gesperrt; eine freigegebene Übergabe reserviert den Bereich.
Während menschlicher Assistenz ist die Fläche wieder belegt. Eine vom Betrachter
neu gesetzte Belegung beendet den automatischen Demolauf und muss im manuellen
Modus ausdrücklich freigegeben werden. Pause und Fortsetzung sind weiterhin
möglich; nach dem Ende startet ein erneuter Demolauf wieder mit den Sperren.

Die frühere Darstellung verwendete die Theme-Textfarbe als Gerätefarbe und
multiplizierte sie mit einer starken Flächenabdunklung. Materialfarben werden
nun unabhängig von der Textfarbe aus den Theme-Farben abgeleitet und bleiben
auch im dunklen Theme hell. Ein höherer diffuser Umgebungsanteil, ein breiter
Lichtanteil aus Richtung der modellierten Fensterseite und eine korrigierte
Helligkeitsübertragung ergeben eine angenäherte Tageslichtansicht. Moderne
CSS-Farbangaben werden vor der Verwendung in Canvas in RGB umgerechnet.

Diese erste Aufhellung war reine Darstellungsbeleuchtung ohne geworfene
Schatten. Das nachfolgend beschriebene orientierte Tageslichtmodell ergänzt
inzwischen Sonnenstand, Fensterlicht und geometrische Verdeckung. Eine
kalibrierte Untersuchung benötigt weiterhin reale Verglasungs-/Materialdaten
und festgelegte Himmelsbedingungen.

Geometrie, PVA-Kurven und deren native Nachweise bleiben unverändert. Der
Renderer prüft weiterhin die geometrischen Quellen und Artefakte; die zwei
Darstellungsdateien werden mit ihren aktuellen Prüfsummen separat im
`preview-receipt.json` gebunden. Der native Build-Bericht bleibt der historische
Nachweis seines dort gespeicherten Quellstands. Für diese Darstellungsänderung
ist kein erneuter CAD-Aufbau nötig.

### Konturen des Mittelregals

Die mittlere Regal-/Schrankgruppe erhält eine eigene Darstellungsgruppe mit
etwas dunklerem Material, stärkerer Flächenabstufung und höherer Deckkraft.
Ihre Teile werden anhand der vorhandenen semantischen Komponente `IslandShelf`
in der gemeinsamen Raum-/Möblierungsquelle identifiziert. Die übrigen oberen
Wandschränke behalten ihre bisherige Transparenz. Sichtbare Bauteilkanten werden
aus den bestehenden Dreiecken abgeleitet; koplanare Dreiecksdiagonalen werden
unterdrückt. Weder Dreieckskoordinaten noch CAD-Geometrie oder Bewegungsdaten
ändern sich. Ein gezielter Test prüft die unveränderten Dreiecke und die
Abgrenzung zur übrigen oberen Möblierung.

Ein bereitgestellter Google-Maps-Kartenpunkt ist lokal als Standortreferenz
unter `exports/tr01-workcell/site-reference.json` notiert. Der Eigentümer bestätigt, dass der Pin nur das Gebäude markiert; die Lage
des Labors innerhalb dieses Gebäudes ist dadurch noch nicht festgelegt.
Die Fensterfront ist inzwischen als Nordwest bestätigt; der nominale
Richtungsbezug steht in [l01-orientation.md](l01-orientation.md). Ein gemessener
Azimut und die metrische Registrierung bleiben offen.

## Orientiertes Tageslicht und geworfene Schatten

Das neue, getrennte Darstellungsprofil
[model/l01-daylight.render.json](../model/l01-daylight.render.json) referenziert
die bestätigte Nordwestausrichtung und die unveränderte Raumquelle. Die
Voreinstellung ist auf Wunsch des Eigentümers **12. November 2026, 14:00 Uhr
Europe/Berlin in Rostock**. Als Vergleich ist **21. Juni 2026, 18:00 Uhr**
auswählbar. Die Beleuchtung bleibt während eines Durchlaufs beim gewählten
Zeitpunkt; die Wiedergabegeschwindigkeit ändert nicht den Sonnenstand.

`l01_daylight.py` berechnet den geometrischen Sonnenstand mit den
[NOAA-Gleichungen](https://gml.noaa.gov/grad/solcalc/solareqns.PDF), einschließlich
der Umrechnung von CET/CEST nach UTC. Die ENU-Richtung wird mit der bestehenden
Orientierungsreferenz in L01 umgerechnet. Am Novembertermin ergeben sich
ungefähr 210,4° Azimut und 13,6° Höhe: Die Sonne steht hinter den nominal nach
Nordwest gerichteten Fensterflächen. Deshalb werden in dieser Voreinstellung
keine direkten Sonnenstrahlen erfunden. Im Sommervergleich ergeben sich etwa
270,1° und 29,4°; dann ist direkter Einfall durch die Fenster möglich.

Die Fensterlage, Höhe und gekrümmten Fassadensegmente werden aus derselben
Raumquelle abgeleitet. Die Wände und Verglasungen werden zusätzlich ohne
Boxvereinfachung aus dem geprüften nativen L01-Modell tesselliert. Zwei
analytische Öffnungsflächen berücksichtigen die vorhandene Wandtiefe und
verhindern Sonnenlicht durch opake Wandabschnitte, Dach oder innere Türportale.
Die transparente Schnittdarstellung ist keine Öffnung für den Lichttransport.

Das diffuse Fensterlicht wird durch drei flächig verteilte, flächengewichtete
Lichtproben pro Fenster angenähert. Eine konstante Verglasungstransmission,
relative Himmels-/Sonnenstärken, Kamerabelichtung und ein angenäherter
indirekter Anteil stehen ausdrücklich als Annahmen im Profil. Es werden keine
realen Wetter- oder Materialmessungen behauptet.

Zehn gefilterte Tiefenkarten berechnen die Verdeckung: neun für die
Fensterlichtproben und eine für die Sonne. Statische Schattenwerfer werden
zwischengespeichert; Transporter, Abdeckung, Gefäß und Armglieder werden mit
ihren tatsächlich ausgewerteten Posen ergänzt. Obermöbel bleiben optisch als
Schnittansicht transparent, werfen jedoch als opake Möbel Schatten. Die
Verglasung ist kein opaker Schattenwerfer. Die Konturen des Mittelregals bleiben
erhalten. Eine empfängerflächenbezogene Tiefenkorrektur unterdrückt
Selbstverschattungsstreifen beim Filtern auf schräg beleuchteten Flächen.

Die 2D-Ersatzdarstellung ist ausdrücklich **ohne Schattenberechnung** beschriftet.
Der schematische Mensch besitzt weiterhin keinen qualifizierten Volumenkörper
und wird nicht als physikalisch geprüfter Schattenwerfer behandelt.

### Aufbau und Prüfung der Darstellung

Nach einem unveränderten nativen L01-Aufbau wird die genaue Hülle einmal exportiert:

```
<FreeCAD-Python> scripts/export_l01_daylight_shell_freecad.py
python3 scripts/render_tr01_workcell.py <absoluter-Vorschaupfad.html>
python3 -m unittest discover -s tests -p 'test_l01_daylight.py' -v
node tests/check_tr01_daylight_gpu.cjs <absoluter-Vorschaupfad.html>
python3 scripts/check_l01_daylight_gpu.py
```

Der letzte Befehl ist ein zusätzlicher macOS-Offscreen-GPU-Test. Er spielt die
aufgezeichneten WebGL-Zeichenbefehle nativ nach; nur GLSL-Versionskopf,
Präzisionsdeklarationen und die Texturallokation werden für Desktop-OpenGL
angepasst. Vier Shader, zwei Programme, Tiefenpuffer, Szenariowechsel und
bewegte Schattenwerfer werden damit tatsächlich auf der GPU ausgeführt.
Dies ist kein Browserlayout-Test. Die erzeugten Winter-/Sommerbilder wurden
visuell kontrolliert. Ein Kontrolllauf mit `--no-casters` unterdrückt nur die
Schattenwerfer-Zeichenbefehle, sodass die tatsächliche Verdeckungswirkung bei
unveränderter Beleuchtung und Empfängergeometrie verglichen werden kann.

Fünf gezielte Tageslichttests prüfen Zeitzone, Sonnenrichtung, die fehlende
direkte Novembersonne, den Sommervergleich und die aus der Raumquelle
abgeleiteten Fensterproben. Der komplette Autodemolauf und die Bench-Sperren
werden weiterhin separat geprüft. Die Konstruktion und die geprüften
Bewegungskurven bleiben bytegleich; für diese Darstellungsänderung wird keine
neue Roboter- oder Transporterfreigabe behauptet.

Die Schatten sind geometrisch berechnet und visuell plausibel angenähert,
jedoch kein photometrischer Nachweis: Fenstermaße und Fassadenwinkel sind
vorläufig, Verglasung und Himmel nicht gemessen. Nachbargebäude und äußere
Verschattung fehlen; Mehrfachreflexionen werden nicht gelöst. Luxwerte,
Blendung, Sonnenschutzbemessung und reale Beleuchtungsqualifikation bleiben
außerhalb dieses Echtzeitmodells.


## Uhrzeitregler und Kunstlicht

Der Uhrzeitregler verändert die lokale Rostocker Uhrzeit zwischen 00:00 und
24:00 unabhängig von der Bewegungszeit. Das gewählte Datum bleibt erhalten;
Datumwechsel stellen dessen bisherige Voreinstellung wieder her. Sonnenrichtung
und relative Direktstrahlung werden aus denselben NOAA-Gleichungen im
Fünfminutenraster abgeleitet, dazwischen interpoliert und die Richtung normiert.
Azimutübergänge über Nord werden zyklisch interpoliert. Fensterlicht und
indirekter Tageslichtanteil gehen über eine ausdrücklich angenommene Dämmerkurve
zwischen −6° und +10° Sonnenhöhe auf null zurück. Dies ist kein Wettermodell.

Vier angenommene Deckenpaneele werden aus Raumabmessungen und den relativen
Positionen in `model/l01-daylight.render.json` abgeleitet. Ihre Umrisse sind in
der Animation sichtbar. Sie ergänzen vier gerichtete Flächenlichtproben samt
gefilterten Schattenkarten; Möbel und bewegte Gruppen verdecken auch Kunstlicht.
Die Automatik blendet zwischen +10° und −3° Sonnenhöhe ein. Die Auswahl
**Ein / Aus** erlaubt den direkten Vergleich. Positionen, Lichtleistung,
Dämmerkurven und indirekte Aufhellung sind Darstellungsannahmen, keine erfasste
Leuchteninstallation, Lichtplanung oder Luxberechnung. Pro Paneel wird eine
Lichtprobe verwendet; reale Leuchtenoptik und Mehrfachreflexionen bleiben offen.

Datum, Uhrzeit und Kunstlichtauswahl werden als Ansichtsstatus gespeichert.
Regleränderungen halten die Fahrt nicht an und ändern keine Bench-Belegung oder
Freigabe. Die 2D-Ausweichdarstellung berechnet weiterhin keine Beleuchtung oder
Schatten und benennt diese Grenze ausdrücklich.

Geprüft wurden Sonnenstände einschließlich interpolierter Zwischenzeiten gegen
die Python-Auswertung, Tag-/Nachtwechsel, Kunstlichtautomatik sowie Ein/Aus,
Bedienung während des vollständigen Autodemolaufs und unveränderte Bench-Sperren.
Der native Offscreen-GPU-Replay kompiliert die tatsächlichen Shader und rendert
Morgen, Nachmittag, Dämmerung sowie Nacht mit und ohne Kunstlicht. Dies ersetzt
keinen Browser-Layouttest und keine photometrische Messung. CAD und geprüfte
Bewegungsbahnen werden unverändert wiederverwendet.


## Drei Transporter

Die Auswahl **Drei Transporter** startet den separaten, lokal sensorbasierten
Verkehrsfall mit drei verschiedenen Stationszielen und Gegenverkehr.
Ablauf, lokale Rückzugsregel, Bench-Sperren und neue native Nachweise stehen
in [l01-opposing-traffic.md](l01-opposing-traffic.md). Der frühere Geradenfall
bleibt als separater Regressionstest erhalten.
