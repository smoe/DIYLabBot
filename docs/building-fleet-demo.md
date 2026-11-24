# BF01 · synthetische Gebäudeflotte

BF01 ist eine ausdrücklich gewählte, separate Simulation für 20 leere
TR01-Instanzen `BF01` bis `BF20`. Die bestehende L01-Aufstellung einschließlich
ihres statischen TR01 und ihrer Bewegungsnachweise bleibt unverändert.
Es gibt keine Probenübergabe, Materialbuchung, T1/T2/T3-Bindung, ROS-,
Gerätenetzwerk- oder Hardwareausführung. Ein normaler Rundgang aktiviert keine Flotte.
Die aktive Browserfassung und der lokale Dienst verwenden denselben Motor;
die frühere zeitlich begrenzte Teilvorschau bleibt ein historischer Prüfstand.

## Aktive Browserfassung

`model/building-fleet-browser.shared.json` beschreibt den zusätzlichen
Browseradapter. Jede geöffnete Seite startet eine **neue, unabhängige aktive
Sitzung** mit 20 leeren Fahrzeugen. Es wird keine frühere Fahrt abgespielt;
ein Rückfall auf die alte Aufzeichnung ist ausgeschlossen. Die laufende
Patrouille und neue Testaufträge werden in dieser Sitzung berechnet. Das
Schließen der Seite beendet sie; eine neue Seite übernimmt weder Aufträge
noch Fahrzeugzustände einer früheren Sitzung.

Der Browser benötigt dafür keinen lokal gestarteten Simulationsdienst und
keinen gemeinsam betriebenen Simulationsserver. Er lädt den in der Quelle
festgelegten Python-Laufzeitkern sowie das quellgebundene Laufzeitpaket und
führt den vorhandenen `PatrolWorldRunner` in einem eigenen Worker aus. Die
übrige Seite bleibt während längerer Berechnungen bedienbar. Physik, anonyme
Scans, 50-ms-Schritte und Bremsnachweise, Rekrutierung, Buchten-, Aufzug- und
Bench-Regeln kommen aus denselben Python-Modulen wie beim lokalen Dienst.
Modellzeit wird nicht vorgezogen, um langsame Berechnungen aufzuholen.

Auf ausreichend langen, freien Geraden ist die leere Flotte auf Schritttempo
ausgelegt. Das BF01-Profil begrenzt die Geschwindigkeit dort auf 1,45 m/s und
verwendet einen synthetischen Rundumscan mit 12 m Reichweite und 1.000 Strahlen.
Die Bremsrechnung berücksichtigt ein entgegenkommendes Fahrzeug mit bis zu
1,45 m/s. Die baulichen Abstände für Begegnungen und Aufzugbuchten basieren
weiter auf der etwas größeren Winkelunsicherheit des E5-Rundumscans. Die
bestehende Begrenzung auf 0,30 m/s in geschützten Bereichen wie
Räumen, Durchgängen und der Aufzugkabine sowie die Beschleunigungs- und
Ruckgrenzen gelten weiter. Kurven und der jeweils verfügbare Bremsweg können
das Tempo zusätzlich begrenzen. Die Scan- und Fahrwerte gelten für die
Simulation. Eine Fahrwerks- oder Sensorqualifikation für TR01 steht aus.

`scripts/build_building_fleet_browser.py` erzeugt HTML, Workerdateien und ein
deterministisches ZIP. Der Browservertrag `/2` enthält originale Module und
Modellquellen sowie ausdrücklich abgeleitete, quellgebundene statische Daten.
Die originalen CAD- und vollständigen Weltdateien werden beim Cacheaufbau
geprüft und als Ableitungsnachweis gebunden; sie sind keine notwendigen
Browserdownloads mehr. Der Browser startet kein natives CAD. Das Laufzeitmanifest bindet
jede Datei mit Größe und SHA256. Aufgezeichnete Programme, Laufjournale,
Controller-Beobachtungen und alte Sitzungssnapshots gehören nicht in dieses
Paket. Die statischen Daten beschreiben Wege und Körper, keine ausgeführte
Mission. Download-, Quellen- oder Rechenfehler bleiben sichtbar, statt eine
gespeicherte Fahrt als aktive Simulation auszugeben.

Die 20 vorhandenen Atrium-Monitore erhalten jeweils die tatsächlich im
synthetischen Funkmodell empfangene Kamerareferenz ihres Fahrzeugs samt
ursprünglicher Aufnahmezeit, Aufnahmepose und damaliger gemeinsamer Szene.
Es handelt sich um lokal gerenderte Modellansichten. Die Hauptansicht zeigt
ausschließlich bereits ausgeführtes PVA, mit begrenztem Darstellungsverzug
und ohne Vorhersage über das berechnete Ende hinaus. Ein Testauftrag und die
auftragsbezogene Bestätigung gehören ausschließlich zu dieser Browsersitzung.
Reale Lasten, Geräteübergaben und Video-Netzwerklastmessungen bleiben offen.

Der Browseraufbau ist eine zusätzlich implementierte Zielunterstützung. Ein
erfolgreicher Paketaufbau ist noch keine Prüfung des öffentlichen Deployments,
der vollständigen Zielabdeckung oder einer realen Schutzfunktion. Die
separaten Browser- und Veröffentlichungsberichte binden jeweils die konkret
geprüften Bytes. Der normale manuelle Rundgang bleibt ohne aktive Flotte.

### Statische Prüfmetadaten zwischen Python-Laufzeiten

Bei der ersten WebAssembly-Rekonstruktion der 3314 festen Routen unterschieden
sich 269 Felder ausschließlich in `portal_certificates[].yaw_rad`, jeweils
um höchstens eine binary64-ULP. Alle übrigen Routenfelder, Punkte, Ressourcen,
Typen und Vorzeichen von Null waren identisch. Diese Winkel sind
Prüfmetadaten; sie sind keine neue Fahrkurve. Die ursprünglichen Bytes und
der Hash der vollständigen Routenbank bleiben maßgeblich.

`building_fleet_browser_navigation.py` verwendet deshalb einen ausdrücklich
gebundenen Browseradapter. Zuerst führt er die unveränderte geometrische
Ableitung und deren frische Prüfungen aus. Er übernimmt anschließend nur
die ursprünglichen, gepinnten Winkelzeugnisse eines ansonsten bis auf diese
Felder bitidentischen statischen Routenobjekts. Jeder andere Unterschied
oder ein unbekanntes Objekt sperrt die Wiederverwendung. Der gewöhnliche
vollständige Routenbank-Hash und der bestehende Ressourcencache-Vertrag
werden danach unverändert geprüft. Alte Berichte werden nicht umgepinnt;
der Browserbericht hält die ursprünglichen und neu berechneten Hexwerte
dieser eng begrenzten Metadatenbindung separat fest. Die Quellenregel
`static_route_witnesses` benennt diese Ausnahme ausdrücklich. Fahrzeugmaße,
Punkte, PVA, Stützung, Abstände und Grenzwerte werden dadurch nicht geändert.

### Start und laufende Bahnvorbereitung

Der Browser startet den einzigen Sitzungsmotor bereits beim Laden des
Seitenkopfs. Derselbe Motor wird anschließend mit der Darstellung verbunden.
Die erste Ansicht enthält die vollständige native Geometrie des EG und die
gemeinsamen Gebäudekörper. Die übrigen Geschosse werden nach tatsächlichem
Fahrtbeginn im Hintergrund geladen; die Vereinigung enthält dieselben
Körper und Dreiecke wie die vollständige Welt. Ein Wechsel oder freier
Kameragang in ein noch nicht geladenes Geschoss wartet auf dessen geprüfte
Geometrie. Die Physik verwendet ihren eigenen vollständigen, quellgebundenen
Geometrievertrag.

`building_fleet_runtime_cache.py` stellt die bisherigen Geometrieklassen aus
offenen JSON- und Zahlenfeldern wieder her. Ganze native Körper bleiben
erhalten; nur unbewegte Körper außerhalb sämtlicher erreichbarer
Fahrzeughöhenbänder dürfen entfallen. Bewegte Körper, Bodenflächen,
Rasterbezug, native Hindernisflächen und exakte Strahlindizes bleiben gebunden.
Geschossdaten werden vor ihrer ersten Verwendung geprüft und materialisiert.
Die statische Wahrnehmungsgrenze darf mit ihren unveränderten mathematischen
Operationen wiederverwendet werden; sie ist kein Scan und keine Fahrfreigabe.
Ein aufgezeichneter Fahrzeugzustand, Auftrag oder Transfer gehört nicht in
diesen Cache.

Die längere Bahnvorbereitung läuft in einem zweiten Worker ohne eigene
Weltzustandsmaschine. Er erhält ausschließlich den eigenen, bereits
zugesagten Auftrag mit Quell-, Aktions- und Freigabebindung. Der Sitzungsmotor
läuft währenddessen weiter. Sobald der Sitzungsmotor die gemeinsamen
Laufzeit- und Paketdateien geladen und geprüft hat, beginnt der Planer
parallel zum Aufbau der Simulationswelt mit dem Depotgeschoss.
Die weiteren Geschosse werden bei ihrem ersten Zugriff geprüft.
Eine erste gerade Teilstrecke darf nur innerhalb
der bereits eigenen Ressource beginnen und benötigt ihre eigenen Grenz-,
Boden- und nativen Abstandsprüfungen. Sie behält die vollständige ursprüngliche
Fahrt und deren Ziel; ihr Planungshorizont ist kein Missionsabschluss.
Alle ausgeführten Schritte benötigen weiterhin den vollständigen nächsten
höchstens 50-ms-Abschnitt samt anschließender Bremskurve gegen denselben Scan.
Auch die gesamte Rückfallbremsung muss innerhalb des geprüften Horizonts liegen.

Eine Fortsetzung während der Fahrt benötigt einen geprüften C2-Anschluss am
tatsächlich beobachteten PVA-Zeitpunkt. Ein verspätetes oder inzwischen
unpassendes Ergebnis ersetzt die bestehende Bremsfreigabe nicht. Ohne
rechtzeitige Fortsetzung bremst das Fahrzeug innerhalb des Horizonts und
wartet; ein erneuter Anschluss aus bestätigtem Stillstand kann danach
geprüft werden. Aufträge, Buchten, Aufzugbeobachtungen, Türfreigaben und
Bench-Sperren bleiben beim Sitzungsmotor. Die Worker übertragen die inneren
JSON-Nachrichten unverändert als Text, damit Zahlenarten und vorzeichenbehaftete
Nullen in den exakten Prüfbindungen erhalten bleiben.

Für eine Fahrt mit geprüfter Startgerade berechnet der Planer die gesamte
Nominalkurve einmal. Seine erste Antwort enthält den Fahrverlauf und die
Tür- und Ressourcenbezüge bis zum Ziel sowie den Geometrienachweis für den
ersten Abschnitt. Jeder weitere Nachweis beginnt genau am zuletzt bestätigten
Knoten und umfasst höchstens 32 ursprüngliche Kurvenintervalle. Die native
Abstands- und Bodenprüfung gilt für jeden Abschnitt. Im Depotgeschoss prüft
der Planer außerdem die Abstände zu den festen Heimplätzen. Die Freigabe
wächst erst, wenn Quellstand, Fahrzeug, Aktion, Generation, Geschoss,
Programmprüfsumme, Knotenbereich und ursprüngliche eigene Zusagen stimmen.
Die Geometrieprüfung verwendet die Wartebucht und die Aufzugstufe vom
Aktionsbeginn. Wechselnde Durchfahrtszusagen prüft `ResourceGate` bei jedem
Fahrschritt anhand des aktuellen Zustands.

Je Fahrzeug ist höchstens ein Prüfauftrag gleichzeitig ausstehend. Anschlüsse
an den beobachteten Fahrzustand haben Vorrang. Unter den weiteren Abschnitten
wird zuerst das Fahrzeug mit dem bei Anforderung kleinsten Abstand zwischen
Bremsende und geprüftem Horizont bedient. Ein abgelehnter Abschnitt erscheint
mit Grund in der Fahrzeugtabelle. Der letzte gültige Horizont begrenzt
weiterhin die Fahrt und die gesamte Rückfallbremsung. Ein Wiederanlauf aus
Ruhe erfordert einen geprüften Anschluss, eine freie Ressource und einen
frischen freien Scan. Aufzugaktionen benötigen vor Fahrtbeginn den bisherigen
vollständigen Einzelnachweis.

Die Darstellungsnachrichten folgen der gewählten Bildrate; die internen
50-ms-Schritte laufen auch ohne neue vollständige Darstellungsnachricht.
Die Anzeige schätzt aus neu eingetroffenen Modellzeiten und ihrer tatsächlichen
Ankunftszeit, wie schnell sie die ausgeführte Bewegung abspielen kann.
Der Regler der Anzeige strebt 0,3 Modellsekunden Puffer an. Er spielt mit
höchstens einfacher Echtzeit und nur bis zum Ende der empfangenen Kurve.
„Simulation rechnet“ kennzeichnet einen aufgebrauchten Puffer. Modellzeit,
Anzeigezeit, vergangene Wandzeit und Wiedergabefaktor sind getrennt ablesbar.
Der Diagnosezustand enthält zusätzlich die gemessenen Rechenzeiten des
Sitzungsmotors und der einzelnen Planerphasen.
Unveränderte geometrische Abstände werden nur mit exakten Eingaben
wiederverwendet. Besitz, Stillstand, aktuelle Bewegungshüllen und die
Weiterfahr-/Bremsprüfung werden weiterhin bei jedem Schritt ausgewertet.
Optional erzeugt `--python-bytecode-compiler` aus den mitgelieferten Originalen
quellhashgeprüfte Python-Importdateien. Größe, Prüfsumme, Quellhash,
Bytecodeversion und Laufzeitkompatibilität werden vor dem Import geprüft.

