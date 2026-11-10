# Entwicklungsplan für den ersten Laborarm

Die [L01-Raumaufstellung](lab-layout-l01.md) ergänzt jetzt eine gemeinsame
Quelle für drei Arme, Stationen und Bodenfahrzeug. Nach dem Aufmaß sind
Türschwenkräume, Anschlüsse, reale Werkzeug-/Greifräume, kollisionsgeprüfte
Armabläufe und der gemeinsame Verkehr mit Menschen weiterzuentwickeln.
Die erste Studie liefert statische Geometrie und Endpunkt-Reichweiten.

## Erste Etappe

Die [mobile Basis MB01](mobile-base-mb01.md) parallel als eigene Baugruppe
qualifizieren: zunächst manuell verschieben, in kompakter Pose zur Seite stellen,
auf drei Füßen abstützen und die lokale Aufgabe neu erfassen. Mitarbeiter können
Parkaufwand und zurückgewonnene Bankfläche beurteilen. Wiederholtes Versetzen mit
unterschiedlicher ungefährer Rückkehrlage soll anschließend Kamerawiedererfassung,
Spitzen-/Gefäßfehler und Einschwingzeit prüfen. Ein Präzisionsdock oder eine
autonome Fahrregelung ist dafür keine Vorbedingung. Masse, Stützsteifigkeit,
Kippmomente, reale Schraubfüße, Tischkante und flexible Zuleitung vor dem Betrieb
auslegen und prüfen; die CAD-Kontaktstellungen ersetzen diese Versuche nicht.

Den aktuellen sechsachsigen Aufbau als gemeinsame Diskussionsgrundlage nutzen.
Anhand vorhandener Pipetten die spätere Werkzeugmasse und den Schwerpunkt
festlegen. Die Pipettenaufnahme bleibt bis zur gesonderten Konstruktion ausgelassen.

Parallel einen optischen Prüfstand aus Gefäßhalter, vorhandener Pipette,
Beleuchtung und Kameras aufbauen. Transparentes Wasser im echten Gefäß untersuchen.
Die erste Kameraansicht wird schräg durch die Öffnung erprobt, eine zweite Ansicht
seitlich. Reflexionen, Verdeckung und Verzerrung durch die Gefäßwand bestimmen
die endgültige Anordnung.

