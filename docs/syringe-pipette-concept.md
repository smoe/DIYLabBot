# SP01 · Spritzenpipette als parametrierbares Konzept

SP01 beschreibt einen eigenständigen Dosierbaustein für das **Ziel 1–1000 µl**.
Zwei motorisch betätigte Glasspritzen der Nennklassen **1 ml und 10 ml** führen
über getrennte Absperrventile in einen kurzen gemeinsamen Luftverteiler mit
Drucksensor-Bauraum. Ein abnehmbarer Spitzenkopf trägt eine austauschbare Spitze.
Die Spritzen bewegen im vorgesehenen Prinzip Luft; die Probe soll in der Spitze
bleiben. Das Modell simuliert weder Luftströmung noch Flüssigkeitstransfer.

Die führende Quelle ist
[`model/syringe-pipette.shared.json`](../model/syringe-pipette.shared.json), ihr
Vertrag [`model/syringe-pipette.schema.json`](../model/syringe-pipette.schema.json).
Die Auswertung leitet Geometrie, Komponenten, Gelenkbezüge und Prüfstellungen
einmal ab. FreeCAD und SolidCraft erzeugen daraus unabhängig ihre Fassungen.

## Aufbau und Parameter

- Jede Spritze besitzt eine eigene Motor-/Spindelhülle und einen verschiebbaren
  Kolben. Ein stillstehender Kolben trennt sein verbleibendes Luftvolumen nicht
  pneumatisch ab; dafür ist das jeweilige Absperrventil vorgesehen.
- Die beiden Ventile sind getrennt betätigbare, illustrative Drehventile.
  Ihre dargestellte offene beziehungsweise geschlossene Lage ist kein Nachweis
  einer bidirektional dichten Absperrung.
- Der gemeinsame Verteiler, die Luftanschlüsse und der Sensor sind räumliche
  Konzeptkörper. Sensorbereich, Auflösung, Schlauchmaterial, Anschlussartikel
  und tatsächlich eingeschlossenes Luftvolumen bleiben auszulegen.
- Der Spitzenkopf hat einen eigenen Wechselbezug. Die Varianten `micro` und
  `macro` sind geometrische Beispiele; sie behaupten keine Passung zu konkreten
  Pipettenspitzen oder eine qualifizierte Zuordnung zu Dosierbereichen.

Alle Abmessungen sind **unvermessene Entwurfsannahmen**. Die mathematische
Zylinderverdrängung ist `V_Hub = π × Innenradius² × Hub`; dabei entspricht
`1 mm³` einem `1 µl`. Die angenommenen Innenradien von ungefähr 2,3033 mm und
7,2837 mm ergeben bei rund 60 mm Hub rechnerisch 1 ml beziehungsweise 10 ml.
Diese Werte sind keine Maße ausgewählter Kaufteile. Abhängige Maße und Bezüge
werden aus den freigegebenen Parametern erneut ausgewertet; geometrische
Varianten sind keine unterschiedlichen Herstellerartikel.

