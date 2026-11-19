# PS01 / TR01: Rackübergabe und Spitzenbox-Nachschub

Der synthetische V1-Lauf übergibt ganze LT01-Träger zwischen zwei referenzierten
PS01-Stationen. Er kann frische Boxen für **10, 200 und 1000 µl** anfordern,
konkreten Vorrat zuordnen, über TR01 liefern und anschließend lokal auf das Deck
setzen. Rack-, Gefäß-, Platz- und Spitzenidentitäten bleiben erhalten.

Dies ist eine lokale Modellimplementierung. Ihre Rollenbelege sind ausdrücklich
`test_fixture`, der Laufzeitadapter ist `teleportation_mock`. Er bewegt weder
Motoren noch reale Proben und misst keine Fahrzeit. Die getrennte CAD-Bahnstudie
ist kein ausgeführter Transportauftrag und keine automatische Bestätigung.

## Gemeinsame Quellen

- [`ps01-logistics.shared.json`](../model/ps01-logistics.shared.json) und
  [Schema](../model/ps01-logistics.schema.json): referenzierte Stationen,
  Übergabeplätze, TR01-Aufnahme und einmalig aufzunehmender Testbestand.
- [`labware-logistics.transport.json`](../model/labware-logistics.transport.json):
  additive Bindung des vorhandenen Transportkerns an typisierte Manifeste für
  `tube_rack`, `well_plate` und `tip_box`.
- [`ps01-logistics.motion.json`](../model/ps01-logistics.motion.json): getrennte
  geometrische Demonstration mit referenzierten Arm-, Proben- und Fahrzeuggrenzen.
- Bestehende [PS01](pipetting-station-ps01.md), [LT01-Quelle](../model/labware-transfer.shared.json),
  [TR01-Quelle](../model/sample-transport-tr01.shared.json) und
  [Spitzenquelle](tip-supply.md) bleiben die Definitionen ihrer Baugruppen.

Die zweite Station `RF02` ist eine weitere Instanz derselben PS01-Definition.
Die Aufstellung setzt die Arbeitsflächen auf 900 mm und definiert für diesen
Versuch drei frontseitige Übergabeplätze. Sie verändert weder das ursprüngliche
PS01-Setup noch einen Gebäuderaum. Der Abstand ist eine synthetische Aufstellung,
keine vermessene Registrierung im Labor.
Fest belegte Deckplätze, etwa der Reservoirplatz, werden aus dieser Definition
abgeleitet und nicht als freie Transportziele angeboten.

## Lokal ausführen

```sh
python3 scripts/run_ps01_logistics.py demo
```

Der Befehl legt unter `exports/ps01-logistics/` einen Journal-Root und einen
JSON-Bericht an. Der Testbestand wird ausdrücklich aufgenommen. Danach läuft
ein Rack mit zwei identifizierten, geschlossenen Gefäßen hin und zurück; für
10 und 1000 µl wird je eine volle Box angefordert; für 200 µl werden die zwei
Boxen des Matrix-Fehlbedarfs nacheinander geliefert und auf freie Deckplätze
gesetzt. Der Bericht enthält die Jobs, Belege,
Holds, Anforderungen und tatsächlichen verbleibenden Spitzenidentitäten.

Für einen eigenen synthetischen Lauf:

```sh
python3 scripts/run_ps01_logistics.py init --run-id MeinTest
python3 scripts/run_ps01_logistics.py status --run-id MeinTest
python3 scripts/run_ps01_logistics.py forecast --run-id MeinTest --station PS01
```

`init` gibt eine Sitzungskennung zurück. Jede spätere Mutation benötigt diese
mit `--session`; `resume` erzeugt eine neue Sitzung und sperrt unklare Jobs.
Zuerst werden `admit` und aktuelle `access`-Beobachtungen benötigt. `act` liest
die Argumente aus einer JSON-Datei, etwa für eine Anforderung:

```json
{
  "demand_id": "Mehr200",
  "station": "PS01",
  "variant": "tip_200_ul",
  "boxes": 2,
  "reason": "Naechster Matrixlauf"
}
```

```sh
python3 scripts/run_ps01_logistics.py act --run-id MeinTest \
  --session SITZUNG --operation request_tips --request-id Anforderung200 \
  --arguments anforderung.json
```

