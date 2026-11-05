# Bevorzugte Servoantriebe und Präzisionsnachweis

Stand: 28. Oktober 2026. Der Eigentümer unterstützt diese Auswahl als Grundlage
für den Prototyp. Sie ist noch keine Bestellung oder Freigabe für die geforderte
Positionierleistung. Sechs Drehachsen und das Gesamtbudget von 3.000–5.000 EUR
bleiben verbindlich.

Die [geometrische Integration](servo-integration.md) ist inzwischen umgesetzt:
sechs Module, getrennte Gehäuse/Ausgänge und zwölf Motorplatten in beiden CADs,
sechs einfache Gehäusequader für RViz. Die vermeintliche X6-Abweichung ist
[geklärt und korrigiert](x6-interface-resolution.md); Passungen sowie die hier
beschriebenen Last-/Präzisionsprüfungen bleiben offen.

## Bevorzugte Bestückung

| Gelenk | Modell, EtherCAT-Ausführung | Hersteller-Nennmoment am Ausgang | Masse je Modul | Planungsbetrag je Stück |
|---|---|---:|---:|---:|
| J1 Sockel, J3 Ellenbogen | RMD-X4-P36-36-E-L | 10,5 Nm | 0,36 kg | ca. 370 EUR |
| J2 Schulter | RMD-X6-P20-60-E | 20 Nm | 0,82 kg | ca. 450 EUR |
| J4 Unterarm, J5 Handgelenk, J6 Flansch | RMD-X2-P28-7-E | 2,5 Nm | 0,26 kg | ca. 300 EUR |

Damit ergeben sich rund **2.090 EUR für sechs Antriebsmodule** und 2,32 kg
Gesamtmasse der Module. Die bewegte Masse hängt von deren Montage ab. Die
ursprüngliche Preisrecherche lag bei 2.084,10 EUR; die Tabelle verwendet gerundete
Planungsbeträge. Aktuelle Händleranzeigen schwanken, zeigen teils widersprüchliche
MwSt.-Hinweise und belegen keine Lieferbarkeit eines kompletten Satzes.
Für die Budgetplanung bleiben **2.500 EUR für die Antriebe** reserviert, bis ein
verbindliches Bruttoangebot für die genauen Varianten vorliegt.

Die heruntergeladenen [Herstellerdateien](../cad/vendor/myactuator/README.md)
belegen die technischen Tabellenwerte. Die Zahl 7, 36 oder 60 im Modellnamen
ist kein zulässiges Dauermoment. Insbesondere Halten gegen die Schwerkraft und
wiederholtes Beschleunigen sind gesonderte thermische Lastfälle.
Beim X4 gilt ausdrücklich die neue **-E-L**-Ausführung; die ältere X4-36 ohne
L wird nicht als austauschbares Kaufteil behandelt.

## Rückmeldung und Steuerung

Alle drei Kandidaten sind integrierte Servomodule mit Getriebe und zwei
Absolutgebern. Die Datenblätter nennen 17 Bit am Eingang und 18 Bit am Ausgang
für X2/X4 sowie 17/17 Bit für X6. Geberauflösung ist keine Aussage über die
erreichbare Positioniergenauigkeit. Vor dem Hardwareadapter müssen wir prüfen,
welcher Messwert tatsächlich als Istposition übertragen wird, seine Skalierung,
Nullreferenz, Mehrumdrehungsverhalten, Datenalter und Verhalten beim Neustart.

