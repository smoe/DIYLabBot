# Roboterbefehle im Rundgang

Arm A in Labor 3.003 lässt sich anklicken oder aus unmittelbarer Nähe mit der
Leertaste auswählen. Das eingeblendete Menü bietet **Demobewegung**,
**Grundstellung** und **Stopp**. Die Grundstellung ist die bisherige
Aufstellungsposition des Arms. Während einer Bewegung sind neue Fahrbefehle
gesperrt. Stopp bremst die Modellzeit über 0,4 Sekunden ab; danach kann der Arm
wieder in seine Grundstellung fahren. Es gibt keine automatische Wiederholung.

`model/walkthrough-robot-commands.json` beschreibt nur die ausgewählte Instanz,
einen kleinen Gelenkversatz und ausdrücklich synthetische Leerfahrtgrenzen.
`scripts/walkthrough_robots.py` leitet Gelenkrahmen und Körperzuordnungen aus
der vorhandenen Roboterquelle und L01-Aufstellung ab. Kameras und Halterungen
folgen ihrem Quellglied; die starren Teile der beiden anderen Arme bleiben
unverändert. Es werden weder Proben noch Greiferaktionen oder Geräteprozesse
gebucht und keine Hardware-/ROS-/Netzwerkbefehle gesendet.

Die gemeinsame quintische PVA-Auswertung bestimmt die Bewegung. Die Fahrzeit
wird aus Geschwindigkeits-, Beschleunigungs- und Ruckgrenzen einschließlich
der Kettenregel für jeden möglichen Stoppzeitpunkt abgeleitet. Die Wiedergabe
verwendet Modellzeit mit Faktor 1; Bildwiederholrate ist kein Geschwindigkeits-
nachweis. Ein menschlicher Vergleich und Herstellerqualifikation fehlen.
Die Leerfahrtgrenzen sind keine Freigabe für beladene Bewegungen.

Prüfungen:

- `python3 scripts/check_walkthrough_regressions.py --pattern test_walkthrough_robots.py`
  prüft Quell-FK gegen Browsertransformationen, Körperbindung, Grenzen und
  Befehlsfolgen einschließlich 78 Stoppfällen.
- `node tests/check_walkthrough_robots_browser.cjs <index.html> <playwright> <chrome>`
  prüft Auswahl per Klick/Leertaste und sichtbare Bewegung der nativen Szene.
- Mit FreeCAD-Python: `scripts/check_walkthrough_robot_native.py <manifest.json> <report.json>`
  prüft 13 Positionen des reversiblen Gelenkpfads gegen die geprüften Gebäude-
  und Geräte-BReps. Bestehende Gelenk-/Montagekontakte werden separat genannt;
  neue oder zunehmende Überschneidungen führen zum Fehler. Direkt benachbarte
  Gelenkglieder sind als mechanische Schnittstellen ausgeschlossen und werden
  nicht als kollisionsgeprüft bezeichnet. Das ist ein
  diskreter Nachweis, keine kontinuierliche Kollisions- oder Sicherheitsprüfung.

Der Pages-Veröffentlichungscheck vergleicht auch den Roboterbefehlsvertrag.
Ein alter Snapshot mit korrekten HTML-Prüfsummen genügt damit nicht.
