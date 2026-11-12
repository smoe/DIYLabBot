# SOP-Entwurf: manueller SK-Mel-29/H3K4me3-Referenzlauf

| Dokumentlenkung | Stand |
|---|---|
| Kennung | SOP-CR-SKM29-H3K4me3 |
| Fassung / Datum | 0.1 / 12. November 2026 |
| Status | **ENTWURF zur fachlichen Prüfung; nicht zur Durchführung freigegeben** |
| Erstellung | Projektentwurf auf Eigentümerauftrag; eine vorherige lokale SOP liegt nicht vor |
| Fachliche Prüfung / Bestätigung | Eigentümer und Chefin/Laborleitung; Sicherheitsbeauftragter entsprechend den bereits festgelegten Zuständigkeiten |
| Bestätigung dieser Fassung | **OFFEN**: verantwortliche Personen, Datum und bestätigte Revision |
| Änderungsverlauf | 0.1: erster quellenbezogener lokaler Entwurf mit offenen Parametern und Paper-Abgleich |

## 1. Zweck, Geltung und Kennzeichnung

Ziel ist ein manueller technischer Referenzlauf mit SK-Mel-29, H3K4me3-Reaktion,
IgG-Kontrolle und getrenntem Input bis zur gereinigten DNA, ausgewählter
Roh-DNA-QC und bestätigter Übergabe. Die PCR-Leerkontrolle ist eine spätere
QC-Rolle, keine weitere CUT&RUN-Reaktion. Durchführung und externe Teilschritte
bleiben im bekannten Labor/direkten Umfeld.

Die erste Entwurfsvariante sieht eine Ausgangsbedingung und serielle Bearbeitung
vor. Sie qualifiziert keine Reproduzierbarkeit. Zahl unabhängiger Ansätze und
technischer QC-Wiederholungen werden in O02/O08 festgelegt. Library-Präparation,
Sequenzierung und p73-Expressionsversuche sind keine Arbeitsgänge dieser Fassung.

Kennzeichnungen gelten im ganzen Dokument:

- **[PAPER]**: im tatsächlich gelesenen Artikel belegt; keine ergänzte Rezeptur.
- **[HERSTELLER]**: aus der unten gebundenen aktuellen CST-Anleitung; kein
  Nachweis der historischen Paper-SOP oder der lokalen Eignung.
- **[LOKALER VORSCHLAG]**: für diesen Entwurf gewählte Variante zur Prüfung.
- **[OFFEN Oxx]**: noch zu bindender Parameter oder Nachweis. Ein kritischer
  offener Punkt wird vor dem betroffenen Arbeitsgang geschlossen.
- **[Dxx]**: bewusste Abweichung, lokale Präzisierung oder nicht belegbare
  Übereinstimmung mit dem Paper; siehe Abschnitt 8.

## 2. Quellen und verbindlicher Rezeptbezug

