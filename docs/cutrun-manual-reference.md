# Manueller CUT&RUN-Referenzlauf: E4-Vorbereitung

**Stand 12. November 2026: Vorbereitung begonnen, kein realer integrierter Lauf
freigegeben oder ausgeführt.** Dieses Dossier konkretisiert E4 der
[Roadmap](../ROADMAP.md) auf Basis des
[Referenzprofilentwurfs](cutrun-reference-profile.md) und des geprüften
[synthetischen E3-Laufs](cutrun-synthetic-workflow.md). Die operative SOP-Bindung
aus E0 bleibt offen. Das Dossier ist eine Entscheidungs- und Nachweisvorlage,
keine Arbeits-SOP und kein ausführbares Laufprofil.

Der [lokale SOP-Entwurf, Fassung 0.1](cutrun-manual-sop-draft.md), ist jetzt
erstellt. Er bindet eine lokal gesicherte CST-Originalfassung als
Entwurfsreferenz, kennzeichnet offene Parameter und führt Abweichungen sowie
unbekannte Übereinstimmungen zum Paper ausdrücklich auf. Seine fachliche
Prüfung und operative Bindung stehen aus.

## Bereits festgelegt

Der aktuelle Eigentümerauftrag benennt **SK-Mel-29/H3K4me3** als E4-Referenz.
Melanomkontext, H3K4me3 als technischer Einstieg, Publikationsbezug, Durchführung
im gezeichneten Labor beziehungsweise dessen direkter Umgebung und die Rollen
Eigentümer, Sicherheitsbeauftragter und Chefin werden übernommen. Die allgemeine
Verfügbarkeit der Ausstattung ist bestätigt; sie wird nicht erneut abgefragt.

Der Eigentümer hat ergänzend klargestellt: **Eine lokale SOP ist nicht
vorhanden; verwendet werden soll das Kit aus der Publikation.** Die Entwicklung
erstellt deshalb einen neuen lokalen Anweisungsentwurf aus den gebundenen
Primärquellen und kennzeichnet offene Varianten und lokale Ergänzungen.
Eine bereits existierende lokale SOP wird nicht als Eingabe vorausgesetzt.

Vorgeschlagener erster Umfang bleibt eine Ausgangsbedingung mit H3K4me3- und
IgG-Reaktion, getrenntem Input und separater PCR-Leerkontrolle. Zunächst erfolgt
ein serieller technischer Pilot bis zur gereinigten DNA, ausgewählter Roh-DNA-QC
und dokumentierter Produktübergabe. Wiederholungszahl und wissenschaftliche
Abnahmekriterien werden vor der Materialplanung festgelegt. Ein Pilot belegt
noch keine Reproduzierbarkeit. Library-Präparation, Sequenzierung, Robotik und
laufübergreifender Stock gehören zu eigenen späteren Schritten.

