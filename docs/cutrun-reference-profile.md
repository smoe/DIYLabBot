# CUT&RUN: erster E0-Referenzprofilentwurf

**Stand 12. November 2026: publikationsbezogener In-silico-Entwurf;
E0 ist begonnen, die konkrete SOP-Bindung bleibt offen.** Dieser Entwurf konkretisiert
[E0 der Roadmap](../ROADMAP.md) innerhalb des
[Architekturvertrags](../ARCHITECTURE.md#cutrun). Der
[wirkungsfreie E1-Preflight](cutrun-preflight.md) ist mit maschinenlesbaren Quellen
und Schema implementiert. Dieser Entwurf ist keine Labor-SOP; eine ausführende
CUT&RUN-Laufzeit oder ein Geräteadapter folgt daraus nicht.

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

Die CST-Kitfamilie wird durch die Publikation gestützt. Die bisher vorgeschlagene
Bindung an **#86652, unfixierte Zellen und Säulenreinigung** bleibt eine
Arbeitsannahme, bis der damalige Quellenstand beziehungsweise eine ausdrücklich
gewählte aktuelle SOP abgeglichen ist. Es wird keine Beschaffung ausgelöst.

| Profilteil | Vorschlag | Noch zu bestätigen |
|---|---|---|
| Material | Melanomzelllinien sind bestätigt; erster In-silico-Kandidat ist die humane SK-Mel-29 aus der Publikation. Frisch/unfixiert bleibt zunächst eine Modellannahme. | Konkrete Laborlinie, Zustand und lokale SOP; keine Kerne oder fixierten Pellets still gleichsetzen. |
| Eingangsmenge | Zunächst 100.000 gezählte Zellen je CUT&RUN-Reaktion und ein entsprechend bereitgestelltes Input-Aliquot. | Verfügbare Menge, Zähl-/Qualitätsevidenz und Bedarf für Vorbereitungstests sowie spätere Wiederholungen. |
| Referenzziel | H3K4me3 ist bestätigt. C42D8-Kaninchen-mAb #9751 und Rabbit-DA1E-IgG #66362 bleiben vorgeschlagene Artikelbindungen. | Mit Publikations-/Laborunterlagen abgleichen; spätere Chargen sind noch keine Voraussetzung für eine synthetische Annahme. |
| Enzym und Kit | CST-Kitfamilie laut Publikation; #86652 mit pAG-MNase #57813 bleibt der konkrete Vorschlag. | Tatsächlich verwendeter Artikel und SOP-Stand; keine ungeprüften Enzym-/Puffersubstitutionen. |
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

Eine lokale Originalkopie mit SHA-256 bleibt offen: Der direkte PDF-Download
wurde am Lesedatum mit HTTP 403 abgewiesen; der Webleser konnte die Anleitung
auswerten. Die gelesene Revision ist deshalb noch keine bytegebundene operative
Quelle. Vor Freigabe einen rechtmäßig bereitgestellten Originalbeleg lokal
archivieren und prüfen; ein späterer Download ersetzt ihn nicht still.
Die Original-PDF wird durch diesen Entwurf nicht im Repository veröffentlicht.

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
3. **Andere vorhandene SOP:** Ist bereits ein anderes Kit oder ein bewährter
   Eigenansatz etabliert, wird dessen vollständiger Quellenstand geprüft und
   gegebenenfalls anstelle dieses Kandidaten gewählt. CR1 v3 bleibt ein
   versionierter Vergleichskandidat; keine Temperatur-, Antikörper- oder
   Reinigungselemente verschiedener Quellen zu einer Misch-SOP verbinden.

## Noch offene Bindungen und E0-Abschluss

Die grundsätzlichen Fragen nach Probenklasse, technischem Ziel, Gerätezugang,
lokalem Umfeld und Verantwortung sind beantwortet. Für die In-silico-Arbeit wird
SK-Mel-29 als erster Kandidat geführt; eine andere bestätigte Laborlinie kann
ihn vor der endgültigen Profilbindung ersetzen.

Offen bleibt vor allem der **konkrete publizierte Labor-/SOP-Stand**: Artikel,
Zellzustand, Eingangsmenge, Antikörper, Inkubations-/Reinigungszweig und QC.
Publikation und vorhandene Laborunterlagen zuerst abgleichen; falls stattdessen
die aktuelle CST-Variante gewählt wird, diesen Wechsel ausdrücklich benennen.
Unbekannte Werte nicht als historische Messdaten ausgeben. Synthetische
Parameter dürfen als solche festgelegt werden; sie schließen keine reale Abnahme.

Für den Abschluss arbeiten wir Quellenbeleg, exakte Parameter-/Variantenwahl,
Gefäß- und Reagenzidentitäten sowie Rollen aus und legen mit den Verantwortlichen
messbare Abnahmekriterien und Wiederholungsumfang fest. Konzentrations-/
Anreicherungsgrenzen werden nicht erfunden; technische Vollständigkeit,
fluorometrische Quantifizierung und biologische Bewertung sind getrennte
Kriterien. Die freigegebene SOP muss auch Pausen, Lagerung, Stoppbereitschaft
und Abweichungen abdecken. E0 ist erst mit diesem abgeglichenen Gesamtpaket
fachlich freigegeben; bis dahin beginnt kein integrierter realer
DIYLabBot-Referenzlauf nach E4 und kein E1-Profil gilt als ausführungsbereit.
