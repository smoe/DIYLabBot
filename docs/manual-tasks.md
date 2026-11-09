# Manuelle Aufgaben und Messgeräte

**Status: Synthetische NanoDrop-/Qubit-Einzelabläufe und ein gemeinsamer CF01–NanoDrop–Qubit-Gesamtlauf.**
Die konkrete Ausführung, Quellen, Zustände und Prüfgrenzen stehen in
[NanoDrop](nanodrop-manual-workflow.md) und
[Qubit 4](qubit-4-manual-workflow.md).
Der [Gesamtlauf](synthetic-lab-workflow.md) führt zwölf Originale auf einem
gemeinsamen Inventar mit einmaligen Anfangsmengen, Buchungen und Reservierungen.
Die drei Gerätestufen verwenden getrennte Zustände und dieselbe Prozessuhr.
Auf Eigentümerwunsch sind zunächst sämtliche Eingaben, SOPs und CSV-Dateien
synthetisch. Die nachfolgende übergreifende Planung umfasst auch spätere Schritte;
Netzwerkadapter, echte Exportqualifikation und reale Mensch-Maschine-
Übergaben sind noch nicht implementiert beziehungsweise geprüft.

## Ziel

Manuelle Arbeitsschritte sollen sich in denselben Ablauf einfügen wie Roboter-
und Stationsschritte. Erstes Anwendungsfeld sind Konzentrationsmessungen an
drei vorhandenen Gerätetypen.

Leitgedanke: **Handarbeit und Datenübernahme werden unabhängig voneinander
beschrieben.** Eine Person kann Proben vorbereiten und messen, während die
Software die Ergebnisse anschließend aus dem Gerät übernimmt. Ebenso kann eine
Person Ergebnisse von Hand erfassen, wenn kein Datenweg besteht.

