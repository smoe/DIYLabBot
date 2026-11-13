# Drei Transporter mit lokaler Hinderniserkennung

`model/l01-local-traffic.demo.json` definiert einen separaten synthetischen
Verkehrsvorläufer auf einer Geraden, ausgeführt von
`python3 scripts/l01_local_traffic.py`. Die aktuelle Auswahl **Drei Transporter**
verwendet inzwischen den [Gegenverkehrsablauf](l01-opposing-traffic.md) mit
unterschiedlichen Stationszielen und lokalem Rückzug. Der hier dokumentierte
Geradenfall bleibt als unabhängiger Regressionstest erhalten.

## Ursprünglicher Geradenfall

TR01, TR02 und TR03 fahren gleichzeitig auf der linken Gangmitte von
DNA/TapeStation Richtung CF01. Eine Person kommt seitlich in den Gang, bleibt
vorübergehend dort und verlässt ihn wieder. Das vordere Fahrzeug bremst, die
folgenden erkennen Hindernisse unabhängig davon und warten beziehungsweise
bremsen ebenfalls. Nach frischen freien Beobachtungen fahren sie erneut an.
Die Endpositionen sind getrennte Haltepunkte auf dem Gang, keine drei neuen
Andockplätze. Die Arme bleiben geparkt; sämtliche Bench-Bereiche bleiben
sichtbar gesperrt. Niemand wird durch Signalton oder seitliches Ausweichen
vom Arbeitsplatz verdrängt.

## Wissensgrenze und Reaktion

Nur `SensorWorld` und der unabhängige Abstandsauditor besitzen Weltpositionen.
Jeder `LocalController` bekommt ausschließlich seine eigene Position,
Geschwindigkeit, Beschleunigung, sein eigenes Ziel und anonyme lokale
Erstrücklaufpunkte samt Erfassungszeit. Andere Fahrzeug-IDs, globale Positionen,
Geschwindigkeiten, Pläne oder Stationszustände werden nicht an ihn übergeben.
Die Welt aktualisiert alle Sensoren aus demselben Zeitschritt vor den
Reglerentscheidungen, ohne Vorrang durch Auswertungsreihenfolge.

Die Sensorannahme ist ein idealer horizontaler Rundumscan mit 2° Raster,
2,2 m Reichweite, 100 ms Abtastung und 100 ms Verzögerung. Der erste Treffer
verdeckt dahinterliegende Objekte. Vereinfachte opake Bench-Grundflächen,
konservative Fahrzeugkreise und ein Personenradius von 250 mm werden verwendet.
Dies ist keine ausgewählte oder qualifizierte LiDAR-/Personenschutzinstallation.

Der Regler berücksichtigt eigene ruckbegrenzte Bremsstrecke und Bremsdauer,
Scanzyklus und Verzögerung, einen angenommenen maximalen Hindernisannäherungswert
von 200 mm/s sowie Reichweitenfehler und Winkelraster. Dieser niedrige
Annäherungswert gehört zum langsamen Demonstrationsfall; er begrenzt keine
reale Person und belegt keinen Schutz gegen beliebige Gehgeschwindigkeiten
oder plötzliches Hervortreten aus Verdeckungen. Bei fehlenden oder veralteten
Scans wird gebremst. Wiederanfahren verlangt mindestens 0,5 s frische freie
Beobachtungen und Freiraum für die nächste Fahrt einschließlich Bremsreserve.
Damit erzeugt eine stehende Person kein periodisches Vorrücken.

Die Beispielsollgeschwindigkeit beträgt 100 mm/s. Beschleunigung und Ruck
bleiben mit einer numerischen Reserve von 2 % unter den unveränderten
TR01-Quellgrenzen. Beschleunigungsfahrten verwenden die gemeinsame
Rest-zu-Rest-PVA-Mathematik, Schutzbremsungen analytische C2-S-Kurven aus dem
aktuellen Geschwindigkeits- und Beschleunigungszustand. Bremsen und Warten
haben konkrete Beobachtungsgründe; Stationsmarken verursachen keine zusätzlichen
Halte. Maximale Geschwindigkeit, Beschleunigung und Ruck werden aus den
Polynomextrema der exportierten Kurven einschließlich Segmentgrenzen geprüft.
Die Animation wertet genau diese Kurven aus. Keine globale Zeitoptimalität,
biologische Qualifikation oder reale Antriebsdynamik wird nachgewiesen.

## Nachweise und Grenzen

Die Fahrt nutzt ausschließlich bereits nativ geprüfte geradlinige Posen mit
X = 1625 mm und Richtung +Y zwischen Y = 1200 und 5250 mm. Der Generator prüft
Quell- und Artefaktpins und die lückenlose räumliche Abdeckung durch die
bestehenden konstanten PVA-Segmente. Fahrzeug, Abdeckung, Ladung und geparkte
Arme bleiben dieselben. Diese Identitätsprüfung verwendet den bisherigen
nativen Geometrienachweis; sie ist kein neuer CAD-Aufbau.

Für dynamische Abstände prüft ein separater Auditor konservative umschließende
Kreise. Eine Bewegungsobergrenze für das gesamte Abtastintervall wird von den
Abständen abgezogen. Der resultierende untere Abstand muss die konfigurierte
Reserve einhalten. Die Reserven und Bedingungen gelten für diesen definierten
synthetischen Lauf, nicht für beliebige Menschenbewegungen.

`tests/test_l01_local_traffic.py` prüft Abschluss und gleichzeitige Bewegung
aller drei Fahrzeuge, Personen- und Fahrzeugabstände, Polynomgrenzen,
Erstrücklaufverdeckung ohne Identitätsweitergabe, Scanausfall und zwei
gegengerichtete lokale Regler. Im Gegenverkehrstest bleiben beide stehen;
Rückwärtsfahrt, Überholen und allgemeine Auflösung solcher Blockaden sind
nicht implementiert. Der Browserplayer prüft vollständiges automatisches
Abspielen und erhaltene Bench-Sperren. Der native Offscreen-GPU-Replay rendert
alle drei Instanzen und ihre Schatten; er ersetzt keinen Browser-Layouttest.

Die Ergebnisdatei `exports/tr01-workcell/local-traffic.json` und die
Vorschaubescheinigung enthalten Quellbezüge, Kurven, anonyme Beobachtungskennwerte,
Stoppgründe und Prüfgrenzen. Das sind ignorierte Simulationsausgaben, kein
Ausführungsjournal, Hardware- oder Sicherheitsnachweis. Bei einer realen
Umsetzung wären Sensorabdeckung, Latenz, Bremsvermögen, Traglast, Retention,
Personenschutz und Wiederanlaufbedingungen gesondert nachzuweisen.
