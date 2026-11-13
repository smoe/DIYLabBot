# Unterschiedliche Stationsziele und lokale Gegenverkehrsauflösung

Die aktuelle Auswahl **Drei Transporter** in der L01-Animation spielt drei
parallel gestartete Missionen aus `model/l01-opposing-traffic.demo.json` ab:

| Fahrzeug | Start | Ziel | Anfangsrichtung |
|---|---|---|---|
| TR01 | DNA | CF01 | links nach Norden |
| TR02 | CF01 | NanoDrop/Qubit | links nach Süden, bewusst entgegen dem Umlauf |
| TR03 | NanoDrop/Qubit | DNA | rechts nach Süden |

Die Ziele sind die vorhandenen Gangwartepositionen der Stationen. Docken,
Be-/Entladen oder eine Arbeitsplatzfreigabe gehören nicht zu diesem Verkehrstest.
Alle stationären Arme bleiben geparkt und die Bench-Bereiche durchgehend
belegt/ungeklärt gesperrt. Die ursprüngliche Übergabedemo bleibt separat.

## Lokale Regel ohne Positionsaustausch

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

## Gemeinsame Geometrie, Bewegung und Darstellung

Die Umlaufgeometrie verwendet ausschließlich die aus dem bestehenden
TR01-Fahrprofil abgeleiteten Gangmitten. Kurven verwenden dieselbe portable
`CornerPath`-Operation wie die bisherigen Fahrbahnen. Keine seitliche
Ausweichspur wird in einer Bench-Zone angelegt. Die drei dargestellten Fahrzeuge
sind Instanzen derselben nativen beladenen, abgedeckten TR01-Geometrie.

Der ursprüngliche [Geradenregler](l01-local-traffic.md) stellt weiterhin
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

## Prüfung und reproduzierbarer Einstieg

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
