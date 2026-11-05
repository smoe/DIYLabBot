# Anforderungen und Entscheidungen

## Bestätigte Anforderungen

| Thema | Festlegung |
|---|---|
| Projekt | SolidCraftBot, eigenständig unter ../SolidCraftBot |
| Einsatz | Molekulares Labor einer Universität |
| Fertigung | Mehrere 3D-Drucker und CNC-Möglichkeiten der Universitätswerkstatt |
| Kinematik | Sechs Drehachsen; durch Eigentümer ausdrücklich bestätigt |
| Mobile Armbasis MB01 | Manuell auf der Laborbank verschiebbar; eigener Griff, kompakte Parkpose, einziehbare Arbeitsstützen; autonome Fahrt zunächst nicht gefordert |
| Lokale Präzision | Tatsächliche Spitze relativ zum Gefäß in Lage, Tiefe und Orientierung kamerageregelt; keine präzise Rückkehr der Basis oder Pflicht zum Präzisionsdock |
| Gemeinsame Banknutzung | Mitarbeitende sollen den angehaltenen, gefalteten Arm leicht zur Seite stellen können; Bedienkraft, Parkzeit und Platzgewinn noch messen |
| Ausbau | Ein Arm zu Beginn, später möglicherweise drei Arme an einer Station |
| Langfristiger Volumenbereich | 1–1000 µl mit verschiedenen Werkzeugen |
| Gefäße | Eppendorf-Gefäße, 96-Well- und 384-Well-Platten |
| Erster begrenzter Prototyp | Budgetziel 3.000–5.000 EUR |
| Infrastruktur | Pipetten und geeignete Labor-Messmöglichkeiten sind vorhanden |
| Erster Präzisionsversuch | 1 µl Wasser am Gefäßrand ablegen und wieder aufnehmen |
| Überwachung | Mehrere stationäre Laborkameras sowie zwei Kameras am Arm vorgesehen; Lageerkennung soll die Feinanfahrt unterstützen |
| Kameras am Arm | Untere Nahkamera und obere Übersichtskamera; seit V02 als provisorische Bauräume auf L6 beziehungsweise L1 in allen drei Ableitungen, endgültige Montageorte noch offen |
| Werkzeugaufnahme | Austauschbar; Pipettenaufnahme zunächst aus dem Entwurf herauslassen |
| Visualisierung | CAD-Modellansichten und Speicherung am 28.10.2026 ausdrücklich erlaubt |
| FreeCAD-Fassung | Parallel zum SolidCraft-Stand; sechs Achsen über Python und interaktive Bewegungsdarstellung, am 28.10.2026 gewünscht |
| Gemeinsame Quelle | CAD-unabhängige Beschreibung als führender Stand; beide CAD-Fassungen daraus ableiten |
| Entwicklungsschleife | Modellüberlegung, programmierte Protokolle und 3D-Prüfung mit möglichst wenig manuellen Zwischenschritten verbinden |
| ROS 2 | Beschreibung und sechsachsige Trajektorienschnittstelle vorbereiten; zunächst Mock-Hardware |
| Kennzeichnung | UMR in kräftigen Buchstaben auf dem Oberarm; vom Eigentümer am 28.10.2026 gewünscht |
| Antriebe | Sechs Servoantriebe mit für die Steuerung auslesbarer gemessener Position; Messort, Referenz und Rückmeldezeit festlegen |
| Flexible Leitungen | Versorgung und Rückmeldung aller Motoren in der gemeinsamen Quelle modellieren, auch bei ausgeblendeter Darstellung; Führung, Reserve, Biegung, Torsion und Zugentlastung auslegen |
| Genauigkeit und Geschwindigkeit | Hohe Positioniergenauigkeit bei kurzen Prozesszeiten; messbare TCP-, Last-, Einschwing- und Zykluszeitziele noch festzulegen |
| Zusammenarbeit mehrerer Arme | Bis zu drei Arme sollen Aufgaben parallelisieren und Übergaben unterstützen; gemeinsame Arbeitsbereiche und Referenzen koordinieren |
| Kaufteilgeometrie | Hersteller-Servomodelle wiederverwenden; eigene Motorplatten als parametrische Schnittstellen entwickeln |
| ROS-Darstellung der Servos | Einfache Quader für die optische Darstellung in RViz; mechanische Detailgeometrie getrennt halten |
| Bezugsquelle und Steuerung | Europäische Nähe und LinuxCNC-Kompatibilität sind Auswahlvorteile; genaue Hardwarekombination prüfen |