| Quelle | Verwendung und Stand |
|---|---|
| R1 · [Möller et al., PMID 41594604](https://pmc.ncbi.nlm.nih.gov/articles/PMC12839168/) | Methoden 2.4 und Ergebnisse 3.1; publiziert 31.12.2025. Methodischer Bezug, Kitfamilie und H3K4me3-Referenz. |
| R2 · [CST #86652, Original-PDF](https://media.cellsignal.com/pdf/86652.pdf) | **Für Fassung 0.1 gewählte Entwurfsreferenz:** Datenblatt Revision 9, Protokoll „1884_CUT & RUN“, Revision 09/2026; abgerufen 12.11.2026. D01 bleibt ausdrücklich bestehen. |
| R3 · [aktuelle CST-Produktseite](https://www.cellsignal.com/products/cut-run-kits-reagents/cut-run-assay-kit/86652) | Aktuelle Herstellerzuordnung des Kitnamens zu #86652; kein historischer Artikelbeleg aus R1. |
| [E4-Vorbereitung](cutrun-manual-reference.md) / [Referenzprofil](cutrun-reference-profile.md) | Projektumfang, bereits getroffene Entscheidungen und noch benötigte lokale Bindungen. |

R2 ist der mitzuführende Rezeptanhang: vollständige Pufferrezepte,
Vorbereitungshinweise, Waschfolgen, Gerätevorgaben und die jeweils gewählten
Verfahrenszweige werden dort nachgeschlagen. Dieser lokale Entwurf ergänzt
Arbeitsfolge, Identität, Aufzeichnung, Entscheidungspunkte und Abnahme. Er
ersetzt R2 nicht durch eine verkürzte, unabhängig gepflegte Rezeptkopie.

Die am 12.11.2026 heruntergeladene Originaldatei liegt lokal unter
`exports/cutrun-e4-sop-sources/cst-86652-2026-11-12.pdf` und ist nicht zur
Veröffentlichung im Repository vorgesehen. Ihre **SHA-256** lautet:

```text
4569c1793c112e94cd8b0e5ca11ac7a82c53b2ce5dd46ce30831f653c830a34f
```

Vor operativer Bindung muss genau diese geprüfte Fassung verfügbar sein.
Ein veränderter Quellenstand erfordert einen dokumentierten Abgleich und eine
neue Entwurfsrevision. Der frühere Abruffehler ist für diese R2-Kopie behoben.
Historische Artikelnummer und Protokollrevision von R1 bleiben unbekannt;
das Supplement wurde nicht ausgewertet. Der Entwurf behauptet keine vollständige
Reproduktion des publizierten Verfahrens.

## 3. Varianten und Parameter für die fachliche Prüfung

### 3.1 Lokale Auswahl in Fassung 0.1

| Punkt | Entwurf / verbleibende Bindung |
|---|---|
| Materialzustand | **[LOKALER VORSCHLAG]** frische, unfixierte SK-Mel-29-Zellen; Zweig R2 II-A. Konkrete Kultur und Ausgangsbedingung: **O01**. Ein Wechsel auf fixiertes Material ändert diese Fassung. |
| Eingangsplanung | **O02**: gezählte Eingänge, Ansatz-/Input-Verhältnis, zusätzliche Prüfaliquots und Wiederholungsumfang festlegen. Keine Zellzahl aus dem SYN-Profil übernehmen. |
| Antikörperinkubation | **[LOKALER VORSCHLAG]** die kurze kalte Herstelleroption aus der nachfolgenden Tabelle; kein ungeprüftes Übernehmen der E3-Übernachtzeit. |
| Reinigung / Input | **[LOKALER VORSCHLAG]** R2 VII-A mit geeignet vorbereitetem Input nach VI/Anhang B. Sonikationsverfahren und Eignungsnachweis: **O04**. Keine Übernahme einer fremden Geräteeinstellung. |
| Normalisierung | **[LOKALER VORSCHLAG]** zunächst ohne optionalen Spike-in; als Entscheidung **O09** bestätigen. Daraus folgt keine quantitative Vergleichbarkeit mehrerer Bedingungen. |
| QC | **[LOKALER VORSCHLAG]** Fluorometrie und qPCR, mit getrennten Regeln für H3K4me3, IgG, Input und NTC. Assays, Umfang und Kriterien: **O08**. |

### 3.2 Quellengeprüfte Eckwerte — ausschließlich R2

Die folgenden **[HERSTELLER]**-Angaben sind unabhängig vom E3-Testmodell
nachgelesen. Sie gelten nur für die benannten Originalreagenzien und den
jeweiligen Zweig; Stockkonzentrationen und ausgegebene Chargen bleiben O03.

| Bezug (PDF-Seite, beginnend bei 1) | Eckwert |
|---|---|
| III, S. 6 | H3K4me3 #9751: 2 µl; IgG #66362: 5 µl; gewählte Option 2 h bei 4 °C. |
| V, S. 7 | Verdau: 150 µl Digestion-Arbeitsmix, 30 min bei 4 °C. |
| V, S. 7 | Stoppen: 150 µl vorbereiteter 1X-Arbeitsmix; Freisetzung 10 min bei 37 °C ohne Schütteln. |
| V, S. 7 | Abtrennung: 16.000 × g, 2 min, 4 °C; produktführenden Überstand identifizieren. |
| VII-A, S. 8 | Reinigungsreferenz #14209; Zentrifugenschritte bis 18.500 × g. |

**Arbeitsmix und Stock getrennt halten:** R2 V nennt für den Verdau
147 µl Digitonin-Arbeitspuffer plus 3 µl Kit-Calciumchlorid. Der Stop-Arbeitsmix
enthält 37,5 µl des 4X-Stocks #48105; die weiteren Bestandteile stehen in R2 V.
Weder Verdau- noch Stop-Gesamtvolumen ist eine Stockdosis. Mischung erfolgt
pipettierend, Inkubation III–V ohne Rotation. [R2](https://media.cellsignal.com/pdf/86652.pdf)

**[OFFEN O10] Quellenwiderspruch:** R2 Anhang A bezeichnet den 10X-Waschpuffer
abweichend von der Komponentenliste. Dort steht #12931, im Katalog #31415;
#12931 bezeichnet Wasser. Vor Ansatz die Reagenzidentität klären und die
Klärung dokumentieren; keinen Artikelverweis still korrigieren.

### 3.3 Offene Punkte und Zeitpunkt ihrer Klärung

| ID | Zu schließen | Spätestens vor |
|---|---|---|
| O01 | Bestandskultur-/Passage-/Bedingungskennung, Materialzustand und passende lokale Qualitätsbelege | Eingangsvorbereitung |
| O02 | Zellmengen je Rolle, Input-Bereitstellung, Zahl unabhängiger Ansätze und Prüfaliquots | Materialzuteilung |
| O03 | Artikel/Chargen, Konzentrationen/Gültigkeit der Stocks, vollständige Rezepte und vorbereitetes Erfassungsblatt; Arbeitsmischungen und Istverbrauch erst bei der Durchführung dokumentieren | Jeweiligem Reagenzansatz; Istdaten bei Ansatz/Zugabe |
| O04 | Input-Verfahren, tatsächlicher Sonikator und bestätigte Einstellungen/Größenprüfung; kompatible Reinigung | Input-Aufbereitung und Säulenbeladung |
| O05 | Reale Geräte-/Rotor-/Gefäßbindung, Zeitquelle, Temperaturbezug, lokale Toleranzen, Stoppzugang und Vertretung; zeitversetzter Plan für beide Reaktionen | Betroffener Phase, vollständig vor Aktivierung |
| O06 | Verantwortliche Personen, Aufzeichnungsmedium, Identitätszuordnung, Originalbelege und Abgleich bei Ausfall | Erster Materialhandlung |
| O07 | Lagerorte, zulässige Pausen einschließlich Wartepunkt der zweiten Reaktion, Produktannahme, Quarantäne-/Abfallwege und Behandlung von Restaliquots | Laufbeginn; aktuelle Orte beim Abschluss bestätigen |
| O08 | Assay/Primer/Kalibrierung, QC-Entnahmen, technische Wiederholungen, Nachweis-/Quantifizierungsgrenzen und rollenspezifische Abnahmekriterien | Laufbeginn; Istentnahmen vor jeweiliger QC |
| O09 | Entscheidung über optionale Normalisierung und Konsequenzen für das Auswertungsziel | Reagenzplanung |
| O10 | Klärung der abweichenden Reagenzkennung in R2 Anhang A | Permeabilisierungsansatz |
| O11 | Fachliche Prüfung dieser Fassung einschließlich aller lokalen Vorschläge und Abweichungen | Verwendung als lokale Arbeitsanweisung |
| O12 | Implementierter und geprüfter realer manueller Beobachtungs-/Zeit-/QC-Vertrag | Erstem integrierten DIYLabBot-E4-Lauf |

**Keine lokalen Toleranzen erfinden:** insbesondere weder das E3-Stoppfenster
noch dessen Temperaturtoleranz als experimentell zulässige Abweichung ausgeben.
Reagenzvorbereitung, Ansatzzuschläge und Restmengen werden aus dem gewählten
Rezept und den tatsächlich benötigten Rollen ermittelt; keine fiktiven Ausbeuten
aus Zellzahl, Pufferzugabe oder Herstellerbeispielen berechnen.

## 4. Material-, Gefäß- und Arbeitsplatzplan

Jeder tatsächliche Ansatz erhält eine neue Lauf- und Versuchskennung. Unter
diesem Kopf H3K4me3, IgG, Input und NTC als unterschiedliche Rollen anlegen.
Gefäße, Rackinstanz und Platz werden separat identifiziert. Die NTC enthält
kein Probenmaterial und erhält keine Buchung gegen das Original.

Für jede Rolle eine Zeile im Laufblatt führen:

| Rolle | Im Laufblatt zuzuordnen |
|---|---|
| H3K4me3 / IgG | Eingang, Reaktionsgefäß, brancheneigene Aktivierungs-/Stoppaliquots, Zwischenfraktionen und Produktgefäß |
| Input | Eigenes Eingangsaliquot, Aufbereitung, Reinigung und Produktgefäß; keine Aktivierungs-/Stoppreaktion wie bei CUT&RUN |
| NTC | Eigene QC-Gefäß-/Wellkennung, Assay und Vergleich zur Probenplatte |
| Alle Arbeitsplätze | Geräte-/Ortskennung, verantwortliche Person, physische Ablage und verfügbare Aufzeichnungen |

Pro Reagenzansatz erfassen: Originalstock/Charge/Konzentration, Rezeptverweis,
Herstellungszeit und Verwendbarkeit, Komponenten mit Einheiten, fertige
Arbeitsmischung, zugeteilte Aliquots, geplanter Transfer und tatsächliche
Zugabe. Antikörpermengen werden je Artikel gebunden; gleiche Volumina würden
keine gleichen Antikörpermengen beweisen. Nach einer Zugabe bleibt die tatsächliche
Mischungsmenge eine Beobachtung; sie ist kein aus E3 übernommener Sollsaldo.

Aufträge und Materialzuteilung gemeinsam führen. Laufexklusive Aliquots genügen
für diesen ersten Umfang; eine globale Stock-Fortschreibung wird nicht
vorausgesetzt. Benutzte Restaliquots werden nicht als frischer Bestand neu angelegt.

## 5. Manuelle Arbeitsfolge und Aufzeichnungen

R2 bleibt für die vollständige Durchführung des ausgewählten Zweigs mitzuführen.
Die nachfolgende lokale Folge benennt die Arbeitsaufträge und erforderlichen
Beobachtungen. Bei jedem Übergang Identität, tatsächliche Durchführung,
Materialbewegung und zuständige Person bestätigen. Ein Timer ersetzt keine
beobachtete erfolgreiche Trennung oder Mischung.

| Schritt | Arbeitsauftrag / Rezeptbezug | Lokaler Abschlussbeleg |
|---|---|---|
| S01 · Lauf eröffnen | Fassung und Quellenkopie prüfen, O01–O11 entsprechend ihrem Zeitpunkt schließen, Rollen und Geräte binden. | Laufkopf, bestätigte Entwurfsentscheidungen, Verantwortlichkeit und Startinventar |
| S02 · Eingänge bereitstellen | Materialzustand nach gewähltem Zweig festlegen; Prüfaliquots und Input eindeutig abzweigen. | Beobachtete Identitäten/Mengen, Herkunft, Aufteilung und Probenzustand |
| S03 · Vorbereitung | Reagenzansätze nach R2 vorbereiten; R2 I und gewähltes II durchführen. Permeabilisierungsbefund gemäß Anhang A zuordnen; O10 vorher klären. | Ansatzblätter, Istentnahmen, Eingangs-/Prüfbefunde und erhaltene Fraktion |
| S04 · Antikörperbindung | R2 III für die getrennten H3K4me3-/IgG-Rollen durchführen; die bestätigte Inkubationsoption verwenden. | Antikörper-/Chargenbindung, Zugabe und Mischung, Beginn/Ende und Temperaturbezug |
| S05 · Enzymbindung | R2 IV; aktuelle Reaktionsidentität und Arbeitsmischung prüfen. | Enzym-/Ansatzbezug, Istverbrauch, Wasch-/Fraktionswechsel und Inkubationsbeleg |
| S06 · Aktivierung vorbereiten | Für das nächste Gefäß Stoppmaterial, Zugang/Mischung, Zeit-/Temperaturbeobachtung und Vertretung aktuell prüfen. Einen erfüllbaren manuellen Ablauf festhalten. | Je Gefäß aktuelle Bereitschaft und gespeicherte beziehungsweise schriftliche Aktivierungsabsicht |
| S07 · Aktivieren und verfolgen | R2 V für genau dieses Gefäß durchführen. Kontakt, bestätigte Zugabe und Mischung getrennt erfassen; Zeit läuft auch bei Dokumentationsunterbrechung weiter. | Frühester/spätester möglicher Kontakt, tatsächliche Zugabe, Exposition und Beobachtungsquelle |
| S08 · Stoppen / Fraktion übergeben | R2 V fortsetzen; Stoppzugabe und Mischung je Gefäß bestätigen. Produktführende Fraktion mit ihrer neuen Material-/Gefäßzuordnung übergeben. | Stoppabsicht/-beleg, Zugabe plus Mischung, Prozesszeiten, Fraktionsübergang und Nebenfraktionen |
| S09 · Input aufbereiten | Den separat identifizierten Input nach R2 VI und bestätigtem O04-Verfahren bearbeiten. | Eingangsmenge, tatsächliche Bearbeitung, Gerätebindung und erforderlicher Qualitätsbefund |
| S10 · Reinigen | Den bestätigten Reinigungszweig R2 VII durchführen. Produkt, Durchfluss, Waschfraktionen und Säulenrest bewusst zuordnen. | Vollständige Istverbräuche, Herkunft des Eluats, beobachtete Menge und bestätigte Dispositionen |
| S11 · QC / Bewertung | Abschnitt 7 dieses Entwurfs und den bestätigten Assayplan abarbeiten. | Produktentnahmen, unveränderte Originaldaten, technische Prüfung und separate fachliche Bewertung |
| S12 · Übergabe / Laufende | Produkte und gewünschte Nebenfraktionen an bestätigte Orte übergeben; vollständiges Inventar und Restverbräuche abgleichen. | Empfänger-/Ortsbestätigung, Enddispositionen, Abweichungsentscheidungen und Abschlussbefund |

S09 kann vor den zeitkritischen Reaktionen vorbereitet werden, soweit der
bestätigte Arbeits-/Pausenplan das vorsieht. Eine einmal aktivierte Reaktion
wartet nicht auf andere Arbeitsgänge. Für den ersten seriellen Pilot wird keine
gleichzeitige Aktivierung aus den freien Rotorplätzen oder der Roboterzahl abgeleitet.
S04–S08 werden so zeitversetzt geplant, dass der Wartepunkt der zweiten
Reaktion durch O05/O07 gedeckt ist. „Seriell“ begründet insbesondere keine
zusätzliche Pause nach Enzymbindung. Ist der bestätigte Ablauf damit nicht
erfüllbar, wird der Plan vor Beginn angepasst und die Änderung dokumentiert.

**Fraktionsregel:** zu Beginn jedes Übergangs benennen, welches Material weiter
Produktvorläufer ist und was Nebenfraktion/Abfall wird. Aufbewahrung wird
bestätigt; Entsorgung ebenso. Für die lokale Aufbewahrung von Rest-Beads oder
Durchfluss O07 anwenden. Keine automatische Entsorgung allein aufgrund eines
Schrittabschlusses; umgekehrt keine nicht angeordnete Daueraufbewahrung sämtlicher Abfälle.

## 6. Stopp, Unterbrechung und Abweichungen

Zeit-/Temperaturbelege enthalten reale Quelle, Datum/Zeit mit Zeitzonenbezug,
Unsicherheit und relevante Beobachtungsintervalle. Kalter Stellplatz und
tatsächlicher Probentemperaturbezug werden unterschieden. Bei Kontaktverlust
oder Neustart wird eine unbelegte Zeitlücke nicht zu null Sekunden.

Ein organisatorischer Halt oder ausgefallener Rechner beendet keine Reaktion.
Das fachlich bestätigte manuelle Stoppverfahren ist unabhängig vom Rechner
zugänglich. Muss eine Person bei Dokumentationsausfall handeln, bewahrt sie
Identität, Handlung, Zeitpunkt/Intervall und verfügbare Belege für den
nachträglichen Abgleich. Keine fiktive vorangegangene elektronische Absicht anlegen.

Eine verlorene Aktivierungsquittung bedeutet möglicherweise erfolgte Zugabe.
Nicht blind wiederholen. Stoppevidenz verlangt beobachtete Zugabe **und** Mischung.
Fehlt nur die Mischbestätigung einer bereits belegten Stoppdosis, wird die
Mischung geklärt; die Dosis wird nicht allein zur Reparatur des Datensatzes
erneut gebucht oder hinzugefügt.

Verspätete tatsächliche Stopps werden mit ihrem Zeitpunkt erhalten. Ein
unbekanntes Expositionsmaximum, Temperaturmangel, fehlende Menge oder
Identitätsabweichung erzeugt einen fachlich zu bewertenden Befund. Die
Verantwortlichen entscheiden anhand der festgelegten Kriterien über
Fortsetzung, Wiederholung, Quarantäne oder Abbruch. Eine spätere gute Messung
löscht den früheren Befund nicht.

Pausen und Lagerung nur aus dem gewählten Quellenzweig und O07 übernehmen.
Für jeden tatsächlich genutzten Pausenpunkt Ort, Beginn, erlaubte Dauer und
Fortsetzungsbedingungen im Laufblatt führen. Bei offenen Wirkungen oder
fehlendem Übergabebeleg Ressourcen/Verantwortlichkeit nicht unbelegt freigeben.

## 7. Produkt-QC und Abschlusskriterien

Jede QC-Entnahme wird vorab dem identifizierten gereinigten Produkt zugeordnet
und belastet dessen tatsächlichen Rest. Das verarbeitete Original wird nicht
erneut belastet. Assayvorbereitung, Verdünnung, Kalibrierung und tatsächliche
Produktentnahme getrennt aufzeichnen. Unbekannte Menge ist weder Null noch
die geplante Menge; keine erwartete Ausbeute als Istmenge eintragen.

| Rolle / Prüfebene | Vorab in O08 zu bestimmen | Bewertung im Lauf |
|---|---|---|
| Fluorometrie | Konkreter Assay/Gerät, Kalibrierung, geeignete Grenzen, Entnahmen und Verdünnungsbezug | Originalsignal und Menge mit Unsicherheit; unter der Quantifizierungsgrenze kein erfundener Zahlenwert |
| H3K4me3-qPCR | Gebundene Primer/Regionen und erwarteter Vergleich zur Kontrolle, Wiederholungen und fachliche Kriterien | Assaygültigkeit und spezifischer Befund; Konzentration allein belegt keine Anreicherung |
| IgG | Zulässiger Hintergrund und Umgang mit zensiertem/nicht nachweisbarem Signal | Ein Signal unter Nachweisgrenze kann zur Kontrollrolle passen; nicht automatisch Fehler oder Nullmenge |
| Input | Zuordnung, Vorbereitungseignung, tatsächliche Verdünnung und gewählte Auswertungsmethode | Vergleichsbezug nachvollziehbar; keine Ableitung allein aus Zeilenfolge oder Uhrzeit |
| PCR-Leerkontrolle | Kontaminations-/Assaykriterium und Plattenzuordnung | Eigenständiger Kontrollbefund ohne Probenentnahme |

Unveränderte Originaldateien mit Assay-/Geräte-/Softwarebezug und eindeutiger
Lauf-, Versuchs-, Reaktions-, Produkt- und gegebenenfalls Platten-/Wellkennung
erhalten. Abgeleitete Tabellen und Korrekturen bleiben mit ihnen verknüpft.
Technische Importvollständigkeit und biologische Eignung werden separat bewertet.
Grenzwerte werden vor Ergebnissichtung festgelegt; dieser Entwurf setzt keine
Konzentrations-, Cq- oder Anreicherungsgrenze.

Abschluss erst nach bestätigter Materialdisposition, Produkt-/Ortsannahme,
vollständigem Inventar und dokumentierten offenen beziehungsweise entschiedenen
Abweichungen. Ein fachlich nicht auswertbarer Lauf kann dokumentiert beendet
werden; er wird dadurch kein erfolgreicher Referenznachweis.

## 8. Abweichungs- und Unsicherheitsregister gegenüber dem Paper

„Nicht beschrieben“ bezieht sich hier auf den gelesenen R1-Abschnitt, nicht
auf eine behauptete Abwesenheit in allen Originalunterlagen oder im ungeprüften
Supplement. **Unbekannte Übereinstimmung ist keine nachgewiesene Abweichung.**

| ID / Einordnung | Paperbezug | Lokaler Entwurf und Konsequenz |
|---|---|---|
| D01 · Neuer Quellenstand | Historische Kitnummer/Anleitungsrevision sind im gelesenen Methodenabschnitt unbestimmt. | Aktuelle R2-Fassung als ausdrücklich neuer Entwurfsbezug; keine Behauptung historischer Protokollgleichheit. |
| D02 · Bewusste Vereinfachung | R1 untersucht p73-bezogene Expressionsbedingungen; H3K4me3 dient als Referenz. | H3K4me3 als eigenes technisches Ziel; keine p73-Expressionsversuche in dieser SOP. Ausgangsbedingung O01 bleibt festzulegen. |
| D03 · Anderes Umfangsende | R1 führt über Libraries zur Sequenzierung. | Ende bei gereinigter DNA, Roh-DNA-QC und Übergabe; keine Aussage über Library- oder Sequenzierleistung. |
| D04 · Andere QC-Ebene | Die im Methodentext genannte Agilent-/Qubit-Prüfung betrifft Libraries. | Lokaler Roh-DNA-Assayplan O08 wird eigens gebunden; Paper-Librarywerte sind keine lokalen Freigabegrenzen. |
| D05 · Übereinstimmung unbekannt | Materialzustand und genaue Inkubations-/Reinigungsvariante bleiben im gelesenen Abschnitt offen. | II-A, kurze kalte Bindung und VII-A sind lokale Entwurfsvorschläge; fachliche Bestätigung erforderlich. |
| D06 · Lokale Präzisierung | Separater Input und genaue Kontroll-/Gefäß-/Chargenbindungen sind dort nicht vollständig operativ beschrieben. | Eigene Rollen, Identitäten und Fraktionsbelege; tatsächliche Artikel/Chargen in O03 bestätigen. |
| D07 · Übereinstimmung unbekannt | Optionaler Normalisierungsweg ist für diesen Vergleich nicht eindeutig gebunden. | Vorläufig kein optionaler Spike-in; O09 schließen und Konsequenzen für Vergleiche dokumentieren. |
| D08 · Unabhängiger Pilot | Der gelesene Text belegt keine übernehmbare Wiederholungs-/Abnahmeregel für diesen vereinfachten Pilot. | Wiederholungsumfang und rollenspezifische Kriterien O02/O08 vorab festlegen; keine Qualifikation aus einem Pilot behaupten. |

## 9. Abgrenzung vom synthetischen E3-Lauf

Keine Prozesswerte, Buchungsbeobachtungen oder Gefäßkennungen aus dem
SYN-Fixture werden als lokale Laborbelege übernommen. Insbesondere ist die
E3-Stoppdosis von 30 µl **synthetisch**; für diesen Entwurf gilt die separat
geprüfte Quellenangabe aus 3.2. Die erfundenen E3-Reaktions-/Fraktionsmengen
und die feste QC-Entnahme sind keine Ertrags- oder Verbrauchsvorgaben.

Die vorhandenen E3-Befehle kennzeichnen Beobachtungen weiterhin als synthetisch.
O12 ist eine eigene Entwicklungsaufgabe auf dem gemeinsamen Journal/Ledger;
diese SOP implementiert keinen neuen Runner und migriert keine alten Läufe.
Für den integrierten Lauf bleiben Absicht, reale Beobachtung, Originalartefakt,
Materialbuchung und fachliche Bewertung getrennte, verknüpfte Nachweise.

## 10. Laufblatt und Prüfung dieses Entwurfs

Laufdaten und Originalbelege gehören nach dem Projektvertrag in den privaten
Laufzeitbereich unter `exports/`, nicht als realer Bestand nach `model/`.
Das folgende Blatt beschreibt benötigte Angaben, keine bereits vorhandene API.

- Lauf-/Versuchskennung, SOP-Fassung und Quellenprüfsumme: **im Lauf ausfüllen**.
- Bearbeitende Person, Stoppvertretung, Geräte und Orte: **O05/O06**.
- Eingang, Artikel/Chargen und vollständige Reagenzansatzblätter: **O01–O04**.
- Je Handlung: Material/Gefäß, Absicht, Istzugabe, Zeitpunkt/Intervall,
  Beobachtungsquelle, Fraktion und gegebenenfalls Abweichungsbeleg.
- Je QC: Produktentnahme, Assay-/Kalibrierbezug, Originaldatei, Zuordnung,
  technische Prüfung und fachlicher Befund: **O08**.
- Endinventar, erhaltene/entsorgte Fraktionen, Lagerort und Übergabe: **O07**.
- Entwurfsprüfung: kritische O-Punkte schließen, D01–D08 prüfen und die
  bestätigte neue Fassung mit Datum dokumentieren: **O11**.

Die Felder für später beobachtete Istwerte sind vor Laufbeginn naturgemäß leer.
Sie sind von noch offenen Methodenentscheidungen O01–O12 zu unterscheiden.
Der Entwurf ist erst nach Quellen-, Varianten- und fachlicher Prüfung eine
verbindliche lokale Arbeitsanweisung; E4 bleibt bis zum tatsächlichen Nachweis offen.
