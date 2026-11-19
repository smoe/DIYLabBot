# PS01 · konfigurierbare Pipettierstation

Stand: 19. November 2026. **Concept; no manufacturing release.**

PS01 verbindet zwei Varianten des vorhandenen Sechsachsarms, eine offene
Arbeitsfläche mit neun belegbaren Plätzen, Labware, 10-/200-/1000-µl-Spitzen und
den Spitzenabwurf T01. Ein Arm übernimmt das Pipettieren, der zweite ist für
Spitzenboxen, Well-Platten und andere Racks vorgesehen.
Die gemeinsame Stationsquelle beschreibt den Aufbau; die Aufstellung und das
Pipettierprotokoll referenzieren diese Definition. Der erste ausführbare Schritt
ist eine Mengen- und Ressourcenplanung mit idealisierter Flüssigkeitssimulation.
Dosierhardware und vollständige Roboterbahnen sind damit noch nicht implementiert.

## Aufbau und Quellen

| Quelle | Verantwortung |
|---|---|
| [Stationsdefinition](../model/pipetting-station-ps01.shared.json) | Parametrisches Deck, neun Aufstellrahmen, nominale Werkzeugklassen und offene Qualifikationen |
| [Aufstellung](../model/pipetting-station-ps01.setup.json) | Referenzierte Labware, fünf deklarierte volle Spitzentrays und deren Belegung |
| [Arbeitsumgebung](../model/synthetic-pipetting-workspace.shared.json) | Unbegrenzter Raum, vorhandener Möbeltyp, eine Referenzbank und Geräteinstanzen |
| [Labwarebibliothek](../model/pipetting-labware.shared.json) | Importierte 96-Well-Koordinaten und ein eigenes parametrisches Reservoir mit drei Kammern |
| [Matrixprotokoll](../model/pipetting-matrix-96.protocol.json) | Ausgangsflüssigkeiten, horizontale/vertikale Verteilung, Auffüllen und Mischen |
| [Transportwerkzeug LT01](../model/labware-transfer.shared.json) | Parametrischer Parallelgreifer, untergreifbare Träger und Aufnahmen |
| [Transportaufstellung](../model/pipetting-transfer-ps01.setup.json) | Träger-/Objektbindungen, drei Übergabeplätze und Parkstellung des zweiten Arms |
| [Transferprotokoll](../model/pipetting-transfer-ps01.protocol.json) | Neue Spitzenbox, Rack zur Station und Platte zur Ausgabe; erforderliche Rückmeldungen |
| [Schema](../model/pipetting.schema.json) | Getrennte Verträge für Station, Labware, Aufstellung und Protokoll |
| [Transferschema](../model/labware-transfer.schema.json) | Definition, Aufstellung und Planungsvertrag der Labware-Handhabung |

Die Bank ist eine Referenzfläche, kein ausgewählter Möbelartikel. Der Arm wird
für das Pipettieren mit 280 mm Oberarm und 250 mm Unterarm instanziert. Der
Transportarm verwendet dieselbe Quelle mit 380 mm Oberarm und 350 mm Unterarm,
um die entfernten Deckplätze zu erreichen. Geometrie, Kameras und Gelenkrahmen
werden nicht kopiert. Die längere Variante ist keine Tragfähigkeitsfreigabe.
T01 und seine Nuten bleiben unverändert. Zwei Deckplätze sind anfangs frei.

| Deckreihe, von hinten nach vorn | Links | Mitte | Rechts |
|---|---|---|---|
| S01–S03 | 96 × 10 µl | 96 × 200 µl | 96 × 200 µl |
| S04–S06 | 96 × 200 µl | 96 × 1000 µl | A, B und Puffer |
| S07–S09 | Frei | Plate01, 96 Wells | Frei |

Die ausgewählten Spitzen stammen aus der [gemeinsamen Spitzenquelle](tip-supply.md).
Ihre tatsächlichen Boxkonturen und Sitzhöhen sind weiterhin unbekannt. Die
farbigen, transparenten Boxhüllen von 128 × 86 × 90 mm sind ausdrücklich
Planungsannahmen, keine nachgebauten Herstellerboxen. Die Deckpads sind
konstruktive Aufstellflächen. Die registrierten Spitzenöffnungen liegen für
diesen Aufbau 90 mm über der Trägerauflage, die wiederum 10 mm über dem Pad liegt.
Diese Werte sind Aufstellannahmen, keine Herstellermaße.
Die Belegung benennt jede Spitze als Rackinstanz plus lokale Platz-ID.

## Zweiter Arm für Boxen, Platten und Racks