`serve` ordnet passende volle Boxen zu und bereitet jeweils einen nächsten
Transportjob vor. `mock-complete --job-id JOB` dispatcht diesen erst nach dem
Journal-Commit und spielt ausdrücklich synthetische Belege ein. Empfangene
Boxen müssen mit `transfer` vom Eingang auf einen freien Deckplatz gelangen.
Der CLI-Demolauf zeigt diese gesamte Folge in
[`run_ps01_logistics.py`](../scripts/run_ps01_logistics.py).

## Bestand, Verbrauch und Wiederaufnahme

Der bestehende Journal-Root hält allein den veränderlichen Bestand. Die Queue
des vorhandenen `async_transport_domain` enthält gebundene Transportmanifeste,
keine zweite veränderliche Spitzenbilanz. Der neue Adapter verwendet dieselbe
Zustandsmaschine und dieselben vier Rollenbelege wie der bisherige Transport.
Das interne historische Feld `rack_id` bezeichnet im typisierten Vertrag den
Träger; `payload_kind` unterscheidet die Fracht ausdrücklich.

- Eine Anforderung erzeugt keinen Bestand. Nur volle, unbenutzte, geschlossene,
  als geeignet bestätigte Boxen der angeforderten Variante werden zugeordnet.
  Teilboxen und andere Größen werden nicht als Ersatz geliefert.
- Fehlbestand, ein belegter Eingang oder fehlende Freiraumbeobachtungen führen
  zu einem benannten Wartegrund. Ein neuer Scheduling-Versuch benötigt eine neue
  Request-ID; Wiederholung derselben Request-ID bleibt wirkungsgleich.
- Angeforderter Nachschub reduziert den noch anzufordernden Bedarf, ist aber
  vor bestätigter lokaler Bereitstellung kein nutzbarer Deckbestand. Empfang
  bucht nicht erneut 96 Spitzen. Erfüllte Anforderungen bleiben auch nach
  späterem Verbrauch oder Rücktransport historisch erfüllt.
- `begin_tip_use` speichert konkrete Spitzenidentitäten vor einem Verbrauch.
  Erst `confirm_tip_use` mit einer passenden Testbeobachtung markiert sie als
  benutzt. Ihre Identitäten bleiben erhalten; dieselbe Spitze wird nicht zweimal
  belastet. Öffnen, Eignung und Deckposition werden getrennt geprüft.
- Dispatch, Worker-Claim, Personenbestätigung und bestätigter Gewahrsam sind
  verschiedene Ereignisse. Unvollständige, widersprüchliche oder verspätete
  Belege sperren die Fortsetzung. Auch ein verspäteter negativer Rückhaltebeleg
  hält abhängige Folgeaufträge an.
- Neustart füllt keinen Bestand auf und wiederholt keine unklare Wirkung.
  Sitzung, Sources, Schreibrevision und Ressourcen werden geprüft. Unklare
  Jobs benötigen extern eingegebene synthetische Abgleichbelege; der Runner
  erfindet sie nicht aus seinem Ledger.

Die Matrix-Bedarfsansicht verwendet den vorhandenen Pipettiercompiler in einem
reinen Prognosemodus, der auch bei erschöpftem Spitzenbestand noch den Bedarf
meldet. Im aufgenommenen Testfall stehen 68 / 48 / 96 Spitzen zur Verfügung;
der nächste Matrixlauf benötigt 28 / 240 / 0. Daraus folgen **zwei volle
200-µl-Boxen**, ohne neue Anforderungen für 10 oder 1000 µl. Diese Rechnung
behauptet keinen zuvor real ausgeführten Pipettierlauf.

## Aufnahme, Geometrie und Bewegung

Die zusätzliche TR01-Aufnahme nutzt dessen vorhandene Auflagestellen und
Passstifte. Die Basis erhält die zugehörigen Freistellungen und vier Eckführungen;
die mittleren Greifbereiche bleiben zugänglich. Der gegenüberliegende belegte
Röhrchenträger bleibt als Nachbarlast im Modell. Die höhere abnehmbare Haube wird
aus der größten verwendeten Boxhülle abgeleitet.

Die Haube und die Rückhaltung verlangen eine ausdrückliche manuelle
Testbestätigung. Ein automatischer Öffner oder eine qualifizierte Verriegelung
wird damit nicht implementiert. Die Spitzenboxen sind weiterhin ungemessene
LT01-Planungshüllen, keine Herstellerkonturen. Geschlossene Röhrchen und eine
synthetisch versiegelte Platte sind getrennte Transportzustände; eine offene
Matrixplatte erhält dadurch keine Freigabe.

