# Unabhängige Transporter und parallele Arm-Übergaben

Die Standardauswahl **Drei Transporter · parallel** benutzt die neue führende
Komposition `model/l01-independent-fleet.demo.json`. Jedes Fahrzeug besitzt
eine eigene Zustandsfolge: Stationsfreigabe, Beladung, lokale Fahrt, Empfangs-
freigabe und Entladung. Ein Fahrzeug startet nach seiner eigenen Beladung;
eine Zielstation beginnt ihre Übergabe ohne auf die beiden anderen Fahrten
zu warten. Die [serielle Referenz](l01-independent-fleet.md#merged-l01-fleet-handoffs) bleibt mit
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

<a id="merged-l01-local-traffic"></a>

<a id="merged-l01-local-traffic--drei-transporter-mit-lokaler-hinderniserkennung"></a>

## Drei Transporter mit lokaler Hinderniserkennung

`model/l01-local-traffic.demo.json` definiert einen separaten synthetischen
Verkehrsvorläufer auf einer Geraden, ausgeführt von
`python3 scripts/l01_local_traffic.py`. Die aktuelle Auswahl **Drei Transporter**
verwendet inzwischen den [Gegenverkehrsablauf](l01-independent-fleet.md#merged-l01-opposing-traffic) mit
unterschiedlichen Stationszielen und lokalem Rückzug. Der hier dokumentierte
Geradenfall bleibt als unabhängiger Regressionstest erhalten.

<a id="merged-l01-local-traffic--ursprünglicher-geradenfall"></a>

### Ursprünglicher Geradenfall

TR01, TR02 und TR03 fahren gleichzeitig auf der linken Gangmitte von
DNA/TapeStation Richtung CF01. Eine Person kommt seitlich in den Gang, bleibt
vorübergehend dort und verlässt ihn wieder. Das vordere Fahrzeug bremst, die
folgenden erkennen Hindernisse unabhängig davon und warten beziehungsweise
bremsen ebenfalls. Nach frischen freien Beobachtungen fahren sie erneut an.
Die Endpositionen sind getrennte Haltepunkte auf dem Gang, keine drei neuen
Andockplätze. Die Arme bleiben geparkt; sämtliche Bench-Bereiche bleiben
sichtbar gesperrt. Niemand wird durch Signalton oder seitliches Ausweichen
vom Arbeitsplatz verdrängt.

<a id="merged-l01-local-traffic--wissensgrenze-und-reaktion"></a>

### Wissensgrenze und Reaktion

Nur `SensorWorld` und der unabhängige Abstandsauditor besitzen Weltpositionen.
Jeder `LocalController` bekommt ausschließlich seine eigene Position,
Geschwindigkeit, Beschleunigung, sein eigenes Ziel und anonyme lokale
Erstrücklaufpunkte samt Erfassungszeit. Andere Fahrzeug-IDs, globale Positionen,
Geschwindigkeiten, Pläne oder Stationszustände werden nicht an ihn übergeben.
Die Welt aktualisiert alle Sensoren aus demselben Zeitschritt vor den
Reglerentscheidungen, ohne Vorrang durch Auswertungsreihenfolge.

Die Sensorannahme ist ein idealer horizontaler Rundumscan mit 2° Raster,
2,2 m Reichweite, 100 ms Abtastung und 100 ms Verzögerung. Der erste Treffer
verdeckt dahinterliegende Objekte. Vereinfachte opake Bench-Grundflächen,
konservative Fahrzeugkreise und ein Personenradius von 250 mm werden verwendet.
Dies ist keine ausgewählte oder qualifizierte LiDAR-/Personenschutzinstallation.

Der Regler berücksichtigt eigene ruckbegrenzte Bremsstrecke und Bremsdauer,
Scanzyklus und Verzögerung, einen angenommenen maximalen Hindernisannäherungswert
von 200 mm/s sowie Reichweitenfehler und Winkelraster. Dieser niedrige
Annäherungswert gehört zum langsamen Demonstrationsfall; er begrenzt keine
reale Person und belegt keinen Schutz gegen beliebige Gehgeschwindigkeiten
oder plötzliches Hervortreten aus Verdeckungen. Bei fehlenden oder veralteten
Scans wird gebremst. Wiederanfahren verlangt mindestens 0,5 s frische freie
Beobachtungen und Freiraum für die nächste Fahrt einschließlich Bremsreserve.
Damit erzeugt eine stehende Person kein periodisches Vorrücken.

Die Beispielsollgeschwindigkeit beträgt 100 mm/s. Beschleunigung und Ruck
bleiben mit einer numerischen Reserve von 2 % unter den unveränderten
TR01-Quellgrenzen. Beschleunigungsfahrten verwenden die gemeinsame
Rest-zu-Rest-PVA-Mathematik, Schutzbremsungen analytische C2-S-Kurven aus dem
aktuellen Geschwindigkeits- und Beschleunigungszustand. Bremsen und Warten
haben konkrete Beobachtungsgründe; Stationsmarken verursachen keine zusätzlichen
Halte. Maximale Geschwindigkeit, Beschleunigung und Ruck werden aus den
Polynomextrema der exportierten Kurven einschließlich Segmentgrenzen geprüft.
Die Animation wertet genau diese Kurven aus. Keine globale Zeitoptimalität,
biologische Qualifikation oder reale Antriebsdynamik wird nachgewiesen.

<a id="merged-l01-local-traffic--nachweise-und-grenzen"></a>

### Nachweise und Grenzen

Die Fahrt nutzt ausschließlich bereits nativ geprüfte geradlinige Posen mit
X = 1625 mm und Richtung +Y zwischen Y = 1200 und 5250 mm. Der Generator prüft
Quell- und Artefaktpins und die lückenlose räumliche Abdeckung durch die
bestehenden konstanten PVA-Segmente. Fahrzeug, Abdeckung, Ladung und geparkte
Arme bleiben dieselben. Diese Identitätsprüfung verwendet den bisherigen
nativen Geometrienachweis; sie ist kein neuer CAD-Aufbau.

Für dynamische Abstände prüft ein separater Auditor konservative umschließende
Kreise. Eine Bewegungsobergrenze für das gesamte Abtastintervall wird von den
Abständen abgezogen. Der resultierende untere Abstand muss die konfigurierte
Reserve einhalten. Die Reserven und Bedingungen gelten für diesen definierten
synthetischen Lauf, nicht für beliebige Menschenbewegungen.

`tests/test_l01_local_traffic.py` prüft Abschluss und gleichzeitige Bewegung
aller drei Fahrzeuge, Personen- und Fahrzeugabstände, Polynomgrenzen,
Erstrücklaufverdeckung ohne Identitätsweitergabe, Scanausfall und zwei
gegengerichtete lokale Regler. Im Gegenverkehrstest bleiben beide stehen;
Rückwärtsfahrt, Überholen und allgemeine Auflösung solcher Blockaden sind
nicht implementiert. Der Browserplayer prüft vollständiges automatisches
Abspielen und erhaltene Bench-Sperren. Der native Offscreen-GPU-Replay rendert
alle drei Instanzen und ihre Schatten; er ersetzt keinen Browser-Layouttest.

Die Ergebnisdatei `exports/tr01-workcell/local-traffic.json` und die
Vorschaubescheinigung enthalten Quellbezüge, Kurven, anonyme Beobachtungskennwerte,
Stoppgründe und Prüfgrenzen. Das sind ignorierte Simulationsausgaben, kein
Ausführungsjournal, Hardware- oder Sicherheitsnachweis. Bei einer realen
Umsetzung wären Sensorabdeckung, Latenz, Bremsvermögen, Traglast, Retention,
Personenschutz und Wiederanlaufbedingungen gesondert nachzuweisen.

<a id="merged-l01-opposing-traffic"></a>

<a id="merged-l01-opposing-traffic--unterschiedliche-stationsziele-und-lokale-gegenverkehrsauflösung"></a>

## Unterschiedliche Stationsziele und lokale Gegenverkehrsauflösung

Die aktuelle Auswahl **Drei Transporter** in der L01-Animation spielt drei
parallel gestartete Missionen aus `model/l01-opposing-traffic.demo.json` ab:

| Fahrzeug | Start | Ziel | Anfangsrichtung |
|---|---|---|---|
| TR01 | DNA | CF01 | links nach Norden |
| TR02 | CF01 | NanoDrop/Qubit | links nach Süden, bewusst entgegen dem Umlauf |
| TR03 | NanoDrop/Qubit | DNA | rechts nach Süden |

Die aktuelle Animation bettet diese Fahrt inzwischen in die
[Be- und Entladephasen der Flotte](l01-independent-fleet.md#merged-l01-fleet-handoffs) ein. Der hier
beschriebene Verkehrsfall bleibt deren unveränderter Bewegungskern.

Die Ziele sind die vorhandenen Gangwartepositionen der Stationen. Docken,
Be-/Entladen oder eine Arbeitsplatzfreigabe gehören nicht zu diesem Verkehrstest.
Alle stationären Arme bleiben geparkt und die Bench-Bereiche durchgehend
belegt/ungeklärt gesperrt. Die ursprüngliche Übergabedemo bleibt separat.

<a id="merged-l01-opposing-traffic--lokale-regel-ohne-positionsaustausch"></a>

### Lokale Regel ohne Positionsaustausch

`MissionController` erhält nur den eigenen Auftrag, die statische Karte mit
Gangmitten und Stationen, die eigene Lokalisation sowie verzögerte anonyme
Rundum-Abstandsscans. Andere Fahrzeugpositionen, Kennungen, Fahrtrichtungen und
Aufträge werden weder ausgetauscht noch vom Weltmodell an den Regler übergeben.
Fahrzeugkennungen in Animation und Prüfprotokoll sind Beobachterinformationen.

Die bekannte Umlaufregel lautet: linker Gang nordwärts, hinterer Gang ostwärts,
rechter Gang südwärts, vorderer Gang westwärts. Eine erkannte Blockierung löst
zuerst eine ruckbegrenzte Bremsung aus. Nach anhaltender **frischer**
Blockierungsbeobachtung wählt allein das Fahrzeug entgegen der Umlaufrichtung
die Alternative: Es fährt nach bestätigtem Freiraum entlang des eigenen Weges
zurück zum hinteren Gangknoten und weiter über den anderen Gang. Das regelkonform
fahrende Fahrzeug wartet, bis seine eigenen Scans eine Weiterfahrt erlauben.
Es erhält keine erfundene Freigabe vom anderen Fahrzeug.

Im definierten Lauf begegnen sich TR01 und TR02 im linken Gang. TR02 hält an,
prüft den zurückliegenden Weg mit demselben Rundumscan und fährt nach Norden
zurück; es umfährt über den hinteren Gang zur rechten Seite. TR01 kann danach
CF01 erreichen. TR03 wartet zusätzlich vor der im rechten Gang stehenden Person
und fährt erst nach deren tatsächlichem Verschwinden aus seinen Beobachtungen
weiter Richtung DNA. Alle drei Missionen werden abgeschlossen.

Ein Zeitwert ist nur die Mindestdauer einer weiterhin frischen Blockierung
beziehungsweise freier Beobachtungen. Er behauptet nicht, dass der Weg frei
geworden sei. Ein rückwärtiges Hindernis oder alte/fehlende Scans sperren den
Rückzug. Allgemeine Vollständigkeit für beliebige Fahrzeugzahlen, ausgefallene
Fahrzeuge, beidseitig versperrte Gangknoten oder beliebige Personenbewegungen
wird nicht behauptet; dann bleibt ein Schutzstopp möglich.

<a id="merged-l01-opposing-traffic--gemeinsame-geometrie-bewegung-und-darstellung"></a>

### Gemeinsame Geometrie, Bewegung und Darstellung

Die Umlaufgeometrie verwendet ausschließlich die aus dem bestehenden
TR01-Fahrprofil abgeleiteten Gangmitten. Kurven verwenden dieselbe portable
`CornerPath`-Operation wie die bisherigen Fahrbahnen. Keine seitliche
Ausweichspur wird in einer Bench-Zone angelegt. Die drei dargestellten Fahrzeuge
sind Instanzen derselben nativen beladenen, abgedeckten TR01-Geometrie.

Der ursprüngliche [Geradenregler](l01-independent-fleet.md#merged-l01-local-traffic) stellt weiterhin
Scanalter-Prüfung, Bremsreserve, frische Freigabebeobachtungen und analytische
C2-Schutzbremsung bereit. Der neue Regler projiziert ausschließlich aus eigenen
Scanpunkten und eigener Lokalisation rekonstruierte Punkte auf seine bekannte
Route. Die Richtung des eigenen Fahrwegs bestimmt, welche Punkte relevant sind;
auch der Rückzug benötigt freie Beobachtungen.

Fahrzeiten werden gemeinsam gleichmäßig gedehnt, bis die unveränderten
linearen, Winkel- und Ladungspunktgrenzen aus dem TR01-Profil für sämtliche
exportierten PVA-Kurven eingehalten sind. Der größte berechnete Grenzquotient
bestimmt die Dehnung im 0,001-Raster mit 0,2 % numerischer Reserve. Im aktuellen
Lauf beträgt der Faktor 2,677344 und die Gesamtdauer rund 300 s. Das ist die
zulässige gleichmäßige Zeitwahl dieser Kurvenfamilie, keine global optimale
Mehrfahrzeugplanung. Sensorperiode, Verzögerung, Beobachtungszeiten und
Hindernisgeschwindigkeitsannahme gehören zum selben synthetischen Zeitmaßstab;
die effektiven Werte stehen im Ergebnis. Die Nominalwerte nicht als geprüfte
Hardwarelatenzen ausgeben.

Die Animation wertet die exportierten vollständigen PVA-Kurven aus. Es gibt
keinen Halt an einem Gangknoten allein wegen eines Wegpunkts. Schutzstopps und
das Erreichen der eigenen Stationswarteposition sind getrennte Zustände.
Tageszeit, Kunstlicht, Pause und Vorschau bleiben verfügbar; ein gespeicherter
Ansichtsstand eines anderen Verkehrsformats wird nicht übernommen.

<a id="merged-l01-opposing-traffic--prüfung-und-reproduzierbarer-einstieg"></a>

### Prüfung und reproduzierbarer Einstieg

1. `python3 scripts/l01_opposing_traffic.py` erzeugt
   `exports/tr01-workcell/opposing-traffic.json`.
2. `scripts/check_l01_opposing_traffic_freecad.py` läuft mit dem vorhandenen
   FreeCAD-Python und dessen Bibliotheksumgebung. Es öffnet ausschließlich die
   gepinnten vorhandenen Fahrzeug- und Workcell-Dateien und schreibt
   `opposing-native-clearance.json`.
3. `python3 scripts/render_tr01_workcell.py <Vorschaupfad>` verlangt aktuelle
   Quellenpins, vollständige Missionen, freie Bench-Hüllen und den passenden
   bestandenen nativen Prüfbericht, bevor die Vorschau erzeugt wird.

Die native Prüfung berücksichtigt das vollständige Fahrzeug einschließlich
Ladung und Abdeckung sowie 974 feste Workcell-Körper bei geparkten Armen.
Der frühere Geradennachweis wird nicht auf die neuen Kurven übertragen.
Für effiziente native Abfragen wird eine gröbere PVA-Referenz ausschließlich
im Prüfer verwendet. Die maximale starre Abweichung zu **jedem** ursprünglichen
Polynomintervall wird über die Extrema der Differenzpolynome begrenzt und zur
geforderten nativen Freigängigkeit addiert. Die ursprünglichen Kurven bleiben
für Dynamik und Darstellung unverändert. Im aktuellen Nachweis liegen diese
Rekonstruktionsgrenzen unter 0,87 mm. Die konservative native Mindestfreigängigkeit
der ursprünglichen Kurven beträgt mindestens etwa 39,5 mm bei geforderten 15 mm.
Ein bloßes Ausdünnen oder Stichprobenvergleich würde dafür nicht ausreichen.

Ein unabhängiger Auditor prüft Fahrzeug/Fahrzeug, Fahrzeug/Person und die
virtuellen gesperrten Bench-Rechtecke über konservative umschließende
Fahrzeugkreise. Von den Abständen wird eine Bewegungsobergrenze für das gesamte
Abtastintervall abgezogen. Im definierten Lauf bleiben so über 415 mm zwischen
Fahrzeugen, über 229 mm zur Person und über 41 mm außerhalb der Bench-Zonen.
Diese Grenzen gelten für den definierten synthetischen Ablauf, nicht für einen
realen Sensor, Bremsantrieb oder Mensch-Maschine-Schutzkreis.

`tests/test_l01_opposing_traffic.py` prüft drei unterschiedliche abgeschlossene
Stationsmissionen, tatsächlichen gleichzeitigen Gegenverkehr, die lokale
Rückzugsentscheidung, gesperrten Rückweg, Scanausfall, Polynomgrenzen,
Bench-Abstände und die native Referenzfehlergrenze. Der vollständige
Browserplayerlauf wird offline geprüft; ein nativer GPU-Replay rendert
Begegnung, Rückzug und Weiterfahrt einschließlich Schatten. Das ersetzt keinen
Browser-Layouttest. Neue SolidCraft-, ROS-, Gazebo- oder Hardwareausführung wird
mit diesem Verkehrstest nicht erzeugt oder nachgewiesen. Die vorhandenen CAD-
Konstruktionen bleiben unverändert.

<a id="merged-l01-fleet-handoffs"></a>

<a id="merged-l01-fleet-handoffs--drei-transporter-mit-be--und-entladen-durch-stationäre-arme"></a>

## Drei Transporter mit Be- und Entladen durch stationäre Arme

Die aktuelle Standardauswahl ist der
[unabhängige Ablauf mit parallelen Übergaben](l01-independent-fleet.md).
Dieser Text beschreibt die erhaltene serielle Referenz.

Die serielle Referenz (**`--fleet-mode serial`**) ergänzt den
[Gegenverkehrsablauf](l01-independent-fleet.md#merged-l01-opposing-traffic) um sechs serielle Arm-Übergaben.
Die führende Quelle `model/l01-fleet-handoffs.demo.json` referenziert den
bestehenden Verkehrsfall und `model/tr01-l01-workcell.protocol.json`. Es werden
keine Arm-, Fahrzeug- oder Stationsgeometrien kopiert oder neu positioniert.

| Fahrzeug | Beladung | Gemeinsame Fahrt | Entladung |
|---|---|---|---|
| TR01 | DNA, ArmDNA | DNA → CF01 | CF01, ArmC |
| TR02 | CF01, ArmC | Gegenverkehr, lokaler Rückzug, Umfahrung → NanoDrop/Qubit | NanoDrop/Qubit, ArmA |
| TR03 | NanoDrop/Qubit, ArmA | NanoDrop/Qubit → DNA | DNA, ArmDNA |

Zuerst wird jedes Fahrzeug beladen. Danach fahren alle drei mit abgedeckter
Ladung gleichzeitig. Die bisherige lokale Gegenverkehrsauflösung und die
Personenbeobachtungen laufen unverändert. Nach der Ankunft werden die Fahrzeuge
an ihren jeweiligen Zielen entladen und kehren zur Gangwarteposition zurück.
Die Übergaben sind absichtlich seriell: Es bewegt sich ein stationärer Arm,
während die beiden anderen Fahrzeuge an ihren geprüften Gangpositionen warten.
Das ist kein Nachweis für beliebige gleichzeitig bewegte Arme und Fahrzeuge.

<a id="merged-l01-fleet-handoffs--schutzbereiche-und-beobachtungen"></a>

### Schutzbereiche und Beobachtungen

Vor jeder Andockfahrt bleibt das Fahrzeug zunächst an der Gangmitte. Eine
benannte synthetische Beobachtung bestätigt erst das Verlassen des
Arbeitsbereichs durch die Person und reserviert den Bereich exklusiv für dieses
Fahrzeug. Andere Transporter und Personen erhalten damit keine allgemeine
Durchfahrfreigabe. Die Bench-Markierung bleibt sichtbar gesperrt; der Status
benennt die exklusive Übergabe. Nach dem Verlassen wird die Freigabe ausdrücklich
widerrufen und der Bereich wieder als belegt/ungeklärt gesperrt geführt.

Abdeckung abgenommen und Armbereich frei, Griff/Identität, Ablage/Übernahme sowie
Armparkstellung/gesicherte Abdeckung/freie Abfahrt sind eigene benannte
Beobachtungen. Die Wartephase enthält jeweils den Zustand **vor** der
Beobachtung. Erst ihr ausdrücklich als `synthetic_demo_fixture` gekennzeichnetes
Ereignis ändert Besitz, Abdeckung oder Freigabe. Die Verfügbarkeit dieser
positiven Testereignisse ist vorgegeben; eine Sekunde ist synthetische Testzeit,
keine reale Bearbeitungsfrist. Ein Timer erzeugt keine Hardwarequittung.

Eine neu markierte Arbeitsplatzbelegung stoppt die Vorschau und macht ihre
Freigabe ungültig. Auch das anschließende Wegnehmen des Häkchens startet keine
Bewegung. Erst **Synthetisch: Arbeitsplatzfreigabe erneuern** erlaubt die
Fortsetzung. Der Sperrzustand bleibt beim Wiederherstellen der Ansicht erhalten.
Das ist eine Schutzreaktion der Visualisierung, keine qualifizierte physische
Arm- oder Transporterbremsung. Der normale Autodemolauf braucht keine einzelnen
Benutzerbestätigungen; er verwendet ausdrücklich die positiven Testereignisse.

<a id="merged-l01-fleet-handoffs--gefäße-und-bewegungen"></a>

### Gefäße und Bewegungen

Drei verschiedene illustrative Gefäß-IDs werden aus der Quelle geführt.
Jedes besitzt genau einen Eigentümer: seinen ursprünglichen Bench-Platz,
einen Arm, den zugehörigen Transporter oder den Zielplatz. Starre Anheftungen
werden bei jedem Griff- und Ablageereignis poseerhaltend umgerechnet. Ein
unbestätigter Griff bleibt beim bisherigen Eigentümer, eine unbestätigte Ablage
beim Arm. Die übrigen 47 modellierten Gefäße je Fahrzeug sind unveränderte
Darstellungshüllen, keine zusätzlich ausgeführten Probenübergaben.

Die vorhandenen Andockkurven und sechsachsigen Lade-/Entladekurven werden direkt
referenziert. Bei der Rückfahrt wird dieselbe Andockgeometrie zeitlich rückwärts
ausgewertet. Ein konstanter ganzzahliger 2π-Offset hält den Winkelkanal am
Übergang zur Verkehrsroute kontinuierlich. Geschwindigkeit, Beschleunigung,
Ruck und vorhandene Kein-Halt-/FK-Prüfungen der Bewegungsquellen bleiben erhalten.
Die Wartebedingungen befinden sich zwischen den Bewegungen, nicht als neue
Zwischenstopps innerhalb der beladenen Transportkurven. Grenzen werden zur
Verkürzung der Vorführung nicht angehoben. Es gibt keinen neuen globalen
Zeitoptimalitätsnachweis.

Der Gesamtfall enthält 68 Phasen, 36 synthetische Beobachtungen und rund 4015 s
Modellzeit. Die vorhandene Wiedergabegeschwindigkeit verkürzt nur die Darstellung.
**Auto** zeigt bei Übergaben den aktiven Arm näher und während der gemeinsamen
Fahrt den Raum. Tageszeit und Kunstlicht bleiben unabhängig davon bedienbar.

<a id="merged-l01-fleet-handoffs--geometrieprüfung-und-grenzen"></a>

### Geometrieprüfung und Grenzen

Die ursprünglichen nativen Andock-/Raum- sowie Armprüfberichte werden über ihre
Artefakt- und Quellenpins aufgelöst. Der bestehende Armnachweis gegenüber den
ursprünglichen festen Workcell-Körpern ist ausdrücklich **diskret**. Er wird
nicht als kontinuierlicher vollständiger Arm-Kollisionsnachweis umgedeutet.

Der neue FreeCAD-Prüfer `check_l01_fleet_handoffs_freecad.py` ergänzt 30 Prüfungen
für die zusätzlichen wartenden Fahrzeuge und die zusätzlich sichtbaren
Bench-Gefäße. Für Andockfahrten begrenzen die vollständigen PVA-Translationsextrema
und der orientierungsunabhängige Radius den gesamten bewegten Fahrzeugkörper.
Für die Arme wird eine konservative Gesamthülle aus aufeinanderfolgenden
Gelenkankerdistanzen und nativen Glied-/Werkzeugboxen abgeleitet; das angeheftete
verschlossene Gefäß ist eingeschlossen. Die Hülle gilt für sämtliche Gelenkwinkel
und damit auch zwischen den Kurvenknoten. Zwei andere Fahrzeuge bleiben dabei
stationär. Diese zusätzliche Hüllprüfung findet im aktuellen Fall mindestens
39,4 mm Abstand bei geforderten 15 mm. Sie verwendet keine positiven
Stichproben als Ersatz für die Hüllgrenze.

Der bestehende native Gegenverkehrsnachweis bleibt unverändert gültig, weil
vor der gemeinsamen Fahrt alle Arme wieder dieselben Parkstellungen und alle
Fahrzeuge dieselben Startposen, Abdeckungen und Lastgeometrien besitzen.
Die ursprüngliche Verkehrsroute und deren lokale Regel werden nicht verändert.

`python3 scripts/l01_fleet_handoffs.py` erzeugt den abgeleiteten Zeitplan unter
`exports/tr01-workcell/`. Der FreeCAD-Prüfer bindet seinen Nachweis an dessen
kanonische Prüfsumme. `render_tr01_workcell.py` verlangt den passenden bestandenen
Nachweis und bindet Quelle, Adapter und Vorschau in der Vorschaubescheinigung.
Es gibt keine neue native Konstruktion; SolidCraft-, ROS-, Netzwerk- und
Hardwareausführung werden hier nicht ergänzt.

Tests prüfen alle sechs Übergaben, exklusive Bench-Reservierungen, geparkte
Arme während der gemeinsamen Fahrt, Eigentümer-/Posekontinuität, Beobachtung vor
Wirkung und die neuen Geometriepins. Der Offline-Player prüft den vollständigen
Autolauf ohne Einzelbestätigungen, den manuellen Belegungswechsel und den
expliziten Wiederanlauf. Der native Offscreen-GPU-Replay rendert alle sechs
Armübergaben einschließlich aller drei Fahrzeuge und ihrer Schatten. Er ist
kein Browser-Layouttest. Dieser Fall bleibt eine synthetische Darstellung,
kein Probeninventar, Ausführungsjournal oder realer Mensch-Maschine-Schutzkreis.
