# AGENTS.md

Diese Hinweise gelten für das Projekt SolidCraftBot.

## Leitidee: abstrakt beschreiben, automatisch ableiten

Die führende Konstruktion ist eine CAD-unabhängige, maschinenlesbare Beschreibung
der Konstruktionsabsicht. FreeCAD, SolidCraft und ROS 2/RViz sind daraus erzeugte
Fassungen. Dasselbe gilt für Arm, Stationen und spätere Mehrarmaufbauten.

Die gewünschte Entwicklungsschleife lautet:

**Idee und Anforderungen → gemeinsame Modellquelle und Protokoll → Generatoren
→ CAD/Visualisierung/Prüfung → Rückmeldung in die gemeinsame Quelle.**

Jedes CAD-Ziel muss seine Geometrie direkt aus den gemeinsamen Quellen und der
Herstellerbibliothek erzeugen können. Ein anderes CAD ist keine notwendige
Build-Abhängigkeit; CAD-übergreifende Prüfungen sind zusätzliche Vergleiche.
Die CF01-SolidCraft-Prüfstellungen haben dafür einen eigenständigen Einstieg
`scripts/export_centrifuge_robot_pickup_solidcraft.py`. Abgeleitete Hersteller-
Teildateien und Körperzuordnungen gehören in den lokalen Build-Bericht.

- Änderungen zuerst in der passenden gemeinsamen Quelle formulieren. Maße,
  Bauteilrollen, Schnittstellen, Gelenke und Abläufe einmal beschreiben;
  zielprogrammspezifische Details gehören in die Adapter unter `scripts/`.
- Neue wiederkehrende Funktionen als portable, semantische Operationen
  ausdrücken, zum Beispiel Motoraufnahme, Lochbild oder Kaufteilinstanz.
  Bereits passende Operationen und gemeinsame Hilfsfunktionen wiederverwenden.
  Nicht für jedes CAD eine unabhängige Konstruktion derselben Funktion pflegen.
- Fehlt eine benötigte Operation, Quelle/Schema und betroffene Generatoren
  gemeinsam erweitern. Eine Planung oder ein Platzhalter ist noch keine
  implementierte Funktion; fehlende Zielunterstützung ausdrücklich melden.
- Native CAD-Bearbeitung ist für Inspektion und Entwurfsexperimente möglich.
  Dauerhafte Änderungen anschließend in Quelle oder Generator zurückführen
  und erneut ableiten. Eine automatische Rückübersetzung ist nicht eingerichtet.
  Erzeugte CAD-, Mesh- und URDF-Dateien nicht als zusätzliche führende Quellen
  von Hand weiterentwickeln.

## Redundanz vermeiden: Definition, Variante und Instanz trennen

- Jede Baugruppe besitzt genau eine führende Konstruktionsquelle. Aufstellungen
  referenzieren diese Quelle; sie enthalten nur Instanz-ID, Transformation,
  Zustand und ausdrücklich benannte Parameterüberschreibungen. Glieder,
  Gelenkrahmen, Lochbilder oder Bauteilgeometrie nicht für eine Szene kopieren.
- Varianten aus derselben Quelle ableiten. Nur unabhängige Parameter mit
  deklarierten Einheiten und gültigen Wertebereichen überschreiben; abhängige
  Maße und Gelenkanker gemeinsam neu auswerten. Unterstützte Instanzverträge
  stehen in `model/assembly-reference.schema.json`; keine unimplementierten
  Variantenfelder als verfügbar darstellen.
- Wiederholte Maßangaben durch Referenzen oder abgeleitete Ansichten ersetzen.
  Berechnete Montage- und Prüfdaten gehören in Berichte beziehungsweise eine
  eindeutig als abgeleitet markierte Bibliothek, nicht als zusätzliche
  Handkopien in Auswahl- oder Aufstellungsdateien.
- Gemeinsame Kinematik und semantische Operationen wiederverwenden. Ein
  zielprogrammspezifischer Adapter ist keine zweite Konstruktionsquelle.
- Native Ausgaben über geprüfte Build-Berichte auflösen. Revisionspfade und
  Datei-Prüfsummen gehören in diese Berichte, nicht in die Instanzdefinition.
  Quellen dürfen zur bewussten Revisionsbindung eine Quellprüfsumme tragen.
- Historische Quellen nur unter `model/history/` führen; alte Generatoren dürfen
  keine aktuellen Baugruppenausgaben überschreiben. Unabhängige Test-Fixtures
  und kuratierte README-Medien sind bewusst erhaltene Momentaufnahmen und
  werden nicht zur führenden Modellquelle.

## Projektweite Vorgabe: fließende Bewegungen

Die Vorgabe gilt für jede neu entwickelte oder erneuerte Roboterbewegung,
auch für leere Fahrten und Raumsondierung. Wegpunkte erzwingen keinen Halt.
Bei Probentransport vom bestätigten Griff bis zur Ablage beziehungsweise
Übergabe eine durchgehende Bewegung ohne unnötige Zwischenhalte planen.
Entnahme-, Freiraum- und Transitmarken sind Durchgangs- oder Ereignispunkte,
keine automatischen Ruhepunkte. Geschwindigkeit,
Beschleunigung und Ruck an der tatsächlich ausgewerteten Kurve begrenzen;
Gelenke, Werkzeug und getragenes Gefäß einschließlich Orientierung prüfen.

Notwendige Griff-, Ablage-, Mess-, Prozess- und Schutzhalte ausdrücklich
begründen und von der Transportbahn trennen. Eine Wartebedingung benennt den
benötigten Abschluss oder die erforderliche Beobachtung, zum Beispiel die
beendete Bewegung einer anderen Achse. Reine Vorführpausen sind keine solche
Bedingung. Eine erforderliche Rückmeldung
nicht durch eine angenommene Freigabe ersetzen. Die gemeinsame PVA-/FK-
Mathematik wiederverwenden; Kein-Halt- und Grenzprüfungen auch zwischen Knoten
und nach Export durchführen. Synthetische Grenzwerte sind keine biologische
oder mechanische Qualifikation; ein sicherheitsbedingter Stopp bleibt möglich.