Wie im [synthetischen CF01-Ablauf](../ARCHITECTURE.md#synthetische-minimale-testumgebungen)
werden Geräteaufstellung und Arbeitsprotokoll getrennt gebunden. Derselbe Ablauf
soll später ohne Änderung in L01 laufen.

## Gerätetypen und Fähigkeiten

| Gerätetyp | Fähigkeit für die Planung | Vorgesehener Datenweg |
|---|---|---|
| NanoDrop One mit WLAN | Mikrovolumen-Absorption UV/Vis | Dateibasierter CSV-Berichtsimport, bisher synthetisch geprüft |
| NanoDrop UltraC, NDULTRACGL | Mikrovolumen-Absorption und Küvette | Lesende Web-API laut Handbuch; Verfügbarkeit am konkreten Softwarestand prüfen |
| Qubit 4 | Assayabhängige Fluoreszenzmessung einzelner Messgefäße gegen Standards | Eigener synthetischer Dateiimport, keine native Exportqualifikation |

Das Verkaufspaket aus NanoDrop One und Qubit 4 wird als zwei eigenständige
Geräte geführt.

Gerätetypen sollen analog zum [Möbelkatalog](../model/furniture/laboratory.catalog.json)
in einem Katalog stehen und Fähigkeiten deklarieren, zum Beispiel
Mikrovolumen-Absorption, Küvettenabsorption oder fluorometrischer Assay.
Arbeitsprotokolle verlangen eine Fähigkeit, keinen bestimmten Gerätetyp. Eine
Geräteinstanz bindet den Typ an einen Standort. Damit verwenden One und UltraC
von selbst dieselbe Protokollquelle.

Für den ersten Durchstich wird keine CAD-Geometrie der Messgeräte benötigt.
Es werden keine geschätzten Bauräume als Gerätegeometrie angelegt. Die heutige
CF01-Szene verlangt genau die Geräte Arm, CF01 und Rack
([synthetic_workspace.py](../scripts/synthetic_workspace.py), `materialize_scene`).
Ein Messgerät gehört deshalb in eine eigene Aufstellung oder braucht eine
ausdrücklich nicht geometrische Bindung. Beides wäre eine Schemaerweiterung.

## Gemeinsamer Mechanismus für manuelle Aufgaben

Übernahme, Bearbeitung, Ergebniserfassung, Probenrückgabe und Wiederfreigabe
werden einmal implementiert und von allen Messprotokollen verwendet.

### Übergabe als Besitzwechsel

Eine Übergabe an eine Person ändert die Verantwortlichkeit. Der physische
Gefäßort wird davon getrennt geführt, etwa weiterhin ein Platz im übernommenen Rack.
[cf01_rack_batch.py](../scripts/cf01_rack_batch.py) führt bereits Inventar für
Rack, Rotor und Greifer und prüft die Probenidentität bei jeder Übergabe. Eine
Person kann im gemeinsamen manuellen Kern auch ein einzelnes Gefäß halten;
der CF01-Runner wird dafür nicht um menschliche Verzweigungen erweitert.

- **Vorbedingung:** Vor der Übernahme liegt ein gemeldeter Zustand „Arbeitsbereich
  für Menschen frei“ vor, analog zu `robot_clear` im
  [CF01-Vertrag](../model/centrifuge-cf01.protocol.json). Im Mock ist das eine
  synthetische Eingabe, keine Sicherheitsfunktion. Der Mensch-Maschine-Betrieb
  bleibt unqualifiziert.
- **Frist statt Heartbeat:** Eine Person sendet keine Lebenszeichen. Die Aufgabe
  erhält eine Frist mit Eskalation. Ein Fristablauf führt in den Zustand
  „Klärung nötig“, nicht zu einem Fehler mit automatischem Wiederanlauf.
- **Rückgabe Platz für Platz:** Jeder Rackplatz wird einzeln bestätigt, nicht
  mit einem einzigen „fertig“. Grundlage sind die stabilen Platz-IDs aus
  [rack_slots.py](../scripts/rack_slots.py). Proben-IDs und ursprüngliche
  Rackplätze müssen erhalten bleiben.
- **Art der Bestätigung:** Eine Bestätigung durch die Person, ein Barcode-Scan
  und eine Kameraprüfung sind unterschiedlich belastbar. Die Art wird mit jeder
  Bestätigung gespeichert.

### Aufgabenzustände

| Zustand | Bedeutung |
|---|---|
| Angeboten | Aufgabe und Proben bereitgestellt, Arbeitsbereich frei gemeldet |
| Übernommen | Person hält die Proben; Frist läuft |
| In Bearbeitung | Messschritte laufen |
| Ergebnisse erfasst | Alle erwarteten Messungen zugeordnet oder ausdrücklich als fehlend markiert |
| Zurückgegeben | Alle Plätze einzeln bestätigt |
| Geprüft | Inventar, Reihenfolge und Ergebniszuordnung stimmen |
| Freigegeben | Folgeschritte dürfen fortfahren |
| Klärung nötig | Frist abgelaufen, Widerspruch oder Wiederaufnahme nach Unterbrechung |
| Abgebrochen | Bewusst beendet; verbleibende Proben bleiben im Inventar erfasst |

Diese Tabelle beschreibt Zielzustände. Die implementierten NanoDrop-Zustände
und einzelnen Freigabebedingungen stehen in der verlinkten Ausführungsdokumentation.

### Laufprotokoll und Wiederaufnahme

- Protokolle und Gerätetypen sind Modellquellen und gehören nach `model/`.
- Aufgaben, Bestätigungen und Importe sind Laufzeitzustand. Sie gehören in ein
  fortlaufend ergänztes Laufprotokoll außerhalb von `model/`. Der aktuelle
  Zustand wird daraus abgeleitet und nicht separat gepflegt.
- Nach einer Unterbrechung wird das Laufprotokoll erneut eingelesen. Offene
  Aufgaben gehen in „Klärung nötig“. Der physische Zustand wird neu bestätigt;
  ein Abschluss wird nie angenommen. Das entspricht der CF01-Regel, nach einem
  Fehler nie automatisch neu zu starten.
- Die dauerhafte Speicherung gilt erst als geprüft, wenn ein Test mit Abbruch und
  Neustart bestanden ist.

### Fehlerfälle

Mindestens zu behandeln und zu testen:

- Gefäß an einem falschen Platz zurückgegeben, fehlend oder zusätzlich vorhanden.
- Probe von der Person einbehalten, verschüttet oder vollständig verbraucht.
- Messung fehlgeschlagen oder wiederholt; Messwerte außerhalb des Messbereichs.
- Nicht zuordenbare, doppelte oder fremde Messungen im Import.
- Frist abgelaufen; Unterbrechung mit Neustart.

## Probenverbrauch und Abstammung

Jede Messung entnimmt Volumen aus einem Quellgefäß. Für Mikrovolumenmessungen
sind typischerweise 1–2 µl je Messung üblich; der Wert hängt vom Messmodus ab
und ist aus den Herstellerangaben zu übernehmen. Ein unbekanntes entnommenes
Volumen bleibt `null`.

Ein gemeinsames Modell beschreibt Quellgefäß, entnommenes Volumen und optional
ein abgeleitetes Gefäß mit eigener ID und Verweis auf das Ausgangsgefäß.
Bei NanoDrop sind Entnahme und Aliquotkennung dokumentiert. Qubit ergänzt einen
ausdrücklichen Transferdatensatz und ein identifiziertes Messgefäß; ein weiterer
physischer Aliquotbehälter wird nicht erfunden. Beide benutzen dieselbe
Verbrauchsfunktion. Anfangsmengen bleiben pro Lauf deklariert; ein
laufübergreifendes Volumenbuch ist noch nicht vorhanden.

**Folge für CF01:** Nach einer Entnahme ändert sich die Probenmasse. Folgt danach
ein Schleuderlauf, braucht jede Probe eine frische Massebestätigung. Der Vertrag
lässt das nominale Volumen nicht als Ausgleichsmessung gelten (`ConfirmSeated` in
[centrifuge-cf01.protocol.json](../model/centrifuge-cf01.protocol.json)).

## Ergebniszuordnung

### Abgleich

Die Zuordnung von Messung zu Probe ist die fehleranfälligste Stelle.

- Jede erwartete Messung erhält eine aufgabenbezogene Mess-ID. Sie wird am Gerät
  als Probenname eingetragen und ist der Schlüssel für den Import.
- Fehlende, doppelte oder fremde Messungen kommen in Quarantäne. Sie werden
  nicht automatisch zugeordnet.
- Reihenfolge oder Zeitstempel sind kein Zuordnungsschlüssel. Das gilt
  besonders für Namen, die von Hand eingetippt werden.

### Gemeinsames Grundformat

Alle Adapter liefern dasselbe Grundformat. Ein einzelner Wert mit Einheit reicht
nicht, weil beide Gerätearten mehrere Größen je Messung liefern.

| Feld | Inhalt |
|---|---|
| Identität | Mess-ID, Proben-ID, Aufgaben-ID, Geräteinstanz |
| Methode | Messverfahren und Parameter, zum Beispiel Probentyp, Faktor, Assay |
| Größen | Liste aus Name, Wert und ausdrücklicher Einheit |
| Replikate | Einzelmessungen; Mittelwerte nur als abgeleitete, gekennzeichnete Größe |
| Bezugsmessungen | Blank beziehungsweise Standards und Kalibrierung |
| Gerätemeldungen | Wörtlich übernommene Qualitäts- und Bereichsmeldungen |
| Eigene Bewertungen | Getrennt geführt, mit benannter Regel |
| Herkunft | Originaldatei oder API-Antwort mit SHA-256, Adapter und Adapterversion, Art der Erfassung |

| Gerätetyp | Größen und Parameter |
|---|---|
| NanoDrop | Konzentration, A260/A280, A260/A230, Probentyp (zum Beispiel dsDNA, RNA, Protein), Faktor, Bezug auf den Blank |
| Qubit | Konzentration im Messgefäß und berechnete Konzentration der Originalprobe, jeweils mit eigener Einheit; Verdünnung, Assay, Kit-Charge, Standards und Kalibrierung, Bereichsmeldungen |

NanoDrop- und Qubit-Ergebnisse bleiben getrennte Messungen mit unterschiedlicher
Methode. A260 erfasst alle absorbierenden Nukleinsäuren, ein Qubit-Assay misst
farbstoffspezifisch. Die Werte werden nie gemittelt oder gegeneinander
abgeglichen.

## Arbeitsprotokolle

### NanoDrop-Mikrovolumenmessung

Ein gemeinsames Protokoll für One und UltraC verlangt die Fähigkeit
Mikrovolumen-Absorption:

1. Messflächen reinigen und Blank mit dem Probenpuffer messen.
2. Je Probe die vorgesehenen Replikate mit der jeweiligen Mess-ID messen.
3. Zwischen den Proben reinigen; Blank bei Bedarf wiederholen.
4. Ergebnisse über den Adapter des Geräts übernehmen oder von Hand erfassen.

Gerätespezifische Bedienhinweise und Exportadapter werden referenziert, nicht
kopiert. Küvettenmessungen erhalten bei Bedarf einen eigenen Ablaufbaustein für
Geräte mit dieser Fähigkeit.

### Qubit-Messung

Originalprobe, entnommenes Aliquot und vorbereiteter Messansatz werden über das
Abstammungsmodell verknüpft. Assay, Arbeitsanweisung, Kalibrierung, Volumina
und Zeitbedingungen wie die Inkubation sind ausdrückliche Parameter.
Probenvolumen und Ansatzvolumen folgen der Anleitung des gewählten Kits. Der
konkrete Assay ist noch festzulegen.

## Datenwege und Prüfgrenzen

- Der erste Import ist dateibasiert. Auf Eigentümerwunsch dienen zunächst
  ausdrücklich synthetische CSV-Dateien als Fixtures. Eine echte Exportdatei
  bleibt ein späterer Qualifikationsschritt. Von Hand erzeugte Tabellen werden
  mit eigener Herkunft gekennzeichnet und durchlaufen denselben Abgleich.
- Ein Web-API-Zugriff über WLAN ist Netzwerkkommunikation. Er wird getrennt
  nachgewiesen. Zugangsdaten und Gerätekonfiguration gehören nicht ins Repository.
- Die oben genannten Herstellerangaben zu API und CSV-Export stammen aus der
  Planung. Sie sind im Projekt noch nicht an einem Gerät oder einer echten
  Exportdatei geprüft.
- Synthetische Bestätigungen von Personen werden genauso ausdrücklich
  gekennzeichnet wie heute die synthetischen Roboterbestätigungen.

## Erster Durchstich

Umfang: die gemeinsame Aufgabenverwaltung und eine manuelle
NanoDrop-Mikrovolumenmessung in der synthetischen Minimalumgebung.

**Ablauf:** Rack bereitgestellt → Arbeitsbereich frei → Übergabe an die Person →
Blank und Mikrovolumenmessung → Import aus einer synthetischen Datei → Abgleich →
Rückgabe Platz für Platz → Reihenfolge prüfen → Freigabe.

**Tests:** alle oben genannten Fehlerfälle, mindestens falscher Platz, fehlendes
Gefäß, nicht zuordenbare und doppelte Messung sowie Unterbrechung mit Neustart.

**Umsetzungshinweise:**

- `Runner.run` in [cf01_rack_batch.py](../scripts/cf01_rack_batch.py) bleibt
  synchron und unverändert. Der NanoDrop-Ablauf verwendet den neuen lokalen Kern
  [manual_tasks.py](../scripts/manual_tasks.py) für Ereignisse, Artefakte und
  Reservierungen sowie die gemeinsamen Rack-Platzkennungen. Eine spätere
  CF01-Anbindung benötigt gezielte gemeinsame Inventarverträge und Regressionen.
- One und UltraC verwenden dieselbe Mikrovolumen-Protokollquelle und einen
  bisher ausschließlich synthetisch geprüften dateibasierten Ergebnisadapter.

**Weiterer Durchstich:** Der [synthetische Qubit-4-Ablauf](qubit-4-manual-workflow.md)
ergänzt Ansatz- und Kalibrierungszuordnung auf demselben Kern.

**Noch nicht enthalten:** Netzwerk-API und die Fortsetzung in CF01, weil
diese zuerst eine neue Massebestätigung je Probe braucht.

## Offene Punkte

- Qualifikation unveränderter echter Exporte und Geräte-Softwarestände für One und UltraC.
- Reales Qubit-Assay und zugehöriges Kit; bisher ausschließlich ein fiktives Assay.
- Identifikation der Gefäße: Barcode, Kamera oder Bestätigung durch die Person.
- Kennzeichnung der Person als Rolle oder Pseudonym; Authentifizierung ist nicht
  vorgesehen.
- Lage des menschlichen Arbeitsplatzes und der Übergabezone in L01.

## Herstellerangaben aus der Planung

Noch nicht im Projekt geprüft:

- [NanoDrop Ultra, Herstellerübersicht](https://assets.thermofisher.com/TFS-Assets/CAD/brochures/nanodrop-ultra-mcs-br1239-en.pdf)
- [NanoDrop Ultra, API-Handbuch](https://assets.thermofisher.com/TFS-Assets/CAD/manuals/nanodrop-ultra-api-reference-manual-m024.pdf)
- [NanoDrop One, Spezifikation](https://assets.thermofisher.com/TFS-Assets/CAD/Specification-Sheets/NanoDrop-One-Specifications.pdf)
- [Paket NanoDrop One mit WLAN und Qubit 4](https://www.fishersci.ca/shop/products/nanodrop-one-spectrophotometer-wifi-qubit-4-fluorometer/13400525)
- [Qubit 4, Herstellerbeschreibung](https://www.thermofisher.com/de/de/home/industrial/spectroscopy-elemental-isotope-analysis/molecular-spectroscopy/fluorometers/qubit/models/qubit-4.html)
- [Qubit 4, Benutzerhandbuch](https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0017209_Qubit_4_Fluorometer_UG.pdf)
