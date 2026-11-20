# BF01 · synthetische Gebäudeflotte

BF01 ist eine ausdrücklich gewählte, separate Simulation für 20 leere
TR01-Instanzen `BF01` bis `BF20`. Die bestehende L01-Aufstellung einschließlich
ihres statischen TR01 und ihrer Bewegungsnachweise bleibt unverändert.
Es gibt keine Probenübergabe, Materialbuchung, T1/T2/T3-Bindung, ROS-,
Netzwerk- oder Hardwareausführung. Ein normaler Rundgang aktiviert keine Flotte.

## Bestätigte Rückstellung von K0_013

Der Eigentümer hat am **20. November 2026** `KG / K0_013` für E2 ausdrücklich
zurückgestellt. Der bisherige Plan erschließt diesen Raum nur über `DK013`
an `KW061` aus `R3_028`. Der Treppenkern bleibt vollständig ausgeschlossen;
diese Entscheidung erlaubt weder seine Durchfahrt noch einen neuen Durchgang.
K0_013 zählt nicht zur Sollabdeckung dieses BF01-Laufs. Die Rückstellung wird
in `missions.deferred_targets` der separaten Flottenquelle geführt und ist
keine Änderung des Gebäude- oder Kellerplans.

Alle anderen Ziele bleiben verpflichtend:

| Auswahl | Geschoss | Ziele | Grundlage |
|---|---|---|---|
| E1 | EG | R0_001, R0_002, R0_003, R0_015, R0_014A | Planbeschriftung |
| E1 | OG3 | R3_001, R3_003, R3_007 | Eigentümerbeschreibung |
| E1 | OG1, OG2 | jeweils R3_001, R3_003, R3_007 | Vorlageflächen, Nutzung unbestätigt |
| E2 | KG | K0_002, K0_006, K0_009, K0_012, K0_011 | Planbeschriftung |

Die Vorlageflächen in OG1 und OG2 werden nicht als bestätigte Labore bezeichnet.
Die Heimplätze sind ausschließlich in `EG / R0_004` und `EG / R0_013` vorgesehen.
Treppenbereiche `R3_028`, `R3_017`, `ExternalStairGround`, Atrium und Schacht
bleiben gesperrt; der Schacht wird ausschließlich über den Aufzugablauf genutzt.

## Arbeitsstand und Nachweisgrenzen

Die Rückstellung hebt nur die zuvor nachgewiesene topologische Sperre für
K0_013 auf. Sie ist keine Freigabe anderer Ziele, Türen, Depots oder Fahrwege.
Vor einer Simulation müssen sämtliche verbleibenden Ziele mit der
Fahrzeughülle, den deklarierten Abständen und den tatsächlichen nativen
Hindernissen geprüft werden. Jede weitere Stoppbedingung des Auftrags bleibt
verbindlich. Ein grobes Raster oder eine Kreis-Breitphase allein beweist
keine Unpassierbarkeit einer orientiert befahrbaren Tür.

Gebäudeabmessungen und Registrierung sind Darstellungsannahmen, keine
Vermessung. Sensorik, Kamera, Kommunikation und Gebäudedienste sind synthetisch.
Personen, reale Tür-/Aufzugsteuerung, Navigation und Sicherheit bleiben
unqualifiziert; der Vergleich mit manueller Durchführung bleibt offen.
Neue Laufzeitdaten und Geometrienachweise entstehen ausschließlich unter den
ignorierten lokalen Ausgabeordnern. Historische Medien bleiben unverändert.

## Erreichte Phase 1

Die separate [Flottenquelle](../model/building-fleet-demo.shared.json) und ihr
[striktes Schema](../model/building-fleet-demo.schema.json) binden die bestehenden
Gebäude-, Rundgang-, TR01-, Winkelprofil-, Sensor- und L01-Quellen sowie den
neuen [Kamerakit](../model/tr01-awareness-camera.shared.json) über SHA256.
Der Lader lehnt Zusatzfelder, ungültige Einheiten/Werte, unbekannte
Qualifikationen und jede weitere Zielauslassung ab. Es gibt 19 aktive Ziele.

