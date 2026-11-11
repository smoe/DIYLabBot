# DNA nacheinander mit NanoDrop und Qubit HS messen

Der ausführbare **synthetische** Ablauf bereitet die automatische Folge
NanoDrop One → Qubit 4 mit dsDNA High Sensitivity (HS) vor. Er bietet unverdünnte
Messung sowie **1 Teil Probe + 9 Teile Verdünner (Faktor 10)** und **1 + 19
(Faktor 20)** an. Die Originalproben werden in einem Rack auf dem Tisch
bereitgestellt und nach jeder Entnahme an ihren ursprünglichen Rackplatz
zurückgegeben. Identität, Rackinstanz und Platz werden getrennt geprüft.

Nur `SyntheticBackend` erzeugt die fiktiven Messwerte und positiven
Beobachtungen. Gerätebefehle, Pipettieren, Mischen, Scannen, Robotertransport,
Netzwerkimport und reale Exportformate sind hier **nicht implementiert oder
qualifiziert**. Auch das Inkubationsende wird durch ein protokolliertes
synthetisches Zeitereignis erreicht. Das ist eine Ablaufvorbereitung, keine
automatisch durchgeführte Labormessung oder freigegebene SOP.

## Einstieg

```bash
python3 scripts/run_dna_quantification.py --help
python3 scripts/run_dna_quantification.py demo
python3 scripts/run_dna_quantification.py demo --dilution '1+9'
python3 scripts/run_dna_quantification.py demo --dilution '1+19'
```

Die Vorgabe enthält eine Probe `DNA01` mit 40 µl. NanoDrop entnimmt 1,5 µl,
Qubit 2 µl. Ein Vorverdünnungsansatz verwendet 2 µl Original plus 18 bzw.
38 µl Verdünner in einem eigenen, identifizierten Gefäß im Verdünnungsrack
auf demselben Tisch. Geräte, Rackgeometrie und bestehende Geräteoperationen
werden wiederverwendet; neue CAD-Geometrie wird nicht erzeugt.

Jeder Demoaufruf erzeugt einen eigenständigen **fiktiven** Anfangsbestand.
Wiederholungen einer vorhandenen Probe müssen im selben Lauf erfolgen, damit
der Bestand nicht zurückgesetzt wird. Der Standard-Store ist derselbe wie bei
den bestehenden manuellen Abläufen; `--store` wählt bewusst einen anderen Store
unter `exports/`. Zwischen unabhängigen Stores/Läufen gibt es keine globale
Bestandsübernahme. Root hält beide Geräte, beide Racks, Arbeitsbereich und
lebende Gefäße bis zum bestätigten Abschluss bzw. Abbruch reserviert.

## Nachträgliche Verdünnung und Ergebnisbewertung

Ein zu hoher NanoDrop-Wert hält vor der Qubit-Vorbereitung an. Ein zu hoher
Qubit-Wert hält nach dem Messpaar an. Dann kann ein noch nicht verwendeter,
höherer Faktor angeboten werden. Der neue Ansatz stammt stets aus dem
Original, erhält eine neue Gefäßkennung und wird erneut mit **beiden** Geräten
gemessen. Alle vorherigen Versuche, Messkennungen, Rohdateien und Entnahmen
bleiben erhalten. Pro Probe sind höchstens drei Versuche vorgesehen; eine
serielle Verdünnung und unbegrenzte Wiederholungen sind nicht implementiert.

Beispiel für eine nachträgliche Verdünnung im selben synthetischen Lauf:

```bash
python3 scripts/run_dna_quantification.py demo \
  --qubit-concentration 500 --after-range '1+9'
```

`--after-range` ist eine ausdrücklich vorgegebene Auswahl aus den angebotenen
Optionen. Ohne diese Auswahl bleibt der Lauf zur Entscheidung offen. Für eine
spätere Auswahl nach einem bereits beendeten Messpaar kann derselbe Lauf mit
explizitem Inventarabgleich fortgesetzt werden:

```bash
python3 scripts/run_dna_quantification.py run RUN_ID --simulation \
  --reconcile-input OBS.json --after-range '1+9' --qubit-concentration 500
```

