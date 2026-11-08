# CF01: Nachtrag zur Claude-Prüfung vom 8. November 2026

Dieser Nachtrag trennt die aktuelle Umsetzung von der unveränderten historischen
README-Mediendemo. Die Prüfung betrifft die synthetische Umgebung und den lokalen
Chargenlauf; sie erweitert weder Hardware- noch Netzwerk- oder Bahnunterstützung.
Die angebotene erneute Claude-Konsultation wurde auf Eigentümerwunsch ausgelassen.

## Abgleich der Hinweise

| Claude-Punkt | Berücksichtigung |
|---|---|
| A1: Kommunikationsausfall | Bereits vorhandene Fehlerbehandlung mit Vertrags-Stopp und `BatchError`; Rückmeldung `None` sowie Verbindungs-, Feld- und Typfehler werden getestet. |
| A2: Identität als Echo | Standardlauf verwendet die separate synthetische Weltinventur, tatsächlichen Rotorindex sowie Stationsbelegung und Fixture-Masse. Das injizierbare Echo bleibt ausschließlich ein ausdrücklich benannter Testhelfer. |
| A3: Rückgabe und Bewegungsbaustein | Alle Chargenübergaben bleiben abstrahiert; der 60-s-Bewegungsbaustein läuft unabhängig. Keine Kopplung einer beliebig zugeordneten Probe an Rotorplatz 01. |
| A4: Mediennachweise | Historische Medien und Prüfsummen bleiben erhalten; ihr vollständiger Quellstand ist unten gebunden. Aktuelle Ausgaben und Prüfungen werden separat erzeugt. |
| A5: Unvollständige Zentrifugation | Explizite Folge `braking` → `succeeded`; Tests für Stopp, Encoder- und Bremsfehler verhindern die Rückgabe. |
| B6: Vertragsdecoder | Runner und Decoder verwenden dieselbe Feldnamenabbildung `centrifuge_protocol.wire`. Stopp läuft über den Decoder; Job-Polling bleibt ausdrücklich lokal und prüft keine Transportserialisierung. |
| B7: Bericht und tatsächliches Profil | Effektives Profil samt Hash, Implementierungsprüfsummen und revisionierte Ausgaben sind vorhanden. Die neue gemeinsame Platzabbildung ist ebenfalls gehasht und im Bericht enthalten. |
| B8: Mock-Annahmen | Leerer Rotor, fiktive Profilmasse und zeitlose Übergaben stehen im Profil und Bericht. Testzeit vergeht nur beim Schleudern und Bremsen. |
| B9: Instanzvertrag | Geräte verwenden `host` und die eingeschränkte gemeinsame `equipment_instance`-Definition im Baugruppenvertrag; Laufzeitprüfung verwendet `assembly.validate_instance`. Armparameter laufen weiterhin über `robot_spec.load` / `parameter_variant`. |
| B10: Geräte und Exportkontext | Die Pflicht zu Arm/CF01/Rack liegt im CF01-Szenenadapter. Der Umgebungsloader erzwingt diese Geräteliste nicht. `_workspace` wird nicht mehr in Szene, Mesh oder HTML geschrieben. |
| B10: Quellen und Plätze | Führende Szene referenziert das Protokoll; Arm- und CF01-Quellen stammen aus Equipment-Assets. `rack_slots.places` erzeugt dieselben stabilen Platz-IDs für Geometrie, Chargenzuordnung und Übergabeprotokoll. `slot_order: row_major` steht in Rackquelle und Schema. `rack` war bereits ein Pflichtfeld. |
| B10: HTML und Sprachen | Deutsch ist Standard; Erklärungen, Bedienung, barrierefreie Labels und Zustände lassen sich auf Englisch umschalten. Fehlendes oder beschädigtes Chargenpanel blockiert die Bewegung nicht. Sprache und laufende Wiedergabe sind unabhängig. Technische IDs bleiben stabil. |
| B10: Regression und Katalog | Numerischer Vergleich mit absoluter Toleranz 1e-8 und relativer Toleranz 1e-12; Struktur und IDs bleiben exakt. Fixture-Herkunft `ad9de56` / Szene `05dba7428daa` bleibt dokumentiert. Der eigene Referenzbankkatalog schützt weiterhin die unveränderte L01-Revisionsbindung. |

Die Vereinfachungen unter C bleiben bestehen: vollständige Zwölferbeladung,
Balanceprüfung durch CF01, Station am Weltursprung, eine Referenzfläche ohne
Raumschale, synthetische Übergaben und fiktive Qualifikation. Die Erweiterungen
unter D bleiben Zukunftsarbeit: vollständige Roboterbahnen, physische Identität,
Netzwerkserver, Wiederanlauf, Teilbeladung und andere Aufstellungen.

## Historische Medien-Provenienz

Unverändert bleiben `docs/media/provenance.json`, `robot-demo.html`,
`robot-demo.png` und `robot-demo.mp4`. Sämtliche **50 Quellprüfsummen** der
Provenienz passen exakt zu Commit
`e5eedc828a2bb1ae4e903378ec9359644bd8a467`.
Die drei Medienprüfsummen passen weiterhin zu den versionierten Dateien.
Die alte fehlgeschlagene SolidCraft-Importprüfung bleibt fehlgeschlagen; neue
native Prüfungen ersetzen diesen historischen Befund nicht.