Die [bevorzugte Antriebsauswahl](actuator-selection.md) ist als Prototypbasis
bestätigt. Sie ersetzt keine Prüfung der geforderten Präzision, Last oder
Geschwindigkeit. Insbesondere die X4-L-Angabe von 0,3° Wiederholgenauigkeit
muss gegen die noch festzulegenden TCP-Ziele bewertet werden.

## Zielversuch

Die mobile [Basis MB01](mobile-base-mb01.md) ist als eigener gemeinsamer Aufbau
mit demselben Sechsachsenarm integriert. Rollen dienen der manuellen Verlagerung;
drei verstellbare Füße sollen beim Arbeiten die Rollen entlasten. Nach jeder
manuellen Bewegung ist die bisherige Aufgabenlokalisierung ungültig. Frische
Spitzen-/Gefäßbeobachtung und bewusste Wiederfreigabe sind Anforderungen, noch
keine implementierte Kameraregelung oder Hardwareverriegelung. Positioniertoleranz,
Bildalter, Last, Steifigkeit, Kippsicherheit und tatsächlicher Parkaufwand bleiben
offen. Der allgemeine Flansch bleibt die Werkzeuggrenze.

Ein einzelner Wassertropfen wird an der Gefäßwand abgelegt. Nach Rückzug der
Pipette wird er erneut optisch lokalisiert. Der Arm nähert die Spitze an, nimmt
das Wasser auf und zieht zurück. Anschließend werden sichtbare Restflüssigkeit
und tatsächlich zurückgewonnene Wassermenge getrennt bewertet.

Die obere Innenwand knapp unterhalb der Öffnung ist eine vorläufige Interpretation
von „am Rand“, keine bereits bestätigte exakte Testposition. Zunächst ist ein
konkreter Gefäßartikel mit reproduzierbarer Halterung festzulegen.

Optisches Verschwinden allein gilt nicht als Volumennachweis. Verdunstung,
Wandbenetzung, Wasser an der Spitzenaußenseite und Messunsicherheit müssen bei
der Wiederfindungsrate berücksichtigt werden.

## Gewünschte Erweiterung: Pipettieren auf Eis

Für die Gefäßstation wurde am 28. Oktober 2026 ein erster Maschinenentwurf mit
einem nachvollziehbaren Interaktionsprotokoll und grundlegender Ausrichtung auf
SiLA 2 gewünscht. Der [Entwurf C01](tube-station-c01.md) enthält dafür eine
separate CAD-Station und eine Feature-Definition im Status Draft. Ein laufender
Server oder nachgewiesene SiLA-Konformität sind damit nicht zugesagt.

Der Eigentümer hat die parallele FreeCAD-Ausführung auch für die Station
bestätigt, um die Abstraktion durch einen zweiten CAD-Kern zu verbessern.
Die [gemeinsame Stationsquelle](../model/tube-station-c01.shared.json) beschreibt
nun Geometrie und Gelenkrahmen für beide nativen Fassungen. Die Ausgabe in zwei
Programmen ersetzt keinen Nachweis der Beladung oder der Deckelbetätigung.

Die Deckelstation trägt auf Eigentümerwunsch ebenfalls die UMR-Kennzeichnung.
Die erhabenen Buchstaben sitzen sichtbar auf der vorderen Außenwand des
Eisbehälters: dieselben Konturen, 24 mm Höhe, 0,8 mm Relief und dunkles Blau wie
am Arm. Die gemeinsame Quelle erzeugt sie in beiden CAD-Fassungen.

Am 28. Oktober 2026 wurde das Pipettieren bei gleichzeitiger Eiskühlung als
zusätzlicher Wunsch genannt. Der Gefäßplatz soll dafür konzeptionell vorbereitet
werden; eine gekühlte Ausführung ist noch keine Pflicht für den ersten
Präzisionsversuch. Öffnen, Pipettieren und Schließen sollen bei dieser Option
am selben gekühlten Platz möglich sein.

