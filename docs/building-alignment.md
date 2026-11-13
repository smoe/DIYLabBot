# Geschossübergreifend deckungsgleiche Gebäudehülle

Die Gebäudekomposition registriert KG und EG auf dieselbe Außenkontur wie
OG1–OG3 und Dach. Referenz ist die aus `roof.opaque_area_ids` abgeleitete
F03-Kontur. Eine bloße Anpassung der Boundingbox würde die unterschiedlichen
Kurven, Rücksprünge und Fassadenabschnitte nicht zur Deckung bringen.

`alignment` in der gemeinsamen Gebäudequelle beschreibt die Randlandmarken,
die feste Kerngeometrie und den EG-Fassadenabschluss. Der gemeinsame Adapter
`scripts/building_alignment.py` verteilt die Randpunkte abschnittsweise nach
Bogenlänge auf die Referenz. Fehlende Konturecken werden als geteilte Grenzen
in denselben Wand-/Flächengraphen eingefügt. Öffnungen werden mit ihren
Wandabschnitten übernommen. Innere Punkte erhalten eine harmonisch
interpolierte Verschiebung. Überkreuzungen und überlappende Raumflächen werden
anschließend durch die bestehende Graphprüfung abgewiesen.

**Aufzug und inneres Treppenhaus bleiben fest:** Ihre vorhandenen Eckpunkte,
Schachtseiten und Türbezüge werden nicht mitverschoben. Die Kernflächen und
Aufzugportwände stimmen auf allen fünf Ebenen mit F03 überein. Geschosshöhen,
Treppenverbindungen und die Aufzugtürregel bleiben aus derselben Quelle
abgeleitet; eine Höhenvariante wird zusätzlich geprüft.

Am EG ergänzt ein schmaler Foyer-Bodenstreifen den bisherigen Rücksprung bis
zur gemeinsamen Glasfassade. Damit kann die äußere Wand des Treppenkerns an
seiner bisherigen Position bleiben. Die unterste Außenmetalltreppe liegt nun
auf dem äußeren EG-Treppenpodest statt auf einer in den Treppenbereich
ragenden Raumfläche. Der Bodenbezug wird geometrisch geprüft. Die separate
Außentreppe ist weiterhin von Gebäudehülle, Innenstiege und Aufzug getrennt.
Der ungeklärte F03-Bereich `ExternalLink` erhält in der Komposition keine
vorspringende Geschossplatte oder exklusiven Außenwände; seine ursprüngliche
Nachzeichnung bleibt erhalten.

Die KG-, EG- und F03-Originalvektoren bleiben bytegleich. Die Registrierung
wird ausschließlich in der Gebäudekomposition aufgelöst und von FreeCAD und
SolidCraft gemeinsam verwendet. Ein identischer Darstellungsumriss ist keine
Vermessung: reale horizontale Maße bleiben unbekannt, `calibration` bleibt
`null`. Raumproportionen außerhalb der festen Kerne werden für diese
Darstellung angepasst.

```sh
python3 scripts/build_building_stack.py --backend both
python3 -m unittest discover -s tests -p 'test_building_alignment.py' -v
```

Die Tests vergleichen beide Richtungen der vollständigen Konturen einschließlich
aller Eckpunkte und Abschnittsinneren. Zusätzlich prüfen sie unveränderte
Kernflächen und Aufzugportwände, gültige Raumgraphen, Höhenvarianten und die
Trennung von abgeleiteter Geometrie und Originalquellen. Native Nachweise und
aktuelle Modellpfade stehen im lokalen Gebäude-Build-Bericht.

Der aktuelle native Prüfstand ist `building-stack-4b47ee12d5a4-r2`: beide Backends bestehen
388 gezielte Geometrieproben und 14 Höhenprüfungen. Alle 1477 Körper
werden zusätzlich über STEP verglichen. Der Quellvergleich der vollständigen
Außenkonturen ergibt höchstens 3,7 × 10⁻¹² Darstellungs-mm Rundungsabweichung;
Aufzug- und innere Treppenkonturen besitzen keine Verschiebung.

Die gezielte Gebäude-/Grundriss-/Galeriesuite besteht aus 155 Tests:
151 bestanden, vier optionale JSON-Schema-Prüfungen wegen fehlendem
`jsonschema` übersprungen. Die nativen CAD-Prüfungen sind davon getrennt
vollständig bestanden.