Die konkrete Bestandskultur, deren Zustand und Versuchsbedingung sind noch zu
binden. Die publizierten p73-Expressionsbedingungen werden nicht automatisch in
den H3K4me3-Referenzlauf übernommen. Der methodische Ausgangspunkt bleibt die
[Publikation, Methodenabschnitt 2.4](https://www.mdpi.com/2218-273X/16/1/63).

## Quellenwahl und neu zu erstellende Laboranweisung

Der [Methodenabschnitt 2.4](https://pmc.ncbi.nlm.nih.gov/articles/PMC12839168/)
nennt das **CUT&RUN Assay Kit von Cell Signaling Technology** und verweist auf
die Herstelleranleitung. Damit ist diese Kitfamilie ausgewählt. Die
[heutige Herstellerseite](https://www.cellsignal.com/products/cut-run-kits-reagents/cut-run-assay-kit/86652)
ordnet denselben Produktnamen **#86652** zu. Diese aktuelle Artikelzuordnung
stammt vom Hersteller; die genaue historische Artikelnummer und damalige
Anleitungsrevision sind durch den gelesenen Paperabschnitt nicht belegt.
Das Supplement-ZIP konnte beim erneuten Abgleich nicht abgerufen werden;
sein Inhalt bleibt ungeprüft. Daraus folgt keine Aussage, dass die Angaben
auch dort fehlen.

Der versionierte lokale [Anweisungsentwurf 0.1](cutrun-manual-sop-draft.md)
verwendet Herstellerrevision 09/2026 als ausdrücklich aktuellen Entwurfsbezug.
Die Originaldatei wurde am 12.11.2026 lokal gesichert; Pfad und SHA-256 stehen
einmalig im Entwurf. Damit ist die frühere Lücke der lokalen CST-Quellenkopie
geschlossen. Die historische Paper-SOP bleibt davon getrennt und unbestätigt.
Als Nächstes werden die offenen Varianten fachlich geprüft und die bestätigte
Fassung operativ gebunden. Vorhandene Notizen oder Optimierungsbelege können
einfließen, sind aber keine vorausgesetzte lokale SOP.

## Noch benötigte Entscheidungen und Belege

Prüfsummen, Quellenabgleich, Anweisungsentwurf und technische Profilbindung
übernimmt die Entwicklung. Vom Eigentümer werden die lokalen Bedingungen und
die fachliche Bewertung der daraus entstehenden Vorschläge benötigt.

| Bereich | Noch benötigte Entscheidung | Benötigter Beleg und Zeitpunkt |
|---|---|---|
| **1 · Verbindliche Quelle** | Kitfamilie ist festgelegt; der lokale Entwurf 0.1 verwendet die aktuelle Herstellerrevision 09/2026. Offene Varianten und die operative Fassung sind noch zu bestätigen. | Originalkopie und SHA-256 liegen vor. Die Verantwortlichen prüfen und bestätigen den Entwurf **vor der operativen Profilbindung**; eine vorherige lokale SOP muss nicht geliefert werden. |
| **2 · Konkreter Pilot** | Welche SK-Mel-29-Bestandskultur und Ausgangsbedingung, welcher native/fixierte beziehungsweise Zell-/Kernzustand, welche geplante Eingangsmenge und wie viele unabhängige Ansätze? | Kultur-/Stockkennung, vorhandene Identitäts-/Qualitätsaufzeichnungen nach lokaler SOP und Bereitstellungsplan vor dem Lauf; tatsächliche Zähl-/Bereitstellungsbeobachtungen bei der Vorbereitung. Die synthetischen 100.000 Zellen werden nicht übernommen. |
| **3 · Material und Variante** | Kitfamilie CST CUT&RUN Assay Kit ist ausgewählt; konkrete H3K4me3-/IgG-, Enzym-, Reinigungs- und Gefäßbindungen sowie Permeabilisierung, Inkubation und Input-/Reinigungsvariante konkretisieren. | Herstellerbelege und neu ausgearbeitete Ansatzanweisung vor dem Lauf; vorhandene Optimierungsnotizen, soweit verfügbar. Konkret ausgegebene Chargen, Aliquot- und Gefäßkennungen werden bei Bereitstellung erfasst. Auch Aktivierungs- und Stoppmischung brauchen reale Identität und Zusammensetzungsbezug. |
| **4 · Geräte und Stoppweg** | Welche vorhandenen Geräteinstanzen und Arbeitsplätze erfüllen die gewählte Variante? Wer führt aus und wer übernimmt bei Ausfall den manuellen Stopp? | Instanz-/Ortsliste mit passenden vorhandenen Prüf-/Kalibrier- oder Funktionsbelegen und lokalem Stoppverfahren vor dem Lauf; aktuelle Material-, Zugangs-, Misch- und Zeitbereitschaft unmittelbar vor jeder Aktivierung. |
| **5 · QC und Bewertung** | Welche Roh-DNA-Assays, Primer/Kontrollregionen, Kontrollen und zweigspezifischen technischen sowie biologischen Kriterien gelten? Welche Wiederholungen sind dafür erforderlich? | Assay-/Primerstand, Auswertungsregeln, Nachweis-/Quantifizierungsgrenzen, Geräte-/Exportformat und gegebenenfalls vorhandener Beispieloriginalexport vor der Softwarebindung. Die Ergebnisse dieses Laufs entstehen erst während beziehungsweise nach seiner Durchführung. |
| **6 · Produkt und Abschluss** | Wer erhält die DNA, wo und wie wird sie aufbewahrt, welche Pausen sind zulässig und wer bewertet Abweichungen? Welche Nebenfraktionen sollen bleiben? | SOP-bezogene Lager-/Pausenbedingungen, Zielorte und Zuständigkeit vor dem Lauf; tatsächliche Mengen, QC-Entnahmen, Enddispositionen und bestätigte Übergabe beim Abschluss. |

Die aktuelle [CST-PDF](https://media.cellsignal.com/pdf/86652.pdf) trägt beim
Lesestand 12.11.2026 weiterhin Datenblatt Revision 9 und Protokoll Revision
09/2026. Dieser Stand liegt nach der Veröffentlichung der Studie 2025 und
belegt deren damalige SOP nicht. Eine lesbare Webseite ersetzt keine lokal
gebundene operative Originalquelle. Es wird keine Misch-SOP aus historischen,
aktuellen und synthetischen Parametern konstruiert.

## Bindung der vorhandenen Ausstattung

Die folgende Liste benennt benötigte Zuordnungen, keine neue Einkaufsliste.
Die genaue Anforderung folgt der gewählten SOP; offene Geräte bleiben offen.

| Prozessrolle | Zu bindende reale Instanz und vorhandener Eignungsbeleg |
|---|---|
| Identifizieren und bereitstellen | Arbeitsplatz, Zähl-/Qualitätsverfahren, Gefäß-/Rackkennungen, ausführende Person und Herkunft der Eingangsbeobachtung. |
| Pipettieren und mischen | Vorhandene Pipetten und passender Mengenbereich, Gefäße/Spitzen sowie SOP-gerechter Mischweg. Bestehende Prüfbelege auf den konkreten Einsatz beziehen. |
| Magnetisch trennen | Magnet/Gefäßkombination, Platz und beobachtbare erfolgreiche Trennung; ein Timer allein ist kein Trennnachweis. |
| Temperieren und stoppen | Reale Temperaturführung und Art der Temperaturbeobachtung, unabhängige Zeitbeobachtung, verfügbarer manueller Stoppweg mit ausreichendem zugeordnetem Material und erreichbarer Mischung. |
| Zentrifugieren | Gerät, Rotor und Gefäß mit zur SOP passender RCF-/Temperatur-/Zeitfunktion. Die modellierte CF01 liefert dafür keinen Nachweis. |
| Input vorbereiten und reinigen | Je nach gewählter Variante geeignete Input-Aufbereitung, deren erforderliche Größen-/Qualitätsprüfung und Reinigungsarbeitsplatz. Keine unbestätigte Säuleneignung aus dem CAD ableiten. |
| Messen und aufbewahren | Tatsächliche Fluorometrie-/qPCR-Instanzen, Assays, Kalibrier-/Kontrollbezug, Originalexport und belegter Produktlagerort. |

E4 benötigt keine qualifizierte automatische Pipettierstation und keinen
implementierten Robotertransport. Menschen nutzen die vorhandenen geeigneten
Geräte. Ein Software-Halt oder PC-Ausfall stoppt keine Reaktion; das vereinbarte
manuelle Verfahren muss unabhängig davon zugänglich bleiben. Ein automatisierter
Hardware-Watchdog wird damit weder verlangt noch nachgewiesen.

## Drei getrennte Zeitpunkte für Nachweise

**Vor der ersten realen integrierten Materialhandlung:** operative SOP und
Quellenstand, reales manuelles Erfassungsformat, Identitäts-/Gefäßplan,
Gerätebindung, Aufzeichnungs- und Abweichungsverfahren sowie vorab festgelegte
QC-/Übergabekriterien müssen gebunden sein. Eine reale Vorbereitung wird nicht
als synthetisches E3-Ereignis gespeichert.

**Unmittelbar vor jeder Aktivierung:** tatsächliche Eingänge und Vorbereitung,
zugeordnete ausreichende Stoppaliquots, Zugang, Mischweg, verantwortliche Person
beziehungsweise Vertretung sowie erfüllbarer Stoppplan werden aktuell bestätigt.
Zeit-/Temperaturbeobachtung muss verfügbar sein. Eine frühere allgemeine
Geräteverfügbarkeit ersetzt diese konkrete Bereitschaft nicht.

**Während des Laufs und beim Abschluss:** tatsächliche Zugaben, Mischung,
Zeitintervalle, Temperaturbeobachtungen, Fraktionswechsel und Verbrauch erfassen;
danach QC-Originaldateien, fachliche Bewertung, Dispositionen und Übergabe.
Gute Ergebnisse dieses noch nicht durchgeführten Laufs werden nicht vorab als
Nachweis verlangt. Fehlende Beobachtung bleibt unbekannt.

## Vorbereitete Aufzeichnungsstruktur

Diese Felder beschreiben den Bedarf für den künftigen manuellen Vertrag; sie
sind noch keine unterstützte API oder ein zweites Laborbuch.

| Aufzeichnung | Zu erhaltender Inhalt |
|---|---|
| Quellen- und Laufkopf | SOP-ID/Revision/Originalprüfsumme, Profilrevision, neue reale Lauf-/Versuchskennung, Ziel, Kontrollrollen, Personenrollen und Geräte-/Ortsbezüge. Keine Wiederverwendung der `SYN.*`-Fixtureidentitäten für reale Materialien. |
| Eingang und ausgegebene Aliquots | Material-/Gefäß-/Rack-/Platzkennungen, Herkunft, Artikel/Charge, tatsächlich zugeordnete Menge mit Einheit, Beobachtungsquelle und gegebenenfalls unbekannte Werte. |
| Einzelne Handlung | Dauerhafte Absicht vor geplanter Durchführung, beobachteter Ausgang, tatsächlicher Verbrauch, Zielgefäß, Person und Quelle des Belegs. Nachträglicher Abgleich einer externen Handlung wird ausdrücklich als solcher gekennzeichnet. |
| Aktivierung und Stopp | Frühester/spätester möglicher Kontakt, bestätigte Zugabe und Mischung getrennt, Stoppbereitschaft und tatsächlicher Stopp je Gefäß. Eine verlorene Quittung wird nicht durch eine neue Dosis ersetzt. |
| Zeit und Temperatur | Reale Zeitquelle, absolute Zeit mit Zeitzonenbezug, relevante verstrichene Spannen und Unsicherheit; Temperaturbeobachtungen mit Quelle und Abdeckung. Kein manuelles Vorrücken einer synthetischen Uhr für einen realen Lauf. |
| Fraktionen und QC | Eltern-/Kindmaterial, tatsächliche erhaltene Menge, Produkt-/Nebenfraktionsrolle, jede Produktentnahme sowie Assay-, Kalibrier-, Reaktions-/Platten-/Well- und Methodenbezug der unveränderten Originaldatei. |
| Unterbrechung und Ende | Letzter belegter Zustand, unbekannte Wirkungen/Zeitlücken, externe Stoppevidenz, Abweichungsentscheidung, vollständiges Inventar, bestätigte Enddisposition und Annahme der Produktübergabe. Korrekturen ergänzen Belege, sie überschreiben keine Originale. |

Laufdaten und Originalartefakte gehören nach dem bestehenden Projektvertrag in
den privaten Laufzeitbereich unter `exports/`, nicht als reale Bestandskopien
nach `model/`. Quellen-/Profilrevisionen und Laufbeobachtungen bleiben getrennt.

Erfasserkennungen werden nach einem passenden lokalen Verfahren konkreten
Personen zugeordnet; erforderliche Gegenzeichnung folgt der lokalen SOP.
Eine eingegebene Kennung authentifiziert noch keine Person. Ebenso belegt
eine Prüfsumme unveränderte Bytes, während die Herkunft als Geräteoriginal,
Personenbeobachtung oder nachträglicher Abgleich gesondert dokumentiert wird.

## QC: kontrollabhängige Kriterien vorab festlegen

Die Publikation beschreibt in ihrem Methodenabschnitt unter anderem
[Library-QC](https://www.mdpi.com/2218-273X/16/1/63). Diese Ergebnisse oder
Grenzen werden nicht auf unseren Endpunkt gereinigte Roh-DNA übertragen.

Für H3K4me3, IgG, Input und PCR-Leerkontrolle werden Methoden, erforderliche
Beobachtungen und Bewertung getrennt festgelegt. Ein IgG-Signal unter einer
Nachweisgrenze kann mit seiner Kontrollrolle vereinbar sein; es ist weder eine
erfundene Nullmenge noch automatisch ein technischer oder biologischer
Fehlschlag. Nachweisgrenze, Quantifizierungsgrenze, nicht quantifizierbares
Ergebnis und tatsächlicher QC-Verbrauch bleiben unterschiedliche Angaben.
Konzentration allein belegt keine spezifische Anreicherung.

Benötigt werden vorab die lokalen Kriterien für auswertbare Assays,
Kontrollgültigkeit, H3K4me3-Anreicherung gegenüber geeigneten Kontrollregionen
und Kontrollen, Abweichungsbewertung und Wiederholungsbedarf. Die Entwicklung
erfindet dafür keine Konzentrations-, Cq- oder Anreicherungsgrenzen. Ergebnisse
werden später fachlich gegen diese Kriterien bewertet; technische Vollständigkeit
und biologische Eignung sind getrennte Entscheidungen.

## Nächste Entwicklungsarbeiten nach der Quellenklärung

Diese Punkte liegen bei der Softwareentwicklung und sind keine vom Eigentümer
zu liefernden Implementierungen:

1. **Lokale Anweisung prüfen und operatives Profil binden:** den vorhandenen
   Entwurf 0.1 mit seinen offenen Varianten fachlich prüfen und bestätigen.
   Danach ausgewählte reale SOP, Materialien, alle
   verwendeten Reagenzrollen, Fähigkeiten, Fraktionen und kontrollabhängige QC
   einmalig beschreiben. E1-/E3-Modelle bleiben synthetisch; kein stiller Wechsel
   ihres Modus und kein Überschreiben historischer Läufe.
2. **Manuelle Beobachtungen versionieren:** gemeinsame Ablaufhülle, Journal,
   Materialbuchungen und laufexklusive Aliquotzuteilung wiederverwenden.
   Personenbestätigung, Messdatei und synthetische Eingabe unterscheiden;
   Originalbelege unverändert erhalten. Es entsteht keine zweite Mengenbilanz.
3. **Reale Zeit und Wiederanlauf ergänzen:** unabhängig fortschreitende
   Zeitführung, Uhrkontinuität beziehungsweise belegte Unsicherheit nach
   Unterbrechung, unveränderte Reaktionsfristen und extern beobachtete Stopps
   erfassen. Eine Rückkehr zum Rechner darf Zeit nicht zurücksetzen.
4. **QC und vollständigen Verbrauch anbinden:** die ausgewählten realen
   Exportformate anhand vorhandener Originalbeispiele prüfen; Produkt-QC,
   Kontrollen und fachliche Bewertung passend zur SOP binden. Sämtliche
   SOP-Reagenzrollen und Istverbräuche erfassen, nicht nur Aktivierung und Stopp.
5. **Ohne biologische Wirkung erproben:** Aufzeichnungs- und Ausfallwege mit
   klar gekennzeichneten Testdaten prüfen, anschließend den gebundenen manuellen
   Referenzlauf vorbereiten. Bestehende synthetische Abläufe bleiben regressionsgeprüft.

Der heutige E3-Lader akzeptiert nur `synthetic_only`, seine Uhr nur
`synthetic_intervals/1`, und Hülle/Ledger kennzeichnen Belege als synthetisch.
E1 verlangt weiterhin offene historische SOP-Felder; deren technische
Weiterentwicklung gehört zur Bindung der neuen lokalen Anweisung. Der E3-QC-Testvertrag
verlangt quantifizierbare Produktsignale in allen Zweigen. Diese Grenzen lassen
sich nicht durch Eintragen realer Messwerte oder Umbenennen des Fixtures lösen.
Bis der eigene manuelle Vertrag implementiert und geprüft ist, sind weder
E3-`demo` noch dessen `act`-Befehle ein Einstieg für E4-Laborhandlungen.

## Aktueller Übergabestand

- **Erledigt:** E4-Umfang, Entscheidungs-/Nachweismatrix, Aufzeichnungsbedarf
  und notwendige Softwareerweiterungen vorbereitet; lokaler SOP-Entwurf 0.1
  und bytegebundene aktuelle CST-Originalkopie erstellt.
- **Offen beim Eigentümer/Labor:** konkrete Unterlagen und Entscheidungen aus
  der Tabelle; insbesondere Bestandskultur/erste Bedingung sowie fachliche
  Prüfung der vorgeschlagenen Varianten und Abnahmekriterien.
- **Offen in der Entwicklung:** Einarbeitung der fachlichen Entscheidungen
  in den Anweisungsentwurf, gebundenes manuelles Laufprofil, reales
  Beobachtungs-/Zeit-/QC-Format und dessen Prüfungen.
- **Nicht nachgewiesen:** tatsächliche Durchführung, biologische Eignung,
  automatische Dosierung, Hardwareausführung oder E4-Abschluss.