Der inzwischen gewünschte Aufbau umfasst zwei Armkameras zusätzlich zu mehreren
stationären Laborkameras. Auf dem Prüfstand die Nahansicht der unteren Armkamera
und die Weitwinkelansicht der oberen getrennt entwickeln. Die zwei zuerst
erprobten Blickrichtungen legen noch keine zwei stationären Kameras und kein
Stereopaar fest. Die Montagevorschläge stehen im [Kamerakonzept](design.md#konzeptoption-zwei-armkameras-und-stationäre-laboransichten).

V02 ist inzwischen in der gemeinsamen Armquelle und allen drei Ableitungen
implementiert: C_tip an L6, C_scene an L1, provisorische Halter und transparente
Sichtkegel. Das ist eine geometrische Diskussionsgrundlage für die folgenden
optischen Versuche. Kein Kameraartikel, Halter oder Sichtfeld ist damit
qualifiziert; die Pipettenaufnahme bleibt außerhalb des CAD-Umfangs.

Vor der Kamerabeschaffung folgende Schritte durchführen:

1. Für Nah- und Übersicht festlegen, welche Merkmale in welchen Arbeitsposen
   sichtbar und messbar sein müssen; Zielgenauigkeit und zulässige Verdeckung
   bestimmen.
2. Mit vorhandener Kamera und einstellbarer Halterung Sicht auf Spitze,
   Gefäßöffnung und Wandtropfen am konkreten Gefäß testen. Deckel, Rack,
   Kühlaufnahme und Kondensat berücksichtigen. Beleuchtungsvarianten vergleichen.
3. C_tip nahe L6 und C_scene nahe L1/L2 als Montagekandidaten vergleichen;
   Sichtverdeckung durch den eigenen Arm, Arbeitsabstand, Schärfentiefe,
   Haltersteifigkeit und Masse über die benötigten Arbeitsposen bewerten.
4. Stationäre Überblicks- und Arbeitsplatzansichten an einer gemeinsamen
   Stationsreferenz kalibrieren; Kamera-Montageglied-Beziehungen und tatsächliche
   Spitzenlage bestimmen. Für bewegte Aufnahmen Belichtungszeitpunkt,
   Gelenkmesswerte und Bildalter zusammen erfassen.
5. Nach der optischen Erprobung Kameras, Objektive und Beleuchtung auswählen,
   Kosten und Schnittstellen erfassen und die provisorischen Bauräume in der
   Modellquelle durch die gewählten Baugruppen ersetzen. Kameraleitungen einschließlich der
   J6-Durchführung und die betroffenen Bewegungsräume erneut prüfen.

Die bisherigen 400 EUR für Optik und Beleuchtung sind durch diese Erweiterung
nicht als ausreichendes Angebot belegt. Zahl und Kosten der stationären Kameras,
Objektive, Halter, Beleuchtung und Rechneranschlüsse gesondert kalkulieren;
die Gesamtbudgetgrenze bleibt bestehen.

## Mechanischer Nachweis

Für die motorlose Gefäßstation [H03](tube-cam-h03.md) zuerst Kurvenscheiben,
Rollenfolger und Riegel als langsamen Prüfstand herstellen. Federn auswählen,
Folgerkontakt, Schließ-/Entriegelungskraft und notwendiges Roboterdrehmoment
messen. Den Halt bei zurückgezogenem Folger sowie den unterstützten Rücklauf
mit realen Gefäßen prüfen. Erst nach bestätigter Übernahme darf der Roboter die
220°-Prüfstellung verlassen. Quelle und beide CADs mit
`python scripts/build_tube_cam.py` neu ableiten; native Kurvenkopplungen mit
`python scripts/verify_tube_cam_native.py` prüfen.

Der vollständige Anschauungszyklus entsteht mit
`python scripts/build_tube_cam_animation.py` aus einer eigenen gebundenen
Ablaufquelle. Geprüft sind Bewegungsreihenfolge, dauernde Gefäßunterstützung,
vollständiges Wiederaufrüsten und native Transformationsmatrizen; Betriebskräfte,
Drehmoment und zulässige Geschwindigkeiten anschließend am langsamen Prüfstand
bestimmen. Die im Film angenommenen Bestätigungen nicht als Sensornachweis werten.

Die [bevorzugte Servoauswahl](actuator-selection.md) ist inzwischen als
[gemeinsame Geometrie](servo-integration.md) mit zwölf Motorplatten integriert.
Gehäuse-/Ausgangsrahmen sind registriert; die vermeintliche X6-Abweichung wurde
als falsche Zuordnung der Maßpfeile geklärt und die Motorplatten korrigiert.
Die [X6-Passungen und Schraubenstapel](x6-fits-fasteners.md) sind jetzt nominell
ausgelegt. Als Nächstes Hülsenmaße und Gehäusegewindetiefen messen, die bedingte
M3×10-Auswahl bestätigen und eine repräsentative Aufnahme am Prüfstand
qualifizieren. Die sechs geometrischen Gelenke sind noch keine fertig
ausgelegten oder qualifizierten Gelenke. Der
[CAD-Integrationsplan](vendor-cad-plan.md) beschreibt die Erweiterung der
gemeinsamen Quelle, beider CAD-Adapter und der RViz-Quaderdarstellung.

Auch [X2/X4](x2-x4-fits-fasteners.md) haben jetzt nominelle Schrauben- und
Stiftauslegungen. Zunächst die Ø3-Herstellerbohrungen und nutzbaren Gewindetiefen
messen, Fertigung der eigenen gestuften Stifte abstimmen, Presssitz und
Steckmontage prüfen. Die reduzierten X2-Köpfe, schmalen Plattenränder und
das vorgesehene Anziehdrehmoment am repräsentativen Prüfglied qualifizieren.

Zunächst eine repräsentative Schulter- oder Ellenbogenbaugruppe fertigen und
unter definierten Kräften vermessen. Lastfälle, Spiel, Steifigkeit und
Positionsmessung am Ausgang bewerten. Auf dieser Basis die übrigen Gelenke auslegen.
TCP-Genauigkeit, Nutzlast, Wiederholbarkeit, Einschwingfenster und Zykluszeit
vorab quantifizieren. Schnelle Transfers und die optische Feinanfahrt getrennt
vermessen; zeitgestempelte Istwerte erlauben ein gemessenes Bewegungsende.
Mehrere Arme sollen später durch Vorbereitung und Übergaben den Durchsatz
erhöhen. Die geforderte Genauigkeit wird weiterhin pro Arm nachgewiesen.

Servoantriebe mit auslesbarer Istposition wählen; Messort, Referenz, Übersetzung,
Abtastrate und Datenalter festlegen. Parallel die logischen Leitungswege
in räumliche Führung, Zugentlastungen und Bewegungsreserven überführen. Biegung,
Torsion, Freiraum und elektrische Versorgung an vorgesehenen Bahnen und
Gelenkgrenzen prüfen. Die Serviceebene bleibt auch bei ausgeblendeten Kabeln Teil
des gemeinsamen Modells; ihre Topologieprüfungen ersetzen diese Nachweise nicht.

Anschließend den kompletten Arm referenzieren und mehrere Werkzeughaltungen
vermessen. Messungen an der Spitze und über unterschiedliche Anfahrtrichtungen
liefern die Grundlage für die spätere Feinanfahrt.

## Zielversuch mit einem Mikroliter

1. Gefäß und Pipettenspitze lokalisieren.
2. Einen Mikroliter Wasser an einer definierten Wandstelle ablegen.
3. Spitze zurückziehen und Tropfen erneut optisch lokalisieren.
4. Bildgeführt langsam annähern und Wasser wieder aufnehmen.
5. Restflüssigkeit und Rückgewinnung unabhängig bewerten.

Als erster Versuchsplan sind 30 manuelle Referenzzyklen unter denselben
Bedingungen vorgesehen. Die Anzahl und endgültigen Abnahmekriterien werden
vor der robotischen Vergleichsmessung festgelegt.

Auswertungen umfassen die Erkennungsquote, Positionierabweichung,
Wiederfindungsrate, Streuung, Laufzeit und notwendige Bedienereingriffe.
Die abgelegte und zurückgewonnene Wassermenge, Verdunstung und Messunsicherheit
müssen nachvollziehbar bestimmt werden.

Leichte Variation der Ablagestelle und Gefäßposition prüft anschließend die
tatsächliche Wirkung der optischen Korrektur.

## Weitere Ausbaustufen

### Optionale Prüfung des Pipettierens auf Eis

Der [Maschinenentwurf C01 und sein SiLA-2-Interaktionsprotokoll](tube-station-c01.md)
liegen als getrennte Diskussionsgrundlage vor. Vor dem Hardwarebetrieb einen
SiLA-Simulator mit echtem Client prüfen: exklusive Roboterfreigabe, Beobachtung
laufender Befehle, veraltete Rückmeldungen, Verbindungsabbruch, Stoppen und
Wiederanlauf. Schema-Prüfung der Feature-XML allein belegt keine Interoperabilität.

Die Station mit `python scripts/build_tube_station.py` in beiden CADs aus der
gemeinsamen Stationsquelle erzeugen. Bei künftigen Geometrieänderungen die
nativen Featurebäume, gemeinsamen Anker und den Körpervergleich erneut prüfen;
die erste Prüfung umfasst vier Geometriefälle. Beladung und reale Kontaktfolge
bleiben davon getrennte mechanische Prüfaufgaben.

Vor der Fertigung den vollständigen Beladungs- und Entnahmeweg mit echtem
Gefäß und vorgesehenem Greifer prüfen. C01 bietet nur 4 mm freien Körperbereich
unter dem Kragen; eine erfolgreiche Deckelpose belegt keine Handhabbarkeit.
Den [vorgeschlagenen wechselbaren Träger](tube-station-c01.md#loading-review-c01-does-not-establish-automatic-tube-handling)
zunächst manuell bestücken und als Alternative zur direkten Gefäßbeladung
untersuchen. Docking, Stationsverriegelung, Greiferfreigang und Wärmekontakt
gemeinsam auslegen; automatische Rack-zu-Träger-Beladung separat bewerten.

Der [H01-Entwurf](tube-carrier-h01.md) stellt dafür jetzt eine abstrakte gemeinsame
Quelle und Generatoren für zwei native CADs bereit. Mit
`python scripts/build_tube_carrier.py` beide Gefäßformen, Parametergrenzen und
gesampelte Frontübergaben prüfen. Anschließend reale Gefäße ausmessen und einfache
Pass-/Stabilitätsmuster drucken; erst danach Clipfreigabe, Greifer, Dockverriegelung
und den Anschluss an C01 samt vollständigem Roboterweg konstruieren.

Für den optischen Prüfstand nun den [offenen H02-Rahmen](tube-frame-h02.md) mit
`python scripts/build_tube_frame.py` in beiden CADs erzeugen. Reale Gefäße zuerst
manuell in offenen Mustern testen: Kippstabilität, Sicht auf Flüssigkeit und
Wandtropfen sowie Beleuchtung. Danach geformten Bodenheber und geteilten Empfänger
mit gemessenen Kontaktkräften und bestätigter Übernahme untersuchen. Heber erst
nach Empfangsbestätigung zurückziehen; Empfänger erst nach freiem Heber bewegen.
Der Verlust großer Kühlkontaktflächen erfordert ein neues thermisches Konzept,
falls die Option Pipettieren auf Eis weiterverfolgt wird.

Für den zusätzlichen Kühlwunsch zunächst einen einzelnen Gefäßplatz aufbauen,
der während Öffnen, Pipettieren und Schließen fest im Stationsrahmen bleibt.
Einen wärmeleitenden Einsatz mit Wassereis kühlen; passende Gefäßartikel und
Füllstände sowie die erlaubte Probentemperatur und Betriebsdauer vorab festlegen.
Diese Option ist noch keine zusätzliche Abnahmebedingung des ersten Zielversuchs.

Blocktemperatur und repräsentative Probentemperatur über Abkühlung, offene
Pipettierphasen und wiederholte Zyklen erfassen. Für den 1-µl-Wandtropfen ein
geeignetes Mess- oder Referenzverfahren nahe der tatsächlichen Ablagestelle
festlegen; ein Fühler in einem vollen Vergleichsgefäß reicht dafür allein nicht.
Gefäßpose bei schmelzendem Eis, Deckelkräfte und Verrastung im kalten Zustand,
Kondensatführung sowie Sichtbarkeit des Tropfens prüfen. Ablage und Wiederaufnahme
bei Raumtemperatur und unter den vorgesehenen kalten Bedingungen getrennt
bewerten. Eine Temperaturmessung am Block ersetzt weder die Probenmessung noch
den Volumennachweis.

### Weitere Entwicklung des Arms und der Station

Für den [Spitzenabwurf T01](tip-collector-t01.md) zunächst die konkreten Spitzen
der 10-, 200- und 1000-µl-Pipetten ausmessen. Freien Schaft, Spitzenrand und Abstand
zur Abwurfhülse prüfen und die austauschbaren Nuten daraus dimensionieren. Am
Prüfstand Abziehkraft, Haltekraft der Pipettenaufnahme, Verschleiß und wiederholtes
freies Abfallen messen. Behälteranwesenheit, tatsächliche Füllgrenze und fehlende
Spitze am Werkzeug erfassen; danach Stationsbezug und vollständige Roboterbahnen
mit dem realen Werkzeug kalibrieren und prüfen. Die drei Volumenmarkierungen des
CAD sind noch keine Artikelqualifikation oder Betriebsfreigabe.

Die parallele T01-Entwicklung erfolgt mit `python scripts/build_tip_collector.py`.
Änderungen der freigegebenen Entwurfsmaße in `parameters` der gemeinsamen Quelle
übernehmen und beide CADs erneut erzeugen. Der aktuelle Vergleich deckt
Standardmaße, eine mittlere Nut von 7 statt 6 mm und einen um 10 mm höheren
Behälter ab; er prüft zusätzlich native Maßänderungen ohne Neuaufbau. Die
sichtbare UMR-Schrift gehört in beiden Fassungen zur entnehmbaren Sammelbox.

Änderungen jetzt in der gemeinsamen Quelle `model/robot.json` ausarbeiten.
Beide CAD-Fassungen und die ROS-2-Dateien daraus neu erzeugen und vergleichen.
Geometrie, Gelenkanker und Bewegungssequenzen müssen denselben Parametern folgen.
Die alten direkt erstellten CAD-Dateien wurden auf Eigentümerwunsch gelöscht; numerische Referenzdaten und historische Prüfberichte bleiben erhalten.

Die Entwicklungsschleife zunächst mit Gelenksequenzen, zeitlichen Abläufen und
nachvollziehbaren Fehlermeldungen ausbauen. ROS 2 und RViz auf einem verfügbaren
Jazzy-System starten und die vorbereitete Trajektorienschnittstelle integrieren.
Danach bei einer konkreten Dynamikfrage Gazebo anbinden; zuvor Massen,
Trägheitstensoren, Antriebseigenschaften und Kontaktannahmen bestimmen.

Für eine spätere Bewegungsplanung konkrete Aufgabenposen und Bahnen mit
Werkzeug, Gefäßhaltern und Tisch modellieren. Die derzeitige Gelenkanimation
und die Prüfung einzelner Posen ersetzen keine vollständige Kollisionsprüfung,
inverse Kinematik, Dynamikrechnung oder reale Positionsmessung.

Nach reproduzierbarem Einzelarmbetrieb weitere Werkzeuge für 1–1000 µl,
96-Well- und 384-Well-Gefäße entwickeln. Eine spätere zentrale Ablaufsteuerung
reserviert gemeinsame Arbeitsbereiche für zwei oder drei Arme.
Werkzeugpose, Gefäßbelegung und Flüssigkeitstransfer werden als definierte Zustände
geführt; Wiederanlauf nach Unterbrechungen braucht einen geprüften Ablauf.

### Analytikstation: zwei zusätzliche Arme und Probenvorverdünnung

Die [neue Zielrichtung](requirements.md#gewünschte-analytikstation-mit-zwei-kooperierenden-armen)
verwendet zwei zusätzliche, weitgehend baugleiche Sechsachsarme neben dem
CF01-Arm. Als erster Prüfaufbau übernimmt ein Arm Gefäße und Deckel, der andere
eine betätigbare Pipette. Damit soll die separate Pipettierpositionierapparatur
entfallen können. Passive Gefäßhalter, Werkzeugablagen, Spitzenvorrat,
Reagenzplätze, Abfall und die NanoDrop-Reinigung gehören zur Auslegung.

1. Vorhandene Pipetten, passende Spitzen, Original-/Verdünnungsgefäße und
   Qubit-Ansatzgefäße bestimmen. DNA- und RNA-Assays, Konzentrationsbereiche,
   Probenverbrauch, Durchsatz sowie Dosier- und Verschleppungskriterien festlegen.
2. Ein gemeinsames Werkzeugkonzept mit Halterung, Dosierbetätigung,
   Spitzenaufnahme/-abwurf und optischem Spitzenbezug ausarbeiten. Masse,
   Betätigungskräfte und Werkzeugverformung am vorhandenen Arm prüfen.
3. Zunächst an einem ruhenden Gefäß in passiver Aufnahme Dosierabweichung,
   Streuung und Verschleppung messen. Die optische Feinanfahrt und die
   Volumenprüfung gesondert nachweisen; einen zweiten bewegten Gefäßbezug erst
   nach dieser Referenzprüfung untersuchen.
4. Zwei Instanzen derselben Armquelle samt unterschiedlichen Werkzeugen aus
   gemeinsamen Quellen aufbauen. Gemeinsame Rahmen, Arbeitszonen, Übergaben,
   gegenseitige Sperren und Parallelaufgaben entwickeln und in beiden CADs
   einschließlich der Werkzeuge und Gerätedeckel prüfen.
5. Im bestehenden Inventar-/Ablaufkern eine eigene Vorverdünnungsoperation
   ergänzen: identifiziertes Zielgefäß, gespeicherte Transferabsichten,
   bestätigte Probe-/Verdünnungsmittelvolumina, Mischung und Herkunftskette.
   Weitere Qubit-Entnahmen belasten das Verdünnungsgefäß; das Original wird
   durch denselben Transfer nicht erneut belastet. Unterbrechungen erfordern
   den Abgleich offener Transfers und Gefäße.
6. NanoDrop-Direktmessung und Qubit-Messung nach optionaler Vorverdünnung
   integrieren. Ergebnisbasis und externe Verdünnungsfaktoren prüfen; eine
   bereits vom Gerät berücksichtigte Assayverdünnung nicht doppelt anwenden.
   DNA- und RNA-Profile getrennt qualifizieren, anschließend Parallelbetrieb
   und Wiederanlauf der beiden Arme prüfen.

Die erste statische Konzeptaufstellung wird inzwischen aus
`model/two-arm-analytics.shared.json` erzeugt. Sie referenziert die bisherige
CF01-Bank mit ihrem Arm und eine separate Analytikbank mit zwei identischen
Armvarianten aus `model/robot.json`. Möbeltyp, Möblierung und Geräteausstattung
bleiben getrennte Quellen. `model/analytics-tools.shared.json` beschreibt die
neuen unvermessen gezeichneten Pipetten-, Gefäßhalter- und Verbrauchsteilmodelle.
Originale, Vorverdünnungen und Qubit-Ansätze besitzen getrennte Ablagen; zwei
passive Einzelaufnahmen stehen zwischen den Analytikarmen. Der Pipettierarm
zeigt sein Werkzeug über der Zielaufnahme, während der Handhabungsarm über dem
Originalrack steht.

```sh
python3 scripts/build_analytics_concept.py
python3 -m unittest discover -s tests -p 'test_analytics_concept.py' -v
```

Der Einstieg verwendet geprüfte native Ursprungsmodelle und den bestehenden
unabhängigen SolidCraft-CF01-Bericht. Dessen Pfad lässt sich mit `--core-report`
angeben; die vorhandenen CAD-Adapter erzeugen diese Eingaben auf einem frischen
Checkout. Quell- und Artefaktprüfsummen sowie die Gleichheit der ursprünglichen
CF01-Konstruktion und Prüfstellungen werden vor Wiederverwendung geprüft.
`cad/two-arm-analytics/shared-build-report.json` löst die neuen FreeCAD- und
SolidCraft-Gesamtmodelle, Gesamtansicht, Analytikdetail und Geometrieprüfungen auf.
Beide CADs verwenden ihre eigenen nativen Geometrien. Die Prüfung vergleicht
Instanzvolumen und Schwerpunkte, Gelenkgrenzen, die dargestellten Werkzeugziele,
statische Überschneidungen und die Stellflächen der neuen Ausstattung.

Die bestehenden manuellen Runner führen keine externe Probenvorverdünnung aus;
das aktuelle Qubit-Assay ist synthetisch. Die neue Ansicht enthält Konzeptkörper
für die Werkzeuge; mechanische Pipettenauslegung, Dosierfunktion, kooperative
Armsteuerung und durchgehende Bewegungen sind weiterhin zu entwickeln. Aus der
statischen Darstellung folgen keine geprüften Gefäßpassungen, Dosiermengen,
Traglasten oder sichere Zusammenarbeit. Bestehende Abläufe sind nicht an die
neuen Konzeptgefäße gekoppelt.

### Manuelle Aufgaben und Messgeräte

Der erste [synthetische NanoDrop-Ablauf](nanodrop-manual-workflow.md) ist
implementiert: gemeinsame Mikrovolumen-Protokollquelle für One und UltraC,
transaktionales Laufprotokoll, Entnahmen und Abstammung, Dateiimport sowie
platzweise bestätigte Rückgabe. Handarbeit und Datenübernahme, Verantwortlichkeit
und physischer Ort sind getrennt. Tests prüfen auch Prozessabbruch und Neustart.
Sämtliche SOPs, Bedienhandlungen und Messdateien sind vorerst synthetisch.
Der [synthetische Qubit-4-Ablauf](qubit-4-manual-workflow.md) ergänzt inzwischen
Ansatzgefäße, Transfers, Standards, eine laufbezogene Kalibrierung und explizite
synthetische Zeit. Beide Abläufe verwenden denselben Kern und Store.
Der [gemeinsame synthetische Gesamtlauf](synthetic-lab-workflow.md) führt zwölf
Originalgefäße durch CF01, NanoDrop und Qubit auf einem Inventar mit dauerhaften
Entnahmebuchungen und getrennten Stufenzuständen. Aktive CF01-Jobs werden nach
Absturz nicht neu gestartet; ein synthetischer Abbruchabgleich ist erforderlich.
Echte Exportqualifikation, Netzwerkadapter, ein laufübergreifendes Volumenbuch
und eine Fortsetzung in CF01 folgen später. Das weitergehende Zielmodell steht unter
[Manuelle Aufgaben und Messgeräte](manual-tasks.md).

## Budgetansatz

Für die [Raumumgebung L01](lab-room-l01.md) den angekündigten Grundriss mit Maßstab
oder mindestens einer bekannten Länge auswerten. Zunächst Raumkontur, Türen,
Fenster, Bänke und Stauraum in der gemeinsamen Quelle korrigieren und mit
`python scripts/build_lab_room.py` beide CADs erneut erzeugen. Erst danach L01
im Gebäude verorten und weitere Räume, Geräte sowie menschliche und maschinelle
Arbeits-/Verkehrsbereiche ergänzen. Das jetzige Modell ist eine abstrakte
Einzelraumskizze mit unbekannten Messwerten.

Für die [Zentrifuge CF01](centrifuge-cf01.md) zuerst die stationäre Entnahme mit
gemessenem Gefäß und echtem Greifer untersuchen. Parallel einen qualifizierten
Zentrifugenkern einschließlich Rotor, Verriegelung und Containment bestimmen.
Für die stärkere Stahlfassung Stahlgüte, Tragverbindungen, Deckelunterstützung
und Verriegelung gegen die erhebliche Deckelmasse auslegen. Netzmodul, Absicherung,
Schutzleiter einschließlich Deckel und Isolation prüfen; Spindelgeber und
Zählereingang anhand der abgeleiteten Bandbreite auswählen und unabhängig vom
Stillstandswächter prüfen. Die vorhandenen Bauräume sind keine Kaufteilfreigabe.
Den Konzeptrotor nicht als Hochgeschwindigkeitsbauteil fertigen oder einen
Kaufrotor mit Heberbohrungen verändern. Kameramarkierungen, Kalibrierung und
vollständige Übergabebahnen gesondert prüfen. Die lokale Mock-Schnittstelle
ist ausführbar; Hardwaretreiber, reale Rückmeldung und ROS/SiLA folgen später.
Die Station ist im bisherigen Armbudget nicht kalkuliert.

CF01s implementierte Motor-/Brems-/Deckelgeometrie als Nächstes mit echten
Kaufteildaten abgleichen. Rotierende Trägheit erfassen, Beschleunigung,
Bremsenergie und thermischen Tastgrad auslegen; die Parkbremse nicht als
Hochgeschwindigkeits-Betriebsbremse behandeln. Motorischen Deckel, Stifte,
Endlagensensoren, Obstruktion und Haltefunktion zunächst ohne drehenden Rotor
prüfen. Erst danach die bewertete Hardwarefolge anbinden und validieren.

Die Roboter-Entnahme ist inzwischen als gemeinsame kinematische Szene animiert
und an diskreten nativen Stellungen geprüft. Als Nächstes Greifwerkzeug und
Anbauhöhe mit echten Gefäßen bestimmen, Roboter-/Stationsrahmen kalibrieren,
Greif-/Abwesenheits-/Freiraumsensorik einbinden und die komplette Bahn mit
Traglast und kontinuierlicher Kollisionsprüfung qualifizieren.

Die lokale CF01-Szene verwendet inzwischen eine podestfreie 280/250-mm-Armvariante
und übergibt das Gefäß in ein geführtes 12-Platz-Rack. Nach den adaptiven
geometrischen Stichproben nun reale Bankbefestigung, längere Glieder, Nutzlast,
Antriebsmomente und Einschwingfehler gegen das ungefähr 1-mm-Transportziel
vermessen. Rack-Unterstützung und Freigabe sensorisch bestätigen. Alle
Beladungsreihenfolgen bei bereits belegten Nachbarplätzen separat prüfen;
die Slot-01-Vorführung ersetzt diese Pfade nicht.

Die CF01-Deckel-/Heberfolge ist jetzt animiert; ROS-Interfaces und SiLA-FDL
werden aus derselben Protokollquelle erzeugt. Als Nächstes in einer echten
ROS-2-Jazzy-Umgebung kompilieren und ROS-/SiLA-Server mit einem Client prüfen.
Der lokale Mock und die XSD-Prüfung ersetzen diese Interoperabilitätsprüfung
nicht. Siehe [CF01-Protokoll](centrifuge-cf01-protocol.md).

Für den ergänzten [Probentransport TR01](sample-transport-tr01.md) zunächst
Zentrifugenartikel und Chargengröße festlegen sowie ausschließlich Bodenrouten
aufnehmen. Tisch-/Spurwagen werden nicht weiterentwickelt. Die gemeinsame Quelle
mit `python scripts/build_sample_transport.py` in beiden CADs prüfen. Je Armstation
zunächst eine erreichbare Park-/Übergabepose für alle vorgesehenen Probenplätze
mit tatsächlichem Werkzeug bestimmen. Artikelpassung, Rückhaltung, lokale
Lageerfassung und Haltefunktion mit Mustern untersuchen; spurgenaue Fahrt ist
keine Anforderung. Am Bodenfahrzeug Übergabehöhen, Türen, Schwellen, Kurven,
Anhalten und Kippstabilität
mit gemessener Dummy-Nutzlast prüfen. Anschließend Antriebe, Energieversorgung,
Stationsverriegelung, Übergabegerät und Verkehrssteuerung auslegen. Kosten und
Betriebsanforderungen der Transporter gesondert kalkulieren.

Die bevorzugte Servoauswahl aktualisiert die frühere pauschale Aufteilung.
Die folgende Verteilung ist ein eigener Planungsansatz, keine Angebotskalkulation:

| Bereich | Ansatz innerhalb 5.000 EUR Gesamtbudget |
|---|---:|
| Sechs Servomodule | 2.500 EUR |
| Versorgung, Steuerungsanbindung, Verkabelung und Abschaltung | 700 EUR |
| Motorplatten, Struktur, Lagerung und Haltesicherung | 700 EUR |
| Optik und Beleuchtung | 400 EUR |
| Reserve und einfache Halter/Versuchsadapter | 500 EUR |
| **Summe** | **4.800 EUR** |

Vorhandene Pipetten, Messgeräte, Rechner und Fertigungsmöglichkeiten sind als
Infrastruktur angesetzt. Die Uni-Werkstattzeit ist mit dem Team separat einzuplanen.
Die untere Budgetgrenze setzt weitere geeignete vorhandene Komponenten voraus.
Auswahl, Preisgrenzen, Präzisionsrisiko und Beschaffungsbedingungen stehen in
[actuator-selection.md](actuator-selection.md). Diese Planung betrifft einen Arm;
weitere Arme sind gesonderte Ausbaustufen.

## Fachliche Referenzen

- [ISO 23783-2, Volumenleistung automatisierter Liquid-Handling-Systeme](https://www.iso.org/standard/76958.html)
- [ISO 8655-6, gravimetrisches Referenzverfahren](https://www.iso.org/standard/75211.html)
- [ANSI/SLAS-Mikroplattenstandards](https://www.slas.org/education/ansi-slas-microplate-standards/)
- [Eppendorf, Pipettieren kleiner Volumina](https://www.eppendorf.com/jp-ja/lab-academy/topics-methods-technology/pipetting-dispensing/how-to-pipette-small-volumes-with-handheld-manual-pipettes/)

Diese Referenzen ersetzen keine Auswahl- oder Leistungsprüfung des eigenen Aufbaus.