Der Kamerakit wird unabhängig in FreeCAD und SolidCraft aus derselben Quelle
abgeleitet. Die TR01-Konstruktion wird nicht verändert. Die leere Ableitung
entfernt nur die 48 Gefäßhüllen, behält beide Racks und die geschlossene Haube
und ergänzt Gehäuse, Linse, Halter und einen ausdrücklich nichtphysischen
Sichtkegel. Kameraposition und -ausrichtung folgen den TR01-Parametern und
benannten Flächen. Eine Kamera-Hardware ist nicht ausgewählt.

```sh
python3 scripts/build_tr01_awareness.py
python3 -m unittest discover -s tests -p 'test_tr01_awareness.py' -v
python3 -m unittest discover -s tests -p 'test_building_fleet*.py' -v
```

Der tatsächliche unabhängige CAD-Vergleich besteht mit je 35 Körpern und
93 exakten Kit-/Fahrzeug-Interferenzprüfungen. Die Kamerahülle einschließlich
Halter bleibt außerhalb von Abdeckung und Kassettenraum. Der optische Rahmen
liegt bei den Standardparametern bei `[250, 0, 182]` mm und blickt in Fahrzeug-+X.
Der lokale Bericht steht unter
`exports/generated/tr01-awareness-ccd729bbb881-r2/build-report.json`.

## Historischer Stopp der ursprünglichen L01-Gangmitten

Nach der Rückstellung von K0_013 sind die übrigen Ziele im optimistischen,
registrierten Tür-/Bereichsgraphen mit den aktiven Aufzuglandeseiten verbunden.
Das beweist keine geometrische Fahrt. Auch ein negativer Kreis-/Rasterbefund
reicht allein nicht zur Ablehnung: Die engeren Kellerportale DK009 und DK011
sind bei gerader orientierter Durchfahrt mit Fahrzeughülle und den unveränderten
Abständen frei; weitere Raumwege wurden damit nicht qualifiziert.

Für das Pflichtziel **OG3 / R3_003 (L01)** ist dagegen die aus dem vorhandenen
Fahrprofil abgeleitete Gangmitten-Verbindung tatsächlich unterbrochen:

| Verbindung | Tatsächlicher Kontakt im gemeinsamen Gebäudebezug |
|---|---|
| Vordere Querverbindung | Chassis bei Fahrzeugmittelpunkt `[11100, 6611.351351351352]` mm trifft das anfangs offene `OG3__DoorLeaf_D3_003B`. |
| Hintere Querverbindung | Die obere Haubenhaut bei Fahrzeugmittelpunkt `[9000, 1571.41768981954]` mm trifft `Lab3003_WindowBenchRight_Worktop`. |

Die Materialzeugen liegen ohne Sicherheitsaufweitung im Inneren der jeweiligen
nativen geschlossenen Hindernishülle: vorn bei Weltpunkt
`[11100, 6611.351351351352, 12850]` mm, hinten bei
`[9000, 1521.41768981954, 13615]` mm. Die Haubenhaut liegt bei TR01-Z = 865 mm;
der hintere Materialzeuge hat Fahrzeug-Y = −50 mm. Nur die Boundingbox der
gekrümmten Fensterbank wäre hierfür kein ausreichender Nachweis.

Die Zeugen liegen jeweils mehr als die bestehenden 250 mm Eckverrundung von
den Gangmitten-Knoten entfernt. Ein größerer Umweg ist keine bereits geprüfte
Eckverrundung dieser referenzierten Bahn. Nach beiden Unterbrechungen sind die
zu D3_003A und D3_003B gehörenden Gangseiten nicht verbunden; die bestehende
Gangmittenstruktur enthält keine zulässige geschlossene Inspektionsschleife.
Eine Rückwärtsinspektion oder Drehung auf der Stelle gehört nicht zu den
zugelassenen Rückwärtsfällen. Das ist eine Ablehnung der **vorgeschriebenen
bestehenden L01-Gangmitten**, keine Behauptung, dass jede denkbare neue Bahn im
Raum unmöglich wäre.