EtherCAT ist die bevorzugte gemeinsame Schnittstelle. Der Hersteller bietet
[ESI-Dateien mit Firmwarezuordnung](https://www.myactuator.com/downloads-ethercatesi)
an. Für LinuxCNC sind der
[EtherCAT-HAL-Treiber](https://github.com/linuxcnc-ethercat/linuxcnc-ethercat)
und die [CiA402-Anbindung](https://github.com/dbraun1981/hal-cia402) ein plausibler
Weg. Die genaue Kombination aus diesen Modellen, Firmware, PDO-Belegung,
CSP-Betrieb und Echtzeitrechner ist **noch nicht erprobt**.
Eine vorbereitete ROS-2-Schnittstelle mit Mock-Hardware ist kein solcher Nachweis.

Nur eine Instanz erhält die Hoheit über die Antriebe: entweder ein ROS-2-
Hardwareadapter oder LinuxCNC mit einer klaren darüberliegenden ROS-Schnittstelle.
Beide dürfen nicht gleichzeitig Sollwerte auf denselben Bus schreiben.
Zeitgestempelte Istposition, Status, Fehler und Referenzzustand müssen bis zur
Ablaufsteuerung gelangen. Ein Kommunikationsausfall braucht einen definierten,
am Prüfstand erprobten Übergang.

X2 und X4 sind für 24 V, X6 für 48 V nominal angegeben. Der veröffentlichte
Betriebsbereich 20–55 V ersetzt keine Auslegung für einen anderen Nennpunkt.
Zunächst zwei Versorgungszweige vorsehen; Strom, Absicherung, Rückspeisung,
Stecker und Leitungsquerschnitte nach dem tatsächlichen Lastprofil bestimmen.
Die drei ausgewählten Ausführungen haben **keine Bremse**. Eine Haltesicherung
oder ein Gegengewicht ist besonders für J2/J3 konstruktiv zu lösen.

## Hohe Genauigkeit und kurze Zykluszeit

Hohe Genauigkeit und schnelle Abläufe sind bestätigte Ziele. Zahlenwerte für
TCP-Fehler, Wiederholbarkeit, Nutzlast, Einschwingzeit und Zykluszeit fehlen noch;
sie werden vor einem Serienkauf als Abnahmekriterien festgelegt.

Das modellbezogene X4-L-Datenblatt nennt **0,4° absolute und 0,3° wiederholte
Positioniergenauigkeit**, außerdem 15 Winkelminuten Getriebespiel. Ein einzelner
Winkelfehler von 0,3° entspricht bei 400 mm Hebelarm ungefähr 2,1 mm
Querabweichung (`400 mm × sin(0,3°)`). Das ist ein Rechenbeispiel, keine
Fehlerprognose für die gesamte Kette. Es zeigt jedoch, warum allgemeine Angaben
wie „control accuracy <0,01°“ und hohe Geberauflösung keinen Präzisionsnachweis
an der Pipettenspitze ersetzen. Die widersprüchlichen Genauigkeitsbegriffe sind
vor der Beschaffung schriftlich mit dem Lieferanten zu klären.

Der erste Prüfstand verwendet eine repräsentative Schulter-/Ellenbogenaufnahme,
einen bekannten Hebel und definierte Lasten. Gemessen werden:

- Ausgangswinkel und Spitzenposition bei Anfahrt aus beiden Richtungen;
  Umkehrspiel, absolute Abweichung und Streuung getrennt auswerten.
- Nachgiebigkeit von Getriebe, Lagerung, Motorplatten und Arm unter Last;
  Verformung hinter dem Ausgangsgeber bleibt für diesen unsichtbar.
- Bahnfehler, Überschwingen und Zeit bis zum Erreichen des Positionierfensters
  bei verschiedenen Geschwindigkeiten, Beschleunigungen und Ruckgrenzen.
- Erwärmung und Drift über repräsentative Bewegungs-/Haltezyklen sowie Verhalten
  bei abgeschalteter Versorgung und nach erneutem Referenzieren.
- Verfügbare Rückmelderate, Zeitstempel, Verzögerung und Fehlerzustände an der
  tatsächlichen LinuxCNC- oder ROS-2-Anbindung.

Schnelle Transfers außerhalb des Gefäßes und eine kurze, optisch korrigierte
Feinanfahrt sind die bevorzugte Prozessstrategie. Das Ende einer Bewegung wird
aus gemessener Lage und Einschwingkriterium bestätigt; eine pauschale lange
Wartezeit ist kein Ersatz für diese Messung. Kamerafeedback kann langsame,
beobachtbare Lagefehler korrigieren, aber weder beliebige Elastizität noch
schnelle Schwingungen automatisch beseitigen.

Falls der Prüfstand die Ziele verfehlt, werden gezielt die betroffenen Gelenke,
Lagerung, Übersetzung oder Messung geändert. Eine höherwertige Harmonic-Variante
mit Ausgangsgeber und gegebenenfalls Bremse bleibt die Angebotsalternative;
ihre Mehrkosten und Steifigkeit müssen gegen den gemessenen Bedarf geprüft
werden. Die sechsachsige Kinematik bleibt bestehen.

## Mehrere Arme

Bis zu drei Arme sollen Vorbereitung, Halten, Transport und Prozessschritte
parallelisieren. Ein Arm kann beispielsweise ein Gefäß vorbereiten, während
ein anderer pipettiert. Das erhöht den Durchsatz, senkt jedoch nicht von selbst
den Positionierfehler eines Arms. Übergaben zunächst über feste, registrierte
Aufnahmen mit definiertem Zustand planen.

Ein Stationskoordinator reserviert gemeinsame Arbeitsräume, Gefäße und Werkzeuge.
Jeder Arm braucht eigene Namensräume, TF-Präfixe, Bus-/Gerätekennungen und eine
zum Stationsrahmen vermessene Basis. Gemeinsame Bewegungen erfordern konsistente
Zeitstempel und eine Prüfung der Kollisionen zwischen Armen. Zwei oder drei Arme
sind eine spätere Budgetstufe; der Betrag von 3.000–5.000 EUR gilt für den ersten
begrenzten Prototyp.

## Beschaffung und Budget

OpenELAB in Garching ist eine deutsche Bezugsquelle für
[X2](https://openelab.de/products/myactuator-rmd-x2-p28),
[X4-L](https://openelab.de/products/myactuator-rmd-x4-p36-36-e-l) und
[X6](https://openelab.de/products/myactuator-x6-p20).
Der Hersteller sitzt in China; ein deutscher Shop garantiert weder europäischen
Ursprung noch lokalen Lagerbestand. MYBOTSHOP ist eine weitere deutsche
[Bezugs-/Anfrageoption für RH-Harmonic-Module](https://www.mybotshop.de/MYACTUATOR-RH-Serie-Harmonic-Module-dual-encoder).
Es wurde keine Anfrage verschickt oder Bestellung ausgelöst.

| Bereich | Vorläufige Reserve |
|---|---:|
| Sechs Servomodule | 2.500 EUR |
| Versorgung, Steuerungsanbindung, Verkabelung und Abschaltung | 700 EUR |
| Motorplatten, Struktur, Lagerung und Haltesicherung | 700 EUR |
| Optik und Beleuchtung | 400 EUR |
| Reserve und einfache Halter/Versuchsadapter | 500 EUR |
| **Summe** | **4.800 EUR** |

Dies ist eine knappe Planungsaufteilung mit vorhandenen geeigneten Rechnern,
Pipetten, Messmitteln und Werkstatt. Sie ersetzt keine Stückliste oder Angebote.
Eine zusätzliche Bremse, teurere Präzisionsgelenke oder eine aufwendige
Pipettenanbindung können die Reserve aufbrauchen. Die untere Grenze von
3.000 EUR ist mit sechs neu gekauften Modulen nur bei erheblichem Bestandseinsatz
realistisch. Beschaffung erst nach Last-/Präzisionsprüfung und bestätigten
Bruttopreisen einschließlich der notwendigen Anschlussadapter und Lieferzeiten.

Die [CAD-Integration](vendor-cad-plan.md) und die maschinenlesbare
[Auswahl](../model/actuator-selection.json) halten diese Entscheidung mit der
gemeinsamen Modellquelle verbunden.