**Nennvolumen, rechnerischer Kolbenhub und abgegebene Probenmenge sind drei
verschiedene Angaben.** Besonders bei 1–2 µl beeinflussen Luftpolster, Dichtheit,
Reibung, Umkehrspiel, Temperatur und Spitzengeometrie das Ergebnis. Eppendorf
empfiehlt für kleine Volumina eine passende kleine Pipetten-/Spitzenkombination
mit kleinem Luftpolster; daraus folgt noch keine Leistung des SP01-Konzepts.
[Eppendorf: Kleine Volumina pipettieren](https://www.eppendorf.com/gb-en/lab-academy/topics-methods-technology/pipetting-dispensing/how-to-pipette-small-volumes-with-handheld-manual-pipettes/)

## Stellungen und Erzeugen

Die Prüffassungen zeigen den feinen beziehungsweise groben Luftzweig, beide
Ventile geschlossen und den abgenommenen Spitzenkopf. Kolbenstellung,
Ventildrehung und Kopfwechsel sind geometrische Zustände. Sie bilden keine
Dosiersteuerung, Verriegelung, automatische Spitzenaufnahme oder sichere
Wiederanlaufsequenz ab. Ein späterer Betriebsvertrag muss das Umschalten und
Abnehmen insbesondere bei gefüllter Spitze ausdrücklich behandeln.

```sh
python3 scripts/build_syringe_pipette.py --backend both
```

Einzelne Fassungen und eigene Annahmen lassen sich gezielt erzeugen:

```sh
python3 scripts/build_syringe_pipette.py --backend freecad --case default --parameter radiusFine=2.6
python3 scripts/build_syringe_pipette.py --backend solidcraft --case macro
```

Anpassbar sind die beiden Innenradien, Glaswand, Achsabstand, Achshöhe,
Luftleitungsquerschnitt und Kopfaufnahme. Namen, Einheiten und gültige Bereiche
stehen in der Modellquelle. Die Hübe werden abgeleitet und sind keine unabhängig
überschreibbaren Parameter. In beiden nativen CAD-Fassungen sind die zugehörigen
Volumen-/Radiusausdrücke ebenfalls erhalten.

Der Aufbau erzeugt die beiden CAD-Fassungen und parameterabhängige Varianten
aus derselben Quelle. Native Geometrie-, Gelenk- und Parameterprüfungen belegen
nur den im jeweiligen Build-Bericht aufgeführten Modellumfang. CAD-Dateien,
Prüfberichte und vollständige Renderings bleiben lokale Ableitungen.

## Ist Luer-Lock hinreichend gasdicht?

**Eine geeignete Luer-Lock-Verbindung kann gasdicht genug sein; die Bezeichnung
allein belegt die Eignung für unsere 1-µl-Aufgabe nicht.** Hamilton verwendet
Luer-Lock beispielsweise an einem Gasprobenventil für Gastight-Spritzen. Die
dort angegebene Druckprüfung ist keine Zusicherung einer bestimmten Leckrate
oder Dosiergenauigkeit für unseren Aufbau.
[Hamilton: Gas Sampling Valve](https://www.hamiltoncompany.com/laboratory-accessories/86580)

Hamilton beschreibt seinen TLL-Anschluss als PTFE-Luerkonus mit separater
Verriegelungshülse. Konstruktiv liegt die Dichtpaarung an den Konusflächen;
die Verriegelung hält die Verbindung zusammen. Kolbendichtung und
Anschlussdichtung sind getrennte mögliche Leckstellen.
[Hamilton: Spritzenauswahl und Anschlüsse](https://www.hamiltoncompany.com/knowledge-base/guide/syringe-selection-guide)

ISO 80369-7 behandelt Abmessungen und Funktion der betreffenden medizinischen
Kleinanschlüsse. Die ISO-Seite grenzt die Anforderungen an angeschlossene
Geräte beziehungsweise Zubehör ausdrücklich aus. Normkonformität eines
Anschlusses wäre deshalb noch kein Dosiernachweis des Gesamtsystems.
[ISO 80369-7:2021](https://www.iso.org/standard/79173.html)

Die Anschlusskörper in SP01 sind ausschließlich **Luer-Lock-Bauräume**.
Normkonus, Gewinde, Gegenstück, Oberflächen, Toleranzen und Montagekräfte sind
nicht als funktionsfähige oder normkonforme Anschlussgeometrie ausgelegt.
Eine abgeleitete CAD-Kontur ist keine druckdichte Fertigungsvorlage.

Für die spätere Abnahme gilt als eigene Fehlerbudget-Überlegung
`Leckvolumenstrom × Haltedauer ≤ zulässiger Leckbeitrag zum Volumenfehler`.
Alle Größen müssen auf dieselben Druck-/Temperaturbedingungen bezogen werden.
Die zulässigen Werte und Prüfbedingungen bleiben offen; das Konzept erfindet
keine numerische Leckgrenze. Die ganze Luftstrecke ist unter vorgesehenem
Unter- und Überdruck, bei tatsächlicher Haltedauer und nach wiederholtem
Verbinden zu prüfen. Ein Druckhalteversuch benötigt thermische Stabilisierung;
die Prüfung tatsächlich abgegebener Flüssigkeitsmengen bleibt zusätzlich nötig.

## Offene Nachweise

Messwerte konkreter Spritzen und Spitzen sowie Grenzen für Leckage,
Dosierabweichung und Wiederholstreuung bleiben ausdrücklich `null`.
Hersteller und Artikel sind nicht ausgewählt. Ebenfalls ungeprüft sind
Werkstoffe, Sauberkeit/Verschleppung,
Betätigungskräfte, Motor-/Spindelauswahl, Bauteilfestigkeit, Roboteraufnahme und
Werkzeuglast. Das Modell enthält keine Fertigungsfreigabe, qualifizierte
Gasdichtheit oder Dosierleistung und keine Hardware-, ROS- oder Netzwerkausführung.

Vor einer Roboterintegration stehen die Vermessung ausgewählter Bauteile sowie
Dosier- und Verschleppungsversuche am ruhenden Prüfstand. Druckverlauf,
Kolbenposition und Befehlsquittung ersetzen keinen Nachweis der abgegebenen
Probenmenge. Die bisherigen synthetischen Pipettiermodelle werden durch SP01
nicht zu ausführbaren Dosiergeräten.

## Geprüfter Konzeptstand

Die Revision `syringe-pipette-017103cfbee9-r2` besteht vier Varianten in beiden
CAD-Systemen: Standard, geänderte Innenradien, größerer Achsabstand und größerer
Spitzenkopf. Jede Variante enthält 47 geschlossene Körper und besteht
33 native Gelenk-/Luftweg-Prüfstellungen. Die 20 Vergleiche benannter Stellungen
zwischen FreeCAD und SolidCraft umfassen 940 Körpervergleiche. In den geprüften
Stellungen wurden keine Überschneidungen zwischen beweglichen Baugruppen und
anderen Komponenten festgestellt; Kontakte innerhalb starrer Baugruppen werden
im Bericht separat aufgeführt.

Zusätzliche Änderungen direkt an den nativen FreeCAD-Radiusparametern bestätigen,
dass Hub, geometrische Nennkapazität, Glasgeometrie und Prüfbezüge gemeinsam
nachgeführt werden. Alle 14 Quell-, Schema- und Nachweistests bestehen ohne
Überspringen. Der aktuelle lokale Bericht liegt nach dem Aufbau unter
`cad/syringe-pipette/shared-build-report.json` und bindet Quellen, CAD-Dateien,
Messungen und Renderings über Prüfsummen. Die FreeCAD-Präsentationsmetadaten
sind geprüft; eine FreeCAD-GUI-Ansicht wurde nicht geprüft.

Diese diskreten Geometrieprüfungen sind keine kontinuierliche Kollisionsprüfung,
Kraft-/Bewegungsqualifikation, Dichtheitsprüfung oder Dosiermessung.