Bis zur ausdrücklich freigegebenen separaten BF01-Verbindung wurde deshalb kein vollständiges BF01-Programm erzeugt. Es wurden weder Türen
umgestellt, Möbel verschoben, neue Fahrspuren erfunden, Abstände verringert
noch weitere Ziele zurückgestellt. Diese Entscheidung wurde am 20. November 2026 ausdrücklich erteilt; die separat geprüfte Umsetzung steht im folgenden Abschnitt. Das bisherige L01-Profil bleibt dabei eine unveränderte Referenz.

Die lokalen, nicht versionierten Nachweise stehen unter
`exports/building-fleet/preflight-current/`: `audit.py`, `report.json`,
`check_portals.py`, `portal-report.json`, `audit_l01_stop.py` und
`l01-stop-report.json`. Aktuelle native BRep-Zeugen werden dort separat geführt.

## Separat geprüfte BF01-Verbindung in L01

Die [neue referenzierende Quelle](../model/building-fleet-l01-route.shared.json)
mit eigenem [Schema](../model/building-fleet-l01-route.schema.json) ersetzt für
BF01 die betroffene Querung. Das ursprüngliche L01-Fahrprofil und seine alten
negativen Nachweise bleiben unverändert. Die Flottenquelle bindet die neue
Quelle ausdrücklich über `sources.l01_route`; der normale Rundgang und die
bisherigen L01-Demos wählen sie nicht stillschweigend aus.

Die Querung wird aus der gebundenen Raumdefinition mittig zwischen der
vorhandenen offenen Türblattspitze und der tatsächlichen Inselvorderkante
abgeleitet. Sie liegt lokal bei Y = 1369,864865 mm. Die freie Streifenbreite
beträgt 660,270271 mm; Fahrzeugbreite und beidseitiger Abstand von je 85 mm
lassen darin 78,270271 mm zusätzliche Breitenreserve. Türstellungen, Möbel,
Arme, vorhandener statischer TR01 und die ursprünglichen Bench-Zonen bleiben
erhalten. Die Schutzbereiche werden starr in denselben Gebäudebezug übertragen,
nicht verkleinert oder skaliert; sie bleiben durchgehend gesperrt.

Die fünf C2-Teilstücke einschließlich Einfahrt durch D3_003A und Ausfahrt durch
D3_003B sind eine durchgehende Fahrt. Die Zeitplanung behandelt schnelle Geraden
und langsamere Kurven getrennt. Sie verzögert vor engeren Kurven bzw. Zonen und
beschleunigt danach wieder innerhalb der unveränderten Grenzen. Wegpunkte,
Türdurchgänge und Querungswechsel enthalten keine Ruhepunkte. Wiedergabefaktor
ist 1; Modellzeit und spätere Browser-Wiedergabe bleiben getrennt.

Das nach 1 ms Zeitquantisierung tatsächlich ausgewertete Profil dauert
**57,947 s**. Seine oberen Schranken betragen 298,70 mm/s, 490,04 mm/s² und
981,02 mm/s³; die Gierrate bleibt unter 0,32442 rad/s bei unverändertem Limit
0,35 rad/s. Die gemeinsame Polynom-Auswertung prüft Beschleunigung, Ruck und
Kein-Halt-Kriterium auch zwischen den Knoten. Es wird keine globale
Zeitoptimalität und kein bestandener menschlicher Vergleich behauptet.

Getrennte Nachweise am exakten exportierten Profil:

- Kontinuierlicher Mesh-/Bench-Nachweis: mindestens 95,3788 mm Abstand nach
  Abzug von Tessellierungs- und Float32-Reserve.
- Exakte Unterstützung des gesamten aufgeweiteten orientierten Rechtecks
  durch die native Bodenflächen-Union; kein Ersatz durch einen verkleinerten
  Kollisionskreis oder reine Zellmittelpunkte.
- Unabhängiger nativer BRep-Kurvennachweis aller 34 physischen Fahrzeug- und
  Kamerakörper gegen die vollständige gebundene Gebäudewelt: konservative
  Intervall-Untergrenze **90,3299 mm**, gefordert sind 85 mm (75 mm Abstand plus
  10 mm Lokalisationstoleranz). 268 Intervalle und 790 exakte BRep-Abstände.

