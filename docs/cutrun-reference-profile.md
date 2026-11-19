# CUT&RUN: erster E0-Referenzprofilentwurf

**Stand 12. November 2026: publikationsbezogener In-silico-Entwurf;
E0 ist begonnen, die konkrete SOP-Bindung bleibt offen.** Dieser Entwurf konkretisiert
[E0 der Roadmap](../ROADMAP.md) innerhalb des
[Architekturvertrags](../ARCHITECTURE.md#cutrun). Der
[wirkungsfreie E1-Preflight](cutrun-reference-profile.md#merged-cutrun-preflight) ist mit maschinenlesbaren Quellen
und Schema implementiert. Der [E3-Lauf](cutrun-synthetic-workflow.md) ergänzt
synthetische Prozessbeobachtungen. Die [begonnene E4-Vorbereitung](cutrun-manual-reference.md)
führt die noch benötigten Entscheidungen und Nachweise für den manuellen
Referenzlauf. Dieser Entwurf ist keine Labor-SOP und kein realer Geräteadapter.
Der [lokale SOP-Entwurf 0.1](cutrun-manual-sop-draft.md) konkretisiert inzwischen
eine aktuelle CST-basierte Variante mit offenen Parametern und Paper-Abgleich;
fachliche Bestätigung und reale Durchführung stehen aus.

## Festgelegter Kontext und erster Modellfall

Der Eigentümer hat für E0 am 11.11.2026 festgelegt:

- Ausgangsmaterial sind **Melanomzelllinien**; **H3K4me3** ist als erstes
  technisches Referenzziel akzeptiert. Spätere wissenschaftliche Ziele sind
  die TP73-Cofaktoren aus der unten gebundenen Publikation.
- Methodischer Ausgangspunkt ist **diese Publikation**. Ein neu vorgeschlagenes
  Herstellerprofil ersetzt den damaligen Laborablauf nicht stillschweigend.
- Die benötigte Ausstattung ist laut Eigentümer im gezeichneten Labor oder
  dessen direkter Umgebung vorhanden. Das ist eine bestätigte Verfügbarkeit,
  noch keine Liste konkreter Geräteinstanzen oder ein Qualifikationsnachweis.
- Durchführung und externe Teilschritte bleiben in diesem lokalen Umfeld.
  Verantwortlich sind Eigentümer, Sicherheitsbeauftragter und Chefin.
- Die aktuelle Arbeit findet **in silico** statt. Reale Gerätefreigaben und
  Laborhandlungen sind damit nicht beauftragt; sie blockieren die weitere
  Modellierung nicht. Für synthetische Fälle werden Annahmen ausdrücklich markiert.

Vorgeschlagener erster Modellfall: **SK-Mel-29, H3K4me3 und IgG, separater
Input, gereinigte DNA mit QC und Übergabe**. SK-Mel-29 folgt der Publikation;
eine konkrete Bestandslinie ist damit noch nicht bestätigt. Zunächst wird eine
einzige Ausgangsbedingung modelliert. Der frühere HCT-116-Vorschlag entfällt.

Mit dem aktuellen E4-Auftrag ist **SK-Mel-29/H3K4me3 als Referenzprofilziel**
ausdrücklich benannt. Die physische Bestandskultur, deren Zustand und erste
Versuchsbedingung bleiben vor dem manuellen Lauf konkret zu binden.

Der Eigentümer hat inzwischen **das Kit aus der Publikation** gewählt und
klargestellt, dass **keine lokale SOP vorhanden ist**. Damit ist die im
[Methodenabschnitt 2.4](https://pmc.ncbi.nlm.nih.gov/articles/PMC12839168/)
genannte Kitfamilie **CST CUT&RUN Assay Kit** festgelegt. Die
[heutige Herstellerzuordnung #86652](https://www.cellsignal.com/products/cut-run-kits-reagents/cut-run-assay-kit/86652)
belegt die aktuelle Artikelbezeichnung; Artikelnummer und Anleitungsrevision
des damaligen Versuchs bleiben im gelesenen Paperabschnitt unbestimmt.
Die Entwicklung erstellt einen neuen lokalen Anweisungsentwurf mit
ausdrücklicher Quellen- und Variantenbindung. Eine vorhandene lokale SOP
wird dafür nicht mehr angefordert.

Die CST-Kitfamilie ist damit gewählt. **Unfixierte Zellen und Säulenreinigung**
bleiben Verfahrenskandidaten. #86652 ist eine aktuelle Herstellerzuordnung,
keine belegte historische Artikelnummer. Der operative Quellenstand wird im
neuen lokalen Entwurf ausdrücklich festgelegt. Es wird keine Beschaffung ausgelöst.

| Profilteil | Vorschlag | Noch zu bestätigen |
|---|---|---|
| Material | Melanomzelllinien sind bestätigt; erster In-silico-Kandidat ist die humane SK-Mel-29 aus der Publikation. Frisch/unfixiert bleibt zunächst eine Modellannahme. | Konkrete Laborlinie, Zustand und lokale SOP; keine Kerne oder fixierten Pellets still gleichsetzen. |
| Eingangsmenge | Zunächst 100.000 gezählte Zellen je CUT&RUN-Reaktion und ein entsprechend bereitgestelltes Input-Aliquot. | Verfügbare Menge, Zähl-/Qualitätsevidenz und Bedarf für Vorbereitungstests sowie spätere Wiederholungen. |
| Referenzziel | H3K4me3 ist bestätigt. C42D8-Kaninchen-mAb #9751 und Rabbit-DA1E-IgG #66362 bleiben vorgeschlagene Artikelbindungen. | Mit Publikations-/Laborunterlagen abgleichen; spätere Chargen sind noch keine Voraussetzung für eine synthetische Annahme. |
| Enzym und Kit | CST CUT&RUN Assay Kit aus der Publikation ist gewählt; #86652 ist die aktuelle Herstellerzuordnung, pAG-MNase #57813 eine zu bindende Komponente. | Ausgegebene Artikel/Chargen und operativer Quellenstand im neuen lokalen Entwurf; historische Nummer/Revision bleiben gesondert offen. |
| Kleiner Pilot | Eine biologische Ausgangsbedingung mit zwei CUT&RUN-Reaktionen (H3K4me3 und IgG) und einem getrennten Input-Zweig. | Material reicht aus. Dieser Pilot ersetzt keine unabhängigen Referenzwiederholungen oder Qualifikation. |
| Reinigung | CST VII-A mit DNA Purification Buffers and Spin Columns #14209; Input nach VI mit passender Sonikation. | Kit #14209 und geeignete reale Geräte vorhanden; Fragmentanforderungen fachlich passend. |
| QC | Fluorometrische Mengenbestimmung mit festzulegendem Assay; CST-VIII-qPCR mit zum Material passenden Kontrollprimern, Input und PCR-Leerkontrolle. | Assay, Gerät/Export, Primer und fachliche Kriterien. Qubit allein belegt keine Anreicherung; keine NanoDrop-Pflichtmessung. |
| Normalisierung | Für den ersten technischen Pilot ohne Vergleich biologischer Bedingungen zunächst keine optionale Hefe-Spike-in-Normalisierung. | Soll bereits quantitativ zwischen Bedingungen verglichen werden, muss diese Wahl vor Freigabe neu bewertet werden. |
| Durchführung und Ende | Jetzt in silico. Später manueller Referenzlauf im gezeichneten Labor/direkten Umfeld; Verantwortung bei Eigentümer, Sicherheitsbeauftragtem und Chefin. DNA behalten, QC-Entnahmen buchen, Übergabe dokumentieren. | Konkrete Orte/Geräteinstanzen und Lager-/Pausenregeln vor realer Durchführung binden. Library/NGS bleiben eigene spätere Aufträge. |

Grundlagen der noch vorgeschlagenen Artikelbindungen:
[CST-Kitbeschreibung #86652](https://www.cellsignal.com/products/cut-run-kits-reagents/cut-run-assay-kit/86652)
für enthaltene Kontrollen;
[CST-Protokoll, II-A, VI–VIII und Anhang A/B](https://www.cellsignal.com/learn-and-support/protocols/cut-and-run-protocol)
für Zellpräparation, Input, Reinigung und QC. Pilotumfang, Reihenfolge der
Entwicklung und vorläufiger Verzicht auf optionale Normalisierung sind unsere
Vorschläge, keine Herstellerfreigabe dieses konkreten Laborprofils und keine
nachgewiesene Rekonstruktion des publizierten Ablaufs.

## Publikationsbezug und spätere TP73-Ziele

Referenz: Möller et al., *Integrative Multimodal Profiling of TAp73 and DNp73
Reveals Isoform-Specific Transcriptomic Coregulator Landscapes in Cancer Programs*.
[PMID 41594604](https://pubmed.ncbi.nlm.nih.gov/41594604/),
[DOI 10.3390/biom16010063](https://doi.org/10.3390/biom16010063),
[Verlagsartikel](https://www.mdpi.com/2218-273X/16/1/63).
Online veröffentlicht am 31.12.2025; Biomolecules 16(1), 63.

Lesestand 11.11.2026: PubMed einschließlich Abbildungslegenden und öffentlich
indexierte Primärtextabschnitte 2.4, 3.1 und 3.7. Der direkte Volltextabruf war
nicht durchgehend möglich; Supplement und vollständige Originalunterlagen sind
noch nicht geprüft. Die folgenden Aussagen bleiben auf diesen Lesestand begrenzt:

- Der CUT&RUN-Abschnitt nennt SK-Mel-29 mit TAp73α-, DNp73β- und GFP-Bedingungen,
  ein CST CUT&RUN Assay Kit und Durchführung nach Herstellerprotokoll.
  H3K4me3 dient als positive Kontrolle.
- Die genannte Agilent-/Qubit-HS-Prüfung bezieht sich auf **Libraries**.
  Daraus folgt keine unveränderte Roh-DNA-QC für unseren Endpunkt.
- Der gelesene Methodenabschnitt belegt weder #86652 noch die native/fixierte
  Variante, Zellzahl, Reinigungsvariante oder einen damaligen Protokollstand.
  Das ist keine Behauptung, diese Angaben fehlten auch im ungeprüften Supplement.

Der einfache H3K4me3-Modellfall ist eine bewusst vorgeschlagene Vereinfachung;
er reproduziert nicht automatisch die publizierten p73-Expressionsbedingungen.
Für spätere Profile sind Cofaktor, p73-Isoform, Zellzustand und geeigneter
Antikörper gemeinsam zu wählen. Eine Histonreferenz qualifiziert diese Targets nicht.

| Späterer Kandidat | Bezug aus der Publikation | Planungsfolge |
|---|---|---|
| PATZ1 | DNp73β-Interaktion durch CoIP-MS gestützt; zusätzlich Motiv-/TFDB-Bezug. | Naheliegender priorisierbarer Kandidat; Interaktionsevidenz und eigene Chromatinbelegung getrennt prüfen. |
| SUB1, YBX3 | TAp73α-bezogene Kandidaten aus CoIP-MS/TFDB, in 3.7 für spätere CUT&RUN-Prüfung benannt. | Eigene Targetprofile und Antikörperprüfung erforderlich. |
| AHCTF1, HMGB3 | Entsprechende DNp73β-bezogene Kandidaten in 3.7. | Eigene Targetprofile und Antikörperprüfung erforderlich. |

Das ist eine erste Orientierung, keine vollständige Kandidatenliste oder
Prioritätsentscheidung. Motivnachbarschaft, CoIP-MS und experimentell gemessene
Chromatinbelegung bleiben unterschiedliche Evidenzarten. Die Quelle ersetzt
keine solche Kennzeichnung durch das Sammelwort „Cofaktor“.

## Quellenbindung und gewählter Zweig

Die inzwischen zusätzlich gelesene
[CST-PDF zu #86652](https://media.cellsignal.com/pdf/86652.pdf) nennt
**Datenblatt Revision 9** und im Protokollfuß
**1884_CUT & RUN Protocol, Revision 09/2026**. Das ist ein präziserer
Revisionsbeleg als der zuvor in der Architektur erfasste Webseitenstand.
Lesedatum: 11.11.2026. Datenblatt- und Protokollrevision nicht gleichsetzen.
**09/2026 ist ein heutiger Vergleichsstand, kein belegter Originalstand der
bereits 2025 veröffentlichten Studie.** Eine Bindung daran wäre ausdrücklich
als aktuelle Variante zu beschließen.

Vorgeschlagene Auswahl: I → II-A → III–V, separater Input nach VI einschließlich
Anhang B, Reinigung VII-A und die gewählte QC aus VIII. Anhang A bindet den
zelllinienspezifischen Permeabilisierungstest. Der konkrete Inkubationszweig aus
III, alle Parameter, Vorbereitungstests, zulässigen Pausen und Abweichungen
müssen vor E0-Abschluss in der lokalen fachlich freigegebenen SOP eindeutig sein.
Die gesamte Anleitung wird hier nicht nachgeschrieben.

Am Lesedatum 11.11.2026 war der direkte PDF-Download mit HTTP 403 abgewiesen
worden. **Aktualisierung 12.11.2026:** Die Originaldatei konnte für den
[lokalen SOP-Entwurf 0.1](cutrun-manual-sop-draft.md) heruntergeladen und mit
SHA-256 gebunden werden. Der Entwurf führt Pfad, Prüfsumme und den aktuellen
Quellenstand; eine historische Paper-Revision wird dadurch nicht rekonstruiert.
Die Original-PDF bleibt im privaten Laufzeitbereich und wird nicht im
Repository veröffentlicht. Die operative fachliche Quellenbindung bleibt offen.

## Abhängigkeiten, die die Wahl verändern können

1. **Input und Reinigung:** Der vorgeschlagene Säulenweg setzt einen geeignet
   fragmentierten Input voraus. CST VI/Anhang B sieht dafür Sonikation vor.
   Ohne Sonikator beschreibt CST für unfragmentierten qPCR-Input organische
   Reinigung. In diesem Fall den Input-/Reinigungszweig ausdrücklich neu wählen;
   weder unfragmentierten Input ungeprüft auf die Säule geben noch ihn still weglassen.
2. **Reale Ausstattung:** Allgemeine Verfügbarkeit im Labor/direkten Umfeld ist
   bestätigt; konkrete Instanzen werden vor realer Nutzung gebunden. CST V
   benötigt eine geeignete kalte Prozessführung
   und gekühlte Zentrifugation; VI/VII-A enthalten Anforderungen bis 18.500 × g.
   Magnet, passende Gefäße, Temperierung, Misch-/Heizweg, Sonikation und QC sind
   am tatsächlichen Arbeitsplatz nachzuweisen. Zur Sonikationsprüfung gehört
   eine Größenkontrolle des Inputs, etwa per Gelelektrophorese nach Anhang B;
   das ist keine pauschale Fragmentanalysepflicht für die CUT&RUN-DNA.
   Die CF01-Konzeptziele und
   modellierte Laborgeräte ersetzen das nicht. Siehe
   [CST V–VII/Anhang B](https://media.cellsignal.com/pdf/86652.pdf).
3. **Neue lokale Anweisung:** Da keine lokale SOP vorliegt, wird für die
   gewählte Kitfamilie ein versionierter Entwurf aus den gebundenen
   Primärquellen erarbeitet und fachlich geprüft. CR1 v3 bleibt ein
   Vergleichskandidat; keine Temperatur-, Antikörper- oder Reinigungselemente
   verschiedener Quellen zu einer Misch-SOP verbinden.

## Noch offene Bindungen und E0-Abschluss

Die grundsätzlichen Fragen nach Probenklasse, technischem Ziel, Gerätezugang,
lokalem Umfeld und Verantwortung sind beantwortet. SK-Mel-29/H3K4me3 ist das
gewählte Referenzprofilziel; die konkrete Bestandskultur und Ausgangsbedingung
werden für den manuellen Lauf noch zugeordnet.

Offen bleibt die **operative Quellen- und Variantenbindung des neu zu
erstellenden lokalen Entwurfs**: Zellzustand, Eingangsmenge, Antikörper,
Inkubations-/Reinigungszweig und QC. Der historische Labor-/SOP-Stand ist
weiterhin nicht belegt; er wird nicht vom Eigentümer als vorhandenes Dokument
vorausgesetzt. Eine aktuelle Herstellerfassung wird ausdrücklich als solche
benannt. Unbekannte Werte nicht als historische Messdaten ausgeben.
Synthetische Parameter dürfen als solche festgelegt werden; sie schließen
keine reale Abnahme.

Für den Abschluss arbeiten wir Quellenbeleg, exakte Parameter-/Variantenwahl,
Gefäß- und Reagenzidentitäten sowie Rollen aus und legen mit den Verantwortlichen
messbare Abnahmekriterien und Wiederholungsumfang fest. Konzentrations-/
Anreicherungsgrenzen werden nicht erfunden; technische Vollständigkeit,
fluorometrische Quantifizierung und biologische Bewertung sind getrennte
Kriterien. Die freigegebene SOP muss auch Pausen, Lagerung, Stoppbereitschaft
und Abweichungen abdecken. E0 ist erst mit diesem abgeglichenen Gesamtpaket
fachlich freigegeben; bis dahin beginnt kein integrierter realer
DIYLabBot-Referenzlauf nach E4 und kein E1-Profil gilt als ausführungsbereit.

<a id="merged-cutrun-preflight"></a>

<a id="merged-cutrun-preflight--wirkungsfreier-cutrun-preflight"></a>

## Wirkungsfreier CUT&RUN-Preflight

**Stand 12. November 2026: E1 für das synthetische SK-Mel-29/H3K4me3-Profil
implementiert.** Der Preflight prüft und beschreibt eine Planung. Er führt keine
Laborhandlung aus, öffnet kein Journal und reserviert oder bucht nichts.
Die historische SOP-Bindung aus [E0](cutrun-reference-profile.md) bleibt offen.
Die [Roadmap](../ROADMAP.md) und der
[Architekturvertrag](../ARCHITECTURE.md#cutrun) unterscheiden diese Vorbereitung
von Lebenszyklus, Ausführung, Wiederanlauf und realer Qualifikation.

<a id="merged-cutrun-preflight--einstieg-und-quellen"></a>

### Einstieg und Quellen

```sh
python3 scripts/prepare_cutrun_automation.py
python3 scripts/prepare_cutrun_automation.py --require-complete
python3 scripts/prepare_cutrun_automation.py --out exports/cutrun-preflight/plan.json
```

Der normale Aufruf schreibt nur JSON nach stdout. `--out` erzeugt auf ausdrückliche
Anforderung eine **neue** JSON-Berichtdatei im ignorierten `exports/`-Bereich;
bestehende Dateien und Pfade außerhalb dieses Bereichs werden abgewiesen,
auch bei aufgelösten Symlinks. Für einen weiteren Bericht einen neuen Dateinamen
verwenden. Es gibt keinen Ausführungs-, Store- oder Geräteschalter.

| Quelle | Inhalt |
|---|---|
| `model/cutrun-automation.catalog.json` | Literatur-/Eigentümerbezüge und vorgeschlagene Material-/Kitrollen |
| `model/cutrun-automation.protocol.json` | Abstrakte Operationen, Kontroll-/Inputketten, Fraktionen, Einheiten sowie Stopp-, Inputgrößen- und QC-Anforderungen |
| `model/cutrun-automation.preparation.json` | Synthetische Identitäten, konkrete Modellannahmen, vorgeschlagene Provider und deren unqualifizierte Grenzen |
| `model/cutrun-automation.schema.json` | Formales Schema mit dem bestehenden gemeinsamen Quellenreferenzvertrag |
| `scripts/cutrun_preparation.py` | Unverändernde Momentaufnahme, semantische Prüfung und Ableitung |

Das Profil pinnt Katalog und Protokoll. Der Bericht bindet zusätzlich Schema,
Compiler und verwendete technische Hilfen über SHA-256; die Quellen werden
am Ende nochmals geprüft. Bei einem in-memory geänderten Profil bezeichnet
`effective_preparation_sha256` den tatsächlich ausgewerteten Inhalt.
Diese lokalen Quellenpins sind keine Prüfsumme der unbekannten historischen SOP.

<a id="merged-cutrun-preflight--was-vollständig-bedeutet"></a>

### Was „vollständig“ bedeutet

Der mitgelieferte Fall hat `planning_complete: true`, aber **immer
`execution_ready: false`**. Vollständigkeit bedeutet ausschließlich, dass die
benötigten E1-Planfelder unter den deklarierten Annahmen ausgefüllt und konsistent
sind. Die Planung ist kein vollständiges Laborrezept. Mehrere reale Zugaben,
Mischvorgänge, Gefäßwechsel und Beobachtungen sind erst später in die konkrete
SOP und einzeln bestätigbare Schritte aufzulösen.

Jeder Parameter enthält `value`, `unit`, `basis`, `source_refs` und `note`.
`owner_confirmed` bezeichnet hier bestätigte Rahmenangaben, keine Durchführung;
`publication_reported` ist eine Literaturangabe. Nicht bestätigte Prozesswerte,
Zelllinienauswahl und Providergrenzen stehen als `synthetic_assumption` mit
Begründung im Profil und mit ihrem Feldpfad in `assumptions` im Bericht.
Das macht sie weder zu Messdaten noch zu qualifizierten Fähigkeiten.

Die Bindung an CST-Kit-/Artikelrollen ist ein synthetischer Vorschlag auf Basis
des dokumentierten Vergleichsstands. Sie belegt keinen Bestand und rekonstruiert
nicht den ursprünglichen Studienablauf. Zellzahl wird nicht aus Volumen abgeleitet.
Eine erwartete DNA-Ausbeute oder ein biologischer Erfolg wird nicht berechnet.

Wird ein erforderlicher Wert offen gelassen, bleibt er `null` mit `basis: unknown`.
Auch ganz fehlende Prozessparameter werden im abgeleiteten Schritt als unbekannt
mit Einheit geführt, statt einen Default anzunehmen. Die betroffenen Pfade
stehen in `open_requirements`; `planning_complete` wird falsch. Bei
`--require-complete` folgt Exitcode **2**, bei widersprüchlichen/ungültigen Quellen
Exitcode **1** mit JSON-Fehler. Ohne diesen Schalter sind gültige Teilplanungen
mit Exitcode **0** zulässig.

Unbekannte historische SOP-Revision, Original-SOP-Prüfsumme und biologische
Abnahmeschwelle bleiben ausdrücklich ungelöst. Sie sind keine für die
synthetische Feldvollständigkeit erfundenen Werte.
Der [E2-Materialvertrag](material-lifecycle.md) ist für explizite synthetische
Materialvorgänge implementiert; seine Bindung an eine biochemische Ausführung,
reale SOP-Nachweise, Providerqualifikation, QC-Anbindung und CUT&RUN-Laufzeit bleiben als
`execution_blockers` erhalten. Ein Quellenwechsel kann diese Sperren nicht
durch ein zusätzliches `execution_ready`-Feld umgehen.

<a id="merged-cutrun-preflight--geprüfte-zusammenhänge"></a>

### Geprüfte Zusammenhänge

- Genau ein H3K4me3-Referenzzweig, ein IgG-Negativkontrollzweig und ein separater
  Input mit unterschiedlichen Material-/Gefäßidentitäten. Der Input durchläuft
  keine Antikörperbindung oder Aktivierung. Die PCR-Leerkontrolle bleibt eine
  eigene QC-Rolle, keine zusätzliche CUT&RUN-Reaktion.
- Pflichtphasen und deren Reihenfolge, einschließlich Input-Sonikation und
  Input-Größenprüfung sowie Säulenwäsche/Trocknung. Eine neu gepinnte Quelle
  kann die Parameter- oder Gefäßanforderungen dieser Vertragsversion nicht entfernen.
- Erhaltung der Bead-/Zellfraktion vor Freisetzung, des Produktüberstands danach,
  der Säulenfraktion während der Reinigung und des Eluats/Produkts bei Übergabe.
  Es werden keine Entsorgungen oder abgeschlossenen Transfers behauptet.
- Typisierte Zellzahl, Volumina, Zeiten, Temperaturen, RCF, Wiederholungen und
  Größenbereiche. Boolesche Zahlen, NaN/Inf, falsche Einheiten und unbekannte
  Felder werden abgewiesen. Für den ausgewählten Säulen-Input wird das geplante
  Größenintervall gegen die im Protokoll deklarierte Modellgrenze geprüft.
- Fähigkeitszuordnung, benötigte Gefäßklassen und vorgeschlagene Volumen-,
  Temperatur- und RCF-Grenzen. Ein fehlender Vorschlag bleibt offen, ein
  widersprüchlicher Vorschlag wird abgewiesen. Eine allgemeine Geräteverfügbarkeit
  oder der Name CF01 bestätigt keine dieser Fähigkeiten.
- Stoppmaterial, Zugang, Durchmischung, manueller Ersatzweg und Abdeckung beider
  aktiven Zweige. Dosierung und Zeitbedarf müssen mit den Zweigparametern
  zusammenpassen; der gesamte deklarierte Servicebedarf muss ins Zeitbudget
  passen. Dies ist eine Planprüfung, kein Ablaufplaner, Watchdog oder chemischer
  Stoppnachweis. Ein Software-Halt bleibt davon getrennt.
- Fluorometrie und qPCR mit passenden Kontrollbezügen. QC-Entnahmen werden
  ausschließlich als Vorschläge gegen die **DNA-Produkte** ausgegeben und gegen
  das vorgeschlagene Elutionsvolumen geprüft. Es findet keine Verbrauchsbuchung
  statt; die Eingänge werden nicht erneut belastet. Library-QC oder Konzentration
  allein ersetzen keine profilgerechte biologische Bewertung.

<a id="merged-cutrun-preflight--prüfung-und-grenzen"></a>

### Prüfung und Grenzen

```sh
python3 -B -m unittest discover -s tests -p 'test_cutrun_*.py' -v
```

Die Schematests benötigen die optionale Entwicklungsabhängigkeit `jsonschema`;
übersprungene Schematests zählen nicht als Nachweis. Die semantischen Tests
benötigen diese Abhängigkeit nicht. Die Tests verbieten Journal-, Datenbank-,
Netzwerk- und Subprozesswirkungen bei der Kompilierung und prüfen unveränderte
Eingaben/Dateien sowie voneinander unabhängige Rückgabewerte.

Vorhandene Quellenprüfung, Hashfunktionen und Validierungshilfen werden
wiederverwendet. Der Extraktionscompiler bleibt unverändert. Journal, Ledger
und gemeinsame Ablaufhülle sind ausschließlich referenzierte Integrationsziele;
E1 erweitert diese Verträge nicht. CAD-Geometrie, Roboterbewegung, Geräteadapter,
Hardware, biologische Abnahme und die E3-Reaktionszustandsmaschine sind nicht
Bestandteil dieses Preflights.