Als erste Interpretation dient gewöhnliches Wassereis als Kältequelle für einen
wärmeleitenden Gefäßeinsatz. Zulässige Probentemperatur, Abkühlzeit, Betriebsdauer
und Temperaturabweichung sind noch festzulegen. Die Temperatur des Kühlblocks
belegt nicht die Temperatur der Probe, insbesondere eines 1-µl-Tropfens an der
oberen Innenwand. Eine Kühl- oder Dosierleistung ist noch nicht nachgewiesen.

## Noch zu bestimmen

Für die gemeinsame Umgebung von Menschen und Maschinen wurde ein erster
[abstrakter Raum L01](lab-room-l01.md) in beiden CADs gewünscht. Bestätigt sind
zwei Türen ohne Bank an der Eingangswand, rechtwinklige Seitenwände, die kürzere
rechte Wand und die vom ovalen Gebäude beeinflusste Fensterseite. Links,
fensterseitig und rechts stehen Randbänke; zwei lange Bänke stehen mittig
Rücken an Rücken. Seitliche Gänge und beide Enddurchgänge bleiben frei.
Geschlossener Stauraum liegt darunter, flacherer Stauraum darüber. Sämtliche
Abmessungen, Türpositionen, genaue Fensteraufteilung und Oberschrankorte bleiben
bis zur Grundrissaufnahme Annahmen. Das Modell erzeugt noch kein Gesamtgebäude.

Präzisierung vom 29. Oktober 2026: Eine vertikale Betonstütze sehr nahe an den
Fenstern teilt die fensterseitige Bank. Gemeldet sind ungefähr 300 mm Breite und
500 mm Tiefe. Ihre Front fluchtet ungefähr mit den Fronten der beiden geraden
Bankabschnitte zu den Raumecken. Die Fensterkrümmung bleibt davon unbeeinflusst.
Heizungsauslässe/-abdeckungen schließen Zwischenräume, damit nichts hinunterfällt.
Genaue Lage, Abstände und Abdeckungsgeometrie bleiben offen; die Modellfarben
wurden für die Darstellung gewählt und sind keine gemessenen Oberflächen.

Zusätzlich ist ein Regal zwischen den beiden mittleren Bänken gewünscht. L01
setzt zunächst ein gemeinsames erhöhtes Regalbrett an deren Rückenlinie um.
Höhe, Tiefe, Länge, Stützen und Befestigung sind noch nicht gemessen; eine
Tragfähigkeit ist nicht festgelegt. Anschließende Präzisierung: Das Regalbrett
liegt auf 1,50 m, die oberen Mittelschränke beginnen bei ungefähr 1,75 m. Dazwischen
soll man zur anderen Bankseite durchgreifen können. Fensterseitige Unterschränke
werden entfernt; Unterstauraum bleibt nur unter den Seiten- und Mittelbänken.

Bestätigte Antriebsentscheidung vom 28. Oktober 2026: Gefäßübergabe durch eine
vom Roboter betätigte Drehmechanik ohne zusätzliche Stationsmotoren.
[H03](tube-cam-h03.md) beschreibt Kurven, Rollenfolger, Schließkeil und
federbelasteten Riegel in der gemeinsamen Quelle und beiden nativen CADs.
Der Roboter führt auch Empfängertransport und Zug-/Vierteldreh-Entriegelung aus.
Federn, Drehmoment, Geschwindigkeit, reale Übernahmebestätigung und Lastnachweis
sind weiterhin offen.

Am 29. Oktober 2026 wurde die Animation des vollständigen H03-Übergabe- und
Rücksetzzyklus gewünscht: Gefäßauswurf, Empfängerübernahme sowie Zug- und
Vierteldreh-Entriegelung einschließlich anschließendem Absenken und Wiederaufrüsten.
Die gemeinsame Ablaufquelle verwendet dieselben Kurvengesetze wie die CADs;
Abspielzeiten sind Anschauungswerte und keine qualifizierten Betriebszeiten.

Zusätzlicher Eigentümerwunsch vom 28. Oktober 2026: Flüssigkeit beim Pipettieren
optisch zugänglich halten, daher einen offenen Rahmen untersuchen. Ein
Bodendurchbruch soll ein Anheben am äußeren Gefäßboden erlauben, ohne
Gefäßöffnung oder Dichtlippe zu greifen. Ein Empfänger muss das angehobene Gefäß
vor Heberrückzug halten. [H02](tube-frame-h02.md) bildet offene Rahmen, getrennte
Unterstützung für 1,5/2,0 ml, Bodenheber und geteilte Empfangssitze in beiden
nativen CADs ab. Sichtbarkeit, Kontaktkräfte und Rückhaltung sind nicht bewiesen.