Die lokalen Nachweise stehen unter `exports/building-fleet/l01-connector/`:
`fast-motion-r2.json`, `fast-r2-mesh-check.json`,
`fast-r2-generic-floor-union-check.json`,
`fast-r2-native-curve-check-efficient.json` und
`motion-generation-report.json`. Diese Qualifikation betrifft die **einzelne
BF01-Verbindung** in der synthetischen Szene. Fahrzeugbegegnungen, alle übrigen
Fahrwege und der vollständige Flottenlauf benötigen weiterhin eigene Nachweise.
Reale Navigation, Personenschutz, Hardware und Aufmaß bleiben ungeprüft.

## Vorbereitete, noch nicht integrierte Komponenten

Ressourcen-/Aufzugdienste, deterministischer Funkkanal, empfangsbasierter
Leitstand und Missionszuweisung besitzen getrennte Unit-Tests. Die Sensorwelt
liefert anonyme Erstreflexionen; der unabhängige Auditor prüft konservative
Intervallabstände, mit orientierter Rechteck-Nachprüfung bei unzureichender
Kreis-Breitphase. Diese Bausteine sind **kein ausführbarer Gesamtsimulator**.
Es gibt keinen bestandenen Flottenlauf, kein natives vollständiges Fahrprogramm
und keine BF01-Browseranimation oder Browserqualifikation.

Die Annahmen E1–E8 bleiben: bestätigte bzw. unbestätigte Zielnutzungen (E1), die
fünf aktiven Kellerziele mit ausdrücklicher Rückstellung K0_013 (E2), Depot nur
in R0_004/R0_013 (E3), synthetische getrennte Leerfahrtgrenzen (E4), referenzierte
Rundumscan-Annahme und 75 mm Abstand (E5), logischer Leitstand (E6), höchstens
zwei nur bei nachgewiesenem Kabinenfreiraum (E7) und die vorhandene statische
L01-TR01-Instanz als Hindernis (E8). Depotkapazität, vollständige Raumwege,
Flotten-Abdeckung, Modellzeit, Dynamik, reale Navigation und menschlicher
Geschwindigkeitsvergleich bleiben offen. Der Quellvertrag verwendet im EG
und KG nur die innere aktive Aufzugseite; die ältere Dokumentationsangabe
„EG beidseitig“ wird nicht als Verhalten übernommen.

### Unabhängige native Kontaktbestätigung

Die beiden statischen Zeugen wurden zusätzlich mit den exakten nativen BReps
überprüft, unabhängig von Raster und Dreiecksprojektion. Bei unveränderter,
korrekt offener Referenztür ergibt Chassis/Türblatt ein positives Schnittvolumen
von 561.210,810 mm³; Haube/Fensterbank ergeben 45.019,010 mm³. Beide exakten
Abstände sind null. Quelle und native Artefakte sind im lokalen
`native-negative-witnesses.json` gepinnt; der Reproduzierer heißt
`check_l01_native_witnesses.py`. Das sind zwei negative statische Zeugen,
kein vollständiger nativer Fahrweg- oder Flottennachweis.

Die neue gezielte Suite besteht aus **55 Tests**: 48 für Flottenvertrag,
Navigation einschließlich Stoppregression, vorbereitete Dienste/Kanal/Sensorik,
Missionszuweisung und native Eingabepins sowie sieben für den Kamerakit.
Alle bestehen ohne Skip. Die getrennten vorhandenen JavaScript-Prüfungen für
Interaktion, Aufzug und Kamerakollision sowie die neun Markdown-Linkprüfungen
bestehen ebenfalls. Die bisherigen L01-Verkehrsläufe werden durch die
unveränderten Quellen nicht als neu ausgeführt ausgegeben.

Die vorhandene Python-Rundgangsuite meldet 58 Tests: 57 bestanden, ein
optionaler Schema-Test wegen fehlendem `jsonschema` übersprungen. Es wurde
nichts installiert; dieser Skip ist kein bestandener Schema-Nachweis.
Die neue BF01-Vertragsprüfung arbeitet ohne diese optionale Bibliothek und
besteht vollständig. Vollständige L01-Verkehrs-, Flotten-, native Programm-
und Browserläufe wurden nach dem Stopp nicht neu ausgeführt.
