# Wasserübung in L01

`model/water-practice-l01.motion.json` bindet die separate Wasserübung an die
vorhandene L01-Aufstellung. A nutzt ArmDNA, B ArmC und C ArmA. Die Arme erhalten
für diesen Darstellungsmodus vormontierte Konzeptpipetten aus
`analytics-tools.shared.json`; die sechs offenen Gefäße referenzieren dessen
vorhandene `workpiece`-Operation. Werkzeug- und Spitzenwechsel sind nicht
implementiert. Die Aufstellung ist ein geometrisch geprüfter Übungsvorschlag,
keine Änderung der E4-Pilotbindung. Die räumliche Projektion der drei
logischen Wege ist kein Laufzeit-Ortsbeleg und verlegt keine Gefäße im
ursprünglichen Fixture-Inventar. Die SYN-Gefäßkennungen bleiben gebunden.

Der Compiler verwendet die gemeinsame PVA-/FK-Mathematik. Zwischen Aufnahme und
Abgabe verläuft jeder beladene Transfer durchgehend; nur Aufnahme und Abgabe
haben begründete Dosierhalte. Leerbewegungen besitzen ein eigenes Profil.
Gelenkextrema und konservative numerische FK-Intervallgrenzen umfassen das
gesamte Werkzeug und den darin getragenen Wasserbereich. Die angegebenen
Grenzen sind synthetische Darstellungsannahmen. Mechanische Eignung, Dosierung,
globale Zeitoptimalität und der Geschwindigkeitsvergleich mit einem Menschen
sind nicht qualifiziert. Wiedergabefaktor und Modellzeit bleiben getrennt.

Die zügige Fassung verwendet ein quintisches Fortschrittsprofil und optimiert
eine glatte Zeitdichte entlang der Bahn anhand der tatsächlichen
Gelenkpolynom-Extrema. Gerade Abschnitte und enge Kurven erhalten damit
unterschiedliche Zeitanteile. Anschließend werden die vollständigen neu
angepassten C2-PVA-Kurven mit unveränderten Grenzwerten zertifiziert; eine
pauschale Erhöhung der Wiedergaberate ersetzt diese Prüfung nicht. Aufnahme-
und Abgabehalte werden dabei nicht verkürzt.

`water_practice_upright_bounds.py` wertet dieselben FK-/Intervall-Jets in einer
algebraisch zusammengefassten Form aus. Sie gilt nur für die ausdrücklich
geprüfte Achsstruktur bei identisch ruhender J4. Pitch- und Yaw-Reste der
tatsächlichen exportierten Quintikpolynome bleiben als Intervalle erhalten.
Unabhängige Vergleiche mit der allgemeinen Sechsachs-FK prüfen Position und
Ableitungen bis zum Ruck einschließlich nicht verschwindender Orientierungsreste.

Der native Einstieg lautet im Checkout mit den benötigten CAD-Abhängigkeiten:

```sh
PYTHONPATH=scripts /Applications/FreeCAD.app/Contents/Resources/bin/python \
  scripts/build_water_practice_l01_freecad.py \
  --native-context exports/worktrees/independent-fleet \
  --report exports/water-practice/software-demo-report.json
```

Anschließend prüft `scripts/check_water_practice_tool_freecad.py` die neue
Pipette zusätzlich gegen alle eigenen Armglieder einschließlich der Kameras
an Kurvenknoten und Intervallmitten. Der Renderer verlangt diesen bestandenen
Zusatznachweis. Ein allgemeiner Selbstkollisionsnachweis folgt daraus nicht.

Die FreeCAD-Umgebung wird wie bei den bestehenden CAD-Builds über
`build_instrument_concepts.freecad_environment` eingerichtet. Der ursprüngliche
native L01-Kontext bleibt mit seinen alten Artefakt- und Quellenpins erhalten.
Seit dessen Ableitung geänderte Kamerageometrien werden durch **vier aktuelle
Armableitungen** ersetzt. Gelenkrahmen, nicht kamerabezogene Abmessungen und
die übrigen Geometriequellen müssen weiterhin übereinstimmen. Es werden keine
alten CAD-Prüfsummen auf neue Quellen umgeschrieben.

Bei den benannten Kompositions-/Formeländerungen des aktuellen `master` prüft
`water_practice_context.py` zusätzlich sämtliche numerischen Raumoperationen
und alle L01-Instanztransformationen gegen den ursprünglichen Kontext. Die
numerische Vergleichsauflösung beträgt 0,000001 mm. Nur die geometrisch gleiche
Standardaufstellung darf so weiterverwendet werden; geänderte Geometrie oder
andere Parametervarianten benötigen einen neuen Kontext. Originalpins und
Äquivalenzbeleg werden getrennt im neuen Bericht erhalten.

`exports/water-practice/l01/native-proof.json` dokumentiert die neue diskrete
BRep-Prüfung der Arme und Pipetten gegen Laboreinrichtung, offene Gefäße und die
anderen geparkten Arme. Positive Überschneidungen werden nicht als erlaubtes
Pipettieren maskiert. Allein der befestigte Armfuß darf seine eigene Halterung
berühren. Diese diskrete Prüfung ist weder ein kontinuierlicher
Kollisionsnachweis noch eine Selbstkollisions- oder Personenschutzqualifikation.

Die geprüften Bewegungsdaten werden als zusätzlicher Modus in die bestehende
Laboranimation eingebunden:

```sh
PYTHONPATH=scripts python3 scripts/render_water_practice_l01.py OUTPUT.html \
  --base-fragment CHECKED_L01.html --base-receipt L01_PREVIEW_RECEIPT.json \
  --fixture-report exports/water-practice/software-demo-report.json
node tests/check_water_practice_l01_player.cjs OUTPUT.html
```

Der Renderer verlangt den zur unveränderten Basisanimation passenden Receipt
und einen bestandenen aktuellen Wasser-Geometriebericht. Die bisherigen
Transportmodi bleiben enthalten. Nur für die Browseransicht werden Armvertices
auf einem 4-mm-Raster zusammengefasst; Pipettenspitzen und Gefäße bleiben davon
ausgenommen. Die nativen Prüfkörper und Bewegungskurven bleiben unverändert. Im Wassermodus fahren keine Transporter in
die reservierten Bench-Bereiche. Eine neue Personenbelegung stoppt die
Darstellung; Abwahl allein löst den Halt nicht, eine erneute ausdrückliche
synthetische Freigabe ist erforderlich. Wiederhergestellte Ansichten starten
pausiert und behalten einen vorhandenen Schutzhalt.

Die vier Zugaben A1, B1, C1 und A2 stammen aus dem abgeschlossenen
`test_fixture`-Bericht. Nach A2 fehlen zunächst die Dokumentationsquittung und
damit die fachliche Gewissheit. Die Flüssigkeitsdarstellung zeigt ausdrücklich
die bekannte **Fixture-Wahrheit**, keine erfundene Sensorbeobachtung. Neustart,
gesperrte Wiederholung und Abgleich ändern weder Gefäßfüllungen noch Armposen;
der Abgleich ordnet nur den bereits erfolgten Transfer zu. Der Player ruft
keine Laufzeitoperationen auf und schreibt weder Journal noch Reservierungen.
Die E4-Entscheidungen und ihr Preflight bleiben unverändert. Für die neuen
Wasserbahnen gibt es keinen SolidCraft-/ROS-Bewegungsexport; geprüft werden
FreeCAD-Geometrie, gemeinsame PVA/FK und die Browserdarstellung.