Am 28. Oktober 2026 wurde zusätzlich ein Probentransport über längere Strecken
gewünscht. Die anschließende Eigentümerentscheidung legt ausschließlich ein
Bodenfahrzeug für Armstationen und Laborwechsel derselben Etage fest, zunächst
auch mehrere unterschiedlich konfigurierte Fahrzeuge. Tisch-/Spurwagen werden
nicht weiterentwickelt; deren Fahrtgenauigkeit wird nicht benötigt. Die Proben
sollen auf dem geparkten Fahrzeug von jedem beteiligten stationären Arm erreichbar
sein. Das ist je Station mit realen Höhen, Werkzeugen, lokaler Lageerfassung,
Haltefunktion und freien Anfahrwegen zu prüfen, keine bestätigte Reichweite.
Die kleine Gefäßklasse wurde ausdrücklich als **2 ml, nicht 2 µl** präzisiert.
Mikrowellplatten und weitere Gefäße sollen durch wechselbare Einsätze abgedeckt
werden. Eine vollständige Zentrifugencharge ist das bevorzugte Kapazitätsziel;
Zentrifuge, Rotor und reale Chargengröße sind noch nicht festgelegt.
[TR01](sample-transport-tr01.md) zeigt Bodenfahrzeuge für zwei Platten, 48 Gefäße
beziehungsweise eine gemischte Last als Konzeptkapazitäten. Routenlänge,
Nutzlast, Fahrtzeit, Beschleunigung, Andockgenauigkeit, Türzugang, Übergabehöhen,
Reinigungs- und Temperaturanforderungen bleiben offen. Das Transportbudget ist
nicht Bestandteil der bisherigen Armkalkulation.

Am 28. Oktober 2026 wurde ein abstrakter Gefäßhalter mit Übergabemöglichkeit und
Generatoren für FreeCAD und SolidCraft gewünscht. Der Eigentümer beobachtet
unterschiedliche Stabilität der konischen 1,5-ml- und runderen 2,0-ml-Gefäße in
einfachen Bohrungen. [H01](tube-carrier-h01.md) verwendet deshalb artikelabhängige
Einsätze bei gemeinsamen äußeren Träger-/Greifschnittstellen. Maße und Passungen
sind Konzeptannahmen; der konkrete Gefäßartikel und Messwerte bleiben offen.

- Für den gewünschten Spitzenabwurf: konkrete 10-, 200- und 1000-µl-Pipetten und
  Spitzenartikel, Kragen-/Schaftmaße, Freiraum zur Abwurfhülse, Abziehkraft und
  zulässige Füllhöhe der Sammelbox; die Nuten im T01-Entwurf sind Platzhalter.
- Pipettenmodelle, Spitzen und Gewicht der vollständigen Werkzeuge.
- Gefäßartikel und genaue Zielposition, Ablage- und Aufnahmeorientierung.
- Beladung und Entnahme der Deckelstation einschließlich echter Greifergeometrie,
  Greifflächen, Rückhaltung und freiem Übergabeweg; C01 weist diese noch nicht nach.
- Erwartete Prozesskräfte, insbesondere bei später automatisierter Spitzenaufnahme.
- Messbare Grenzwerte für Positionierung, Wiederfindung und Wiederholbarkeit.
- Kameraartikel, Objektive, Beleuchtung, stationäre Standorte und genaue Montageglieder der beiden Armkameras; Sichtlinien und Kalibrierung am echten Gefäß.
- Anforderungen an Reinigung und Kontaminationstrennung sowie Temperaturbereich,
  Betriebsdauer und Messverfahren für den gewünschten Betrieb auf Eis.
- Tischabmessungen, Armpositionen und gemeinsame Arbeitsbereiche.
- Verfügbare Werkstattzeiten und tatsächliche Angebote für Kaufteile.

## Kameraüberwachung: Eigentümerwunsch vom 28. Oktober 2026