SHA-256 der unveränderten `docs/media/provenance.json`:

```text
80e954c9b2b7a4a16ee40f280382e0a134702b9edcefa6d01b6d267e45e5160c
```

Zur unabhängigen Nachprüfung lassen sich die mit `source_files_sha256` benannten
Dateien durch `git show e5eedc8:<Dateipfad>` lesen und ihre Bytes gegen den
jeweiligen gespeicherten SHA-256 vergleichen. Die aktuelle Arbeitskopie ist kein
Ersatz für diese historische Quellrevision.

## Aktuelle Ausgaben und Prüfung

Der neue lokale Aufbau ist `centrifuge-cf01-robot-19cf33001d73-r2`.
Seine Dateien liegen unter `cad/generated/`, `exports/generated/` und `renders/`;
sie werden nicht als zusätzliche führende Quellen versioniert. Die neue
zweisprachige Demo liegt unter
`renders/centrifuge-cf01-robot-19cf33001d73-r2/cf01-robot-pickup.html`.

Der Browsercheck ist mit `node tests/check_cf01_demo.cjs <HTML-Datei>`
wiederholbar; optional folgen der Playwright-Modulpfad und das Chrome-Programm.
Er kontrolliert Deutsch/Englisch, Sprachwechsel bei laufendem Chargenpanel,
Besitz bei 0/15/30/45/60 s, wiederhergestellte Rackreihenfolge, fehlende und
beschädigte Chargendaten sowie Breiten von 320/600/960 px ohne Konsolenfehler.
Die beiden Sprachfassungen wurden zusätzlich als Bilder visuell geprüft.

Die Galerie wird nur für die drei betroffenen Einträge `synthetic-workspace`,
`guided-rack` und `rack-batch` erneuert und an den aktuellen Quellstand gebunden.
Der vorherige Galerienachweis bleibt in Commit `ad94615` nachvollziehbar;
`docs/media/provenance.json` bleibt davon unabhängig.

Bestanden sind 219 Offline-Tests, 13 Schema-Dokumentprüfungen und die oben
beschriebenen Browserchecks. Die Ablehnung alter `parent_frame`-Instanzen,
fehlender Hosts, nicht unterstützter Instanzfelder und nicht numerischer
Aufstellungskoordinaten wurde zusätzlich gegen das Schema geprüft.
Beide lokalen Vertragsdecoder (`ros2`, `sila2`) stellen die ursprüngliche
Rackreihenfolge wieder her.

FreeCAD hat sieben native Snapshots mit jeweils 223 Körpern erzeugt.
Ihre aggregierten Volumina und Schwerpunkte stimmen exakt mit dem vorherigen
Medien-Build überein; Körper-IDs, Mesh-Geometrie, Farben und Deckkraft ebenfalls.
Die Referenzbank bleibt bei `#8a959d` und Deckkraft 0,38. Die native Szenenprüfung,
Selbst-/Greifprüfung und der adaptive Bewegungstest bestehen: 1601 angeforderte
Prüfstellungen, 1593 unterschiedliche Zustände und kleinster geprüfter Abstand
5,47699 mm. Das ist eine diskrete BRep-Prüfung, kein kontinuierlicher
Bewegungsraum- oder realer Funktionsnachweis.

SolidCraft hat beide nativen Prüfstellungen unabhängig von FreeCAD erzeugt und
mit jeweils 235 geschlossenen Körpern geprüft. Die gemeinsame Beschreibung
enthält weiterhin 223 semantische Körper; die größere native Zahl entsteht
allein durch die dokumentierte Aufteilung der Herstellergehäuse. Beide
Stellungen bestehen den Quervergleich mit FreeCAD: relative Volumenabweichung
unter 4,51e-7, Schwerpunktabweichung unter 0,00018 mm. Es handelt sich um
statische Prüfstellungen, keine native Übergabebewegung.

Die vollständige lokale Zuordnung von Quellen, Generatoren und Ausgaben steht
unter `exports/generated/centrifuge-cf01-robot-19cf33001d73-r2/` in
`robot-pickup-build-report.json`, `solidcraft-scene-validation.json` und
`claude-review-validation.json`. Historische Quell-/Medienprüfsummen und die
Übereinstimmung der vorherigen Geometrie sind im letzten Bericht separat
festgehalten. Netzwerk, Hardware und das Live-FreeCAD-Makro wurden nicht
ausgeführt.

Die drei betroffenen Galerieansichten wurden erneut erzeugt und visuell geprüft.
Alle drei Bilddateien sind bytegleich mit dem vorherigen Stand; aktualisiert
wurden ausschließlich ihre Quellen-, Modell- und Berichtsbindungen in der
Galerie-Provenienz. Der abschließende Galeriecheck besteht für 27 Bilder und
22 abgedeckte Modellquellen bei insgesamt 2.231.021 Bildbytes.