Der breite Parallelgreifer fasst einheitliche Träger von 134 × 94 mm. Vier Füße
lassen unter der Trägerplatte Platz für zwei Auflagen am Greifer. Nominal greifen
diese je 5 mm unter die Platte; zum Dock bleiben 3 mm Luft. In geöffneter Stellung
bleiben je Seite 7 mm zwischen der Auflage und dem Träger. Die Backen schließen
symmetrisch von 118 auf 94 mm; diese Werte werden aus derselben Quelle in beide
CADs übernommen. Antrieb, Klemmkraft, Retention und Flanschpassung sind offen.
Die native Gesamtszene zeigt eine statische Parkstellung; eine interaktive
Greiferbetätigung und ein ausführbarer Greiferbefehl sind noch nicht angebunden.

Aus derselben Trägerdefinition entstehen Aufnahmen für die vorhandene Well-Platte,
die drei Spitzenklassen und das bestehende leere Zwölfer-Röhrchenrack. Eckanschläge
werden aus den jeweiligen Außenmaßen abgeleitet. Platte und Spitzenöffnungen
werden gemeinsam mit ihrer Auflage angehoben; ihre ursprünglichen IDs bleiben
erhalten. Die Halter selbst sind keine neuen Proben oder zusätzlichen Spitzen.

Rechts stehen `PS01.InfeedTips` und `PS01.InfeedRack`, vorn `PS01.Outfeed`.
Der Transferplan schlägt folgende Folge vor:

1. Eine neue synthetische 200-µl-Spitzenbox von der Zufuhr nach S07 bringen.
2. Das leere Röhrchenrack von seiner Zufuhr nach S09 bringen.
3. `Plate01` von S08 zur Ausgabe bringen.

Dies ist ein eigener Plan, kein ausgeführter Gesamtworkflow mit dem Matrixlauf.
Die Reservebox wird dadurch nicht automatisch in dessen Spitzenbestand gebucht.
Der Plan führt Trägeridentität, bestehende Well-/Spitzenkennungen und lokale
Rackplätze fort. Unbekannte oder belegte Ziele und doppelte Schrittkennungen
werden abgewiesen. Die ursprüngliche Aufstellung bleibt unverändert.

Vor einem Transport fordert der Vertrag die bestätigte freie Parkstellung des
Pipettierarms, das Ende aktiver Flüssigkeitstransfers und die exklusive Freigabe
des gemeinsamen Bereichs. Griff, Identität, Zielbelegung, Absetzen und leerer
Greifer benötigen eigene Rückmeldungen. Pipettieren verlangt umgekehrt den
bestätigt zurückgezogenen Transportarm. Diese Rückmeldungen werden weder erfunden
noch simuliert; eine Steuerung, die die Freigaben tatsächlich erzwingt, fehlt noch.

Die additive [PS01/TR01-Logistik](ps01-logistics.md) implementiert jetzt
synthetische Übergaben ganzer Träger und Anforderungen frischer Boxen für alle
drei Spitzenklassen. Sie führt Jobs, Rollenbelege, Bestand und Verbrauch im selben
Journal-Root. Ihre referenzierte Aufstellung, Aufnahme und geometrische Bahnstudie
sind vom bisherigen statischen PS01-Nachweis getrennt. Hardware, reale Boxmaße
und qualifizierte Rückhaltung bleiben offen. Der
[ursprüngliche Ausbauplan](ps01-interstation-logistics-plan.md) bleibt nachlesbar.