Die Überwachung soll mehrere stationäre Kameras an verschiedenen Laborplätzen
und zusätzlich zwei mit dem Arm bewegte Kameras umfassen. Die untere Armkamera
soll auf die Pipettenspitze blicken; die obere dient der räumlichen Orientierung.
Die Anzahl zwei bezieht sich auf die Armkameras, nicht auf alle Laborkameras.
Die genaue Bedeutung von oben/unten in der bewegten Kette und die endgültigen
Befestigungsorte sind noch offen. Als Konzept wird unten zunächst als Unterseite
nahe Handgelenk/Werkzeug verstanden, nicht als fester Sockelstandort.

Die unterschiedlichen Bildaufgaben sind getrennt auszulegen: Spitze, Gefäßöffnung
und sichtbare Tropfen für die Feinanfahrt; Racks, Gefäße und Arbeitsbereiche für
die Übersicht. Die zwei Armkameras sind damit nicht als Stereopaar festgelegt.
Stationäre Kameras sollen die Sicht ergänzen; ein gemeinsamer Stationsbezug ist
für spätere Zusammenarbeit mehrerer Arme vorzubereiten.

Kamerablick, erkennbare Merkmale, Beleuchtung, zulässiges Bildalter und Messfehler
sind experimentell zu bestimmen. Ein sichtbarer oder verschwundener Tropfen ist
weiterhin kein unabhängiger Volumennachweis. Es wurden noch keine Kameras,
Objektive oder fertigungstauglichen Montagegeometrien ausgewählt. Seit V02 sind
zwei Kamerabauräume, provisorische Halter und visuelle Sichtkegel in der
gemeinsamen Quelle sowie FreeCAD, SolidCraft und RViz enthalten. Die Kamera-
und Halterbauräume sind geometrisch mitgeprüft; Sichtkegel sind ausdrücklich
keine physischen Kollisionskörper. Optische Sichtbarkeit und reale Eignung
der Halter sind damit nicht nachgewiesen.

## Spitzenabwurf: Eigentümerwunsch vom 28. Oktober 2026

Eine Sammelbox mit unterschiedlichen Abstreifnuten soll gebrauchte Spitzen von
10-, 200- und 1000-µl-Pipetten aufnehmen. Der eigenständige [Entwurf T01](tip-collector-t01.md)
enthält drei austauschbare Gabeleinsätze an einem festen Rahmen und einen nach
vorne entnehmbaren Behälter. Der Roboter soll den freiliegenden Schaft seitlich
in die Nut führen und die Pipette senkrecht abziehen; die Spitze wird unterhalb
der Gabel am oberen Rand zurückgehalten und fällt in den Behälter.

Die vorläufigen Nutbreiten 4/6/9 mm sind keinem gemessenen Artikel zugeordnet.
Volumenklassen bestimmen keine Passung. Spitzenablösung, Füllstand und eingesetzter
Behälter müssen vor automatischem Betrieb zuverlässig erfasst werden. Kraft,
Verschleiß, Kontaminationsanforderungen und vollständige Roboterbahnen sind offen.
Die Pipettenaufnahme bleibt weiterhin außerhalb des Arm-CAD-Umfangs.

Auch für den Spitzenabwurf wünscht der Eigentümer die gemeinsame Entwicklung in
SolidCraft und FreeCAD analog zum Arm sowie dieselbe UMR-Schrift. Die gemeinsame
Quelle `model/tip-collector-t01.shared.json` erzeugt beide nativen Fassungen.
Die UMR-Konturen werden aus demselben projektinternen Zeichensatz wie beim Arm
abgeleitet; eine geometrische Übereinstimmung ersetzt keine Funktionsprüfung.

## Zentrifuge CF01

Präzisierung vom 5. November 2026: Der Arm soll ohne Kasten/Podest direkt auf
der Bank stehen; nötige Reichweite über längere Armglieder herstellen.
Für Gefäßtransporte genügt als Entwurfsziel ungefähr 1 mm Genauigkeit.
Kollisionen mit der Zentrifuge berücksichtigen und ein Ablagerack ergänzen.
Die lokale CF01-Szene setzt dafür 280/250 mm Gliedlängen, ein 12-Platz-Rack
und eine geordnete Übergabe nach Deckelschluss um. Statische Befestigung,
Steifigkeit und reale Genauigkeit sind weiterhin zu qualifizieren. Das
Transportziel ersetzt keine späteren Pipettier- oder lokalen Aufnahmeziele.