`OBS.json` enthält das vollständig beobachtete Inventar wie unten beschrieben.
Die fiktiven Konzentrationsargumente müssen bei einem neuen `run` erneut
angegeben werden: Der Demo-Treiber speichert sie nicht als Szenariovorgabe;
ohne Argumente verwendet er wieder NanoDrop 50 und Qubit 48 ng/µl.
`choose-dilution` speichert alternativ nur die Auswahl samt **offener Absicht**.
Danach benötigt eine Fortsetzung zusätzlich deren ausdrücklichen
`performed`-/`not_performed`-Abgleich; ein einfaches `run --simulation` wiederholt
oder bestätigt diese Absicht nicht automatisch.

Eine Verdünnung hilft bei einem **zu niedrigen** Signal nicht. Ein niedriger
NanoDrop-Wert lässt die Qubit-HS-Messung noch zu, führt aber nicht automatisch
zu einer erfolgreichen Gesamtbewertung. Unbekannte Einheiten, widersprüchliche
oder unbekannte Geräteflags und ungeklärte Werte sperren die automatische
Annahme. `accept-result --allow-unquantified --reason ...` erlaubt eine
ausdrückliche Bewertung ohne Quantifizierungsfreigabe; der Gesamtbericht
bleibt dann `passed: false`. Widersprüchliche Bereichsverletzungen beider
Geräte erfordern ebenfalls eine Entscheidung. Ein in den Referenzgrenzen
liegendes synthetisches Messpaar belegt keine reale analytische Genauigkeit.

## HS-Ziel und Konzentrationsbezug