Die Bahnquelle erzeugt C2-Gelenk-PVA für Anfahrt, Greifen, durchgehenden
beladenen Transfer, Freigabe und Rückzug. Entnahme- und Transitpunkte erzeugen
keinen Halt. Greif- und Freigabebewegungen sind getrennte Vorgänge; notwendige
Beobachtungszeiten bleiben unbekannt. Die gesamte Last wird über ein
konservatives Punkthüllvolumen und FK-Intervallgrenzen geprüft, einschließlich
Orientierung. Adaptive Verfeinerung verwendet Stichproben nur als Entscheidung
für weitere Verfeinerung, niemals als Ersatz für eine obere Grenze.

FreeCAD und SolidCraft bauen direkt aus denselben Quellen. CAD-Dateien sind
keine Laufzeitabhängigkeit des Journals. Lokale Artefakte und Prüfsummen liegen
unter `exports/ps01-logistics-cad/`; ein fehlender oder nicht bestandener
Bewegungsbericht ist keine Kollisionsfreigabe.

### Native Modelle und Animation erzeugen

Ein neuer Build benötigt einen neuen Ausgabeordner. Die Toolpfade können mit
`--freecad-python` und `--solidcraft-cli` ausdrücklich angegeben werden.

```sh
python3 scripts/build_ps01_logistics.py --backend both \
  --output exports/ps01-logistics-cad/review
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib \
  /Applications/FreeCAD.app/Contents/Resources/bin/python \
  scripts/audit_ps01_logistics_freecad.py exports/ps01-logistics-cad/review continuous
python3 scripts/audit_ps01_logistics_solidcraft.py \
  exports/ps01-logistics-cad/review \
  --solidcraft-cli /Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli \
  --partition exports/ps01-logistics-cad/review/freecad-continuous.json
python3 scripts/export_ps01_logistics_animation.py exports/ps01-logistics-cad/review
python3 scripts/report_ps01_logistics.py \
  --freecad exports/ps01-logistics-cad/review \
  --solidcraft exports/ps01-logistics-cad/review \
  --animation exports/ps01-logistics-cad/review \
  --output exports/ps01-logistics-cad/final-report.json
```

`--partition` ist optional. Es übernimmt ausschließlich eine vollständige
Intervallaufteilung als Startpunkt; SolidCraft prüft seine eigenen nativen
Körper und Abstände in jedem Intervall erneut. Beide CAD-Generatoren sind
voneinander unabhängig. Der Bericht prüft zusätzlich die Körperzuordnung,
Volumina, Schwerpunkte und Grenzen beider Modelle.

Die SolidCraft-Bauteile entstehen bereits in ihrer Nullstellung. Ihre native
Instanztransformation wird deshalb direkt aus der gemeinsamen FK gesetzt.
Eine zusätzliche inverse Home-Transformation wäre falsch. Der optionale
Buildschalter `--reuse-solidcraft` verwendet vorhandene native Körper nur bei
identischen vollständigen Geometriebefehlen; abweichende Instanzstellungen
werden mit ausdrücklich protokollierten nativen Bewegungsbefehlen korrigiert.

Für eine wiederholte FreeCAD-Ableitung kann
`verify_ps01_logistics_breps.py ALTER_ORDNER NEUER_ORDNER` die serialisierten
nativen Körper einschließlich ihrer Platzierungen bytegenau vergleichen.
Nur mit identischer Bahn und Körper-/Rahmenzuordnung darf der Sammelbericht
über `--freecad-audit ALTER_ORDNER` auf den erhaltenen früheren Nachweis verweisen.
Historische Berichte werden dabei nicht umgeschrieben.

Die Animation verwendet die nativen FreeCAD-Netze und FK-Abtastungen der
exportierten PVA-Kurve mit mindestens 30 Hz. Ihre Modellzeit beträgt für den
Racktransport **58,804 s**, Wiedergabefaktor **1×**. Manuelle Haubenhandhabung
und unbekannte Rückmeldezeiten kommen hinzu. Die HTML-Datei enthält alle
Darstellungsdaten lokal; ihre Abtastung ist selbst kein Kollisionsnachweis.

