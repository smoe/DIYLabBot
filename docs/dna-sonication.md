# DNA-Sonikation: Vorbereitung des getrennten CUT&RUN-Inputs

Der ausführbare Preflight verbindet einen **Gerätekandidaten** mit dem bereits
vorhandenen, getrennt identifizierten Input-Zweig des CUT&RUN-Plans. Er liest
Quellen und berechnet einen möglichen Pulszeitplan. Er schreibt kein Journal,
reserviert nichts und führt keine Laborhandlung aus. `execution_ready` und
`local_qualification` bleiben immer falsch.

H3K4me3- und IgG-angereicherte CUT&RUN-DNA werden nicht zur Sonikation geführt.
Die hier gebundene Sonikation betrifft den Input für die gewählte
Säulenreinigung. CST beschreibt dafür eine empirisch zu optimierende Sonikation
und empfiehlt als Vergleichsziel 100–600 bp. Die bestehende Modellanforderung
**unter 10 kb** für Säulen-Input ist davon getrennt. Beide Angaben sind keine
lokale biologische Abnahme. Ein NanoDrop- oder Qubit-Konzentrationswert belegt
keine Fragmentgrößenverteilung. [CST, VI und Anhang B](https://www.cellsignal.com/learn-and-support/protocols/cut-and-run-protocol)

## Einstieg und führende Quellen

```sh
python3 scripts/prepare_dna_sonication.py
python3 scripts/prepare_dna_sonication.py --require-complete
python3 scripts/prepare_dna_sonication.py --out exports/dna-sonication/plan.json
```

Standardmäßig erscheint JSON auf stdout. Die Vorlage lässt lokale Einstellungen
und Nachweisbezüge ausdrücklich unbekannt; `--require-complete` liefert deshalb
Exitcode **2**. Ungültige Eingaben liefern **1**, gültige offene Planungen ohne
diesen Schalter **0**. `--out` erlaubt nur neue JSON-Dateien unter dem
ignorierten Projektverzeichnis `exports/`; vorhandene Dateien und aus diesem
Bereich führende Symlinks werden abgewiesen.

| Datei | Verantwortung |
|---|---|
| `model/dna-sonication.protocol.json` | Kandidat, Herstellerbezüge, Einheiten-/Parametervertrag, Input-Verknüpfung und Pulssemantik |
| `model/dna-sonication.profile.json` | Pins des Vertrags und bestehenden E1-Profils; offene lokale Bindungen |
| `model/dna-sonication.schema.json` | Formales Schema beider Quellen |
| `scripts/dna_sonication.py` | Wirkungsfreie Komposition mittels `cutrun_preparation.compile_plan()` |

Der Bericht übernimmt Input-Zweig, Ursprungsmaterial, Ursprungsgefäß,
geplantes Prozessgefäß und Produktidentitäten aus dem bestehenden E1-Plan.
`sonicate_input` wird mit dem späteren `check_input_size` und der manuellen
Bindung **S09/O04** verknüpft. Das ist ein Planbezug, keine Bestätigung von O04.
Die tatsächliche Materialidentität zur Laufzeit bleibt offen; eine spätere
Wirkung muss der vorhandene Root mit aktuellem Material-/Gefäßbezug führen.
Es entsteht kein zweiter Bestand. Pins umfassen auch die transitiven E1-Quellen,
Schema und verwendeten Compiler-/CLI-Helfer; sie werden abschließend erneut
geprüft. Alte E1/E3-Quellen und bestehende Läufe werden nicht umgeschrieben.

## Gerätekandidat und lokale Bindungen

**UP200St mit VialTweeter** dient als Kandidat für indirekte Sonikation
geschlossener Röhrchen. Herstellerangaben nennen bis zu zehn Röhrchen und
nominale Röhrchenvolumina von 0,5, 1, 1,5 und 2 ml. Ein bestimmter Artikel,
Füllvolumen, sicherer Verschluss und tatsächlicher Sitz sind damit nicht
bestätigt. Die nominellen 200 W und 26 kHz sind Geräteangaben; daraus wird
weder Energie je Probe noch eine gleiche Energieverteilung berechnet.
[VialTweeter-Datenblatt, Dateistand 13.02.2024](https://www.hielscher.com/wp-content/uploads/FactSheet-VialTweeter-HielscherUltrasonics_eng-13022024.pdf),
[UP200St](https://www.hielscher.com/de/up200st-powerful-ultrasonic-lab-homogenizer.htm)

Der gebundene E1-Input verlangt ausdrücklich die Klasse `tube_1_5ml`. Eine
lokale Nennvolumenangabe von 0,5, 1 oder 2 ml wird deshalb trotz der allgemeinen
Kandidatenbeschreibung abgewiesen. Das Füllvolumen ersetzt oder verändert keine
bestehende E1-Zugabe und belegt noch keine Eignung des Gefäßes.

Amplitude, Kühlung, Temperaturgrenze, Geräteinstanz/Firmware, Gefäßartikel,
Passungsnachweis und empirisch geeignete Einstellungen bleiben lokal zu binden.
Der Hersteller beschreibt einen Sensor in einem Referenzröhrchen sowie
automatische Temperaturpause und Wiederaufnahme. Das misst nicht die Temperatur
jedes geschlossenen Probenröhrchens. Die Zuordnung und Eignung müssen gesondert
belegt werden. Eine solche Pause kann die tatsächliche Laufzeit verlängern.
[Herstellerbeschreibung zu Temperatur und VialTweeter](https://www.hielscher.com/sample-preparation-with-the-ultrasonic-vialtweeter.htm)

Ein vollständig ausgefülltes Testprofil darf ausschließlich
`synthetic_assumption` verwenden. Es macht eine Planberechnung vollständig,
bestätigt aber weder Originalbelege noch Gerätequalifikation oder Ausführung.
Die Prozentwertprüfung 0–100 ist lediglich Zahlensemantik; lokale zulässige
Amplitude und Gerätedutycycle sind nicht daraus abgeleitet.

## Pulszeiten und Ausführungsgrenze

Die führenden Felder sind Zykluszahl, Einschaltzeit je Puls und Pause **zwischen**
den Pulsen. Für `n` Pulse werden `n × Einschaltzeit` und `(n−1) × Pause`
berechnet; nach dem letzten Puls wird keine zusätzliche Pause eingefügt.
Unbekannte Werte bleiben `null`. Dies sind logische Plansekunden, keine
gemessenen Gerätesekunden, keine Temperaturwartezeit und kein Firmwareprogramm.
Die alten synthetischen E1-Werte werden nicht als lokales Pulsrezept übernommen.
E3 behandelt die Sonikationsphase bislang abstrakt und führt keine Pulsfolge
auf einem Gerät aus.

Hielscher veröffentlicht Hinweise zu Browser-/API-Automation für den
**UIP400MTP** sowie ein generisches Beispiel zum lesenden Abruf von
`/mdata.xml`. Modell und Firmware können dessen Felder und Reihenfolge ändern.
Das ist keine gebundene Start-/Stopp-/Quittungsschnittstelle für diesen
UP200St-Kandidaten. Es werden keine Endpunkte aufgerufen. SiLA-/ROS-Adapter,
Hardwaresteuerung und Roboterübergaben bleiben spätere Arbeit.
[UIP400MTP-Automation](https://www.hielscher.com/uip400mtp-automation.htm),
[Herstellerbeispiel für XML-Telemetrie](https://www.hielscher.com/xml-excel-vba.htm)

Vor Effekten müssen Absicht, aktuelle Identität, Beobachtung, Wiederaufnahme,
Abbruch und Ressourcenfreigabe an den vorhandenen Root-/Materialvertrag gebunden
werden. Ein erneuter Preflight wiederholt keine Wirkung und gibt nichts frei.
Hardware, qualifizierte Sonikation, Temperaturnachweis, echte Fragmentgrößen,
SiLA-/ROS-Ausführung und biologische Eignung sind hier nicht nachgewiesen.
Historische Medien, Galerie und Provenienz werden nicht erzeugt oder verändert.

```sh
python3 -B -m unittest discover -s tests -p 'test_dna_sonication.py' -v
```
