# README-Demo

Bewusst versionierte Medienauswahl, keine zusätzliche Konstruktionsquelle:

- `robot-demo.html`: lokal ausführbare CF01-Entnahmeszene, ohne Netzabhängigkeit.
- `robot-demo.mp4`: kurzer, beschleunigter Überblick des vollständigen 60-s-Zyklus.
- `robot-demo.png`: Vorschau bei 30,5 s, Gefäß am Greifer außerhalb der Zentrifuge.
- `provenance.json`: Quell- und Medienprüfsummen, historischer Prüfstand und Grenzen.

Die Geometrie und Bewegung stammen unverändert aus der bereits erzeugten Szene
`centrifuge-cf01-robot-05dba7428daa`. Die eigenständige HTML-Hülle ergänzt das
Farbschema der früheren Einbettung. Die frühere native Prüfung ist historische
Evidenz; bei dieser Repository-Bereinigung wurde kein neues CAD erzeugt.
Die Browserprüfung kontrolliert station → gripper → rack und Konsolenfehler.
Konzeptgreifer, synthetische Rückmeldungen und modellierte Zeiten belegen keine
reale Roboterfunktion, Sicherheit oder Dosierleistung.

## Aktualisieren

Die Szene aus `model/centrifuge-cf01.robot-pickup.shared.json` mit dem bestehenden
`scripts/build_centrifuge_robot_pickup.py` erzeugen und nativ prüfen. Dieser
Build-Einstieg enthält derzeit Windows-Laufzeitpfade; eine vollständige
Mac-Portierung ist noch offen. Das geprüfte HTML aus `renders/` übernehmen und
die eigenständige Hülle mit ihren CSS-Farbvariablen erhalten. Die Medienauswahl
wird bewusst aktualisiert, nicht bei jedem CAD-Build automatisch überschrieben.

Mit Node, Playwright und dessen Chromium vom Repository-Stamm aus:

```sh
node scripts/export_readme_video.cjs
```

Optional sind der Pfad zum installierten Playwright-Modul und ein
Chromium-/Chrome-Programm als erstes und zweites Argument übergebbar.
Danach Vorschau und Videowiedergabe visuell prüfen und `provenance.json` auf den
neuen Quellstand einschließlich Medienprüfsummen aktualisieren. GitHub zeigt
HTML nur als Datei; für die interaktive Bedienung herunterladen und lokal öffnen.
