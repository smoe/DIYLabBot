# Unabhängige Transporter und parallele Arm-Übergaben

Die Standardauswahl **Drei Transporter · parallel** benutzt die neue führende
Komposition `model/l01-independent-fleet.demo.json`. Jedes Fahrzeug besitzt
eine eigene Zustandsfolge: Stationsfreigabe, Beladung, lokale Fahrt, Empfangs-
freigabe und Entladung. Ein Fahrzeug startet nach seiner eigenen Beladung;
eine Zielstation beginnt ihre Übergabe ohne auf die beiden anderen Fahrten
zu warten. Die [serielle Referenz](l01-fleet-handoffs.md) bleibt mit
`--fleet-mode serial` verfügbar.

Die ursprünglichen Arm-, Andockkurven, Geometrien, Gelenk- und Gefäßgrenzen
werden referenziert. Die neue Komposition ersetzt ausdrücklich die bisherige
Einfahrtbedingung `all_stationary_arms_parked`: Stattdessen müssen exklusive
Stations-/Armressourcen, getrennte geprüfte Bewegungshüllen, freie beobachtete
Anhaltehüllen und ein aktueller gekoppelter Nachweis vorliegen. Die übrigen
Einfahrtbedingungen bleiben bestehen. Es gibt keine neue Konstruktion und
keine angehobenen Bewegungsgrenzen. Nicht beteiligte Arme bleiben geparkt.

## Stationen und lokale Fahrt

Die Stationen vergeben ihre Ressourcen exklusiv. Sie beobachten anonyme
physische Hindernis- und Anhaltehüllen; die Transporter erhalten keine fremden
Positionen, Kennungen oder Bewegungsabsichten. Die vorhandenen
`MissionController` und `RangeWorld` bleiben die einzigen Fahrregler bzw.
Scanmodelle. Neue Fahrkurven werden mit ihnen simuliert. Der bestehende lokale
Rückzug bei Gegenverkehr und die Umfahrung über den anderen Gang bleiben aktiv.

Für Stationseintritte wird die unvermeidbare Bewegung während Reaktion und
ruckbegrenzter Bremsung eingegrenzt. Ringfortschritt wird nicht als exakte
Bogenlänge behandelt: Ein oberer Ableitungsfaktor aus den Bezier-Kontrollpunkten
begrenzt seine Umrechnung in kartesischen Weg. Eine aktive Station erscheint
im synthetischen Scan als konservativer undurchsichtiger Workspace-Proxy;
das ist eine Modellannahme, kein qualifizierter realer Sensor.

Arbeitsplätze mit Belegung oder unbekanntem Zustand bleiben gesperrt. Der
Beispiellauf enthält eine anfängliche CF01-Belegung und eine ausdrücklich
vorgegebene synthetische Person-frei-Beobachtung bei 300 s. Zeitablauf allein
ist keine Freigabe; ohne positives Ereignis beginnt die Übergabe nicht.
Eine neue negative Quellbeobachtung während eines laufenden Stationsauftrags
bricht die Programmerzeugung ab. Eine neue Stopp-/Fortsetzungsbahn wird dadurch
nicht behauptet.

Eine interaktiv markierte neue Belegung friert die gesamte **Vorschau** ein.
Abspielen, Zeitachse, Neustart, Stationswechsel und eine ältere gespeicherte
Ansicht können diese Sperre nicht aufheben. Erst eine explizite erneute
synthetische Freigabe erlaubt die Fortsetzung. Das ist keine qualifizierte
physische Notbremsung. Eine nur lokal angehaltene Zeitachse eines Fahrzeugs
würde die gemeinsam geprüften Begegnungen verändern und wird nicht als sicher
ausgeführt. Der normale positive Autolauf benötigt keine Einzelbestätigungen.

## Nachweise

`build_l01_independent_workspaces_freecad.py` leitet aus den nativen Glied-,
Werkzeug-, Gefäß- und Fahrzeugkörpern sechs Stationshüllen ab. FK-Mittelpunkte
werden für das ganze jeweilige Zeitintervall um eine konservative
Geschwindigkeitsgrenze aufgeweitet: analytische PVA-Gelenkgeschwindigkeiten,
Ankerabstände und native Boxen liefern eine Ganzkörper-Radiusgrenze. Der gesamte
mögliche Fingerhub zwischen geschlossen und offen wird zusätzlich eingeschlossen.
Die Andockhüllen verwenden vollständige PVA-Translationsextrema und einen
orientierungsunabhängigen Fahrzeugradius. Positive Stichproben ersetzen diese
Intervallgrenzen nicht.