Für die Platte wird die unveränderte offizielle
[Opentrons-Labwaredefinition „Corning 96 Well Plate 360 µL Flat“, Version 1](https://github.com/Opentrons/opentrons/blob/759045308b15973bae25204a580d8cf91f95fd44/shared-data/labware/definitions/2/corning_96_wellplate_360ul_flat/1.json)
mit Revision und SHA-256 referenziert. Original, Lizenz und NOTICE liegen unter
`cad/vendor/opentrons/`. Dies ist eine Labwaredefinition des Automatisierungsanbieters,
kein vollständiges Corning-Fertigungsmodell und keine Kalibrierung unseres Arms.
Die CAD-Hülle übernimmt Außenmaße und zylindrische Well-Freiräume; tatsächliche
Wandprofile, Toleranzen und Flüssigkeitsmenisken sind nicht rekonstruiert.
Die Zuordnung `A1` → `A01` ist ausdrücklich im Adapter enthalten. A liegt hinten,
H vorn; Spalte 1 liegt links. Das Reservoir ist ein eigener, unqualifizierter
Entwurf mit 40 ml Planungsobergrenze je Kammer unterhalb des geometrischen Volumens.

Die sichtbare Konzeptpipette wird aus dem bestehenden, rein geometrischen
`pipette`-Fall von `analytics-tools.shared.json` abgeleitet. Dieser Fall verwendet
nur seine TCP-Länge; der historische `robot_mount`-Verweis des vollständigen Kits
wird nicht auf einen neuen Stand umgeschrieben oder als geprüft übernommen.
Die Station bindet die Hülle ausdrücklich an den aktuellen Armflansch.
Eine passende reale Pipette, Betätigung, Wechselkupplung und Spitzenaufnahme
sind dadurch nicht ausgewählt oder qualifiziert.

## Allgemeiner Protokollumfang

Der Compiler ist nicht auf die Matrix festgelegt. Er unterstützt geordnete
`transfer`-, `distribute`-, `consolidate`-, `fill_to`- und `mix`-Schritte:

- Ein Transfer verbindet zwei benannte Labware-/Well-Orte. Mengen über 1000 µl
  werden in mehrere Hübe aufgeteilt, sofern Quell- und Zielkapazität dies erlauben.
- Eine Verteilung verwendet eine konstante Menge, eine Liste je Ziel oder eine
  Mengenfolge entlang der Reihen beziehungsweise Spalten. Achsenfolgen werden
  gruppiert, um unnötige Wechsel der nominalen Werkzeugklasse zu vermeiden.
- Sammeltransfers führen mehrere Quellen in einem Ziel zusammen. Verdünnungsreihen
  entstehen aus denselben Transfers und ausdrücklich angeordnetem Mischen.
- `fill_to` berechnet die fehlende Menge aus dem aktuellen Planungszustand.
  `mix_after` mischt unmittelbar nach der letzten Abgabe mit derselben Spitze.
  Ein eigenständiger `mix`-Schritt nimmt eine frische Spitze.

Jeder Transferhub erhält eine frische Spitze. Nach Zielkontakt beziehungsweise
Mischen wird sie verworfen; sie kehrt nicht zur Quelle zurück. Ein erschöpfter
10-µl-Spitzenvorrat wird nicht still durch 200-/1000-µl-Spitzen ersetzt. Die Auswahl
verwendet die kleinste ausreichende **nominale** Kapazität. Untere qualifizierte
Dosiergrenzen, Auflösung, Restvolumen und Genauigkeit bleiben `null`.
Reine Nullzugaben verbrauchen weder Flüssigkeit noch Spitzen. Ein ausdrücklich
zusätzlich angeordnetes Mischen benötigt auch dann eine Spitze.

Beispiel eines frei kombinierbaren Schritts innerhalb des Protokollvertrags:

```json
{
  "id": "Aliquot",
  "operation": "transfer",
  "source": {"labware": "Sources", "well": "A01"},
  "target": {"labware": "Plate01", "well": "D07"},
  "volume_ul": 25,
  "mix_after": {"volume_ul": 20, "cycles": 3}
}
```

Die Mengenprüfung weist Überfüllung, Entnahme unter das deklarierte Totvolumen,
unbekannte Orte, doppelte Ziele, unzulässige Werte, Spitzenmangel und Entnahme
aus einer noch ungemischten Mehrkomponentenquelle zurück. Das Mischen verändert
keine Mengen. Bei einer späteren Entnahme aus einer gemischten Quelle wird deren
Zusammensetzung proportional weitergeführt. Anfangs deklarierte Gemische gelten
im Plan als homogen. Das sind ideale Rechenannahmen;
reale Homogenität, Verdunstung, Rückstände und Benetzung sind nicht gemessen.
„Beliebige Pipettierarbeiten“ bedeutet hier frei kombinierbare Aufgaben innerhalb
dieses unterstützten Vertrags. Neue Labwareformen und physikalische Liquidklassen
benötigen einen passenden Adapter und eigene Nachweise.

## Beispiel: zwei unabhängige Reihen auf 96 Wells

A steigt über die zwölf Spalten in 5-µl-Schritten von 0 bis 55 µl. B steigt über
die acht Reihen in 10-µl-Schritten von 0 bis 70 µl. Anschließend ergänzt Puffer
jedes Well auf 200 µl; drei ideale Mischzyklen zu 100 µl schließen es ab.
Die Pipettierauswahl ist pro Well, keine angenommene Mehrkanalpipette.

| Menge | Bedarf | Anfang im synthetischen Beispiel | Rest |
|---|---:|---:|---:|
| A | 2640 µl | 4000 µl | 1360 µl |
| B | 3360 µl | 5000 µl | 1640 µl |
| Puffer | 13200 µl | 15000 µl | 1800 µl |

Das deklarierte Totvolumen beträgt je Quellkammer 200 µl; es ist eine
Testannahme. Alle 96 Zielvolumina betragen 200 µl, zusammen 19,2 ml.
`A01` enthält nur Puffer. `H12` enthält 55 µl A, 70 µl B und 75 µl Puffer.
Die Gesamtbilanz jedes Ausgangsmaterials bleibt erhalten.

Es entstehen **268 Transfers**, 96 abschließende Mischoperationen und vier
logische Werkzeugauswahlen. Benötigt werden 28 Spitzen der 10-µl-Klasse und
240 der 200-µl-Klasse. Die 1000-µl-Klasse ist eingerichtet, wird in diesem
Beispiel aber nicht benötigt; ein Test prüft einen 1500-µl-Transfer in zwei Hüben.

## Ausführen und prüfen

```sh
python3 scripts/run_pipetting_protocol.py plan
python3 scripts/run_pipetting_protocol.py plan --protocol model/pipetting-matrix-96.protocol.json
python3 scripts/run_pipetting_protocol.py handling-plan
python3 scripts/build_pipetting_station.py --backend both
python3 -m unittest discover -s tests -p 'test_pipetting*.py' -v
```

Der Planungsaufruf schreibt einen neuen lokalen Ordner unter `exports/pipetting/`
mit `plan.json`, `well-volumes.csv` und Build-Bericht. Fehler werden vor der
Ausgabe abgewiesen. Mengen werden intern mit Dezimalarithmetik fortgeschrieben.
Ein erneuter Aufruf berechnet erneut denselben isolierten Plan; er setzt keinen
echten Verbrauch zurück und ist keine Fortsetzung eines Material-Journals.
Laufzeitbuchungen im gemeinsamen Material-Root werden hier nicht durchgeführt.

Die vorgeschlagenen Geräteaktionen nennen jeweils eine erforderliche Rückmeldung,
etwa bestätigte Spitzenaufnahme oder abgeschlossene Aspiration. Es werden weder
Quittungen erzeugt noch Gerätebefehle gesendet. `hardware_ready` bleibt `false`.
Ein späterer Ausführungsadapter muss Absichten und Rückmeldungen im bestehenden
Material-Root führen und unklare Wirkungen ohne automatische Wiederholung sperren.

Der native Aufbau schreibt separate Revisionen unter `exports/pipetting-cad/`.
FreeCAD und SolidCraft bauen direkt aus den gemeinsamen Quellen und der
Herstellerbibliothek; kein CAD benötigt die Ausgabedatei des anderen.
Berichte enthalten Quellenpins, Körpermaße, native Dateiprüfsummen, die statische
Parkstellung und bei `both` den Vergleich beider CADs. Die dargestellten
Flüssigkeiten sind aus dem Plan abgeleitete Volumenmarkierungen, keine Beobachtungen.
Physische Spitzen und Herstellerboxen sind mangels vollständiger Maße nicht
enthalten; die sichtbaren Boxhüllen sind als ungemessene Planungskörper markiert.
Verglichen werden Volumen (0,1 % Toleranz), Schwerpunkt und exakte Körpergrenzen
(je 0,02 mm). FreeCAD verwendet dafür `optimalBoundingBox` ohne Triangulation;
die gewöhnliche, netzabhängige `BoundBox` kann bei gekrümmten Gehäusen größer sein.

Der Schema-Test benötigt `jsonschema`. Native Berichtstests sind mit
`SOLIDCRAFTBOT_PIPETTING_NATIVE_TESTS=1` aktivierbar und verlangen einen aktuellen,
bestandenen lokalen Aufbau. Übersprungene Tests sind kein nativer Nachweis.

Die statische Prüfung betrachtet getrennte Stationskörper, beide Arme
gegeneinander und beide Werkzeuge gegen die Ausstattung. Interne bestehende
Arm-/T01-/Werkzeugkonstruktionskontakte und die jeweils zugehörige Flanschmontage
sind ausdrücklich ausgenommen. Die Prüfung ist kein
neuer Selbstkollisionsnachweis und kein Nachweis einer Pipettierbewegung.
Der Transportarm erhält zusätzlich eine Prüfung der Gelenkgrenzen und FK-Abweichung
an 24 diskreten Zielen: Griff- und obere Position an allen neun Deckplätzen und
drei Übergabeplätzen. FreeCAD prüft den Greifer separat an jedem der acht Träger
in drei Backenstellungen, einschließlich des Auflagekontakts bei geschlossenem
Greifer. Diese lokalen Prüfungen sind keine vollständige Entnahme-/Transferbahn.
Vollständige Anfahrt, Eintauchtiefe, Nachbarspitzen, Werkzeug-/Spitzenwechsel und
T01-Kompatibilität bleiben zu entwickeln. Für spätere Bahnen gelten die
gemeinsamen Geschwindigkeits-, Beschleunigungs-, Ruck- und Kein-Halt-Prüfungen.
Eine Modellzeit oder ein bestandener Geschwindigkeitsvergleich mit Menschen
wird hier nicht behauptet.
Ein Browser-/ROS-Adapter für die gesamte PS01-Aufstellung ist noch nicht angebunden.