Die Animation soll zusätzlich zeigen, wie der sechsachsige Roboter das angehobene
Gefäß greift und aus der Zentrifuge zurückzieht, bevor der Deckel schließt.
Die neue gemeinsame Entnahmeszene ergänzt dafür einen ausdrücklich provisorischen
Flanschgreifer und eine lokale, noch unkalibrierte Armaufstellung.

Am 29. Oktober 2026 wurden eine Animation von Deckelöffnung/-schluss und
Einzelgefäß-Anhebung sowie, soweit machbar, vorbereitete ROS-/SiLA-Protokolle
gewünscht. Die gemeinsame Ablaufquelle führt die reversible Vorführung und
den getrennten Roboter-Entnahmeablauf; Schnittstellendefinitionen und lokale
Mock-Prüfungen sind implementiert, Netzwerkserver und reale Roboterbahn offen.

Am 29. Oktober 2026 wurde eine montierte, halbtransparente Ansicht zum Einblick
in die Mechanik gewünscht. Die Darstellung gilt für die Stahlhülle einschließlich
Kammerboden und Deckel; die Materialfestlegung bleibt Stahl.

Am 28. Oktober 2026 wurde eine mit dem Roboter zusammenarbeitende Zentrifuge
gewünscht: befohlenes Öffnen/Schließen des Gerätedeckels, bis 16.000 × g,
sichtbare Rotorreferenzen mit üblicher Nummerierung und gezielte Anhebung
einzelner Eppendorf-Gefäße. Der [Entwurf CF01](centrifuge-cf01.md) interpretiert
dies als 12-Platz-Festwinkelrotor mit langsamem Indexieren bei geschlossenem
Deckel und axialem Anheben nach bestätigtem Stillstand. Die Rampe ist eine
Anregung, keine festgelegte Bauform. Kapazität, Artikelpassung, Kaufteile,
Qualifikation, Kosten und Roboterübergabe bleiben offen; 16.000 × g ist nicht
mechanisch nachgewiesen.

Für CF01 wurden anschließend stärkere Wände, Stromkabel und ein Drehsensor
verlangt. Stahl gilt nach ausdrücklicher Klärung für Gehäuse, Kammer und Deckel;
der Rotorwerkstoff bleibt offen. Der aktuelle Entwurf enthält eine massive
Stahlkammer mit Boden und Stützen, Netzanschluss-/Kabelbauräume und einen
A/B/Z-Spindelgeber. Güte, elektrische Bemessung, reale Geberdaten und
Containment-Nachweis sind weiterhin offen.

Zusätzlich wurden Bremse, Motor, Drehzahlmessung und vollständig motorisches
Öffnen/Schließen ohne manuelles Anheben oder Zudrücken gefordert. CF01 enthält
jetzt eine eigene Spindelbaugruppe, elektrische Betriebsbremsung, eine nur im
Stillstand anzulegende Parkbremse sowie Deckelgetriebe, Haltebremse und zwei
elektrisch betätigte Stifte. Beide CADs und der Mock bilden die Bewegungsfolge
ab; reale Kaufteile, Leistungs-/Energiebemessung und Hardwaretreiber sind offen.

## Geänderte Konzeptentscheidung

Für die erste bestückte L01-Raumstudie stehen zwei Arme gemeinsam auf einer
Bank; auf neueren Eigentümerwunsch ist dies die rechte der beiden Mittelbänke.
CF01 und ein dritter Arm stehen am Fensterende der linken Wandbank.
TR01 fährt auf dem Boden; drei Racks und der vorhandene Spitzenabwurf T01
ergänzen die Aufstellung. Durchgänge und Bankzugang werden zunächst geometrisch
geprüft. Die Raummaße sind weiter vorläufig. Koordinierte Armbewegungen und
Mensch-Maschine-Betrieb sind damit nicht freigegeben. Details und Prüfgrenzen:
[L01-Aufstellung](lab-layout-l01.md).

Der frühere SCARA-Vorschlag wurde durch die feste Anforderung eines
sechsachsigen Arms abgelöst. Die Zahl der Drehachsen beschreibt die Beweglichkeit;
die erreichbare Werkzeugpräzision wird am realen System gesondert nachgewiesen.