Ältere Wegpunktillustrationen und statische CAD-Prüfstellungen nicht als
konforme Transportprogramme ausgeben. Bei ihrer Überführung in ein aktuelles
Transportprogramm die Bahn zuerst migrieren und neu prüfen. Einzelheiten und
bekannte Altstände stehen in [ARCHITECTURE.md](ARCHITECTURE.md) und
[docs/requirements.md](docs/requirements.md#fließender-probentransport).

## Zeilenenden und bytegebundene Quellen

Aktive Textdateien verwenden LF im Repository und beim Auschecken
(`.gitattributes`: `text=auto eol=lf`). Herstelleroriginale, `model/history/`,
`tests/fixtures/` und `docs/media/` bleiben bytegenau erhalten. Etwaige aktive
CRLF-Ausnahmen müssten ausdrücklich mit `eol=crlf` deklariert werden.
`docs/line-ending-migration.json` hält die einmalige Umstellung und die
Prüfsummenkette fest. Historische Build-Prüfsummen und Revisionsnamen nicht
auf heutige Bytes umschreiben; Äquivalenz separat dokumentieren. Der Bericht
ist ein historischer Migrationsstand, keine neue Geometrieprüfung.

## Zielarchitektur für Arbeitsumgebungen

Das Vier-Ebenen-Zielmodell steht in [ARCHITECTURE.md](ARCHITECTURE.md):
Arbeitsumgebung → referenzierte Möbeltypen und deren Möblierung → Geräteausstattung.
Für L01 sind Raumgeometrie, Möbelkatalog und Möblierung bereits getrennte Quellen;
`model/lab-room-l01.shared.json` bindet ihre Revisionen als Komposition. Die
bestehenden Körper-IDs, Bezugssysteme und Gerätepositionen sind zu erhalten.
Gebäudekonturen nicht in Möbeltypen und Möbelrezepte nicht in Aufstellungen
kopieren. Flur-/Mehrraumtopologie und allgemeine Gerätebindungen an Möbelrahmen
sind nächste Schritte, noch keine implementierten Funktionen. Vor entsprechenden
Änderungen auch `ARCHITECTURE.md` lesen.

Synthetische Minimalumgebungen sind ebenfalls Teil des Zielmodells: unbegrenzter
Raum, eine Referenzbank und kompakte Geräteaufstellung für Kommunikations- und
Ablauftests. Unbegrenzt, unbekannt und nur zur Darstellung begrenzt unterscheiden;
keine riesigen Ersatzräume konstruieren. Geräte- und Protokollquellen zwischen
realen und synthetischen Aufstellungen wiederverwenden. Mocks, Testzeit,
Netzwerkkommunikation und Hardwareausführung getrennt nachweisen. Die README-
Interaktion Arm/CF01/Rack wird aus `model/synthetic-cf01-workspace.shared.json`
abgeleitet. `model/cf01-rack-batch.protocol.json` beschreibt den ausgeführten
lokalen Mock-Lauf Rack → CF01 → ursprüngliche Rackplätze. Sämtliche Roboterübergaben
sind abstrahiert; eine native Ladebahn, Transporterausführung und
Hardwarekommunikation sind damit nicht implementiert. Der separate
[CF01-Netzwerkadapter](docs/sila2-network.md) ergänzt TLS/gRPC zum Simulator;
die lokale Auswahl `--transport sila2` bleibt ein Mock-Vertragsdecoder. Proben-IDs
und ursprüngliche Rackplätze müssen bei Hin- und Rückgabe erhalten bleiben.

Vor Änderungen an geglätteten CF01-Entnahmebahnen
[docs/cf01-smooth-unloading.md](docs/cf01-smooth-unloading.md) lesen.
`model/cf01-unload-demo.motion.json` referenziert vorhandene Geometrie und
Chargenquellen; Kurven, Eigentümerereignisse und Grenzwerte einmal kompilieren
und in nativer Prüfung, Browser und ROS-Armexport gemeinsam auswerten.
C2-PVA mit begrenztem, gegebenenfalls springendem Ruck nicht als C3 oder
biologisch qualifiziert bezeichnen. Geometriecaches nur mit gültigen Quellen-
und Artefaktpins wiederverwenden; geänderte Bahnen benötigen neue native
Bewegungsnachweise einschließlich aller Gefäße, belegter Rackplätze und
Nachbargeräte. Diskrete Prüfung, ROS-Dry-run, Netzwerk und Hardware getrennt
ausweisen; Stations-/Greiferbefehle sind kein Bestandteil des ROS-Armexports.
Historische Medien und SolidCraft-Importgrenzen unverändert erhalten.

Die beladene Drei-Proben-Fahrt wird vom bestätigten Griff bis zur Rackankunft
als eine durchgehende Bahn kompiliert. Keine Zwischenhalte an Entnahme-,
Freiraum- oder Transitmarken einfügen. Entnahme und Freiraum aus der tatsächlichen
FK bestätigen; Ruhe nur an Griff und Ablage, Bestätigungszeiten anschließend
getrennt führen. Das Kein-Halt-Kriterium und die Grenzen auch zwischen den
Kurvenknoten sowie nach ROS-Zeitquantisierung prüfen. Die Grenzwerte im
Motionprofil nicht zur Verkürzung der Vorführung anheben; biologische Toleranz,
globale Zeitoptimalität und reale Sicherheit bleiben ungeprüft.
Bei adaptiver FK-Verfeinerung bleiben Intervallhüllen die oberen Grenzen;
Abtastwerte nur zur Verfeinerungsentscheidung verwenden. Start-/Höchstauflösung
und Abbruchgrund aus dem Profil beziehungsweise Prüfbericht ausweisen.

Offene Rotorindexierung ist eine additive Opt-in-Simulation aus
`model/cf01-open-lid-index.protocol.json` und `scripts/cf01_open_lid_index.py`.
Basisquellen, Standardbefehle und deren Prüfsummen beibehalten; `index` und
Schleuderstart benötigen weiterhin den verriegelten Deckel. `index_open_lid`
nicht still in MockProtocol, ROS, SiLA, bisherigen Chargenrunner oder gemeinsamen
Workflow aufnehmen. Die neue Befehlsfolge separat mit den vorhandenen
Stationsprädikaten abspielen. Eine logische Uhr beweist keinen Watchdog; der
zeitgebundene Armkanal enthält noch keinen stations-/sensorabhängigen
Abbruchzweig. Geänderte Bahn- und Stationsfenster benötigen neue native
Prüfungen aller jeweils bewegten Gruppen, auch bei durchgehend offenem Deckel.

## Manuelle Aufgaben und Laufzeitdaten

NanoDrop- und Qubit-4-Abläufe sind vollständig synthetisch. Vor Änderungen
[docs/nanodrop-manual-workflow.md](docs/nanodrop-manual-workflow.md) beziehungsweise
[docs/qubit-4-manual-workflow.md](docs/qubit-4-manual-workflow.md) lesen.
One und UltraC verwenden denselben Mikrovolumen-Vertrag in
`model/nanodrop-manual.protocol.json`; Gerätetypen und Fähigkeiten stehen im
Katalog, Instanzen und Testparameter im referenzierenden Laufprofil.
Geräteaufstellung, Arbeitsanweisung und Ausführungszustand getrennt halten.
Eine Katalogfähigkeit oder synthetische Testdatei ist kein geprüfter Geräteadapter.
`scripts/manual_workflow.py` führt die gemeinsame Ablaufhülle; `manual_tasks.py`
speichert deren Ereignisse und Originalartefakte. Beide Runner verwenden denselben
Standard-Store. Laufart und gespeicherte Laufzeitquellen bei Wiederaufnahme prüfen;
keine fremden Zustände oder stillen Migrationen zulassen.

- Verantwortliche Person, physischer Ort, Rackinstanz und Platz-ID getrennt
  führen. Gefäßidentität und ursprünglichen Rackplatz bei jeder Übergabe prüfen.
  Personenbestätigung, synthetische Eingabe und tatsächlichen Scan unterscheiden.
  Gefäß-IDs auch über unterschiedliche Racks hinweg reservieren. Qubit-Ansatz-
  und Standardgefäße bereits bei der Absicht identifizieren und bis zur bestätigten
  Entsorgung im Inventar behalten. Ein Aliquottransfer ist kein zusätzliches Gefäß.
- Entnahmeabsichten vor der Durchführung speichern. Verbrauch und Abstammung
  einschließlich NanoDrop-Aliquots dokumentieren; unbekannte Mengen nicht
  schätzen. Eine Entnahme macht frühere Massenbestätigungen ungültig.
- Messungen über lauf-/versuchsbezogene Kennungen zuordnen. Zeilenfolge und
  Zeitstempel sind keine Identitätsnachweise. Originaldateien und Meldungen
  erhalten; fachliche Bewertung von Messende und Arbeitsplatzrückgabe trennen.
- Laufereignisse, Bestätigungen, Reservierungen und Importe gehören außerhalb
  von `model/` in den ignorierten Laufzeitbereich. Nach Unterbrechung oder Frist
  keine Durchführung, Rückgabe oder Freigabe annehmen. Offene Entnahmen und
  Inventar ausdrücklich abgleichen; Reservierungen bis dahin erhalten.
- Der Einstieg ist `python3 scripts/run_nanodrop_manual.py demo`. Die Tests
  enthalten einen Prozessabbruch mit Neustart. Reale SOP, Exportdateien,
  Mensch-Maschine-Schutzfunktion, Hardware und Netzwerk sind nicht geprüft.
  Qubit startet mit `python3 scripts/run_qubit_manual.py demo`; Netzwerkadapter
  bleiben spätere Schritte. CF01-Fortsetzung benötigt
  aktuelle gemessene Gesamtgefäßmassen und die bestehenden Stationsbedingungen.
- Qubit-Prozesszeit nur durch protokollierte synthetische Zeitereignisse vorrücken.
  Ansatz, Kalibrierung, Assayrevision und Chargen eindeutig verbinden. Der
  Kalibrierungsbezug stammt aus dem Workflow, nicht aus einem geprüften Export.
  Berichtete Originalkonzentrationen nicht nochmals verdünnungskorrigieren;
  Sie erfordern beide bestätigten Ansatzvolumina
  in derselben synthetischen Ergebniszeile. Ableitungen mit Formel, Volumina und
  Einheitenfaktoren ausweisen.

## Gemeinsamer synthetischer Laborablauf

`python3 scripts/run_lab_workflow.py demo` führt zwölf Originale durch CF01,
NanoDrop und Qubit 4. Vor Änderungen
[docs/synthetic-lab-workflow.md](docs/synthetic-lab-workflow.md) lesen.
`model/synthetic-lab-workflow.manifest.json` ist die einmalige Quelle für
Originalproben, Gefäße, Ursprungsplätze und Anfangsmengen. Die Komposition
`model/synthetic-lab-workflow.shared.json` referenziert die vorhandenen Quellen.
Geometrie, bisherige Gerätepositionen und Standalone-Fixtures nicht kopieren.

- Inventar, Buchungen, Prozessuhr und Ressourcen gehören zum Gesamtlauf;
  Geräteergebnisse, Akteure, Fristen und offene Operationen zu `stages[stage_id]`.
  `ManualOperations`, `NanoDropOperations` und `QubitOperations` wiederverwenden.
  Kompatibilitätsansichten sind keine zweite führende Bilanz.
- Plätze als Rackinstanz plus lokale Platz-ID führen. Die Rackinstanz aus der
  Aufstellung referenzieren. Geometrie-IDs und historische Standalone-Orte an
  der Adaptergrenze übersetzen; bestehende Fixtures nicht still neu binden.
- Entnahmen mit eindeutiger Absicht buchen; Restvolumen aus Manifest und
  bestätigten Buchungen ableiten. Unbekannt ist kein Nullverbrauch und die
  Sollmenge keine Obergrenze. Qubit-Messung und Entsorgung belasten das
  Originalgefäß nicht ein zweites Mal.
- Gesamtgefäßmassen mit aktueller Inhaltsrevision und ausdrücklich synthetischer
  Evidenz bestätigen. Bereits offene Entnahmeabsichten entwerten die Freigabe.
  Keine Masse aus Restvolumen ableiten. Qubit-Kammer und Halterplätze sind
  verschiedene Rollen; nur Halterplätze für Vorbereitung/Ablage verwenden.
- CF01-Checkpoints vor Effekten synchron speichern. Negative, fehlende oder
  unvollständige Quittungen, Speicherfehler und Fristen sperren Folgeschritte.
  Aktive CF01-Versuche nach Neustart nicht mit leerem Simulator neu ausführen.
  Abbruchabgleich ist synthetische Personenbestätigung, keine Stationsmessung.
- Root hält Rack, Gefäße und Bankbereich über Stufengrenzen. Gesamtabschluss und
  Abbruchfreigabe prüfen Journal und sämtliche Stufenartefakte vollständig.
  Den geprüften Journal-Präfixpfad nur mit seinen dokumentierten Grenzen nutzen;
  fremde Änderungen, Rollback und getrennte Zustandskopien berücksichtigen.

Die Bilanz gilt innerhalb eines Gesamtlaufs. Globale Bestandsübernahme zwischen
unabhängigen Läufen, Reagenzvorräte, aktive CF01-Jobfortsetzung, Workflow-Netzwerkimport,
Hardware, neue CAD-Geometrie und Sicherheitsqualifikation bleiben unimplementiert.
Vor dem Ausbau der laufübergreifenden Bilanz
[docs/stock-continuation.md](docs/stock-continuation.md) lesen. Der dortige Plan
ist noch kein Laufzeitvertrag: Mengen nicht durch Profilkopien zurücksetzen,
Root-/Stockbuchungen atomar speichern und parallele Fortsetzungen über denselben
Bestandskopf und persistente, gegen veraltete Schreiber abgesicherte Leases führen.

## NanoDrop-UltraC-Netzwerkmodell

Vor Änderungen [docs/nanodrop-ultra-network.md](docs/nanodrop-ultra-network.md)
lesen. `model/nanodrop-ultra-network.protocol.json` führt den ausgewählten
Hersteller-GET-Vertrag einmalig; Client und synthetischer HTTP-Modelladapter
verwenden ihn gemeinsam. Die separate synthetische Modellquelle pinnt Vertrag
und UltraC-Katalogtyp. Keine CAD-Datei ist Netzwerk-Laufzeitabhängigkeit.

- Dokumentierte Pfade und Querytypen von synthetisch gewählten Antwortformen,
  Filterregeln und Pagination unterscheiden. Keine Ultra-Unterstützung für One
  allein aus dem gemeinsamen manuellen Protokoll ableiten.
- Unveränderte Antwortbytes mit Status und Prüfsumme erhalten. Token nicht in
  Quellen, Logs oder Metadaten übernehmen; Redirects nicht verfolgen.
- Abruf, fachlichen Decoder und Workflowwirkung trennen. `SampleName`, Zeit,
  Reihenfolge oder `IsDiscarded` beweisen keine Probenidentität oder Entsorgung.
  Netzwerkabruf bucht keinen Verbrauch und nimmt kein Ergebnis automatisch an.
- `python3 scripts/run_nanodrop_ultra_network.py serve` stellt das synthetische
  Modell bereit; `read` verwendet denselben Client wie eine konfigurierte
  Original-URL. Loopback-HTTP ist geprüft, reale Geräteantworten, Ergebnisdecoder
  und Hardware nicht. Modellkennzeichen sind Selbstauskunft, keine Authentifizierung.

## CF01-SiLA-Netzwerkmodell

Vor Änderungen [docs/sila2-network.md](docs/sila2-network.md) lesen.
`model/cf01-sila2.shared.json` führt den separaten CF01-v2-Netzwerkvertrag und
pinnt Stations-, Protokoll- und Chargenquellen. Der Adapter verwendet denselben
Simulator-/Protokollkern; keine zweite Prozesszustandsmaschine oder Probenbilanz
anlegen. Standard-FDLs und deren Provenienz unverändert erhalten; Versionen
nicht stillschweigend wechseln.
Der implementierte Server verwendet `LockController` v1.0 im Status `Verified`.
Die GENtle-Zielarchitektur in `ARCHITECTURE.md` beschreibt dagegen v2 `Draft`;
diese Verträge nicht gleichsetzen und daraus keine vorhandene GENtle-Bindung
ableiten.

- Einstieg: `python3 scripts/run_cf01_sila2.py --language de --help`.
  `init`, `serve` und `batch` verwenden private Laufzeitdaten unter `exports/`.
  TLS und explizites Zertifikatsvertrauen beibehalten; Zugangsdaten nicht loggen.
- Quellenpins vor dem Start prüfen. Absichten vor Effekten dauerhaft speichern;
  Sperrablauf, Stoppquittung und bestätigten Stillstand getrennt behandeln.
  Unklare Übergaben und alte Ausführungen nach Neustart nicht automatisch
  wiederholen oder freigeben. Bestehende Journale nicht still migrieren.
- Tests aus `requirements/sila2-test.lock` ausführen. Ohne Schalter bleiben
  Netzwerk-/Prozessprüfungen aus; `SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1` aktiviert
  diese. `SOLIDCRAFTBOT_SILA_DOTNET_TESTS=1` setzt die gebaute unabhängige
  .NET-Probe voraus. Übersprungene Tests sind kein bestandener Netzwerknachweis.
- Ausschließlich Simulator, synthetische Roboterbeobachtungen und lokale
  Netzwerkprüfung: keine Hardware, native Ladebahn, Sicherheitsqualifikation,
  formale SiLA-Zertifizierung oder LAN-Qualifikation. Eine GENtle-Bindung und
  die Geräte-Netzwerkanbindung des gemeinsamen CF01/NanoDrop/Qubit-Workflows sind
  damit nicht implementiert; dessen Checkpointvertrag vor Effekten bleibt bestehen.
  T3 ergänzt separat Transport-HTTPS, keine Gerätekommunikation.

## DNA-SiLA-Dienst und vorbereitete Worker-Aufträge

Vor Änderungen [docs/dna-sila2-network.md](docs/dna-sila2-network.md) lesen.
`model/dna-quantification-sila2.shared.json` pinnt DNA-Quellen, Standard-FDLs und
den Auftragsvertrag `model/dna-quantification-tasks.protocol.json`. Der SiLA-Root
bleibt einziger Eigentümer von Journal, Bilanz und Reservierungen. Quittungen
und erste Wirkung atomar im selben Root speichern; Principal, verantwortliche
Person, ausführenden Agenten und Gewahrsam trennen. Keine Geräte-Teilschritte
als Netzwerkbestätigung anbieten. Unklare Ausführungen nicht wiederholen.

`scripts/build_dna_ros_interfaces.py` erzeugt nur ignorierte Action-Definitionen;
der lokale Mock-Worker importiert kein ROS. Worker-Ergebnisse sind Behauptungen,
keine Ortsbeobachtungen oder Verbrauchsbuchungen. Goal-Cancel und Lockablauf geben
keine Root-Ressourcen frei. Weder ROS-Knoten/Action-Server noch Robotik wurden
gebaut oder ausgeführt. RoboStack/pixi ist spätere B1-Arbeit; jetzt nichts
installieren. Neue schematische Nachweise nur unter `exports/dna-evidence/`
ablegen; historische Medien, Galerie und Provenienz unverändert erhalten.

## DNA-Sonikationsvorbereitung

Vor Änderungen [docs/dna-sonication.md](docs/dna-sonication.md) lesen.
`model/dna-sonication.profile.json` bindet den Sonikationsvertrag und die
bestehende CUT&RUN-Vorbereitung. Nur den separaten Input-Zweig zuordnen;
H3K4me3- und IgG-Reaktionen behalten ihre MNase-Fragmentierung. Der Hielscher
UP200St/VialTweeter ist eine Gerätereferenz, keine qualifizierte Gerätebindung.
`python3 scripts/prepare_dna_sonication.py` plant ohne Journal, Reservierungen
oder Geräteeffekte. Unbekannte Puls-, Kühlungs- und Gefäßparameter offen lassen;
ein Geräteabschluss oder NanoDrop-/Qubit-Wert belegt keine Fragmentgröße.
Keine Sonikations-Nebenbilanz, Hardware-, ROS- oder SiLA-Ausführung ableiten.

Die additive [S09-Laufzeitanbindung](docs/cutrun-input-sonication-runtime.md)
verwendet `model/cutrun-input-sonication.profile.json` und die eigene Engine
`input_sonication_mock/1`. Ausschließlich Testuhr und Fixture-Beobachtungen
zulassen; reale SOP-Bereitschaft und fehlendes Herstelleroriginal offen halten.
Absicht, Transformation, QC-Verbrauch, Originalbelege und Ressourcen im
bestehenden Root speichern. Unklare Wirkungen nicht wiederholen; Gerätelease
und ursprüngliche Rackrückgabe ausdrücklich abgleichen. Neue Nachweise nur
unter `exports/sonication-evidence/`; eine abgeschlossene S09 ist kein
abgeschlossener CUT&RUN-Gesamtlauf und kein Hardware- oder Bewegungsnachweis.

## Asynchroner Labortransport T0/T1

Vor Änderungen [docs/async-lab-transport.md](docs/async-lab-transport.md) lesen.
Protokoll, Schema und A/B-Fixture unter `model/async-lab-transport.*.json`
führen den synthetischen Vertrag. `async_transport_domain.py` prüft dieselben
Rollen-/Manifestregeln für Boten- und Robotermock. Keine unabhängige Bilanz oder
zweite Zustandsmaschine pro Adapter anlegen. Der gemeinsame Material-Ledger
führt Material/Gefäß/Inhaltsrevision; Rackplatzierung ist dessen Ownerkontext.

Jobs, Inbox/Outbox, Requests, Job-Unterclaims und Ressourcen gemeinsam im
Rootzustand des vorhandenen Journals committen. Dispatch erst nach dem
erfolgreichen Commit; keine SQL-Transaktion oder globale Sperre über die
Ausführung halten. Die Fixture beginnt unadmitted ohne behauptete Reservierung;
erst Admission führt Inventar und Basisholds atomar ein. Jobabschluss darf weder
einen belegten Platz freigeben noch andere Root-Holds entfernen.

`python3 scripts/run_async_transport.py demo` verwendet `teleportation_mock`:
null Fahrzeit, keine Bahn oder Hardware. Claim, Personenbestätigung, Scan und
Übergabe nicht gleichsetzen; die vier Mock-Rollenbelege bleiben synthetisch.
Ungeordnete Belege kausal anwenden. Ein neues Workerboot oder Session-Resume
rechtfertigt keine Wiederholung eines dispatchten Effekts. Alte/widersprüchliche
Belege und unklare Ausgänge erhalten und ausdrücklich abgleichen; keine
Zeitablauf-Freigabe und kein Zurücksetzen des Orts annehmen.
Späte Konflikte auch auf Folgeaufträge desselben Racks anwenden. Für gehaltene
terminale Jobs gibt es in T1 keine Freigabe-API; das Rack bleibt gesperrt.
Historische Erfolgsereignisse dabei nicht umschreiben.

T1 bindet noch keinen bestehenden biologischen Workflow an, betreibt kein
Netzwerk und authentifiziert keine realen Personen. Die Mocks haben nur einen
instanzlokalen Cache; der Owner bleibt die dauerhafte Autorität. Permanente
Aliquotzuordnungen unverändert lassen. Unabhängige Owners/Stores benötigen den
Stockvertrag. Quellenänderungen sperren aktive Fortsetzungen; keine stillen
Migrationen. Spätere Bewegungsadapter müssen die fließende Bewegungsvorgabe
und eigene reale Übergabe-/Sensorbedingungen erfüllen.

### T2 im gemeinsamen Laborworkflow

`model/synthetic-lab-workflow.transport.json` ist eine ausdrücklich gewählte
referenzierende Komposition; `scripts/run_lab_transport_workflow.py demo` startet
die synthetische T2-Laufart. Bestehende V1-Läufe nicht still umstellen. Topologie
und Routen von Inventar und Geräten trennen. Die Queue bleibt im selben Root und
enthält keine zweite Inventar- oder Mengenliste. Den eingebetteten gemeinsamen
Domänenport und vorhandene Geräteoperationen verwenden; Inhaltsansichten nur aus
den führenden Proben/Gefäßen ableiten. Historische Terminalmanifeste erhalten,
aktuelle Inhaltsrevisionen bei offenen Claims prüfen.

Empfangsstufen benötigen Vorgängerfreigabe und beide vollständigen Quittungspaare.
Transportclaims auch gegenüber Gerätebewegungen und Verbrauch desselben Owners
durchsetzen. NanoDrop-Import und -Bewertung dürfen nach bestätigter Rackrückgabe
während des Transports weiterlaufen; eine Gerätereconciliation darf keinen
Transporthold beseitigen. Absicht, Quittung, Artefakt und Ressourcen atomar per
Root-CAS speichern. Beim Wiederanlauf Sitzung und Queueepoche gemeinsam fencen;
unklare dispatchte Arbeit nicht erneut ausführen.

Die T2-Komposition hält Rack, Originalgefäße und belegte Endpunkte nach biologischem
Abschluss weiter. Späte Konflikte bleiben berichtswirksam; eine terminale
Freigabe-API oder Stock-/Ownerübernahme ist damit nicht implementiert. Der
synthetische Laborlauf besitzt genau das vorhandene Originalrack; generische Tests mit
disjunkten Payloads sind unabhängige Testwelten und keine Bestandskopien. Beam-
Mocks, Netzwerknachweis, reale Robotik und Schutzfunktionen getrennt halten.

### T3: Botenoberfläche und Transportnetzwerk

Vor Änderungen [docs/lab-transport-network.md](docs/lab-transport-network.md)
lesen. Die ausdrücklich neue T3-Komposition referenziert T2; bestehende
Journale nicht migrieren. `NetworkWorkflow` und HTTPS-Service verwenden
denselben Root und Domänenport. Keine zweite Queuezustandsmaschine, Inventar-
oder Mengenliste im Netzwerkadapter beziehungsweise Browser führen.

Konto (`subject`), fachlichen Principal und ressourcengebundenen Grant trennen.
Owner-, Endpunkt-, Agenten- und Beobachterbefugnisse serverseitig prüfen;
Owner dürfen nicht automatisch alle Übergaberollen quittieren. Originalbytes,
Kontobindung, Grant, Fingerabdruck, Quittung und erste Wirkung atomar speichern.
Rollen-/Tokenprüfung und Ownerboot/-epoche unmittelbar vor dem Commit erneut
prüfen. Übergabebelege behalten ihre eingefrorene Jobepoche und Übergabe-ID.

Start, Login, Polling und Wiederverbindung dürfen nichts bestätigen oder
dispatchen. Neue Wirkungen benötigen ausdrückliches Owner-Resume; lesender
Replay einer alten Quittung darf keine aktuelle oder fremde Sitzung übernehmen.
Nach Antwortverlust zuerst den eigenen Beleg einschließlich Originalfingerabdruck
prüfen, gegebenenfalls dieselben Bytes und Kennungen ausdrücklich wiederholen.
Passwörter und Tokens nicht in Browserpersistenz, Journal, URL oder Logs speichern.
Offene Entwürfe dürfen ihre Konto-/Lauf-/Dienstbindung nicht still wechseln.

HTTPS mit explizitem Zertifikatsvertrauen und localhost-Begrenzung erhalten.
Der enge Workflowabgleich gilt nur für unbegonnene manuelle Empfangsstufen;
aktive Gerätearbeit und offene Transportkonflikte nicht pauschal freigeben.
Kontozugang, synthetische Rollenangabe, Scan und physische Übergabe unterscheiden.
Browserfixture, echter HTTPS-/Root-Test und vollständige CLI-Demo getrennt
ausweisen. Transportnetzwerk belegt keine Instrumentkommunikation, reale
Personenzuordnung, LAN-, Windows-, Hardware-, Bewegungs- oder Sicherheitsprüfung.
Stock-/Ownerübernahme und die T2-Freigabegrenzen bleiben unimplementiert.

## Gemeinsame Quellen und Generatoren

| Baugruppe | Führende Quelle | Aufbau |
|---|---|---|
| Laborarm | `model/robot.json` | `python scripts/build_models.py --ros2` |
| Deckelstation C01 | `model/tube-station-c01.shared.json` | `python scripts/build_tube_station.py` |
| Spitzenabwurf T01 | `model/tip-collector-t01.shared.json` | `python scripts/build_tip_collector.py` |

Die Stationsgeneratoren erzeugen derzeit FreeCAD und SolidCraft; eine
ROS-Integration der Stationen ist damit noch nicht implementiert.
Komponentendaten liegen ergänzend in `model/actuator-selection.json` und
`cad/vendor/`. Die ausgewählten Servos sind über `vendor_component` und
`mount_plate` geometrisch integriert. Die X6-Lochbildzuordnung ist in
`model/x6-mounting-interface.json` geklärt: Gehäuse 10 × M3 plus zwei
Zentrierhülsen, Ausgang 12 × M4. Dieselbe Quelle enthält nun eine Ø5-H7-Bohrung,
ein radiales Entlastungslangloch und versenkte M3×10/M4×6-Schraubenstapel.
M3×10 setzt eine bestätigte nutzbare Gewindetiefe voraus; Musterprüfung und
mechanische Qualifikation stehen aus (siehe `docs/x6-fits-fasteners.md`,
`docs/x6-interface-resolution.md` und `docs/servo-integration.md`).
X2/X4 führen Passungen und Schraubenstapel analog in
`model/x2-mounting-interface.json` und `model/x4-mounting-interface.json`.
Eigene Rund-/Entlastungsstifte sitzen mit Pressschäften in den Platten und
greifen in vorhandene Herstellerbohrungen. X4: M3×8 ISO 4762; X2: M3×6/M3×8
DIN 7984 mit reduzierter Kopfbelastbarkeit. Siehe `docs/x2-x4-fits-fasteners.md`.
Aktuelle Modellpfade aus den jeweiligen
Build-Berichten beziehungsweise README beziehen, nicht aus alten Dateikopien.

Die gemeinsame Beschreibung umfasst nach Bedarf:

- Parameter und Abhängigkeiten mit Einheiten, starre Baugruppen, stabile IDs,
  benannte Schnittstellen und Koordinatenrahmen.
- Gelenktypen, Anker, Achsen, Nullstellungen, Grenzwerte und Referenzposen.
- Kaufteilreferenzen mit Revision/Prüfsumme, Montagebeziehungen und eigenen
  parametrischen Anschlussplatten.
- Bewegungs- und Laborprotokolle mit Zuständen, Vorbedingungen, Rückmeldungen
  und Fehlerfällen; dieselben IDs verbinden Ablauf und 3D-Prüfung.
- Nicht sichtbare Anforderungen wie Versorgung, Positionsrückmeldung,
  Kabelführung, Biegeradius, Freiraum, Lasten und Kalibrierbeziehungen.

Unbekannte Werte als offen beziehungsweise `null` führen. Geplante
Schemaerweiterungen nicht als bereits unterstützte Felder ausgeben. Das feste
Sechsachsen-Roboterschema nicht für anders aufgebaute Stationen zweckentfremden.

## Darstellung passend zur Aufgabe

| Ziel | Aufgabe und Detailgrad |
|---|---|
| FreeCAD | Native parametrische Geometrie und Bewegungsdarstellung; Herstellergeometrie für Kaufteile wiederverwenden |
| SolidCraft | Dieselbe Konstruktion und Gelenkstruktur durch den SolidCraft-Adapter erzeugen |
| ROS 2/RViz | Gemeinsame Rahmen, Gelenke, Zustände und Protokolle; leichte Visualisierung und gesonderte Kollisionsgeometrie |
| Gazebo, bei späterem Bedarf | Physik-/Sensorsimulation mit begründeten Massen, Trägheiten, Antriebs- und Kontaktannahmen |

RViz visualisiert Zustände und Sensordaten; es berechnet keine mechanische
Physik. Der aktuelle ROS-Aufbau verwendet Mock-Hardware. ROS-Laufzeit,
Hardwareanbindung und Gazebo nur dann als geprüft bezeichnen, wenn sie
tatsächlich ausgeführt und validiert wurden.

Die Abstraktion soll unnötige Detailarbeit vermeiden: Fasen, Gewinde oder
einzelne Getriebezähne nur modellieren, wenn Fertigung, Kontakt, Passung oder
die konkrete Untersuchung sie benötigen. Für Kinematik können Übersetzung,
Schnittstellen und Bauraum genügen. Vereinfachungen und ihre Prüfgrenzen
dokumentieren; relevante Anschlüsse, Freiräume und Kabelanforderungen erhalten.

Herstellergeometrie unverändert archivieren; Vereinfachungen separat und
nachvollziehbar ableiten. Eigene Motorplatten bleiben editierbare Konstruktionen.
Servos in RViz als einfache Quader vorsehen, ohne dieselbe Servogeometrie noch
einmal im Gliedmesh darzustellen. Gehäuse dem tragenden Elternlink, rotierenden
Ausgang dem Kindlink zuordnen. Montageframes und Lochbilder aus Zeichnungen
registrieren; CAD-Flächenindizes oder geschätzte Außenmaße sind keine stabile
mechanische Schnittstelle. Eine vereinfachte Hülle liefert keine reale Masse
oder Trägheit.

## Projektgrenzen

- Sechs Drehachsen sind eine feste Eigentümeranforderung.
- Zunächst einen Arm entwickeln; bis zu drei Arme an einer Station vorsehen.
- Die austauschbare Pipettenaufnahme bleibt zunächst außerhalb des CAD-Umfangs.
  Das Modell endet an einem allgemeinen Flansch.
- Budgetziel des ersten begrenzten Prototyps: 3.000–5.000 EUR.
- Vorhandene Pipetten, Messgeräte, 3D-Drucker und Universitätswerkstatt berücksichtigen.
- Projektdateien unter diesem Projektordner halten.

## Vor Änderungen lesen

README.md sowie docs/requirements.md, docs/design.md und docs/development-plan.md.
Für Änderungen an Quelle oder Generatoren außerdem `docs/shared-model.md` lesen;
für ROS `docs/ros2.md`, für Kaufteile `docs/vendor-cad-plan.md` und die
Dokumentation der jeweils betroffenen Baugruppe.

## Arbeitsablauf und Rückmeldung

1. Anforderungen und maßgebliche Quelle bestimmen; betroffene Schnittstellen,
   Generatoren und Prüfungen identifizieren.
2. Konstruktionsabsicht in der Quelle ändern, benötigte Adapter ergänzen und
   die betroffenen Zielmodelle neu erzeugen. Unterstützte Ausgaben gemeinsam
   aktuell halten. Fehlende Backends oder bewusst ausgelassene Inhalte benennen.
3. Geometrie, Gelenkrahmen und relevante Protokollstellungen vergleichen.
   Parametervarianten müssen Geometrie und Anker zusammen verändern. Fehler
   mit Baugruppen-/Gelenk-/Protokoll-ID auf die Quelle zurückführen.
4. Quellstand, Generatorstand, Ausgaben und Prüfgrenzen im Build-Bericht
   zuordnen. Neue Revisionen erzeugen, damit geöffnete oder historisch geprüfte
   Konstruktionen nachvollziehbar bleiben.
5. Dokumentation und Einstiegspfade aktualisieren. Im Ergebnis sagen, was sich
   tatsächlich geändert hat, welche Fassungen erzeugt wurden, was geprüft ist
   und welche Teile weiterhin Platzhalter sind.

Für den Arm ist der gemeinsame Einstieg `python scripts/build_models.py --ros2`.
Bei Änderungen an Generatoren oder Modellverträgen die passenden Prüfungen
ausführen; die vorhandene Offline-Suite startet mit
`python -m unittest discover -s tests -v`. Reine Dokumentationsänderungen
benötigen keinen CAD-Neuaufbau. Ein erfolgreicher Dateiexport allein gilt nicht
als bestandene Geometrie-, Bewegungs- oder Funktionsprüfung.

## CAD und Validierung

- SolidCraft-MCP für die Ausführung des SolidCraft-Adapters und Modellinspektion
  bevorzugen. Der reproduzierbare CLI-Aufbau ist ein vorhandener Ausführungsweg;
  beide müssen dieselbe gemeinsame Quelle verwenden.
- Längen in mm; Gelenkwinkel und Grenzwerte mit expliziten Einheiten dokumentieren.
  ROS-Ausgaben ausdrücklich in m/rad umrechnen; Zeiten in s führen.
- Vor Ersetzen einer offenen Konstruktion deren Änderungen und Speicherort prüfen.
- Konzept-Bauräume nicht als ausgewählte oder berechnete Kaufteile ausgeben.
- Bei Änderung der Gliedlängen Geometrie und Gelenkanker aus denselben Parametern
  ableiten und neu prüfen. Im historischen, direkt erstellten A01-Konzept sind
  die Elternkoordinatensysteme fest; eine isolierte native Maßänderung gleicht
  diese nicht automatisch ab.
- Nach geometrischen Änderungen Gelenklösung und betroffene Stellungen prüfen.
  Standpose und vollständigen Bewegungsraum im Prüfbericht unterscheiden.
- Überlappende Konstruktionskörper innerhalb einer starren Baugruppe sind im
  Konzept dokumentiert; daraus folgen keine geprüften Passungen.
- Tragfähigkeit, Steifigkeit, Präzision, Dosierleistung und Sicherheit anhand
  geeigneter Messungen oder Berechnungen belegen, bevor sie zugesichert werden.

## Renderings und Dokumentation

Der Eigentümer hat am 28. Oktober 2026 Modellrenderings und deren Speicherung
für dieses Projekt ausdrücklich freigegeben. Für Modellansichten bevorzugt
SolidCraft `source: model` verwenden.

Anforderungen, Konstruktionsentscheidungen und Grenzen zusammen mit dem CAD
aktualisieren. Exportdateien und Renderings dem zugehörigen Modellstand zuordnen.

Die kuratierte Modellgalerie unter `docs/models/` ist bewusst versionierte
Dokumentation. Ihre Auswahl steht in `catalog.json`; Bilder und Quellen sind
über `provenance.json` gebunden. Nach Änderungen betroffene Ansichten erneuern
und visuell prüfen; `python3 scripts/render_model_gallery.py --check` prüft
Abdeckung, Quell-/Bildprüfsummen und das Bildbudget von 4 MB. Schematische
Darstellungen ausdrücklich benennen; keine CAD- oder Funktionsprüfung aus einem
Bild ableiten. Native Modelle und vollständige Arbeitsrenderings bleiben lokal.


## RNA-/DNA-Extraktionsvorbereitung

Vor Änderungen [docs/extraction-automation.md](docs/extraction-automation.md)
lesen. `model/extraction-automation.*.json` führt Kitmaterial, abstrakte
Prozessrollen und ein synthetisches Vorbereitungsprofil für getrennte
Säugerzellpellet-Aliquots. Der Preflight bucht, reserviert und extrahiert nichts;
`execution_ready` bleibt falsch. Herstellerunterstützung für QIAcube belegt
keinen DIYLabBot-Adapter und keine CF01-Eignung. Kitvarianten und Säulen nicht
stillschweigend austauschen. Nach der gDNA-Eliminator-Säule den RNA-haltigen
Durchfluss von späterem Säulenabfall unterscheiden. RNA-/DNA-Eluate besitzen
eigene Identitäten und bleiben Produkte. Vor Ausführung den gemeinsamen
Lebenszyklus und Ledger für Produktaufbewahrung, Materialumwandlung und
SOP-gebundene Verbräuche erweitern; keinen parallelen Bestand einführen.


Die passive Kitstation K01 steht separat in
`model/extraction-kit-station.shared.json`; vor Änderungen
[docs/extraction-kit-station.md](docs/extraction-kit-station.md) lesen.
Kitrollen aus dem Extraktionskatalog referenzieren, keine zweiten Material-
oder Mengenlisten pflegen. Physische Hüllen und Passungen sind synthetische
Entwurfsannahmen. Geschlossene Kitvorräte, Arbeitsansätze und Probenlagerung
nicht gleichsetzen. Beide CADs unabhängig aus denselben Operationen erzeugen;
ein einzelner Backend-Aufbau belegt keinen CAD-übergreifenden Vergleich.

K01 hält in Version 1 beide Kits direkt an der Station bereit. Griffe und
Greifbezüge aus demselben Behälter-/Deckelrezept ableiten und für alle
statischen Fälle neu prüfen. Modellierte Griffe belegen weder reale
Greifbarkeit noch Transportfreigabe; Last, Retention, Druckfestigkeit und
Greifer bleiben gesondert zu qualifizieren. Einen späteren Regalzugriff
nicht als bereits implementierte Funktion ausgeben.

## Synthetischer Storage-Testfall S01

Vor Änderungen [docs/synthetic-storage-s01.md](docs/synthetic-storage-s01.md)
lesen. Die S01-Komposition referenziert genau einen geschlossenen K01-Träger;
Geometrie, Greifrahmen und Freiraumproben gemeinsam aus derselben Quelle und
Transformation ableiten. Alternative statische Fälle nicht als Roboterbahn
ausgeben. Die bestehende fließende Bewegungsvorgabe gilt für spätere
Transportprogramme weiter.

Ein Fixture ist eine ausdrücklich synthetische Testwelt im vorhandenen Journal,
kein realer oder zweiter Materialbestand. Symbolische Inhaltsidentitäten nicht
als Packungsstückzahl oder Mengenbestand ausgeben. Derselbe Fixturezustand darf
bei Initialisierung nicht zurückgesetzt werden. Absichten vor Bestätigungen
speichern; offene Vorgänge und Reservierungen bei Neustart erhalten und
ausdrücklich abgleichen. Keine Hardware-, Stock-, Greif- oder Lastqualifikation
aus dem Mock oder statischen CAD-Fällen ableiten.

## Relative Mehrraumgeometrie F03

Vor Änderungen [docs/floorplan-f03.md](docs/floorplan-f03.md) lesen.
`model/floor-f03.shared.json` führt ausschließlich freigegebene manuelle
Ableitungen mit relativen Koordinaten. Gemeinsame Wände und Öffnungen einmal
beschreiben; Bereichsränder und Nachbarschaften daraus ableiten. Unklare
Grenzen nicht durch erfundene Wände, Türen oder Raumnummern vervollständigen.
Ohne Kalibrierung bleiben reale Maße `null`; ein ausdrücklich gewählter
CAD-Darstellungsmaßstab ist keine metrische Gebäudeaufnahme. Keine automatische
Übernahme der bisherigen L01-Maße oder Gerätepositionen vornehmen.

Das private Originalfoto, Kopien, Ausschnitte sowie dessen lokale Pfade,
Prüfsummen und Metadaten nicht in Git-Quellen, Galerie oder öffentliche
Provenienz übernehmen. Lokale Zuordnungsdaten liegen ausschließlich im
ignorierten Bereich unter `exports/`. Öffentliche Ansichten nur aus den
freigegebenen Vektordaten erzeugen, ohne das Originalbild einzubetten.
Native Öffnungsschnitte und relative Nachbarschaften belegen keine realen
Türmaße, Durchfahrbarkeit, Fluchtwege oder Sicherheitsqualifikation.

Die viergeschossige Komposition `model/building-stack.shared.json` referenziert
F03 einmal; vor Änderungen [docs/building-stack.md](docs/building-stack.md)
lesen. Geschoss-IDs, Höhenableitung und die gemeinsame Atriumabdeckung durch
die vorhandenen EG-Raum-/Flurböden auswerten. 4 m lichte Höhe und die vorläufige Plattendicke
nicht mit dem Geschossabstand gleichsetzen. Die referenzierte ungemessene
L01-Breite ist nur eine Darstellungsproportion, keine metrische Registrierung.
Vorlagen-Raumnummern nicht als bestätigte Nummern weiterer Geschosse ausgeben.
Die Dachglasfläche referenziert Atrium, alle vier Flure und den eingeschlossenen
Kern statt einer kopierten Kontur oder pauschalen Rechteckabdeckung. Gewölbeachse
und Querprofil gemeinsam auswerten; die aktuelle X-Achse besitzt ein Y/Z-Profil.
Die erweiterte Dachöffnung nicht auf die kleineren Geschossöffnungen übertragen;
Flurböden erhalten.
Der Kellerplan bleibt ausstehend; eigenes EG und Dach sind implementiert. Konzeptmarker
für vertikalen Austausch getrennt von Gebäudegeometrie und Transportprogrammen
führen; statische Bilder und offene Geschossplatten beweisen keine freie Bahn,
Förderfunktion, Tragfähigkeit oder Schutzwirkung.

Gebäudeaufzug, inneres Treppenhaus `R3_028` und äußere Metalltreppe `R3_017`
besitzen getrennte Quellenrollen und CAD-Gruppen. Nur die innere Treppe und
der Aufzug reichen vom Keller bis ins 3. OG; die Metalltreppe reicht vom Dach
zum Boden und endet im EG neben Zugang 22. Keine Treppe an den Aufzug hängen.
Der Flur und der seitliche Versatz bleiben aus den Quellbezügen erhalten.
Die bestätigte Aufzugzuordnung lautet außen =
`W049` zum Flur `C3_020`, innen = `W062` zum `NorthCore` der Obergeschossvorlage.
Im EG gelten die entsprechenden eigenen Flurflächen; deren Darstellung ist
weiterhin kein Nachweis einer navigierbaren oder qualifizierten Verbindung.
EG beidseitig, Obergeschosse nur außen; KG nur innen als vorgemerkte Regel
ohne Kellerhöhe oder Kellergeometrie führen. Türseiten nicht aus Blickrichtung
oder Gebäudeschwerpunkten neu erraten. Öffnungen in den tatsächlichen
Wandkörpern prüfen, nicht nur Türrahmen vor geschlossene Wände setzen.
Treppenläufe und Podeste aus einem Rezept erzeugen; obere Platten mit
passenden Aussparungen versehen und geometrische Anschlüsse neu nachweisen.
Die vorhandenen F03-Quellen und deren alte Nachweise bleiben unverändert.
Ein Aufzugmodell besitzt eine Kabine, keine Kabinenkopie je Geschoss.
Gebäudeerschließung vom blauen Atrium-Austauschkonzept unterscheiden;
Stufendarstellung, statische Kabine und Aussparungen belegen keinen Betrieb,
keine Begehbarkeit, Schachtfreigabe oder Brandschutzqualifikation.

Das EG verwendet `model/ground-floor-eg.shared.json` statt einer F03-Kopie;
vor Änderungen [docs/ground-floor-eg.md](docs/ground-floor-eg.md) lesen.
Kernvertices referenzieren F03 direkt. Literalvektoren sind bereits manuell
im gemeinsamen Rahmen; die vermerkte 180°-Planorientierung nicht nochmals
anwenden und keine starre photogrammetrische oder metrische Registrierung
behaupten. Seminarraum, Foyer und WC-Anordnung gehören nur zur EG-Quelle.
Die vorhandenen EG-Raum-/Flurböden gemeinsam auf Atriumabdeckung prüfen;
keine zusätzliche Füllplatte über sie legen. Originalfotos bleiben privat.

Dach, gewölbtes Glas und Umrandung aus derselben Komposition ableiten. Das Dach
ist kein fünftes Geschoss. Seine Platte liegt über der obersten lichten Höhe;
Glasränder reichen über die Atriumöffnung auf die äußere Dachfläche. Parameter
sind Darstellungsannahmen, keine nachgewiesene Entwässerung, Tragfähigkeit oder
Absturzsicherung. Außenmetalltreppe nie mit Kelleranschluss ausstatten; der
Kelleranschluss von Aufzug und innerer Treppe bleibt bis zum Plan ohne Geometrie.