Die frühere vollständige lokale Browserprüfung beobachtete die erste Bewegung
nach **7,56 s** und ihre erste native Bildschirmdarstellung nach **7,80 s**
ab Seitenaufruf. Alle 20 Kamerazuordnungen und physischen Monitorflächen,
das Laden aller Geschosse, Pause/Fortsetzung, Testrekrutierung und ein
tatsächlich übernommener C2-Anschluss aus der Hintergrundberechnung bestehen.
Die zusätzlich gesetzte 5-Sekunden-Marke wurde verfehlt und bleibt offen;
dies ist kein vollständiger Missions- oder Hardware-Nachweis. Originalbericht
und unveränderte Messwerte liegen unter
`exports/building-fleet/background-startup-0b10fe1/full-r7/`.

**Lokaler Kontinuitätstest mit Seed 20261120.** Ein neuer Chromium-Prozess
öffnete je Fassung den vollständigen Rundgang mit leerem Browsercache.
Ein Beobachter erfasste die Workerzustände und die dargestellte Modellzeit
pro Browserbild. Als erste Bewegung zählt eine Ortsänderung von mindestens
1 mm. Ein Anzeigestillstand bei vorhandener Bewegung im Puffer
(`display_freeze`), ein aufgebrauchter Puffer (`buffer_underrun`) und ein
im Modell tatsächlich ruhendes Fahrzeug (`real_stop`) sind getrennt messbar.
Die alte Fassung meldete weder den Haltegrund noch die Warteschlangenposition.

In der Zwischenfassung mit früherem Planerstart stand BF06 nach der Abfahrt
bei 0,821 m. Der vollständige Prüfauftrag war noch offen. Von 66,14 s
Wandzeit entfielen 30,61 s auf die native Geometrie, 3,50 s auf die Heimplätze,
17,57 s auf die Kurvenberechnung, 2,38 s auf deren zeitliche Anpassung und
11,38 s auf Ressourcen- und Türbezüge. Diese Messung begründet die
abschnittsweise Geometrieprüfung. Die synchrone Prüfung der Startgeraden
benötigte 1,02 s im Kontrolllauf und 0,94 s in der Zwischenfassung. Dort
war der Planer erst 1,64 s nach Beginn der Starterarbeit bereit. Daher
verbleibt die Prüfung der Startgeraden beim Sitzungsmotor.

Der Sitzungsmotor benötigte in der Zwischenfassung während aktiver Planung
durchschnittlich 0,165 s Rechenzeit je 50-ms-Schritt (395 Schritte), bei
bereitem, untätigem Planer 0,461 s (20 Schritte). Die Phasen enthalten
unterschiedliche Fahr- und Startzustände. Ein isolierter Einfluss der
Planerlast auf die Schrittzeit lässt sich daraus nicht bestimmen.

Die folgende Tabelle vergleicht die ersten 55 s Wandzeit. Modell- und
Anzeigezeit stammen aus der letzten verfügbaren Beobachtung im Fenster.
Die beiden Faktoren geben den mittleren Zeitfortschritt während der
laufenden Simulation bzw. Darstellung an.

| Messgröße | Ausgangsstand mit Zeitmessung | Früher Planer und gepufferte Anzeige | Zusätzlich abschnittsweise Freigabe |
|---|---:|---:|---:|
| Erste Bewegung ab Seitenaufruf (Wandzeit) | 14,37 s | 16,18 s | 13,17 s |
| Erreichte Modellzeit / Anzeigezeit | 9,20 / 8,99 s | 8,80 / 8,12 s | 6,80 / 6,33 s |
| Modellsekunden / Wandsekunde | 0,189 | 0,193 | 0,142 |
| Angezeigte Modellsekunden / Wandsekunde | 0,187 | 0,179 | 0,133 |
| Anzeigestillstand bei gepufferter Bewegung (Episoden / Wandzeit) | 31 / 4,28 s | 2 / 0,03 s | 4 / 0,17 s |
| Aufgebrauchter Puffer (Episoden / Wandzeit) | 28 / 27,10 s | 3 / 3,48 s | 4 / 2,27 s |

BF06 wartete in der Endfassung zunächst auf einen freien Scan. Ein zweiter,
kurzer Halt blieb an der Grenze der Startgeraden. Vom beobachteten Stillstand
bis zur nächsten beobachteten Bewegung vergingen 1,12 s Wandzeit (5,0 bis
5,2 s Modellzeit). Mit dem früheren vollständigen Prüfauftrag lagen zwischen
diesen beiden Beobachtungen 35,99 s Wandzeit (5,0 bis 20,6 s Modellzeit).
Die übrigen 19 Fahrzeuge warteten auf die von BF06 gehaltene Depotressource.

Die erste Teilfreigabe beanspruchte 30,33 s Planerzeit, ihr C2-Anschluss
weitere 0,56 s. Nach 86,98 s Wandzeit war die gesamte erste Route bis
59,195 m geprüft. Der bestätigte Horizont wuchs von 1,240 m bis zum Ziel
mit durchschnittlich 1,29 m je Wandsekunde. Diese Messung liegt unter der
freien Profilgrenze von 1,45 m/s. Im letzten beobachteten Fahrzeugzustand
nach 90,75 s Wandzeit hatte BF06 1,010 m zurückgelegt. Die Modellzeit betrug
12,20 s, die Anzeigezeit 11,72 s. Der momentane Wiedergabefaktor reichte
von 0 bis 0,897. Es gab keinen Sprung zu einer späteren Anzeigezeit.

Der Kaltstart der Endfassung lag 1,20 s unter dem Kontrolllauf und 5,61 s
über der historischen Messung von 7,56 s. Auslieferung und Rechnerlast
unterscheiden sich zwischen den Einzelmessungen. Der menschliche
Geschwindigkeitsvergleich, die tatsächliche Ankunft am Ziel sowie
Hardware- und Sicherheitsqualifikation bleiben offen. Der lokale Vergleich
und die Zeitreihen liegen unter `exports/building-fleet/bf01-live-continuity/`
in `browser-comparison.json`, `final-live.json` und der zugehörigen
`.trace.json.gz`. Das dabei geprüfte Browserpaket liegt in `final-browser/`.

Der spätere Vergleich der Depotausfahrten verwendete Seed 20261120 und
frische Chromium-Sitzungen. Im seriellen Kontrolllauf fuhr BF06 in
62,40 s Modellzeit 6,867 m (179,60 s Wandzeit). Im Lauf mit zwei
Ausfahrten bewegte sich BF06 nach 5,28 s Wandzeit. Nach 16,13 s
Wandzeit fuhren BF06 in R0_013 und BF01 in R0_004 im selben
Modellschritt von 4,15 bis 4,20 s. Beide Regler bestätigten anhand
ihres eigenen Scans von 4,00 s Modellzeit den folgenden Bremsweg.
BF01 wartete ab der Beobachtung bei 8,20 s Modellzeit an der
0,821-m-Grenze auf BF06. Weitere 18 Fahrzeuge standen am Heimplatz.
Alle 20 Kameras lieferten Bilder. Der Browserlauf endete bei 15,40 s
Modellzeit nach 60,96 s Wandzeit. Der Integrationstest prüft die spätere
Übergabe und das Wiederanfahren derselben Mission an einem kürzeren
Beispiel mit vorgegebenem Geometrieprüfergebnis. Die Messungen stehen in
`exports/building-fleet/bf01-live-followup/merged-180s.json` und
`concurrency-r2.json` im selben Verzeichnis.

Die Browserquelle bindet zusätzlich
`model/building-fleet-browser-python.shared.json`. Dessen fünf unveränderte
Pyodide-Kerndateien werden mit ihren Originalprüfsummen von derselben Website
geladen; Herstellerlizenzen und der in dieser Quelle geführte Hinweis auf den
verfügbaren Quelltext werden mit veröffentlicht. Python und Modellpaket laden
parallel. Inhaltlich adressierte Dateien dürfen den HTTP-Cache nutzen;
Größe und SHA256 werden auch bei einem Cachetreffer geprüft. Das ist weiterhin
eine neue lokale Browsersitzung, kein gehosteter Simulationsdienst.

Der optionale Ressourcencache `/2` bindet die vollständige ursprüngliche
Konstruktion aller statischen `Path`-Objekte mit typ- und bitgenauen
Eingangsprüfsummen. Seine Wiederherstellung rekonstruiert die tatsächlichen
Konfliktflächen und prüft Quellen, Routenbank und Abschlussbedingungen;
ungenutzte Abtasttabellen dieser bereits geprüften statischen Wege werden
nicht nochmals aufgebaut. Der alte Cache `/1` behält seine vollständige
Konstruktion. Neue Kompatibilitätsberichte belegen die Gleichheit der
statischen Daten separat, einschließlich aller 3314 Wege und 2117104
Abtastintervalle. Historische Berichte bleiben unverändert. Ein solches
Ergebnis ist kein neuer vollständiger Flotten- oder Bewegungsnachweis.

Aufzugöffnung, Topologie und Startbelegungsraster werden aus der bereits
quellen- und artefaktgeprüften Welt übernommen. Welt, Fahrzeughöhe,
Bodenbank und Auflösung müssen exakt passen. Die unabhängige
Geometrieprüfung ohne diese Navigation behält ihren eigenen Aufbau.
Tatsächliche native Hindernisflächen, die Prüfung der Anfangsbelegung sowie
die Abstands- und Bodenprüfung jeder neu geplanten Kurve bleiben erhalten.

Die nominale Kurvenanpassung verwendet ihre funktionalen Rampen-,
Geometrie-, Zonen- und Endereignisse sowie die zusätzlichen Knoten in
gekrümmten Abschnitten. Ein regelmäßiger 50-ms-Knoten wird nicht zusätzlich
allein zur Anpassung einer nominalen Kurve eingefügt. Zeitquantisierung,
vollständige Polynomgrenzen und Kein-Halt-Prüfung bleiben verbindlich;
die so neu angepassten Kurven benötigen ihre eigenen Geometrieprüfungen.
Schutzbremsung und Wiederanlauf behalten ihre bisherigen regelmäßigen
Anpassungsknoten. Der Regler beobachtet und prüft weiterhin jeden nächsten
höchstens 50-ms-Schritt samt vollständiger Anschlussbremskurve gegen
denselben vorhandenen Scan. Modellzeit wird nicht beschleunigt.

Die native Intervallprüfung beginnt mit Gruppen von höchstens 32 bestehenden
Kurvenabschnitten. Eine Freigabe benötigt weiterhin die vollständigen
Polynomgrenzen aller enthaltenen Abschnitte, native Abstände und die
vollständige aufgeweitete Bodenstützung. Ein nicht bewiesener Gruppenbereich
wird zunächst an den ursprünglichen Knoten geteilt; anschließend gilt die
bisherige Unterteilungstiefe je ursprünglichem Abschnitt. Das verändert
keine Abstandsschwelle, Bodenregel, Türfreigabe oder Bench-Sperre.
Zusätzlich werden ausschließlich identische, unveränderliche PVA- und
Koeffizienteneingaben in begrenzten Prüf-Caches wiederverwendet. Andere
Eingaben erhalten die ursprüngliche gemeinsame Mathematik; deren Quellen
und die Bewegungsgrenzen werden nicht geändert.

Die frühere Browsermessung vor dieser Hintergrundvorbereitung beobachtete
die erste Ausführungsnachricht nach 31,9 statt 193,5 s, die erste Bewegung
von mindestens 1 mm nach 71,2 statt 475,7 s und die Vorbereitung der ersten
nominalen Kurve in 34,9 statt 278,3 s. Die geplante Modellzeit dieser ersten
Fahrt blieb bei 530,384 s. Das sind einzelne Messungen der minimalen
Worker-Testseite; das Modellpaket kam lokal, die frühere Python-Laufzeit vom
CDN und die neue vom selben Ursprung. Download der vollständigen
Gebäudeansicht, parallele Rechnerlast und öffentliche Auslieferung sind
gesondert zu betrachten. Die Rohdaten und der Vergleich liegen lokal unter
`exports/building-fleet/startup-performance-586ff76/` in
`before/measurement.json`, `after-final/measurement.json` und
`comparison-final.json`. Auch die neue Fassung hat noch eine sichtbare
Vorbereitungsphase; eine sofortige Fahrt oder Echtzeit des Gesamtlaufs ist
damit nicht nachgewiesen. Die öffentliche Fassung wird separat auf
tatsächliche Bewegung und alle 20 physischen Monitorflächen geprüft.

## Experimentelle Teilvorschau

**Historischer Prüfstand:** Die frühere BF01-Seite zeigte eine ausdrücklich
**experimentelle Teilvorschau** der aufgezeichneten Fahrt von 0 bis 1188,1 s mit allen
20 Fahrzeugen. Fahren, Warten und Parken folgen der Aufzeichnung; die
Fahrzeuge sind nicht ständig gleichzeitig in Bewegung. Der Browser berechnet
keine neue Fahrt. Die Aufzeichnung endet mit unvollständiger Zielabdeckung;
ein sichtbarer Hinweis und der Endzustand kennzeichnen diese Grenze.
Zwei Stationsbesuche sind protokolliert.
Die spätere BF09-Fahrt ist darin noch nicht enthalten; deren Ruckkorrektur
ist durch die separate vollständige Kurvenregression geprüft.

Der erneute Seed-Lauf auf `596d801` wurde kontrolliert unterbrochen, um
die Entwicklungsansicht mit begrenzter Funktionsprüfung bereitzustellen.
Alle 20 aufgezeichneten Trajektorien reichen gemeinsam bis 1188,1 s.
Originaldaten, Laufzeitquellen und Unterbrechung bleiben unverändert;
der Darstellungsadapter bindet seine eigenen Quellen separat. Er übernimmt
die vorhandenen PVA-Knoten, empfangenen Meldungen und Kamerareferenzen mit
ihren synthetischen Aufnahmeposen.
Der normale Rundgang und der strenge Vollprogramm-Builder bleiben erhalten.