## Prüfgrenzen

Die CAD-freien Tests prüfen Rücktransportidentitäten, alle drei Spitzenklassen,
Fehlbestand, belegte Ziele, doppelte Anforderungen, vertauschte Quittungen,
fehlende Belege, verspätete Konflikte, Verbrauch, Neustart und konkurrierende
Schreiber. Der unveränderte v1-Vertrag erhält eigene Regressionstests.

```sh
python3 -m unittest discover -s tests -p 'test_ps01_logistics*.py' -v
SOLIDCRAFTBOT_PS01_LOGISTICS_NATIVE_TESTS=1 \
  python3 -m unittest discover -s tests -p test_ps01_logistics_native.py -v
```

Der optionale native Test benötigt den aktuellen Sammelbericht und seine
unveränderten Artefakte. Ohne Schalter wird er ausdrücklich übersprungen;
das ist kein bestandener CAD-Nachweis. Die Schema-Prüfung benötigt `jsonschema`.
Der native Bewegungsnachweis bezieht sich auf **Rack01 mit zwei geschlossenen
Gefäßen von PS01.Outfeed über TR01 nach RF02.InfeedRack**. Die Laufzeittests
decken außerdem Spitzenboxen und lokale Deckwechsel ab; deren vollständige
native Bahnen sowie ein Plattentransport sind damit noch nicht geprüft.

Prüflauf vom 19. November 2026: 19 Laufzeit-, acht Geometrie-/Bahn- und 85
bisherige Transporttests bestanden. Der Demolauf enthält 112 Journalereignisse
und 15 abgeschlossene Transportjobs. Am PS01-Deck stehen danach 164 / 240 / 192
unbenutzte Spitzen für 10 / 200 / 1000 µl zur Verfügung. Der Zweibox-Test
bestätigt das Warten der zweiten 200-µl-Lieferung am belegten Eingang.

Die kontinuierliche Rackprüfung besteht in FreeCAD mit 871 Intervallen und
1.731 nativen Prüfstellungen sowie in SolidCraft mit 946 Intervallen und
1.021 Prüfstellungen. Beide prüfen 19.948 Körperpaare unter den im Bericht
benannten Montage-/Gelenkausschlüssen. Für vorgesehene Auflagekontakte gilt
eine numerische Abstandstoleranz von 0,002 mm; positive native Überlappungen
über 0,0001 mm³ werden abgewiesen. Das ist keine physische Eindringfreigabe.
Es handelt sich um konservative Intervallgrenzen mit numerischem Schutzabstand,
nicht um ein formales Gleitkommazertifikat.

Alle 605 semantischen Körper stimmen zwischen den CAD-Modellen innerhalb der
Prüfgrenzen überein: maximale relative Volumenabweichung 0,0104 %, maximale
Schwerpunktabweichung 0,00112 mm und maximale Abweichung der Körpergrenzen
0,000156 mm. Alle sechs Armfahrten bestehen zusätzlich die erneut aus dem
exportierten JSON berechnete Kein-Halt-Prüfung.

Der lokale Sammelbericht liegt unter
`exports/ps01-logistics-cad/final-report.json`. Er bindet den aktuellen
FreeCAD-Aufbau `native03`, die unabhängige SolidCraft-Ableitung `solid02` und
die bytegenau zugeordnete FreeCAD-Prüfung sowie Animation unter `verified01`.
Die separate Nachprüfung des Bewegungsexports liegt unter
`native03/exported-motion-check.json`. Laufzeitjournal und Ergebnis des
Demolaufs stehen unter `exports/ps01-logistics/release/`. Diese Ausgaben bleiben
lokal und ignoriert; sie sind keine zusätzlichen führenden Modellquellen.

Laufübergreifender Stock-Import, mehrere unabhängige Owner/Stores, Geräte- und
Transportnetzwerk, reale Scanbelege, Motorsteuerung, Ladungssicherung,
Tragfähigkeit, Dosiereignung und Sicherheitsqualifikation bleiben offen.
Dass das Bewegungsmodell seine übernommenen Grenzen einhält, beweist keine
biologische oder mechanische Qualifikation. TR01s bisherige 200-mm/s-Grenze
bleibt bestehen. Ein gemessener menschlicher Vergleich fehlt; das Ziel
„schneller als manuell“ wird deshalb nicht als erfüllt ausgewiesen.
