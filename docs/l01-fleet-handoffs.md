# Drei Transporter mit Be- und Entladen durch stationäre Arme

Die aktuelle Auswahl **Drei Transporter** ergänzt den
[Gegenverkehrsablauf](l01-opposing-traffic.md) um sechs serielle Arm-Übergaben.
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

## Schutzbereiche und Beobachtungen

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

## Gefäße und Bewegungen

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

## Geometrieprüfung und Grenzen

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