Diese historische BF01-Seite verbindet die bewegten Fahrzeugmodelle mit den 20
physischen Bildschirmen der [Foyer-Kamerawand](foyer-camera-wall.md#flottenansichten-in-der-experimentellen-bf01-vorschau).
Die Startbelegung ordnet M01 bis M20 jeweils BF01 bis BF20 zu; die vorhandenen
Monitor- und Kamera-IDs werden wiederverwendet. Die Bilder entstehen aus den
gespeicherten Aufnahmeposen der bis dahin empfangenen Kamerareferenzen. Sie
sind historische synthetische Modellansichten, keine realen Videos. Ohne
empfangene Referenz bleibt ein Platzhalter. Aufnahmezeit, Empfangszeit und
Alter in der Wiedergabemodellzeit werden von der Zeit seit der letzten
Browserbildberechnung unterschieden. Die manuell bedienbare Normalansicht
bleibt ohne Flottenbindung und behält ihre bisherige Monitorbelegung.

Für den bisherigen Vorschau-Stand bestehen 385 BF01-Tests und ein separat
ausgeführter nativer Fall sowie alle 22 FreeCAD-Hüllentests. Die neue
Monitoranbindung ist zusätzlich begrenzt im Browser geprüft: 20 native
Bildschirmflächen mit zugeordneten Texturen, empfangene Aufnahmen derselben
Modellzeit, Fahrzeugbewegung, Pause, Rückwärtssuche, Quellenwechsel,
Fahrwegtürsperre und Aufzeichnungsende. Die Kamerapässe erzeugen weder
rekursive Monitorbilder noch WebGL-Texturfeedback.
Dies ist **kein vollständiger Flotten-, Zielabdeckungs-, nativer Bewegungs-
oder unabhängiger Exportnachweis**. Diese Nachweise bleiben offen; ein
Entwicklungsfehler in der Vorschau wird nicht als bestandener Lauf behandelt.
Die lokalen Originale und die Unterbrechungsquittung liegen unter
`exports/building-fleet/jerk-01c7cff/full-seed-r3/` beziehungsweise
`full-seed-r3-interruption-r1/` im selben Ausgabeordner.

Die 60 Körper der Foyer-Kamerawand sind bereits Bestandteil der geprüften
Welteingabe mit 5788 Körpern. Die Monitoranbindung ergänzt nur die Darstellung;
Gebäude, Kamera- und Fahrzeugmesh sowie die 216 Laufzeitpins des R3-Standes
werden unverändert wiederverwendet. Die getrennten Darstellungsquellen werden
neu gebunden. Historische Berichte bleiben bytegleich erhalten; ältere
Freiraum-, Boden- und Fahrtnachweise gelten weiterhin nur für ihren jeweiligen
Quellstand. Der vollständige Flottennachweis bleibt **unproven**.
Die Eismaschine im Labor 3.016 gehört ebenfalls zur Welteingabe. Die gemeinsame
Anzeige erzeugt keinen neuen Flotten- oder nativen Gesamtbewegungsnachweis.

Die separate L01-Verbindung wurde am früheren Gebäudestand geprüft. Mit der
Labormöblierung und den nach außen öffnenden Labortüren sind die Gebäude- und
Rundgangbindungen in beiden BF01-Quellen aktualisiert. Die daraus neu abgeleitete
L01-Verbindung benötigt neue Kurven-, Boden- und native Abstandsnachweise;
die folgenden Messwerte und Prüfberichte beschreiben ausschließlich den alten,
jeweils gepinnten Stand. Historische Berichte werden nicht umgepinnt.

Die anschließend vom Eigentümer angeforderte Schwellenkorrektur ergänzt
Kabinen- und Landeschwellen mit angenommenen 8 mm Trennspalt. Der frühere
breite bodenlose Streifen ist damit ein historischer Befund. Die neue native
Nachmessung am Startstand `84c61cb` bestätigt die 8-mm-Fuge an allen fünf
aktiven Ports. Die neue Stützregel und ihre Grenzen stehen im folgenden
Abschnitt; eine bestandene Portprüfung qualifiziert keinen vollständigen
Flottenlauf.

<a id="aktive-lokale-patrouille-und-transporterrekrutierung"></a>

## Aktive Patrouille und Transporterrekrutierung

`model/building-fleet-patrol.shared.json` ergänzt einen ausdrücklich gewählten
aktiven Testmodus. Die Browserfassung und der optionale lokale Python-Dienst
sind getrennte Laufzeitadapter für denselben Motor. Ihre 20 leeren
Fahrzeuge verwenden dieselben Modellquellen, Fahrgrenzen, anonymen Scans,
50-ms-Weiterfahr-/Bremsnachweise, Bodenprüfungen und Aufzugdienste.
Die bestehenden BF01-, TR01- und L01-Quellen werden nicht überschrieben.

Die Patrouille endet nicht nach der ersten Zielabdeckung. Erlaubte Ziele
werden pro Fahrzeug erst vergeben, nachdem dessen erste synthetische
Kameraaufnahme tatsächlich empfangen wurde. Andere Fahrzeuge müssen dafür
noch keine Aufnahme geliefert haben; der Gesamtstatus meldet weiterhin,
ob alle 20 Erstaufnahmen eingegangen sind. Die erste Wahrnehmungsmeldung
entsteht unmittelbar nach dem tatsächlichen Empfang des ersten verzögerten
Scans; danach bleibt der bestehende Meldetakt erhalten. Sensor- und
Funklatenzen, frische Scans und Weiterfahr-/Bremsnachweise bleiben verbindlich.
Das ältere Profil `first_received_camera_frames` behält seine gemeinsame
Startfreigabe nach allen 20 empfangenen Erstaufnahmen. Danach werden die Ziele
nach dem ältesten **empfangenen** Besuch ausgewählt; bei gleicher
Besuchszeit zählen ausstehende Aufträge und die bestehende Seed-Auswahl.
Geplante Ankünfte setzen das Besuchsalter nicht zurück. Das sind die 19
vorhandenen BF01-Ziele und ihre Verbindungswege, keine Behauptung einer
lückenlosen Sichtabdeckung aller Gebäudeflächen. K0_013, Treppenkern,
Bench-Schutzbereiche und andere ausgeschlossene Zugänge bleiben gesperrt.

Die beiden EG-Depots teilen sich eine Flurfreigabe. Die Räume R0_004
und R0_013 gehören zur selben exklusiven Ressource
`EG.resource.0e0d9d15541065e1`. Ein nachvollzogener Abschluss ihrer
199 Aliase umfasst zehn Verbindungen aus Raum- und Türnachbarschaft, 187
positive Überlappungen von Schutzflächen und eine weitere Verbindung über
überlappende Fortschrittsintervalle. Die beiden Depots sind bereits über
ihre Türen und die Schutzflächen der Flure miteinander verbunden.
Bei Seed 20261120 belegt BF06 diese Ressource auf seiner gesamten ersten
Route von 59,195 m. Der Endpunkt seiner ersten geprüften Geraden liegt
bereits bei 0,821 m. Im Live-Zustand lässt sich ablesen, welches Fahrzeug
die Ressource hält, welches anfragt und an welcher Stelle der Warteschlange
es steht. Die vollständigen Alias- und Geometriebezüge stehen im lokalen
Prüfbericht `exports/building-fleet/bf01-live-continuity/depot-closure.json`.

Im Live-Rundgang darf ein zweiter Transporter während dieser Fahrt seine
eigene Mission beginnen. Dafür muss seine erste Gerade einschließlich
Fahrzeughülle und Reserve im anderen Depot liegen. Der Abstand wird gegen
die gesamte Bahn des ersten Transporters einschließlich Rückweg und gegen
die zwischen den 50-ms-Schritten ausgewerteten Kurven geprüft. Beide
Fahrzeuge benötigen für jeden Schritt einen eigenen Scan, der auch den
anschließenden Bremsweg abdeckt. Potenziell verlassene Heimplätze bleiben
bei der Auswertung verzögerter Scans als feste Oberflächen ausgeschlossen.

Der zweite Transporter erhält den nächsten Flurzugang erst bei beobachteter
Ankunft des ersten an dessen Heimplatz oder gebuchter Wartebucht. Erreicht
er vorher das Ende seiner Geraden, bremst er dort bis zum Stillstand. Die
Fahrzeugansicht zeigt den Grund „Wartet im eigenen Depot auf die Flurfreigabe“.
Danach setzt er dieselbe Mission aus seinem tatsächlichen Bewegungszustand
fort. Nach einer vorgezogenen Vergabe kommt wieder das erste Fahrzeug der
regulären Warteschlange zum Zug.

„Transport anfordern“ erzeugt einen priorisierten **leeren Testauftrag** aus
Testabholung und Testabgabe an zwei vorhandenen Raumzielen. Geeignete
Fahrzeuge geben eigene skalare Ankunftszeitschätzungen ab. Die Auswahl
verwendet die vorhandene Routenlänge, Quellgrenzen und aggregierte
Aufzugzeiten statt des direkten räumlichen Abstands. Die Schätzung ist
keine Ankunftszusage. Fahrzeuge kennen weiterhin keine fremden Positionen.

Ein Fahrzeug wird nur an einer beobachteten stationären eigenen Grenze
rekrutiert: ohne laufende Fahrt, Kabinenbelegung, unbestätigten Auftrag oder
offene fremdgeschossige Buchung. Bereits verpflichtete Fahrten werden zu Ende
geführt; bei fehlendem Kandidaten bleibt der Testauftrag sichtbar vorgemerkt.
Ein ausstehender Testauftrag verhindert neue nachrangige Patrouillenzusagen,
bis ein Kandidat verfügbar wird. Auftragskennung und Fahrzeugzuordnung
bleiben erhalten; ein wiederholter Request erzeugt keinen zweiten Auftrag.
Bereits empfangene, noch nicht gestartete lokale Patrouillen werden mit ihrer
ursprünglichen Kennung und Quittung zurückgestellt. Nach dem Testauftrag
werden sie fortgesetzt. Liegt die Testabgabe auf einem anderen Geschoss,
führt zuerst eine neue regulär gebuchte Rückkehrinspektion zum ursprünglichen
Geschoss; die alte lokale Zusage wird nicht in einen fremdgeschossigen
Auftrag umgedeutet.
Geschosswechsel benötigen unverändert ihre eigenen atomaren Buchtenzusagen.
Erst empfangene Missionsquittungen und Besuchsabschlüsse führen die beiden
Teststufen weiter; danach wird das Fahrzeug wieder für Patrouillen verfügbar.
Die Ankunft ist eine Durchfahrtbeobachtung, kein Halt zum Be- oder Entladen.

Die aktiven Atriumbilder verwenden die tatsächlich empfangenen Kameraposen
mit der damaligen gemeinsamen Fahrzeug- und Aufzugstellung. Ein
Verbindungsfehler lässt die zuletzt ausgeführten Stellungen stehen. Der
Browser extrapoliert keine ungeprüfte Fahrt. Eine geschlossene Fahrwegtür
fordert eine Pause des ganzen Sitzungsmotors an; ein manuell gesetzter
Pausenzustand bleibt beim Wiederöffnen erhalten. Diese Browserbedienung ist
keine qualifizierte Schutzfunktion. Modellzeit und tatsächliche Laufzeit
bleiben getrennt; rechenintensive Prüfungen können langsamer als Echtzeit sein.

Ein lokaler Einstieg mit bereits erzeugten, quellgebundenen Artefakten ist:

```bash
python3 scripts/run_building_fleet_patrol.py \
  --walkthrough-export exports/building-fleet/jerk-01c7cff/walkthrough-r1 \
  --camera-report exports/generated/tr01-awareness-ccd729bbb881-r2/build-report.json \
  --vehicle-mesh exports/building-fleet/support-680652f/native-vehicle-mesh.json \
  --navigation-cache exports/building-fleet/jerk-01c7cff/navigation-r1 \
  --resource-cache exports/building-fleet/jerk-01c7cff/resource-catalog-r2 \
  --output-dir exports/building-fleet/patrol-local-new
```

Der Dienst bindet ausschließlich `127.0.0.1` und meldet seine lokale URL.
Ausgabeverzeichnisse müssen neu sein. Vorhandene Caches werden nur bei
unveränderten Quellen verwendet; sie sind keine neuen Bewegungsnachweise.
Ein optionaler `--graph-cache-report` beschleunigt den erneuten Start anhand
eines separat quellgebundenen statischen Vorbereitungsberichts. Alte Berichte
werden nicht umgepinnt. Der Aufbaubericht, die empfangenen Request-Kennungen
und die eigenen Controllerbelege bleiben im ignorierten Ausgabeordner.
Mit `--initial-request <Datei.json>` lässt sich ein ausdrücklich benannter
leerer Testauftrag vor Beginn der Patrouille über denselben Eingang vormerken.
Die Datei wird dabei als Laufzeiteingabe gebunden. Eine Abfahrt vom eigenen
Heimplatz bereitet ihre Kurve erst nach Zusage des schon vorhandenen
Depot-Durchgangstokens vor; wartende Fahrzeuge benötigen diese teure
Vorbereitung noch nicht. Die Tokenreihenfolge wird nicht umgeschrieben.

Für diese Ergänzung bestehen 36 gezielte Python-Tests und die gemeinsamen
JavaScript-Grenz-/Darstellungsprüfungen. Eine getrennte Browserprüfung mit
kontrollierten Aufzeichnungen prüft unter anderem das originale PVA,
Request-Wiederholung, Türpause und Verbindungsausfall. Der kurze tatsächliche
lokale Lauf `patrol-5f4da9d/live-r5` beobachtete BF04-Bewegung von Modellzeit
0,9 bis 1,9 s, 20 empfangene Kameraansichten und die Rekrutierung von BF03
aus 20 eigenen Ankunftszeitangeboten. Die Testabholung wurde quittiert;
eine abgeschlossene Testabgabe wird damit nicht behauptet. Die zusätzliche
echte Browserbeobachtung desselben Dienstes bestätigt 20 native Fahrzeuge,
20 physische Bildschirmtexturen und Bewegung ohne WebGL-Fehler. Die getrennten
Berichte heißen `short-real-run-check.json` und
`active-patrol-browser-observation.json` im genannten lokalen Ausgabeordner.

Dieser Entwicklungsmodus führt keine Last, Probe, Armübergabe, Materialbilanz
oder biologische Prozessbindung aus. Die Kameraansichten entstehen lokal;
ein Video-Netzwerklasttest und dessen Durchsatzmessung sind nicht implementiert.
Der HTTP-Eingang begrenzt die Sitzung auf 100 unterschiedliche Testaufträge.
Der Motor stoppt mit sichtbarem Fehler beim Erreichen der getrennten Speichergrenzen
von 1000 Aufträgen, 100000 empfangenen Meldungen oder 1000000 aufbewahrten
PVA-Punkten; Controllerbelege werden nicht zur
Fortsetzung gelöscht. Diese Grenzen sind Implementierungsgrenzen des Tests,
keine Fahrzeug- oder Netzwerkgrenzen. Ein vollständiger aktiver Flottenlauf,
alle Zielbesuche, neue native Gesamtbewegungen, unabhängiger Gesamtexport und
reale Sicherheit bleiben unbestätigt. Die offenen E4-Entscheidungen bleiben
unverändert.

## Eigentümerregel für Bodenstützung und Aufzug

`support_rule` in der BF01-Quelle führt die Entscheidung vom **20. November
2026** mit Einheiten, Wertebereichen und ihrer Grundlage. Die Gebäudequelle
und die gepinnte TR01-Konstruktion werden dafür nicht geändert;
`floor_threshold_height_mm` bleibt `null`. Die 15-mm-Grenze und der aus der
Aufzugquelle abgeleitete derzeitige +3-mm-Versatz sind **synthetische
Eigentümerannahmen ohne Rad-/Fahrwerksqualifikation**.

- **R1:** Die gesamte aufgeweitete orientierte Fahrzeughülle muss durch die
  native Bodenflächen-Union nach konservativer morphologischer Kreisschließung
  gestützt sein. Der Radius ist die halbe Spaltgrenze (15 mm / 2). Die Regel
  gilt überall in BF01; sie erlaubt keinen Überhang an offenen Kanten.
- **R2:** Nur `LiftCabinFloorFinish`, `LiftCabinSill_<side>` und
  `LiftLandingSill_<level>_<side>` dürfen am Aufzug den aus den tatsächlichen
  Quellflächen abgeleiteten Höhenversatz haben. Andere erhöhte Körper zählen
  nicht als Boden. Eine geänderte Quellhöhe verlangt einen neuen Nachweis.
- **R3:** Portquerungen benötigen über ihr vollständiges Prüfintervall die
  tatsächliche Kabinen-FK am betreffenden Geschoss und vollständig offene
  aktive Türen. Ein schon geparktes Fahrzeug wird starr an die absolute
  Kabinenhöhe gebunden; seine Unterstützung durch den echten Kabinenfinish
  ist ein eigener Invariantennachweis und erlaubt keine Portquerung.

Der gemeinsame Standardbibliothekskern verwendet exakte rationale
Weltkoordinaten und eine Flächenprüfung ohne Akzeptanztoleranz. Eine innen
liegende Polygonscheibe beim Dilatieren und eine außen liegende beim Erodieren
liefern ausschließlich eine Teilmenge der exakten Kreisschließung. Die
Prüfungen bestehen bei 8 und 15,0 mm Spalt und scheitern bei 15,5 mm, beim
historischen 297-mm-Spalt sowie bei Überhang an offenen Kanten. Auch kleinste
positive Flächenfehler werden nicht über eine Flächentoleranz gelöscht.

Jede tatsächlich benötigte Flächenzugabe wird mit Weltkoordinaten, Breite,
angrenzenden Quellkörpern und betroffenen Kurven im jeweiligen neuen
Prüfbericht geführt. Raster und Suchnachbarn sind nur Routenvorschläge;
akzeptierte Verbindungen, Sichtlinienverkürzungen, vollständige Rechtecke und
exportierte C2-Kurven erhalten die kanonische Bodenprüfung. Eine reduzierte
Suchhülle ist keine Freigabehülle. Bench-Zonen und Treppenkern bleiben gesperrt.

### Unabhängige Nachmessung der fünf aktiven Ports

Die native BRep-Prüfung versetzt die vorhandene Kabine per Quell-FK an jedes
Geschoss und untersucht die vollständige Türbreite, die Bodenflächen und den
Anschluss unter der Wand. Die nachstehenden Koordinaten sind abgeleitete
Darstellungs-mm, kein Aufmaß. Die gemeinsame Y-Spanne der Türöffnung beträgt
15608,108108 bis 16529,729730 mm.

| Aktiver Port | X der ungestützten Fuge | Breite | Quellhöhenversatz |
|---|---|---|---|
| KG innen | 12605,702703–12613,702703 | 8,0 mm | +3,0 mm |
| EG innen | 12605,702703–12613,702703 | 8,0 mm | +3,0 mm |
| OG1 außen | 10099,810811–10107,810811 | 8,0 mm | +3,0 mm |
| OG2 außen | 10099,810811–10107,810811 | 8,0 mm | +3,0 mm |
| OG3 außen | 10099,810811–10107,810811 | 8,0 mm | +3,0 mm |

Es wurde kein zusätzlicher breiter dunkler Schlitz gefunden. Die lange graue
Schwelle zwischen Kabinen- und Schachttür ist reale Modellgeometrie; die
Landeschwelle überlappt den Flurboden unter der Wand. Die Messung betrachtet
13 zulässige Stützkörper aus 4616 Gebäudekörpern; sie behauptet keinen
vollständigen Kollisionsnachweis der gebundenen Welt mit insgesamt 5299
Körpern. Der neue lokale Messbericht ist
`exports/building-fleet/support-84c61cb/lift-native-surfaces-r4.json`.
Historische Berichte bleiben unverändert; neue Revisionsnachweise erhalten
eigene Dateien und aktuelle Quellen-/Artefaktpins.

Alle 15 Portkurven (fünf Ports, jeweils Einfahrt und beide
Ausfahrrichtungen) bestanden am jeweils gepinnten Zwischenstand die
kontinuierliche kanonische Stützungs- und Meshprüfung sowie die unabhängige
native Intervallprüfung. Die konservativen
Abstandsuntergrenzen betragen mindestens 87,85855 mm bzw. 86,816 mm bei
geforderten 85 mm. Die native Prüfung verwendet die vollständige gebundene
Welt mit 5299 Körpern und eine geprüfte geschlossene native Hülle aller 34
physischen Fahrzeug-/Kamerakörper; reicht deren konservative Untergrenze
nicht, bleibt die exakte Prüfung der Einzelkörper erforderlich. Der
nichtphysische Sichtkegel zählt nicht zur Fahrzeughülle.

Die lokalen Berichte heißen `lift-c2-support-r4.json` und
`lift-native-curves-r3.json` im selben Ausgabeordner. Sie binden die
tatsächlich exportierten PVA-Kurven, Quell-FK und Artefakte. Sie belegen
Portquerungen, keine ausgeführten Kabinenparkmanöver oder vollständigen
Flottenbegegnungen. Nach einer weiteren BF01-internen Optimierung der reinen
Positionsauswertung ist ihr Modul-Pin historisch; trotz separat geprüfter
bytegleicher Positionen sind frische Kurvennachweise für den endgültigen
Quellstand weiterhin erforderlich. Die unabhängige Flächenmessung und die
Negativkontrollen für falsches Geschoss und geschlossene Türen bleiben
quellaktuell. `lift_operation_implemented` bleibt `false`.

## Bestätigte Rückstellung von K0_013

Der Eigentümer hat am **20. November 2026** `KG / K0_013` für E2 ausdrücklich
zurückgestellt. Der bisherige Plan erschließt diesen Raum nur über `DK013`
an `KW061` aus `R3_028`. Der Treppenkern bleibt vollständig ausgeschlossen;
diese Entscheidung erlaubt weder seine Durchfahrt noch einen neuen Durchgang.
K0_013 zählt nicht zur Sollabdeckung dieses BF01-Laufs. Die Rückstellung wird
in `missions.deferred_targets` der separaten Flottenquelle geführt und ist
keine Änderung des Gebäude- oder Kellerplans.

Alle anderen Ziele bleiben verpflichtend:

| Auswahl | Geschoss | Ziele | Grundlage |
|---|---|---|---|
| E1 | EG | R0_001, R0_002, R0_003, R0_015, R0_014A | Planbeschriftung |
| E1 | OG3 | R3_001, R3_003, R3_007 | Eigentümerbeschreibung |
| E1 | OG1, OG2 | jeweils R3_001, R3_003, R3_007 | Vorlageflächen, Nutzung unbestätigt |
| E2 | KG | K0_002, K0_006, K0_009, K0_012, K0_011 | Planbeschriftung |

Die Vorlageflächen in OG1 und OG2 werden nicht als bestätigte Labore bezeichnet.
Die Heimplätze sind ausschließlich in `EG / R0_004` und `EG / R0_013` vorgesehen.
Treppenbereiche `R3_028`, `R3_017`, `ExternalStairGround`, Atrium und Schacht
bleiben gesperrt; der Schacht wird ausschließlich über den Aufzugablauf genutzt.

## Arbeitsstand und Nachweisgrenzen

### Ruckkorrektur auf dem Stand `01c7cff`

Die konkrete nächste BF04-Kurve des früheren Abbruchs bei 616 s wurde aus
den damaligen Quellen rekonstruiert. Ihr vollständiger 36-Punkte-Vorschlag
reproduziert die Ruckobergrenze von 1433,6473387483768 mm/s³.
Zwei Ereignisse einer konstanten Fahrt liegen dabei nur 0,389 ms auseinander;
die frühere Rundung passte ein einziges Exportpolynom über beide Ruckwechsel.

Der Compiler fasst jetzt ausschließlich belegte konstante Fahrabschnitte
mit zusammen weniger als 1 ms zu einem C2-Transitknoten zusammen.
Geschwindigkeit, Beschleunigung und Weg-/Zeitbeziehung werden dafür geprüft.
Beim Übertragen der Ereignisse auf das Millisekundenraster wird ihre eigene
PVA mitgeführt. Der danach neu gefittete skalare Clock ist dieselbe Quelle
für räumliche FK-Ausgabe und Fahrzeugregler. Funktionale Endorte und
Ruhezustände bleiben erhalten. Der vollständige skalare und räumliche
Verlauf wird einschließlich der tatsächlichen 50-ms-Reglerknoten und der
benachbarten Grenzereignisse auf PVA-, Zonen-, Monotonie- und Kein-Halt-
Verletzungen geprüft; notwendige Nachskalierung bleibt örtlich begrenzt.

Runner und Regler verwenden außerdem denselben bereits vorhandenen,
an der quantisierten Bremsfamilie geprüften Wahrnehmungscap. Es wurden
keine Quellgrenzen angehoben. Die konkrete Regression dauert nun
418,824 s bei einer räumlichen Ruckobergrenze von 995,227948 mm/s³
und einer skalaren von 995,227185 mm/s³. Der echte Regler übernimmt
die Kurve mit Dilatationsfaktor 1 und unverändertem Endhalt. Die
Quantisierung ergänzt bei dieser Kurve 0,828 ms zum qualifizierten
Vorschlag; eine allgemeine Obergrenze von 1 ms wird nicht behauptet.
Globale Zeitoptimalität und ein gemessener menschlicher Vergleich bleiben offen.
16 Bewegungstests und der unabhängige mathematische Review bestehen.
Der reproduzierbare Teilbericht steht unter
`exports/building-fleet/jerk-01c7cff/diagnosis-final-r2/report.json`.

Die aktuelle physische Welt wurde mit 5788 Körpern und 163 physischen
Quellenpins frisch abgeleitet. Navigation und Routenkatalog stammen
aus diesem Stand. Der unveränderte Nav-R1-Cache bleibt die Eingabe
für Katalog und anschließenden Vollversuch. Alle 22 nativen Hüllentests
bestehen. Der normale Browserrundgang, seine Büro–Labor–Aufzug-Route
und das gehende Ein-/Aussteigen an allen fünf Geschossen sind geprüft.
Der Fünf-Geschoss-Gehversuch schließt vorher ausdrücklich die große
Kellertür `KG.DK015.Door`, deren offenes Blatt in die Kabine reicht;
er belegt diese Testaufstellung. Die Büro–Labor–EG-Route benötigt
diese Keller-Vorbereitung nicht.
Der Aufzug-Gehprüfer pausiert seinen kontrollierten Testtakt jetzt
ausdrücklich, damit zwischen Browserabfragen keine unbeabsichtigte
zusätzliche Modellzeit verstreicht; die Produktionskollision bleibt
unverändert. Der erste entsprechende Fehlbericht bleibt erhalten.

Der neue Katalog umfasst 3314 Routen, 2895 Splice-Reparaturen und
35 Ressourcen; seine Ableitung benötigte 816,916 s. Alle 38 erfassten
Eingabepins und die Nav-R1-Bytes blieben unverändert. Ein älterer
Controller-Regressionsfall wird am kurzen Restweg statt an seiner
früheren absoluten Fahrzeit positioniert; alle 24 Controllertests bestehen.

Die gesamte BF01-Suite besteht mit 383 von 384 Tests in 503,177 s;
die optionale native Prüfung ist in den 22 separat ausgeführten
FreeCAD-Hüllentests enthalten. Der erneute Vollversuch mit Seed `20261120`
wird mit denselben eingefrorenen Quellen geprüft. Dieser Stand ist noch kein
vollständiger Flotten-, Native-, Export- oder Browsernachweis. Für die
angeforderte Veröffentlichung ist eine separate Opt-in-Seite `bf01/`
mit Rücklink zum normalen Rundgang vorbereitet. Der normale Rundgang
aktiviert weiterhin keine Flotte. Der Präsentationsadapter pinnt auch
das seit dem aktuellen Master konsumierte Seminar-Projektionsskript.

#### Vollversuch nach der BF04-Korrektur

Der auf `8492e32` eingefrorene Versuch
`exports/building-fleet/jerk-01c7cff/full-seed-r1/` verwendet Seed
`20261120` und unveränderte Grenzwerte. Alle 20 ersten nominalen
Fahrkurven wurden akzeptiert. Die zuvor fehlerhafte nächste BF04-Kurve
startete bei 563,55 s; auch die anschließende BF06-Kurve startete.

Bei 1466,35 s wurde die nächste BF09-Kurve vor Registrierung und
Ausführung verworfen. Nach acht lokalen Nachskalierungen beträgt ihre
skalare Ruckobergrenze 1103,6884113872482 mm/s³ und die räumliche
1103,6884112289151 mm/s³, jeweils bei erlaubten 1000 mm/s³.
Beide Kein-Halt-Prüfungen bestehen. Die eigenständige Rekonstruktion
aus dem tatsächlichen BF09-Endhalt, Mission 23 und den unveränderten
Quellen ergibt die protokollierten 48 Punkte, 58842,170925576516 mm
und 110,85445803957835° größten Richtungswechsel.

Der Versuch endete regulär nach 9000,767 s CLI-Zeit, davon 8877,876 s
Laufzeitphase. Drei Pflichtziele sind besucht; die endgültige Heimkehr
ist noch nicht erreicht. Der geschlossene `/2`-Trace enthält 293280
Scans, 586445 Entscheidungen, 55534 Stoppkurven und 22 eigene Pfade.
Eine getrennte Prüfung bestätigt Gzip-CRC, Abschluss und Originalzähler;
sie ist keine vollständige Entscheidungsnachprüfung. Alle 218 beim
Fehlerabgleich erfassten Pins und die Fehlerartefakte sind unverändert.
Die lokalen Berichte liegen unter `bf09-full-seed-r1-capture-r1/` und
`bf09-full-seed-r1-analysis-r1/` im selben Ausgabeordner. Dieser Versuch
liefert keinen vollständigen Native-, Export- oder Browsernachweis.

#### Örtliche Nachkorrektur der BF09-Kurve

Der unveränderte Compiler reproduziert beide BF09-Ruckwerte bitgleich.
Im betroffenen geraden Stück senkte die bisherige Nachkorrektur nur
die Geschwindigkeitskappe. Die Übergänge wurden weiterhin mit den vollen
Planungsgrenzen von 490 mm/s² und 980 mm/s³ erzeugt, auch nach acht
Nachkorrekturen. Ihre Ruckspitze blieb dadurch erhalten.

Ein örtlicher Faktor `f` begrenzt jetzt die Geschwindigkeit mit `f`,
die geplante Rampenbeschleunigung mit `f²` und den Rampenruck mit `f³`.
Dies gilt sowohl für die Machbarkeitsprüfung kurzer Geraden als auch
für ihre tatsächlichen Beschleunigungs- und Bremsrampen. Die endgültige
Millisekundenkurve wird weiterhin vollständig geprüft; weder die
deklarierten Grenzwerte noch die acht erlaubten Nachkorrekturen ändern sich.
Die Metadaten benennen die örtlichen Planungsgrenzen. Eine exakte
nachträgliche Zeitumparametrisierung wird damit nicht behauptet.

Die konkrete BF09-Regression besteht mit 607,898 s Dauer, einer skalaren
Ruckobergrenze von 987,239892713 mm/s³ und einer räumlichen von
987,239894654 mm/s³. Ihre Spitzengeschwindigkeit bleibt bei
511,235286 mm/s; der echte Fahrzeugregler benötigt keine zusätzliche
Zeitstreckung. Alle 18 Bewegungstests einschließlich BF04 und BF09
bestehen. Der vollständige Seed-Lauf bleibt separat erforderlich.

### Folgeschrittnachweis auf dem Stand `f1eb858`

Die Weiterfahrfreigabe bindet den nächsten Integrationsschritt von höchstens
50 ms an eine vollständige Rückfallkurve: tatsächlicher eigener Präfix plus
exakt anschließender Stopp. Die gesamte quantisierte Kurve muss die
PVA-, Zonen- und Kein-Halt-Grenzen erfüllen; der Übergang bleibt C2.
Eigenfortschritt, zusätzliche Annäherungszeit und die höchste relevante
Quell-Zonenkappe gehen in dieselbe vollständige Beobachtungsbilanz ein.
Der bisherige verzögerte Scan wird auch am Schrittende mit seinem wirklichen
Alter ausgewertet. Eine zukünftige freie Beobachtung wird nicht angenommen.

Eine neue Kurve ersetzt den gespeicherten Rückfall erst nach erfolgreicher
Prüfung. Fehlt die Reserve oder wird der Scan zu alt, wird dessen bereits
geprüfter Suffix ausgeführt. Dies gilt auch für Schutzbremsungen; eine neue
Anfahrt benötigt erst ihren konkreten Präfixnachweis und die bestehende
Frisch-frei-Bedingung. Ein früher funktionaler Endhalt bleibt über den Rest
des Integrationsschritts konstant. `advance` führt ausschließlich den
zertifizierten Präfix einschließlich seiner inneren Knoten aus.

Der neue Rohdatenvertrag
`solidcraftbot.building-fleet-own-input-evidence/2` ergänzt `step_end_s`
und `continuation_stop_clock`. Letzteres referenziert die unveränderte
Clockbank für die gesamte Präfix-/Stoppkurve. Die unabhängige Exportprüfung
bindet alle Präfixintervalle an die tatsächlich exportierte PVA und prüft
Bilanz, Scan-Alter, gespeicherten Rückfall und Wiederanlauf erneut. Alte
`/1`-Traces bleiben historische Belege; sie qualifizieren diesen Vertrag nicht.

Nach dem Rebase auf `master` `f1eb858` wird ausschließlich der separate
physische `world-build-report.json` verwendet. Die aktuelle Welt mit
5519 Körpern wurde mit 155 unveränderten physischen Pins frisch gebunden;
native Mesh-/CAD-Daten wurden nur nach exaktem Bytevergleich wiederverwendet.
Navigation und Routenkatalog werden daraus neu abgeleitet. Browser-Overlay
und dessen Kameraeinträge gehören nicht zu den physikalischen Eingaben.
Die aktive Kamera-Overlay-Komposition bindet das aktualisierte BF-Profil
mit dessen aktuellem Quellenhash; dieser reine Kompositionspin verändert
keine physische Geometrie oder historischen Nachweise.
Der alte Seed-Lauf und seine folgenden Befunde bleiben ihren ursprünglichen
Quellen und Berichten zugeordnet. Ein vollständig bestandener Lauf steht
weiterhin aus; der neue Vollversuch ist nachstehend dokumentiert.

Die aktuelle BF01-Suite besteht mit 376 von 377 Tests in 342,360 s; eine
optionale native Prüfung läuft separat. Alle 22 Hüllenregressionen bestehen
mit installiertem FreeCAD. Die zehn neuen Controllerfälle enthalten den
portablen historischen BF04-Zustand; beide bisherigen stoppfreien Corner-/S-
Regressionen behalten ihre Erwartungen. Vierzehn unabhängige
Folgeschrittprüfungen und echte kurze `/2`-Rohtraces decken zusätzlich
Schutzbremsung, gespeicherten Rückfall und frischen Wiederanlauf ab. Dies
ersetzt den vollständigen Seed-, Native- und Browsernachweis nicht.

#### Vollversuch mit Seed `20261120`

Der auf Implementierungscommit `1a5238a` eingefrorene dritte Versuch
`exports/building-fleet/guard-f1eb858/full-seed-r3/` verwendet weiterhin
20 Fahrzeuge, 19 Pflichtziele, unveränderte Bewegungsgrenzen und
Wiedergabefaktor 1. Alle 20 ersten nominalen Fahrkurven wurden geprüft.
Der tatsächliche gemeinsame Lauf passierte die frühere BF04-Fehlerstelle
bei 75,2 s und protokollierte bei 420 s den ersten Zielbesuch.

Bei 616,0 s Modellzeit wurde die nächste BF04-Kurve noch während ihrer
Erzeugung verworfen: Nach der Zeitquantisierung beträgt die obere
Ruckgrenze 1433,6473387483768 mm/s³ bei erlaubten 1000 mm/s³.
Die Kein-Halt-Prüfung besteht; acht lokale Nachskalierungen beseitigten
die Rucküberschreitung nicht. Die verworfene Kurve wurde nicht gefahren.
Dieser neue Befund betrifft die Erzeugung der nächsten Fahrkurve,
nicht die zuvor fehlende Reserve für den nächsten Integrationsschritt.
Der Motioncompiler und seine Grenzen wurden in diesem Auftrag nicht
zusätzlich verändert.

Der CLI-Versuch endete nach 4222,601 s (70,377 min); damit ist auch
das 600-s-Rechenzeitziel verfehlt. Der geschlossene `/2`-Rohtrace enthält
123200 Scans, 246314 Entscheidungen, 23801 Stoppkurven und 20 eigene
Pfade. `runtime-failure.json`, `compile-failure.json` und
`partial-program.json` erhalten den unvollständigen Stand: ein Zielbesuch,
kein Fahrzeug am endgültigen Heimplatz. Der separate Analysebericht
`exports/building-fleet/guard-f1eb858/full-seed-r3-analysis/report.json`
bindet Fehler, Teilprogramm, Rohdaten und die noch vorhandenen Eingaben.
Ein vollständiges Programm wurde nicht erzeugt; dessen native Prüfung,
unabhängiger Gesamtexportnachweis und Browserlauf wurden nicht gestartet.

Der vorherige zweite Versuch wurde durch eine Turn-Unterbrechung beendet;
er ist kein bestandener Lauf und kein beobachteter Simulationsfehler.
Die separat gesicherten vollständigen BF04-Rohdatensätze von 74 bis 76 s
zeigen eine Schutzbremsung ab 75,05 s. Bei 75,20 s bleibt für die gesamte
Restbremskurve aus der konservativ fortgeschriebenen ursprünglichen
Beobachtung eine nachgerechnete Reserve von 17,101 mm. Die 41 Präfixe
passen zur jeweils nächsten aufgezeichneten PVA. Die Berichte unter
`full-seed-r2-interruption/` und `full-seed-r2-bf04-prefix/` desselben
Exportverzeichnisses unterscheiden diese Teilprüfung ausdrücklich vom
fehlenden tatsächlichen Gesamtexport und nativen Abstandsnachweis.

### Stand `680652f`: Missionszulassung und Katalogberechnung

Der Folgeauftrag setzt die Arbeit auf dem geprüften `master`-Stand `680652f`
fort. Der private Branch wurde darauf rebasiert; der ursprüngliche Seed
`20261120`, die 19 Pflichtziele, die Bench-Sperren und der Ausschluss des
Treppenkerns bleiben erhalten. Die nachstehende frühere Laufzeitunterbrechung
und ihre Berichte bleiben als historische Befunde bestehen.

Die Missionszulassung sichert Start- und Zielbucht **vor** Ausgabe eines
geschossübergreifenden Auftrags und bindet die Zusage an dessen unveränderliche
Missionskennung. Nach bestätigtem Kabinenparken darf höchstens ein weiterer
Geschosswechsel die bereits zugesagte Ankunftsbucht als künftigen Start
vormerken; diese Vormerkung wird
erst nach beobachteter vollständiger Ausfahrt aktiv. Sie erlaubt vorher weder
das Betreten ihrer Zielbucht noch einen weiteren Aufzugruf. Notwendiges
Kapazitätswarten erfolgt an einer eigenen Bucht oder am eigenen Heimplatz;
ein vorläufiger Heimplatz ist kein abgeschlossener Heimkehrauftrag. Ein
Durchgangstoken darf an einer exakt beobachteten eigenen Parkposition nur
freigegeben werden, wenn die exklusive Buchtenzusage bestehen bleibt und alle
anderen Bahnen deren vollständige Fahrzeughülle ausschließen.

Eine unabhängige Prüfung verbindet die ursprünglich ausgegebenen Aufträge,
den mit demselben Seed wiederholten Abwärtskanal, die tatsächlich empfangenen
eigenen Quittungen, die Aufzugbeobachtungen und die Abschlussbelege anhand
derselben Missionskennung. Sie übernimmt keine Planer-Abschlussflags.
Der Dienstregressionstest des früheren Neun-Buchten-Zyklus kann nach zehn
zulässigen, missionsgebundenen synthetischen Buchungszyklen weiterhin neue
Arbeit vergeben. Dieser Test simuliert Boarding und Ankunft ohne Fahrgeometrie.
Dies ist noch kein Nachweis des vollständigen Flottenprogramms.

Der Katalog verwendet konservative räumliche Vorauswahl und begrenzte Caches
für unveränderte exakte Distanzabfragen. Die vollständigen Raumdurchfahrten,
Rohressourcen und Fortschrittsintervalle bleiben erhalten. Am eingefrorenen
Vergleichsstand benötigte der Katalog für alle **3128 vollständigen Routen
235,881 s**. Die Summe separat gemessener Navigation, Routengraph- und
Katalogphasen betrug **331,284 s**; sie belegt keine durchgehende
Vorbereitung in dieser Zeit. Ein direkter Vergleich derselben 64 Routen benötigte vorher
6,140 s und danach 2,557 s (2,40-fach), bei exakt gleichen Katalogausgaben und
Abfragen in beiden Fahrtrichtungen. Der vollständige frühere Zeitwert unten
ist dagegen kein isolierter Katalogvergleich. Die neuen Messungen stehen in
`exports/building-fleet/support-680652f/catalog-performance-r1/`.
Die endgültigen Aufzugvarianten benötigen einen eigenen aktuellen Katalog
und neue Bewegungsnachweise; alte Caches werden nicht umgepinnt.
Der zweite integrierte Versuch benötigte bis zu seinem Geometrieabbruch
1095,628 s, davon 262,597 s für den Weltlauf einschließlich dessen
Initialisierung; die Differenz von 833,032 s entfällt auf die vorgelagerte
integrierte Vorbereitung. Diese Laufzeit ist vom isolierten Katalogvergleich
zu unterscheiden und überschreitet bereits das Zehn-Minuten-Ziel.

`building_fleet_port_paths.py` leitet die Einfahrt, Ausfahrt und Abfahrt aus
der eigenen Bucht aus Quellöffnung, tatsächlichen vollständig offenen
Türblättern, Fahrzeughülle und zugeteilter Kabinenspur ab. Die festen
Varianten werden vor dem Schließen des Katalogs registriert. Nur die engen
Port-Ecken erhalten kleinere Eckkappen; anschließende normale Flur- und
L01-Ecken behalten ihre ursprüngliche Geometrie. Eckkappen, Ereignisfortschritt,
Zonen und die tatsächlich ausgeführte PVA werden gemeinsam exportiert und
unabhängig rekonstruiert. Die Bremsauswahl prüft für jede Kandidatenfamilie
dieselbe vollständige Sicht-, Reaktions- und Annäherungsbilanz. Ein kürzerer
zulässiger Bremsverlauf ersetzt einen konservativ zu langen Kandidaten;
die Grenzen und das nominale Fahrprofil werden dafür nicht angehoben.

Der erste integrierte Versuch wurde bei 0,15 s Modellzeit geordnet
unterbrochen. Eine gleichzeitig geprüfte OG3-Buchtenabfahrt hatte zum anderen
geparkten Fahrzeug nur 38 mm nativen Abstand statt der erforderlichen 85 mm.
Die neue lokale Umfahrung erhält den öffentlichen Flurknoten und seine
Anfahrtangente. Sie wird aus den vollständigen anderen Buchtenflächen und der
vorhandenen Sensorreserve abgeleitet; neue Flurparkplätze und kleinere
Sicherheitsbereiche werden nicht eingeführt. Der fehlgeschlagene Lauf bleibt
unter `support-680652f/full-seed-r1/` ausdrücklich unvollständig erhalten.

Ein weiterer belegter Scan-Fehlalarm wird durch einen einseitigen Nachweis
gegen die gesamte eigene aufgeweitete Rechteckbahn ausgeschlossen. Gerade
Teilstücke verwenden ihren vollständigen Rechtecksweep, Kurven konservative
Intervallhüllen aus Translation und Rotation. Die Sensorreserve bleibt gleich;
Kontakte, Grenzfälle und unaufgelöste Intervalle behalten den ursprünglichen
Alarm. Weder fremde Fahrzeugkennungen noch deren Positionen oder Zusagen gehen
in diese Prüfung ein. Ein kurzer eigener Goalclock-Rest darf zuletzt als
Stoppkandidat dienen, wenn seine tatsächliche PVA und sein vollständiges
Beobachtungsbudget erneut bestehen. Die neuen tatsächlichen Controllerläufe
erreichen beide OG3-Buchtenausgänge und die nötige EG-Umfahrung ohne
Schutzstopp; ihre Grenzen, ihre Frisch-frei-Bedingung und das
Reichweitenbudget bestehen in diesen Peer-Scan-Fixtures ohne echte
Türreturns. Die zusätzliche Prüfung geschlossener Türen und der
Gesamtlauf benötigen eigene Belege.

Am Zwischenstand vor der zusätzlichen Prüfung geschlossener Türen bestanden
alle zehn korrigierten Buchtenabfahrten ihre eigene
kanonische und native Prüfung mit unveränderter 85-mm-Reserve. Die unteren
Grenzen betragen 85,2260 mm zur vollständigen nativen Welt und 88,2894 mm zu
den anderen realen Fahrzeugkörpern. Der neue Bericht ist
`support-680652f/port-helper-final-r2/native-departures-r1.json`. Ein exakt
gleicher Einzelkandidat wird mit nachgewiesener binary64-PVA-/FK-/Fixture-
Gleichheit und aktuellem vollständigem Physik-Byteaudit referenziert; neun
Fälle wurden frisch geprüft. Alte Zertifikate behalten ihre Bytes und Pins.
Alle 20 neu abgeleiteten Boarding-Geometrien und PVA sind binär gleich zur
erhaltenen Vorphase. Diese separaten Portprofile verwenden eine deklarierte
300-mm/s-Zonenobergrenze; die tatsächlichen zusammengesetzten Seed-Kurven
mit den Runner-Zonenfenstern benötigen weiterhin ihren Gesamtnachweis.

Der aktuelle Bericht
`support-680652f/port-helper-final-r3/native-departures-r1.json` prüft
alle zehn Buchtenabfahrten frisch mit tatsächlich geschlossenen
Aufzugtüren und den aktuellen Quellen. Alle bestehen mit mindestens
148,277689 mm Abstand zur Gebäudewelt und 88,328467 mm zu anderen
realen Fahrzeugkörpern; der kanonische Mindestabstand beträgt 90,207443 mm.
Die zusätzliche Abfahrecke verwendet das Maximum aus physischer Reserve
und voller Sensorreserve. Der Generator prüft die X-Invarianz aller
zugehörigen Tür- und Elternachsen, sodass dieser Abstand auch bei
geschlossenen Türen gilt. Dies betrifft allein die Abfahrt aus der eigenen
Bucht; Boarding-Geometrie, feste Buchten und Kabinenspuren bleiben erhalten.
Auch dieser Nachweis gilt für separate Portprofile mit
300-mm/s-Zonenobergrenze, nicht für das vollständige Seed-Programm.

Der zweite integrierte Versuch wurde ebenfalls vor der Ausführung abgelehnt:
Die nominale Raum-/Heimfahrt von BF06 hatte ohne eigene Buchtenzusage nur
84,917825 mm Abstand zur reservierten EG-Bucht1. Alle vier vorhandenen
Inspektionsvarianten teilten dieselbe 152,171°-Transitkehre. Ihre sichere
Verbindung wurde allein vom achsenweise aufgeweiteten Bay-Vorfilter
verworfen. Nur solche Voralarme werden nun durch den vollständigen
konstanten-Yaw-Rechtecksweep mit euklidischem Abstand und unveränderter
Reserve verfeinert; andere Treffer und der vollständige Bodentest bleiben
erhalten. Die vorhandene Shared-Splice-Reparatur registriert die neue
Verbindung vor dem Katalogabschluss, ohne eine Rauminspektion zu verkürzen.

Der deshalb ehrlich neu abgeleitete Cache `support-680652f/navigation-r2/`
enthält unveränderte Heim-, Warte-, Hub- und Kabinenschnittstellen; kein
R1-Cache wurde umgepinnt. Navigation und Routengraph benötigten ohne den
Ressourcenkatalog 161,414 s und
registrierte 2895 statt 2783 generische Splice-Reparaturen, entsprechend
3314 festen Routen. Originalmission6 behält ihre Identität, ihr Ziel und
ihren Heimabschluss. Ihre tatsächliche retimierte, quantisierte
nominale Controller-PVA besteht ohne Bay-Ausnahme den vollständigen kanonischen
Nachweis mit mindestens 103,604940 mm Abstand und ohne Zwischenhalt.
Der eigenständige Bericht ist
`support-680652f/bf06-actual-controller-pva-r1/report.json`; er belegt diesen
Regressionsfall ohne SensorWorld, keinen vollständigen Flottenlauf.

Der dritte integrierte Versuch bestand elf nominale Startbahnprüfungen,
wurde aber bei 0,2 s Modellzeit geordnet unterbrochen. Die zusätzliche
unabhängige Prüfung fand eine Prüferlücke: Mehrere fremde Missionen konnten
dieselbe Buchungskennung beanspruchen; ein Mengenvergleich verlor diese
Doppelbelegung. Zwei synthetische Gegenbeispiele auf Basis der
Ein-Fahrzeug-Testfixture wurden vom alten Prüfer
akzeptiert, darunter eine Mission mit späterer fremder Buchung. Sie stehen
unter `support-680652f/assignment-booking-bijection-bypass-r1/`.
Das ist kein beobachteter Fehler der tatsächlich ausgegebenen Missionen.
Der korrigierte Prüfer verlangt die eindeutige Bindung jeder Mission an
ihre eigene vorher angelegte Buchung. Alle 16 fokussierten Tests bestehen;
beide Gegenbeispiele werden abgelehnt, die gültige bedingte Folgebuchung
bleibt zulässig. Der Versuch unter
`support-680652f/full-seed-r3/` bleibt ausdrücklich unvollständig erhalten;
seine Weltlauf-Initialisierung benötigte bis zum Abbruch 1602,910 s.
Navigation und statischer Katalog bleiben durch diese reine Prüferänderung
unverändert und dürfen nur mit ihren weiterhin passenden Quellpins
wiederverwendet werden.

Am aktuellen eingefrorenen Integrationsstand bestehen 344 von 346 Python-Tests
in 118,882 s; zwei optionale Prüfungen sind übersprungen
(`support-680652f/bf01-integration-tests-r6.log`). Die separate Ausführung der 22
nativen Hüllenregressionen mit installiertem FreeCAD besteht vollständig.
Dies ersetzt weder den ursprünglichen Seed-Lauf noch dessen nativen
Gesamtprogrammnachweis. Die aktuelle Byteprüfung bestätigt außerdem
154 unveränderte Konstruktionsdateien gegenüber `master` `680652f` und
alle 160 im Bericht aufgeführten unveränderten Referenzen der
geschützten/physikalischen Quellkette.
Der Bericht heißt `protected-source-byte-audit-r2.json` unter
`exports/building-fleet/support-680652f/`.

Der vierte integrierte Versuch verwendet unverändert Seed `20261120`,
alle 20 Fahrzeuge und den quellgebundenen 3314-Routen-Katalog des dritten
Versuchs. Alle 20 nominalen Startbahnen bestehen ihr kanonisches
Geometriegate. Der tatsächliche Weltlauf bricht jedoch bei **75,2 s
Modellzeit** selbst mit
`No bounded own protective-stop enclosure; replan before execution` ab.
`interrupted` ist `false`; ein manueller Abbruch wurde nicht gesendet.
Betroffen ist BF04 mit `mission-4` nach EG/R0_001. Der letzte erfolgreiche
Entscheid bei 75,15 s erlaubt noch `clear_scan`; nach weiteren 50 ms eigener
Beschleunigung gelingt der Schutzbremsnachweis nicht mehr. Der Befund
belegt die fehlende Freigabe, keine bereits erfolgte Kollision.
Der begrenzte Repro unter
`support-680652f/full-seed-r4-failure-analysis/report.json` verwendet die
tatsächlichen Eingaben und rekonstruiert auf dem geraden Teilstück den
skalaren Zustand aus den tatsächlichen kartesischen Jets. Die ursprüngliche
Stoppfamilie reproduziert den Fehler ohne nominale Neukompilierung.
Alle 20 abgefragten Roh-Stoppbudgets sind negativ; der beste geprüfte
Abstand zum unveränderten Beobachtungsbudget beträgt −35,368515 mm.
Dies beweist keine physikalische Unmöglichkeit aller denkbaren Stopps.
Der gesonderte nächste Korrekturschritt ist eine Weiterfahrfreigabe, die
die erforderliche Bremsreserve für den folgenden 50-ms-Schritt nachweist
und vor deren Verlust bremst. Außerdem bleiben die Kosten der wiederholten
PVA-/Zonenextrema außerhalb der beschleunigten Katalogberechnung offen.

Die CLI benötigt bis zu diesem Fehler **3043,275 s (50,7 min)**, davon
2980,044 s für Weltinitialisierung und Weltlauf einschließlich der
nominalen Bahnvorbereitung. Der Durchsatz zwischen 10 und 30 s Modellzeit
beträgt 78,656 s Wandzeit; die bis 10 s aufgelaufenen 2740,558 s sind
ausdrücklich keine isolierte Katalogmessung. Die Grenze von zehn Minuten
für Vorbereitung und Programmerzeugung zusammen wird deutlich verfehlt.
Die Stoppregel aus Abschnitt 12 des vorliegenden BF01-Auftrags bleibt
maßgeblich; weitere Vollversuche werden an diesem Stand nicht gestartet.
Höhere Bewegungsgrenzen, ein anderer Seed oder beschleunigte Wiedergabe
ersetzen den fehlenden Nachweis nicht.

`support-680652f/full-seed-r4/runtime-failure.json` und
`compile-failure.json` dokumentieren den Fehler und
`complete_fleet_qualified: false`. Das erhaltene `partial-program.json`
ist unvollständig. `assessment.json` daneben bündelt die unveränderten
Artefaktreferenzen, Testergebnisse und Prüfgrenzen ausdrücklich als
fehlgeschlagene Bewertung. Die tatsächlichen eigenen Eingaben enthalten 15060
anonyme Scans, 20 eigene Pfade, 30001 Entscheidungen und 1467 Stoppuhren;
die Gzip-Datei bleibt unter derselben Ausgabe erhalten. Alle 203
Laufzeit-Quell-/Artefaktpins stimmen nach dem Abbruch weiterhin mit ihren
Startwerten überein. Ein vollständiges Programm, dessen nativer
Gesamtnachweis, die unabhängige Exportfreigabe und eine BF01-Browserfreigabe
liegen nicht vor. Die separaten Portnachweise bleiben davon getrennt.

### Historisch: BF01-2-Stopp am Laufzeitbudget

Der Folgeauftrag wurde auf dem geprüften `master`-Stand `84c61cb` im separaten
Worktree `exports/worktrees/building-fleet-support-rule` und Branch
`codex/building-fleet-support-rule` bearbeitet. Die neue Vorbereitung aus dem
aktuellen möblierten Rundgang umfasst 20 Heimplätze, 19 Pflichtziele, 100
Endpunkte, 3128 vollständige Routen und 35 geschlossene Konfliktressourcen.
2783 Routen enthalten vorab geprüfte Korrekturen stumpfer Kreuzungsumwege;
sie ersetzen keine vollständigen Raumdurchfahrten durch lokale Teilstücke.

Die abgeschlossene Vorbereitung benötigte **2009,411 s (33,5 Minuten)**,
noch ohne den integrierten Flottenlauf, dessen nativen Gesamtnachweis und
Browserprüfung. Der Quellstand und diese Messung stehen im ignorierten
`exports/building-fleet/support-84c61cb/static-preparation-r8/preparation.json`.
Der vollständige Ressourcenkatalog und seine Cache-Rekonstruktion stimmen
überein; `resource-cache-roundtrip.json` dokumentiert diesen statischen
Vergleich. Das ist keine Bewegungsqualifikation.

Damit ist das Laufzeitziel von zehn Minuten bereits in der Vorbereitung
deutlich überschritten. Gemäß der ausdrücklichen Stoppbedingung des Auftrags
wurde die weitere Programmerzeugung angehalten. Der unveränderte Seed
`20261120` wurde nicht durch einen günstigeren ersetzt. Ein früherer
diagnostischer Lauf erreichte 68,7 s Modellzeit und ist ausdrücklich
unvollständig; er belegt weder alle Ziele noch die Heimkehr aller Fahrzeuge.
Ein bestandener vollständiger 20-Fahrzeug-Lauf, ein nativer Gesamtprogrammcheck
und eine tatsächliche BF01-WebGL-Prüfung liegen nicht vor.

Eine zusätzliche Ablaufprüfung weist außerdem einen erreichbaren
Wartebuchtenzyklus nach: neun Fahrzeuge können ihre aktuellen Buchten so
belegen, dass alle zugewiesenen Folgemissionen auf volle andere Geschosse
warten. Der Nachweis steht in
`exports/building-fleet/support-84c61cb/audit_waiting_capacity_cycle.json`;
er ist ein reproduzierbarer Dienst-/Planerzustand, kein im obigen Seed-Lauf
beobachteter Deadlock. Die atomare Zusage von Start- und Zielbucht vor dem
Aufzugruf allein verhindert diesen Folgezustand nicht.

Der nächste konkrete Schritt ist eine getrennte Korrektur der
Auftragszulassung: die Zielbucht bereits vor Vergabe eines geschossübergreifenden
Auftrags fest zusagen, höchstens einen Folge-Geschosswechsel vormerken und
diese Vormerkung erst nach beobachteter vollständiger Ausfahrt aktivieren.
Erforderliches Warten muss an einer bereits eigenen Wartebucht oder am eigenen
EG-Heimplatz erfolgen, einschließlich korrekter Durchgangstoken. Neue
Flurparkplätze, Bench-Ausweichflächen, Freigaben allein durch Zeitablauf und
höhere Bewegungsgrenzen sind keine Lösung. Anschließend ist die Vorbereitung
mit unveränderter vollständiger Routensemantik zu beschleunigen und erneut zu
messen, bevor der ursprüngliche Seed vollständig geprüft wird.

Die unabhängige Exportprüfung muss dabei auch um die Bindung zwischen
ursprünglich ausgegebenem Auftrag, eigener Quittung und Abschlussbeleg anhand
derselben Missionskennung ergänzt werden. Die bisherige Zuordnung nach
Fahrzeug, Raum und Zeitpunkt allein reicht dafür nicht aus. Bedingte
Folgebuchten dürfen vor ihrer beobachteten Aktivierung außerdem keine
geometrische Betretungserlaubnis geben.

Die neuen Python-Implementierungen für Ablauf, Prüfung und Browserbau sind
prüfbare Bausteine. Der Browserbau verlangt einen exakt an das Programm
gebundenen nativen Gesamtnachweis und die unabhängige Exportprüfung; ohne
diese Nachweise entsteht keine freigegebene Flottenanimation. Es wurde weder
gemergt noch gepusht oder auf Pages veröffentlicht. Die offenen biologischen
E4-Entscheidungen sind unverändert.

Der neue lokale Gesamtstatus steht unter
`exports/building-fleet/support-84c61cb/fleet-report.json` mit
`status: blocked_performance` und `complete_fleet_qualified: false`.
Die abschließende BF01-Pythonsuite umfasst 261 Tests: 259 bestanden, zwei
native Opt-in-Fälle wurden übersprungen. Der separate installierte
FreeCAD-Vertragstest bestand zuvor alle 20 Fälle. Sieben Kamerakit-Quelltests
und neun Markdown-Linktests bestehen ebenfalls. Die Rundgangsuite umfasst
63 Tests, davon einen übersprungenen optionalen `jsonschema`-Test; die drei
bestehenden JavaScript-Rundgangprüfungen bestehen. Die reine neue
Node-Prüfung bestätigt PVA-/Meldungswiedergabe, Steuerungssperren,
verlustfreie Projektion und Bytegleichheit des normalen Rundgangs, ersetzt
aber keine tatsächliche WebGL-Prüfung. Die alten L01-Lokal-/Gegenverkehrstests
benötigen weiterhin den fehlenden aktuellen ignorierten Workcell-Build;
veraltete Artefakte wurden nicht als Ersatz übernommen. Eine separate
Schutzprüfung bestätigt 157 unveränderte Konstruktions-/TR01-/L01-Quelldateien
gegen die Arbeitsbasis `84c61cb`.

Die Rückstellung hebt nur die zuvor nachgewiesene topologische Sperre für
K0_013 auf. Sie ist keine Freigabe anderer Ziele, Türen, Depots oder Fahrwege.
Vor einer Simulation müssen sämtliche verbleibenden Ziele mit der
Fahrzeughülle, den deklarierten Abständen und den tatsächlichen nativen
Hindernissen geprüft werden. Jede weitere Stoppbedingung des Auftrags bleibt
verbindlich. Ein grobes Raster oder eine Kreis-Breitphase allein beweist
keine Unpassierbarkeit einer orientiert befahrbaren Tür.

Gebäudeabmessungen und Registrierung sind Darstellungsannahmen, keine
Vermessung. Sensorik, Kamera, Kommunikation und Gebäudedienste sind synthetisch.
Personen, reale Tür-/Aufzugsteuerung, Navigation und Sicherheit bleiben
unqualifiziert; der Vergleich mit manueller Durchführung bleibt offen.
Neue Laufzeitdaten und Geometrienachweise entstehen ausschließlich unter den
ignorierten lokalen Ausgabeordnern. Historische Medien bleiben unverändert.

### Welteingabe aus dem Rundgang

`NativeMesh` erwartet im Exportordner `world-build-report.json`. Es prüft
alle dort gebundenen Quellen sowie `world-manifest.json` und
`native-mesh.json` auf Bytegleichheit. Die Welt enthält native Gebäude-
und L01-Körper einschließlich der Monitore, Objektbindungen und
Navigationsdaten. Sie hängt von der physischen Monitorquelle ab. Änderungen
an der BF01-Quelle oder am Kameraregister haben nur Auswirkungen auf das
separat geprüfte Browser-Overlay.

Frühere Navigationscaches sind durch den neuen Welteingabevertrag und die
geänderten Generatorpins veraltet. Der neue Weltexport und sein Lader
qualifizieren keine Flottenfahrt. Der BF01-Status bleibt **unproven**.

## Erreichte Phase 1

Die separate [Flottenquelle](../model/building-fleet-demo.shared.json) und ihr
[striktes Schema](../model/building-fleet-demo.schema.json) binden die bestehenden
Gebäude-, Rundgang-, TR01-, Winkelprofil-, Sensor- und L01-Quellen sowie den
neuen [Kamerakit](../model/tr01-awareness-camera.shared.json) über SHA256.
Der Lader lehnt Zusatzfelder, ungültige Einheiten/Werte, unbekannte
Qualifikationen und jede weitere Zielauslassung ab. Es gibt 19 aktive Ziele.

Der Kamerakit wird unabhängig in FreeCAD und SolidCraft aus derselben Quelle
abgeleitet. Die TR01-Konstruktion wird nicht verändert. Die leere Ableitung
entfernt nur die 48 Gefäßhüllen, behält beide Racks und die geschlossene Haube
und ergänzt Gehäuse, Linse, Halter und einen ausdrücklich nichtphysischen
Sichtkegel. Kameraposition und -ausrichtung folgen den TR01-Parametern und
benannten Flächen. Eine Kamera-Hardware ist nicht ausgewählt.

```sh
python3 scripts/build_tr01_awareness.py
python3 -m unittest discover -s tests -p 'test_tr01_awareness.py' -v
python3 -m unittest discover -s tests -p 'test_building_fleet*.py' -v
```

Der tatsächliche unabhängige CAD-Vergleich besteht mit je 35 Körpern und
93 exakten Kit-/Fahrzeug-Interferenzprüfungen. Die Kamerahülle einschließlich
Halter bleibt außerhalb von Abdeckung und Kassettenraum. Der optische Rahmen
liegt bei den Standardparametern bei `[250, 0, 182]` mm und blickt in Fahrzeug-+X.
Der lokale Bericht steht unter
`exports/generated/tr01-awareness-ccd729bbb881-r2/build-report.json`.

## Historischer Stopp der ursprünglichen L01-Gangmitten

Nach der Rückstellung von K0_013 sind die übrigen Ziele im optimistischen,
registrierten Tür-/Bereichsgraphen mit den aktiven Aufzuglandeseiten verbunden.
Das beweist keine geometrische Fahrt. Auch ein negativer Kreis-/Rasterbefund
reicht allein nicht zur Ablehnung: Die engeren Kellerportale DK009 und DK011
sind bei gerader orientierter Durchfahrt mit Fahrzeughülle und den unveränderten
Abständen frei; weitere Raumwege wurden damit nicht qualifiziert.

Für das Pflichtziel **OG3 / R3_003 (L01)** ist dagegen die aus dem vorhandenen
Fahrprofil abgeleitete Gangmitten-Verbindung tatsächlich unterbrochen:

| Verbindung | Tatsächlicher Kontakt im gemeinsamen Gebäudebezug |
|---|---|
| Vordere Querverbindung | Chassis bei Fahrzeugmittelpunkt `[11100, 6611.351351351352]` mm trifft das anfangs offene `OG3__DoorLeaf_D3_003B`. |
| Hintere Querverbindung | Die obere Haubenhaut bei Fahrzeugmittelpunkt `[9000, 1571.41768981954]` mm trifft `Lab3003_WindowBenchRight_Worktop`. |

Die Materialzeugen liegen ohne Sicherheitsaufweitung im Inneren der jeweiligen
nativen geschlossenen Hindernishülle: vorn bei Weltpunkt
`[11100, 6611.351351351352, 12850]` mm, hinten bei
`[9000, 1521.41768981954, 13615]` mm. Die Haubenhaut liegt bei TR01-Z = 865 mm;
der hintere Materialzeuge hat Fahrzeug-Y = −50 mm. Nur die Boundingbox der
gekrümmten Fensterbank wäre hierfür kein ausreichender Nachweis.

Die Zeugen liegen jeweils mehr als die bestehenden 250 mm Eckverrundung von
den Gangmitten-Knoten entfernt. Ein größerer Umweg ist keine bereits geprüfte
Eckverrundung dieser referenzierten Bahn. Nach beiden Unterbrechungen sind die
zu D3_003A und D3_003B gehörenden Gangseiten nicht verbunden; die bestehende
Gangmittenstruktur enthält keine zulässige geschlossene Inspektionsschleife.
Eine Rückwärtsinspektion oder Drehung auf der Stelle gehört nicht zu den
zugelassenen Rückwärtsfällen. Das ist eine Ablehnung der **vorgeschriebenen
bestehenden L01-Gangmitten**, keine Behauptung, dass jede denkbare neue Bahn im
Raum unmöglich wäre.

Bis zur ausdrücklich freigegebenen separaten BF01-Verbindung wurde deshalb kein vollständiges BF01-Programm erzeugt. Es wurden weder Türen
umgestellt, Möbel verschoben, neue Fahrspuren erfunden, Abstände verringert
noch weitere Ziele zurückgestellt. Diese Entscheidung wurde am 20. November 2026 ausdrücklich erteilt; die separat geprüfte Umsetzung steht im folgenden Abschnitt. Das bisherige L01-Profil bleibt dabei eine unveränderte Referenz.

Die lokalen, nicht versionierten Nachweise stehen unter
`exports/building-fleet/preflight-current/`: `audit.py`, `report.json`,
`check_portals.py`, `portal-report.json`, `audit_l01_stop.py` und
`l01-stop-report.json`. Aktuelle native BRep-Zeugen werden dort separat geführt.

## Separat geprüfte BF01-Verbindung in L01

Die [neue referenzierende Quelle](../model/building-fleet-l01-route.shared.json)
mit eigenem [Schema](../model/building-fleet-l01-route.schema.json) ersetzt für
BF01 die betroffene Querung. Das ursprüngliche L01-Fahrprofil und seine alten
negativen Nachweise bleiben unverändert. Die Flottenquelle bindet die neue
Quelle ausdrücklich über `sources.l01_route`; der normale Rundgang und die
bisherigen L01-Demos wählen sie nicht stillschweigend aus.

Die Querung wird aus der gebundenen Raumdefinition mittig zwischen der
vorhandenen offenen Türblattspitze und der tatsächlichen Inselvorderkante
abgeleitet. Sie liegt lokal bei Y = 1369,864865 mm. Die freie Streifenbreite
beträgt 660,270271 mm; Fahrzeugbreite und beidseitiger Abstand von je 85 mm
lassen darin 78,270271 mm zusätzliche Breitenreserve. Türstellungen, Möbel,
Arme, vorhandener statischer TR01 und die ursprünglichen Bench-Zonen bleiben
erhalten. Die Schutzbereiche werden starr in denselben Gebäudebezug übertragen,
nicht verkleinert oder skaliert; sie bleiben durchgehend gesperrt.

Die fünf C2-Teilstücke einschließlich Einfahrt durch D3_003A und Ausfahrt durch
D3_003B sind eine durchgehende Fahrt. Die Zeitplanung behandelt schnelle Geraden
und langsamere Kurven getrennt. Sie verzögert vor engeren Kurven bzw. Zonen und
beschleunigt danach wieder innerhalb der unveränderten Grenzen. Wegpunkte,
Türdurchgänge und Querungswechsel enthalten keine Ruhepunkte. Wiedergabefaktor
ist 1; Modellzeit und spätere Browser-Wiedergabe bleiben getrennt.

Das nach 1 ms Zeitquantisierung tatsächlich ausgewertete Profil dauert
**57,947 s**. Seine oberen Schranken betragen 298,70 mm/s, 490,04 mm/s² und
981,02 mm/s³; die Gierrate bleibt unter 0,32442 rad/s bei unverändertem Limit
0,35 rad/s. Die gemeinsame Polynom-Auswertung prüft Beschleunigung, Ruck und
Kein-Halt-Kriterium auch zwischen den Knoten. Es wird keine globale
Zeitoptimalität und kein bestandener menschlicher Vergleich behauptet.

Getrennte Nachweise am exakten exportierten Profil:

- Kontinuierlicher Mesh-/Bench-Nachweis: mindestens 95,3788 mm Abstand nach
  Abzug von Tessellierungs- und Float32-Reserve.
- Exakte Unterstützung des gesamten aufgeweiteten orientierten Rechtecks
  durch die native Bodenflächen-Union; kein Ersatz durch einen verkleinerten
  Kollisionskreis oder reine Zellmittelpunkte.
- Unabhängiger nativer BRep-Kurvennachweis aller 34 physischen Fahrzeug- und
  Kamerakörper gegen die vollständige gebundene Gebäudewelt: konservative
  Intervall-Untergrenze **90,3299 mm**, gefordert sind 85 mm (75 mm Abstand plus
  10 mm Lokalisationstoleranz). 268 Intervalle und 790 exakte BRep-Abstände.

Die lokalen Nachweise stehen unter `exports/building-fleet/l01-connector/`:
`fast-motion-r2.json`, `final-current-mesh.json`,
`final-current-floor.json`, `final-current.json` und
`motion-generation-report.json`. Diese Qualifikation betrifft die **einzelne
BF01-Verbindung** in der synthetischen Szene. Fahrzeugbegegnungen, alle übrigen
Fahrwege und der vollständige Flottenlauf benötigen weiterhin eigene Nachweise.
Reale Navigation, Personenschutz, Hardware und Aufmaß bleiben ungeprüft.

## Fortgesetzte Navigation und lokale Regelung

Die neuen Standardbibliothek-Module leiten 20 vorwärts zugängliche Heimplätze
aus den beiden zulässigen EG-Depots ab (zwei in R0_004, 18 in R0_013). Feste
Wartebuchten am Aufzug sind getrennte, reservierte Flächen; normale Fahrwege
verwenden eigene freie Durchfahrtsknoten und meiden die Buchten. Breite Flure
verwenden richtungsabhängige Rechtsfahrspuren mit zusätzlicher, aus der
Sensorunsicherheit abgeleiteter Planungsreserve. Die unveränderte
Qualifikationsreserve beträgt 85 mm. Kandidatenressourcen werden vor einer
Ausführung anhand überlappender statischer Konfliktbereiche zusammengeführt;
das ist noch kein nachgewiesener konfliktfreier Gesamtlauf.

Die Sichtlinienverkürzung kann nun einen vollständigen Rechtecknachweis auch
während der Rastersuche verlangen. Dadurch entstehen die Kellerverbindungen
zu K0_009 und K0_011 ohne handeingetragene Zielkoordinaten. Die beiden
tatsächlich exportierten C2-Kurven bestehen zusätzlich den kontinuierlichen
Mesh-, Bodenflächen-Union- und Wartebuchtennachweis: 75,798 bzw. 70,739 s mit
Abstandsuntergrenzen 85,0338 bzw. 85,2880 mm. Dies sind einzelne Verbindungen,
keine Flottenbegegnungs- oder nativen vollständigen Fahrprogramme.

Der lokale Regler erhält eigene Aufträge, eigene Lokalisation, verzögerte
anonyme Scans und eigene Zusagen. Er benutzt dieselbe tatsächlich begrenzte
Bremskurve für Reichweitenbudget und Ausführung, wartet auf die geforderte
Frisch-frei-Beobachtung und prüft die exportierten PVA-Polynome. Körper- statt
Kreisrückläufe vermeiden künstliche Blockaden benachbarter Fahrspuren. Ein
Wiederanlauf bewahrt die eigene Pose einschließlich unaufgewickelter Gierrichtung.
Die Regler-, Dienste-, Funkkanal-, Leitstand- und Sensorprüfungen belegen
Bausteine; sie belegen weder einen integrierten Flottenlauf noch reale Sensorik.

## Historischer Stopp vor der Schwellenkorrektur: fehlender Aufzugboden

Am obligatorischen aktiven Port `LiftPort_EG_inward` verband die damals gepinnte
Geometrie Kabinenboden und Flurboden nicht durchgehend. Die Lücke war keine
zu enge geplante Kurve: Ein positiver Streifen über die **gesamte aus der Quelle
abgeleitete Türöffnung** besitzt keine tragende native Geometrie. Jede
Verbindung von der Kabine zum Flur muss diesen Streifen queren.

Der konservative Zeuge im Gebäudebezug lautet:

| Koordinate | Streifen / Kontaktband in Darstellungs-mm |
|---|---|
| X | 12642,827703 bis 12679,952703 (Breite 37,125) |
| Y | 15608,108108 bis 16529,729730 (vollständige Quellöffnung) |
| Z (natives Prisma) | −20 bis +20 um die EG-Bodenhöhe |

Der Mesh-Nachweis betrachtet auch andere Körper als ausgewiesene Bodenplatten:
er projiziert sämtliche Flächen im Band Z = 0 bis +20 mm und findet im ganzen Streifen
keine Stützung. Das unabhängige native Prisma erweitert das Z-Band auf −20
bis +20 mm; seine Prüfung durchsucht die AABBs aller
**2758 Gebäudekörper** und prüft die 14 nahen BReps exakt. Der Abstand des
vollständigen Streifenprismas zur nativen Gebäudewelt beträgt mindestens
**37,125 mm**; das Schnittvolumen ist null. Dies bestätigt einen fehlenden
Bodensteg unabhängig von Raster, Route und Dreieckstessellierung. Die Zahl
2758 betrifft diese fokussierte Gebäudeprüfung; der L01-Kurvennachweis
verwendet separat die gesamte gebundene Welt mit 3441 Körpern.

Die lokalen Nachweise für diesen historischen Befund sind
`exports/building-fleet/lift-preflight/inner-port-support-barrier.json` sowie
`exports/building-fleet/lift-threshold/native-eg-threshold-strip.json` mit
Reproduzierer `check_native_threshold_strip.py`. Der Preflight kann separat
mit einem neuen Weltexport ausgeführt werden. Exitcode 2 meldet einen
ausstehenden Nachweis beziehungsweise eine festgestellte Sperre.

```sh
python3 scripts/build_building_walkthrough.py --no-rebuild
python3 scripts/building_fleet_lift_checks.py \
  --walkthrough 'exports/building-walkthrough/<Revision>' \
  --output exports/building-fleet/lift-preflight/current-support-barrier.json
```

Dieser Einstieg prüft einen konkreten Zeugen für eine Stützungslücke;
das Ausbleiben dieses Zeugen beweist keine vollständige Aufzugfreigabe. Heute gilt
die oben dokumentierte Eigentümerannahme für höchstens 15 mm geschlossene
Bodenlücke; eine reale Radüberbrückung bleibt unqualifiziert. Der geometrische
Bodenstützungsnachweis bleibt erforderlich. Quellen, native CAD-Ausgaben
und Prüfberichte sind über SHA256 gebunden. Es wurden keine historischen
Berichte umgepinnt und keine Schwelle, Tür, Kabine oder Gebäudequelle verändert.

Der ursprüngliche Auftrag verlangte hier ausdrücklich Anhalten und Berichten.
Daher gab es damals keinen vollständigen Seed-Lauf, keine bestätigte Zielabdeckung,
keine Flotten-Aufzugsstatistik, keinen nativen Gesamtkurvennachweis und kein
qualifiziertes BF01-Browserprogramm. Die damaligen unfertigen Missions-,
Laufzeit- und Browserentwürfe bleiben unter
`exports/building-fleet/incomplete-components/` erhalten. Der Folgeauftrag
BF01-2 überprüft die wiederverwendeten Bausteine erneut, ergänzt insbesondere
die atomare Zusage von Start- und Ziel-Wartebucht vor dem Aufzugruf und prüft
die Gesamtintegration separat. Alte Entwürfe sind kein neuer Nachweis.

Der damals erforderliche nächste Schritt war eine ausdrücklich freigegebene
Geometriekorrektur der befahrbaren Aufzugsschwelle in der gemeinsamen
Gebäudequelle mit neuen nativen und Bodenstützungsnachweisen. Für den
Folgeauftrag bleiben Treppenkern-Ausschluss, alle übrigen Ziele, Bench-Sperren und
unveränderte TR01-/L01-Quellen verbindlich. Ein Aufheben der Bodenprüfung oder
ein erfundener virtueller Steg wäre kein zulässiger Fortsetzungsschritt.

Die Annahmen E1–E8 bleiben bestehen: bestätigte bzw. unbestätigte Zielnutzungen
(E1), fünf aktive Kellerziele und die ausdrückliche Rückstellung K0_013 (E2),
Depot nur in R0_004/R0_013 (E3), synthetische getrennte Leerfahrtgrenzen (E4),
referenzierte Rundumscan-Annahme und 75 mm Abstand (E5), logischer Leitstand
(E6), höchstens zwei nur bei nachgewiesenem Kabinenfreiraum (E7) und die
statische L01-TR01-Instanz (E8). Im EG und KG gilt die innere aktive
Aufzugseite der Quelle; die ältere Dokumentationsangabe „EG beidseitig“
wird nicht übernommen. Reale Navigation, menschlicher Vergleich, Personen,
Tür-/Aufzugsautomatik, Netzwerk, Hardware und Pages bleiben ungeprüft bzw.
unveröffentlicht.

### Unabhängige native Kontaktbestätigung

Die beiden statischen Zeugen wurden zusätzlich mit den exakten nativen BReps
überprüft, unabhängig von Raster und Dreiecksprojektion. Bei unveränderter,
korrekt offener Referenztür ergibt Chassis/Türblatt ein positives Schnittvolumen
von 561.210,810 mm³; Haube/Fensterbank ergeben 45.019,010 mm³. Beide exakten
Abstände sind null. Quelle und native Artefakte sind im lokalen
`native-negative-witnesses.json` gepinnt; der Reproduzierer heißt
`check_l01_native_witnesses.py`. Das sind zwei negative statische Zeugen,
kein vollständiger nativer Fahrweg- oder Flottennachweis.

## Historischer Prüfstand vor BF01-2

Die gezielte BF01-Pythonsuite besteht **121 Tests ohne Skip**; sie enthält
auch die ausdrücklich aktivierte Regression am aktuellen gepinnten
Aufzugsexport. Dazu bestehen sieben Kamerakit-Quelltests und neun
Markdown-Linkprüfungen. Die lokalen Prüfprotokolle liegen unter
`exports/building-fleet/l01-connector/final-bf01-tests.log` und
`exports/building-fleet/lift-preflight/lift-check-tests.log`.

Die erneut ausgeführte Python-Rundgangsuite meldet 62 Tests: 61 bestanden,
ein optionaler Schema-Test wurde wegen fehlendem `jsonschema` übersprungen.
Es wurde nichts installiert; der Skip ist kein bestandener Schema-Nachweis.
Die drei bestehenden JavaScript-Prüfungen für Interaktion, Aufzug und freie
Kamerakollision bestehen. Der normale Rundgangexport wurde nicht verändert.

Die alten L01-Lokal-/Gegenverkehrstests sind in diesem isolierten Worktree
wegen des fehlenden ignorierten
`cad/tr01-workcell/shared-build-report.json` nicht ausführbar. Die alten
Mehrfahrzeug-Quelltests bestehen (sieben Tests) mit einem zusätzlich
ausdrücklich übersprungenen Programmtest mangels dessen lokalem Build.
Der fehlende Altbuild wurde nicht durch veraltete Artefakte ersetzt. Die
zehn geschützten Module sind bytegleich zur Arbeitsbasis `80abbc7`.

Die native Einzelkurvenprüfung und die native Schwellenprüfung sind die
oben getrennt beschriebenen Geometrienachweise. Ein vollständiger
Flottenlauf, ein nativer Gesamtprogrammcheck und die BF01-WebGL-Prüfung
wurden wegen des Schwellenstopps nicht ausgeführt. Der lokale
`exports/building-fleet/l01-connector/fleet-report.json` führt deshalb
den Status `blocked_geometry` und keinen bestandenen Gesamtlauf.
Der Prüfstand `f46b8d3` entstand lokal auf `codex/building-fleet-demo` ohne
Merge, Push oder Pages-Veröffentlichung. Die damalige Integration in den
`master` änderte keine geprüfte Geometrie und führte keinen neuen
Flottenlauf aus. Der oben genannte Gesamtbericht bleibt ein historischer
Bericht zu `f46b8d3`; Push und Pages-Veröffentlichung bleiben gesperrt.
