# Türen und Geräte im Gebäuderundgang

Ein Klick auf eine nahe Tür, Klappe oder einen Griff öffnet beziehungsweise
schließt das Teil. Alternativ darauf blicken und die Leertaste drücken.
Die Leertaste erreicht auch die geschlossene Fläche, wenn das Blatt bereits
weggeschwenkt ist. Davorliegende Körper sperren den Zugriff weiterhin.
Die Reichweite bleibt der gemeinsame Rundgangparameter.

Die Bedienung umfasst alle 139 vorhandenen Raumtüren auf KG, EG und OG1–OG3.
Fensterlose Holz- und Stahlblätter, runde Guckfenster samt Ringen und das
Glastürblatt behalten ihre bestehenden Körper und Materialien.

In Labor 3.003 sind zusätzlich bedienbar:

- Gefrierschranktür und alle sechs Schubladen;
- die vertikal verschiebbare Abzugsscheibe und drei Unterschrankklappen;
- der Qubit-Deckel und der NanoDrop-Hebel.

Die Gefrierschranktür schließt erst, wenn jede Schublade vollständig
eingeschoben ist und ihre Bewegung beendet hat. Eine Schublade lässt sich
erst bei vollständig geöffneter Tür ausziehen. Gleichzeitig eintreffende
Befehle prüfen aktuelle Stellung, Zielstellung und laufende Bewegung.
Eine gesperrte Betätigung meldet die betroffenen Teile und die benötigte
Stellung. Der geschlossene Schrank lässt sich über sein Türblatt oder seinen
Griff wieder öffnen.

## Aufzug

Die eine vorhandene Kabine erhält zwei gegenüberliegende Schiebetürpaare.
Jeder aktive Geschosszugang besitzt ein eigenes Türpaar. EG öffnet beidseitig,
OG1–OG3 nur nach außen und KG nur nach innen. Nach einem Ruf oder einer
Zielwahl schließen zuerst die Türen. Erst nach deren Abschluss fährt die
Kabine; am Ziel öffnen die dort aktiven Kabinen- und Geschosstüren automatisch.
Ein- und Aussteigen ist erst nach vollständiger Öffnung möglich.

Panel und Telefon folgen der beschriebenen Anordnung: Panel auf der
nordwestlichen, Telefon auf der nordöstlichen Kabinenseite, jeweils ganz hinten.
Die Positionen beziehen sich auf den vorhandenen Gebäuderahmen. Abmessungen
bleiben Darstellungsannahmen. Panel, Etagenknöpfe und Telefon fahren mit der
Kabine; ihre Türblätter kombinieren Kabinenhub und seitliche Türbewegung.
Die Etagenwahl erfolgt weiterhin über die vorhandenen Bedienknöpfe des
Rundgangs. Das Telefon ist ein sichtbares Ausstattungsmodell.

## Gemeinsame Quellen und Prüfung

`model/building-walkthrough.shared.json` enthält unter `mechanisms` ausschließlich
typbezogene Beschriftungen, Darstellungszeiten und Betrachtungsabstände.
`scripts/walkthrough_mechanisms.py` bindet die vorhandenen Raumtürflächen und
die Gelenke der referenzierten Geräte. Die native Referenzstellung bleibt
erhalten, auch beim zunächst ausgezogenen vierten Gefrierfach und bei den
teilweise geöffneten Gerätehebeln. Die Browsertransformation wird relativ zu
dieser Stellung ausgewertet.

Die Gefrierschrankbedingungen werden aus der bestehenden `validate_pose`-Prüfung
des Geräteproviders abgeleitet. Der Compiler vergleicht die abgeleiteten
Zustandsbedingungen mit sämtlichen Kombinationen der Endstellungen. Die
Bedienung verlangt konservativ die vollständig erreichte Zugangsstellung.

Die Aufzugausstattung entsteht aus `circulation.elevator.fittings` der
Gebäudequelle über `scripts/lift_fittings.py` als portable CAD-Geometrie.
Öffnungsweiten und Schiebewege stammen aus den bestehenden Geschossöffnungen.
`scripts/walkthrough_elevator.py` bindet dieselben Körper und Gelenke an den
Rundgang. `scripts/walkthrough_interaction.js` führt Türfolge, Verriegelung und
absolute Kabinenbindung aus. Bewegungen verwenden weiterhin die gemeinsame
quintische Darstellung mit ruhigem Beginn und Ende; reduzierte Bewegung
führt dieselben Zustandsprüfungen in identischer Reihenfolge aus.

```sh
python3 -m unittest discover -s tests -p 'test_*walkthrough*.py' -v
node tests/check_walkthrough_interaction.cjs
node tests/check_walkthrough_lift.cjs
node tests/check_walkthrough_mechanisms.cjs
node tests/check_walkthrough_mechanisms_browser.cjs <index.html> <playwright> <chrome>
```

Die Browserprüfung betätigt alle Raumtüren, prüft jede Gefrierschublade als
einzelne Sperrbedingung und verwendet Maus-/Tastaturereignisse auf den nativen
Flächen. Ein zeitlich ausgeführter Aufzuglauf prüft geschlossene Türen während
der Fahrt, mitfahrende Kabinentüren und die Zielseiten. Native Gebäudeprüfung,
Browserbedienung und reale Ausführung bleiben getrennte Nachweise: Die native
Gebäudedatei enthält eine statische Referenzstellung; Schwenkfreiheit,
Quetschschutz, reale Aufzugsteuerung und Gerätehardware sind nicht qualifiziert.

Der lokale Nachweis `exports/building-walkthrough/building-walkthrough-65c15de308d5/`
enthält den geprüften Rundgang, `browser-check.json` für die bestehenden
Bedienwege und `mechanisms-browser-report.json` für die neuen Funktionen.
Beide Browserprüfungen bestehen, ebenso alle 49 Modell-/Rundgangtests und die
drei JavaScript-Prüfungen für Picking, Kabinenbindung und Verriegelungen.
Der native FreeCAD-Gebäudebericht
`exports/generated/building-stack-7eed558ca997/build-report.json` bestätigt
2.388 gültige Körper, 509 Geometrieprüfungen und 16 Höhenprüfungen.
`exports/lift-fittings-7eed558ca997/validation.json` prüft die 26 neuen
Aufzugbauteile unabhängig in SolidCraft gegen ihre abgeleiteten Maße;
dies ist kein vollständiger SolidCraft-Gebäude- oder Kollisionsnachweis.
Die linearen Kabinentürwege halten in der Modellprüfung Abstand zu Endwänden,
Panel und Telefon. Der bestehende Circulation-Fixture-Test
`test_stack_integration_preserves_source_floor_ids_and_separates_blue_marker`
scheitert weiterhin am fehlenden Eintrag `D3_002_003`; derselbe Fehler wurde
auch auf dem unveränderten Ausgangsstand bestätigt.