`check_l01_independent_fleet_freecad.py` prüft die drei neuen vollständigen
Fahrzeugkurven gegen die 974 festen nativen Körper. Weitere Intervallprüfungen
umfassen Fahrzeug/Fahrzeug, Fahrzeug/Person, Fahrzeug/aktive fremde Station,
parallele Stationshüllen und die Bench-Zonen während der Gangfahrt. Eigene
Andockfahrten benötigen die exklusive aktuelle Freigabe. Der ursprüngliche
Armnachweis gegenüber festen Workcell-Körpern bleibt ausdrücklich **diskret**;
er wird nicht in einen kontinuierlichen vollständigen Armnachweis umgedeutet.

Nach dem Export werden PVA-Grenzen und das Kein-Halt-Kriterium innerhalb jeder
zusammenhängenden Fahrepisode erneut ausgewertet. Notwendige lokale Schutz-,
Beobachtungs- und Ankunftshalte werden getrennt geführt. Nur bei ruhenden
Anschlussposen werden Unterschiede bis 64 Gleitkomma-ULP vereinheitlicht;
bewegte Anschlüsse und reale Ortsänderungen bleiben unverändert.

Die 4399 zusätzlichen Intervallprüfungen bestehen mit mindestens 16,11 mm
Abstand; die drei vollständigen nativen Fahrzeugprüfungen halten die geforderten
15 mm ein.

Der geprüfte Fall enthält alle sechs Übergaben, bis zu drei gleichzeitig
bewegte Arme sowie Fahrten während anderer Arm-Übergaben. TR02 führt den lokalen
Rückzug mit anschließender Umfahrung aus. Die Modellzeit beträgt rund 1742,3 s
gegenüber 4015,2 s für die serielle Referenz. Die Wiedergabegeschwindigkeit
verändert nur die Anzeige. Globale Zeitoptimalität oder allgemeine
Deadlock-Freiheit sind nicht nachgewiesen. Ein gemessener menschlicher
Vergleichswert fehlt; das Akzeptanzziel „schneller als manuell“ bleibt offen.
Der Fahrzeug-Zeitfaktor 2,68 ergibt sich aus den unveränderten Grenzen der
exportierten gekrümmten Fahrt einschließlich Drehung und getragenem Gefäß;
er ist keine zusätzliche Vorführpause. Die referenzierten Armprofile werden
in dieser Änderung nicht zeitlich umgeplant.

## Aufbau und Wiedergabe

Voraussetzung sind die ursprünglichen bytegebundenen Workcell-, Arm- und
Gegenverkehrsnachweise. In deren unverändertem, quellenäquivalentem Build-Kontext:

```sh
<FreeCAD-Python> scripts/build_l01_independent_workspaces_freecad.py
python3 scripts/l01_independent_fleet.py
<FreeCAD-Python> scripts/check_l01_independent_fleet_freecad.py
python3 scripts/render_tr01_workcell.py <absoluter-Vorschaupfad.html>
node tests/check_tr01_workcell_player.cjs <absoluter-Vorschaupfad.html>
```

Die vorhandene FreeCAD-Umgebung wird wie bei den übrigen Adaptern eingerichtet.
Berichte, Programm, Workspace-Hüllen und Vorschau-Belege liegen lokal unter
`exports/tr01-workcell/`. Historische CAD-Dateien und Nachweise werden nicht
umgeschrieben. Der Renderer kann einen geprüften Projekt-Worktree explizit
verwenden, ohne dessen ursprüngliche CAD-Indexbindungen umzuschreiben:

```sh
python3 scripts/render_tr01_workcell.py <absoluter-Vorschaupfad.html> \
  --native-context exports/worktrees/independent-fleet
```

Dabei müssen führende Geometriequellen und Präsentationscode mit dem aktuellen
Checkout übereinstimmen; der delegierte Build prüft die originalen Artefaktpins.
Die Vorlage enthält weiterhin Tageszeitregler, Kunstlicht und Schatten.
Aktiv bewegte Arme werden zur Übersicht farblich hervorgehoben.

Python-Tests prüfen unabhängige Starts, echte überlappende Arm-/Fahrintervalle,
Beobachtung vor Freigabe, unveränderte PVA-Grenzen, exklusive Ressourcen,
Gefäß-/Andockkontinuität, Gegenverkehr und den vollständigen nativen Nachweis.
Der Offline-Player prüft Autolauf, Parallelzustände und Belegungs-Interlocks.
Native Offscreen-GPU-Bilder zeigen alle sechs Übergaben, drei gleichzeitig
bewegte Arme und die Überlagerung von Fahrt und Arm-Übergabe. Das ersetzt keinen
Browser-Layouttest, keine biologische oder mechanische Qualifikation und
keinen Hardware-/Netzwerk-/Mensch-Maschine-Sicherheitsnachweis.