Der neue Zielvertrag verwendet den klassischen dsDNA-HS-Assay **Q32851/Q32854**,
200 µl Gesamtansatz, 1–20 µl Probe, 10 µl Standard und mindestens 120 s
Inkubation nach dem Mischen. Sein Bereich ist **0,1–120 ng DNA im Assay**.
Bei den vorgegebenen 2 µl Probe entspricht das 0,05–60 ng/µl des tatsächlich
eingesetzten Materials. Ein pauschaler Konzentrationsbereich ohne Bezug zur
Probenmenge wird nicht verwendet. Grundlage ist die
[Herstelleranleitung MAN0002326, Rev. C.0, 08.03.2022, S. 1/5/8](https://assets.thermofisher.com/TFS-Assets/LSG/manuals/Qubit_dsDNA_HS_Assay_UG.pdf).
Mischung und Inkubation sind synthetische Bestätigungen; eine reale Arbeits-
oder Mischanweisung wird damit nicht qualifiziert.

Die NanoDrop-One-Pedestalreferenz nennt für dsDNA 2–27.500 ng/µl. **2 ng/µl
ist eine Nachweisgrenze, keine qualifizierte Quantifizierungsuntergrenze.**
Diese Werte gelten nicht automatisch für Küvette oder andere Gerätetypen.
Quelle: [NanoDrop One Specifications PS52754_E 0220, S. 2](https://assets.thermofisher.com/TFS-Assets/CAD/Specification-Sheets/NanoDrop-One-Specifications.pdf).

Der Bericht trennt den gemessenen Assaybezug, die Konzentration des
eingesetzten Materials und die auf das Original zurückgerechnete
Konzentration. Qubit-Eingangswerte, die bereits anhand der bestätigten
Ansatzvolumina assaykorrigiert sind, werden nicht erneut mit dem
Assayverdünnungsfaktor multipliziert. Nur der externe Faktor aus den
**tatsächlich bestätigten** Proben- und Verdünnervolumina wird einmal
angewendet. Formel, Faktor, Einheiten und Ursprungsbezug stehen im Ergebnis;
Originalwerte bleiben unverändert. Hintergrund:
[Qubit 4 User Guide MAN0017209, Rev. D.0, S. 24–27](https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0017209_Qubit_4_Fluorometer_UG.pdf).
Das NanoDrop-Rohfeld `Factor` wird nicht als externe Verdünnung verwendet.

Der vorhandene eigenständige synthetische Qubit-100-µl-Testvertrag bleibt
unverändert. Nur die abgeleiteten Kontexte dieses neuen Laufs erhalten den
200-µl-HS-Zielvertrag und die ausdrückliche synthetische Assaykennung
`SYN.DNA.HS`. Reagenzverträglichkeit, reale Kalibrierung und ein passender
Verdünner müssen vor einer Hardwareanbindung separat festgelegt werden.

## Quellen, Buchungen und Unterbrechungen

- `model/dna-quantification.protocol.json` führt Reihenfolge, Verdünnungsteile,
  Wiederholungsregeln und die versionierten Herstellerreferenzen.
- `model/dna-quantification.synthetic.json` bindet die bestehenden Geräteprofile
  und Rackdefinitionen mit Quellprüfsummen und beschreibt Proben, Ursprungsplätze
  und synthetische Anfangsmengen. Das Profilschema steht in
  `model/dna-quantification.schema.json`; der Loader prüft zusätzlich Semantik
  und Quellenpins.
- `scripts/dna_quantification.py` führt ein Root-Journal mit kanonischem
  Gefäßinventar, Entnahmebuchungen und neuen Gerätekontexten je Versuch.
  `ManualOperations`, `NanoDropOperations` und `QubitOperations` werden durch
  Kontextansichten wiederverwendet. Es gibt keine zweite führende Probenbilanz.

Vorverdünnung und Probenentnahmen speichern ihre Absicht dauerhaft vor der
Verbrauchsbestätigung. Rückgabe und Entsorgung sind ausdrücklich bestätigte
Ereignisse ohne eigenen getrennten Absichtszyklus.
Originalverbrauch entsteht bei einem Verdünnungsansatz genau einmal durch
den Aliquottransfer. Spätere NanoDrop- und Qubit-Entnahmen belasten den Ansatz;
Qubit-Messung und Entsorgung belasten das Original nicht nochmals. Abweichende
bestätigte Mengen brauchen eine Begründung. Unbekannte Anfangsmengen oder
offene Entnahmen bleiben unbekannt. Massenfreigaben werden durch Entnahmen
entwertet und nicht aus Volumen geschätzt.

`status RUN_ID` und `report RUN_ID` lesen ohne Sitzungsübernahme. Für Änderungen
nach Sitzungsende ist ein ausdrücklicher Abgleich nötig. `--resume` übernimmt
eine noch offene alte Sitzung und entwertet deren Schreiber. Mit
`--reconcile-input DATEI` können explizite Abgleichdaten **im selben Prozess**
vor dem nächsten Befehl angewendet werden. Die JSON-Datei enthält mindestens
`observations` (vollständige Gefäßkennungen, Probenkennungen und beobachtete
Orte) und `workspace_clear: true`; offene Absichten benötigen zusätzlich eine
passende `pending_resolution` mit Absichtskennung und `performed`,
`not_performed` oder `unknown`. Bei ausgeführter Verdünnung gehören beobachtete
Quell-/Zielgefäße, tatsächliche Volumina, Misch- und Rückgabebestätigung dazu.
`unknown` gibt weder Bestand noch Ressourcen frei. Der Abgleich ist eine
ausdrückliche synthetische Eingabe, keine Messung oder Scannerbestätigung.

Bereits begonnene Gerätekontexte werden auch nach Abgleich vom Demo-Treiber
nicht automatisch erneut ausgeführt. Solche Kontexte können über die
gerätebezogenen Python-Operationen geprüft fortgeführt oder über Root
abgebrochen werden. Verlorene Blank-/Kalibrierungsbestätigungen werden nicht
angenommen. Für `cancel`/`finish-cancel` müssen offene Effekte abgeglichen,
Originale zurückgegeben und abgeleitete Gefäße ausdrücklich entsorgt werden.
Abbruchabsicht und Reservierungen überleben einen Neustart. Auch beim normalen
Abschluss bleibt Restmaterial im Verdünnungsgefäß bis zur bestätigten
Entsorgung inventarisiert; der Bericht erhält die entsorgte Restmenge.

Laufzeitdaten und Originalartefakte liegen ausschließlich im ignorierten
Bereich unter `exports/`. Quelländerungen sperren alte Läufe ohne stille
Migration. Historische Medien, deren Provenienz, bestehende Standalone-Fixtures,
CF01 und die separate NanoDrop-UltraC-Netzwerkanbindung werden nicht verändert.

## Prüfung

```bash
python3 -m unittest discover -s tests -p 'test_dna_quantification_*.py' -v
```

Die Tests prüfen Bereichsbezug, F10/F20, getrennte Gerätewerte, Rohdaten,
Verbrauch, Rackrückgabe, nachträgliche Messpaare sowie Abbruch/Wiederaufnahme.
Ein bestandener Lauf ist ein lokaler synthetischer Funktionsnachweis; er ist
kein Hardware-, Netzwerk-, Bewegungs- oder Sicherheitsnachweis.
