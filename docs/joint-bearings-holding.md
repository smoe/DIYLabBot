# Lagerung und Haltesicherung der Armgelenke

Stand: 20. November 2026. **Phase 1: technischer Vorschlag vor Eigentümerentscheidung.** Die
[Konzeptquelle](../model/joint-bearings-holding.json) ist führend; der [abgeleitete
Bericht](joint-bearings-holding.report.json) enthält Quellpins, Lastfälle, Zeugenposen,
Rechenlücken, Lagerkräfte, Versatz und Budget. Weder Fertigung, Tragfähigkeit, Sicherheit noch
Hardwarebetrieb sind freigegeben.

## Eigentümervorgabe und bedingte Empfehlung

Der Auftrag priorisiert ausdrücklich: **„So wenig wie möglich, das möglichst schnell
funktioniert.“** Lagerung und messbare Steifigkeit haben Vorrang. **„Die Empfehlung für den
Erstprototypen darf keine Bremse enthalten.“** Das sind Eigentümervorgaben, keine Ergebnisse einer
Sicherheitsrechnung.

Konzeptpräferenz: für J2/J3/J5 zuerst je ein gegenüberliegendes Radialgegenlager untersuchen; J4/J6
und J1 zunächst als Vergleich auf dem vorhandenen Servoausgangslager belassen. Das betriebliche
Minimalkonzept ist aktive Haltung mit anschließend bestätigter, mechanisch abgestützter Parklage.
Passiven Gewichtsausgleich vor einer späteren Bremse bewerten.

**Diese Präferenz ist keine Bau- oder Betriebsfreigabe.** Zulässige Kippmomente, statische Thermik,
Haltedauer, tatsächliche Absenkendpunkte und eine SP02-taugliche Parklage fehlen. Die vorhandene
Lagerung ist geometrisch unverändert, aber nicht als tragfähige Alternative ohne Plattenrevision
akzeptiert. Auch die Unmöglichkeit einer solchen Alternative ist nicht bewiesen. Deshalb keine
Platte ändern oder eine Zusatzlagerung still als passend ausgeben. Die bestehende Forderung, J2/J3
konstruktiv zu sichern, bleibt bestehen; ein Verzicht auf Zusatzhardware ist eine offene
Eigentümerentscheidung.

## Quellen und Massenmodell

[robot_spec.py](../scripts/robot_spec.py) liest Parameter, Gelenkrahmen, Posen und
`flange_reference` aus der unveränderten [Armquelle](../model/robot.json). Servomassen stammen aus
der [Antriebsauswahl](../model/actuator-selection.json), Hüllen und Platten aus der
Herstellerbibliothek und den drei Schnittstellenquellen. [SP02](arm-syringe-pipette.md) liefert das
gesonderte Betriebsfenster; Pumpe, sieben Clips und Schlauchschleifen bleiben unverändert.
Geometrie, Servoauswahl und Profile sind keine neuen Kopien in der Konzeptquelle.

| Fall | Annahme und Grenze |
|---|---|
| `servo_only` | Nur veröffentlichte Servomassen; gesamtes Modul als Massenpunkt an seiner Ausgangsfläche, dem Gehäuse-Elternlink zugeordnet. Reale Schwerpunktlage und Gehäuse-/Rotoraufteilung unbekannt. |
| Sensitivität | `tau_j(q) = servo_tau_j(q) + sum(m_i * unit_tau_ji(q))`; tatsächliche Glied- und Werkzeugmassen bleiben `null`. Der Bericht nennt Koeffizienten je kg und ihre Bezugspunkte. |
| `planning_empty` | Unvermessene Strukturansätze L1…L6: 0,40 / 0,45 / 0,30 / 0,30 / 0,20 / 0,15 kg; Werkzeug 0,50 kg. |
| `planning_loaded` | Derselbe Planungsfall plus 0,02 kg für Gefäß und Probe. Keine erklärte zulässige Nutzlast. |

Der Servo-Fall ist eine Untergrenze des **berücksichtigten Massenumfangs**, keine bewiesene
Untergrenze des tatsächlichen Moments bei unbekannten Schwerpunkten. Der vorsorglich gewählte
Planungsfall ist ebenfalls keine nachgewiesene obere Lastgrenze. Struktur-Schwerpunkte liegen
vereinfachend zwischen benachbarten Quellrahmen; das Werkzeug liegt an `flange_reference`. Die
wirkliche SP02-Pumpe sitzt jedoch an L2. Ihre Masse und die Verteilung der übrigen Werkzeugteile
sind unbelegt. Weder eine Flansch-Punktmasse noch diese Planwerte ersetzen deren Vermessung. Alle
Werte und Gründe stehen als Annahmen mit Einheit in der Quelle; echte Massen und Eigen-Trägheiten
bleiben `null`.

## Statik, Suchgrenzen und Dynamik

Je Massenpunkt gilt `F_i = m_i * g`, `M = sum((p_i-o) cross F_i)` und `tau = axis dot M`. Gerechnet
wird in der gemeinsamen FK mit konsistenten mm-/m-Einheiten. Der Bericht trennt Antriebsmoment,
Radial-/Axialkraft und den zur Achse senkrechten Kippmomentanteil.

Die Extremsuche enthält exakte trigonometrische Auswertung für Zeugen und analytische
Taylor-/Trigonometrie-Hüllen ganzer Winkelboxen. Es handelt sich um Gleitkomma-Hüllen, **keine
formal zertifizierte Intervallarithmetik**. Zeugen liefern untere, Hüllen obere Grenzen für
`max(abs(tau))`. Rasterwerte werden nicht als globale Maxima ausgegeben. Toleranz, Zellbudget,
Abbruchgrund und verbleibende Lücke stehen je Ergebnis im Bericht; nicht konvergierte Fälle behalten
`maximum_exact_nm: null`. J1 wird für Schwerkraft wegen der senkrechten Achse herausgekürzt, J6 nur
für die hier axial angesetzten L6-Punktmassen. Eine seitliche reale Werkzeugmasse kann diese
Vereinfachung für J6 aufheben.

Abgeleitete Momentenhüllen in Nm, jeweils Zeugen-Untergrenze…obere Hülle:

| Massenfall | Winkelraum | J2 | J3 | J5 |
|---|---|---:|---:|---:|
| Nur Servos | Robotergrenzen | 3,601…3,640 | 1,365…1,406 | 0,255…0,255 |
| Nur Servos | SP02-Fenster | 3,389…3,399 | 1,362…1,392 | 0,255…0,255 |
| Planung leer | Robotergrenzen | 9,672…9,825 | 4,151…4,281 | 1,081…1,081 |
| Planung leer | SP02-Fenster | 9,154…9,164 | 4,151…4,247 | 1,081…1,081 |
| Planung beladen | Robotergrenzen | 9,768…9,925 | 4,208…4,340 | 1,103…1,103 |
| Planung beladen | SP02-Fenster | 9,247…9,257 | 4,208…4,306 | 1,103…1,103 |

Zeugen im beladenen Planungsfall; Winkelreihenfolge J1…J6 in Grad:

| Winkelraum | Zielgelenk | Zeugenpose | Restlücke Nm |
|---|---|---|---:|
| Robotergrenzen | J2 | 0,00 / 90,00 / -0,18 / 90,00 / 0,00 / 0,00 | 0,157 |
| Robotergrenzen | J3 | 0,00 / 24,82 / -115,00 / 90,00 / 0,00 / 0,00 | 0,133 |
| Robotergrenzen | J5 | 0,00 / 90,00 / 0,00 / 0,00 / 0,00 / 0,00 | <0,001 |
| SP02-Fenster | J2 | 0,00 / 65,00 / 25,11 / -30,00 / -0,10 / 0,00 | 0,010 |
| SP02-Fenster | J3 | 0,00 / 65,00 / 24,89 / 30,00 / 0,10 / 0,00 | 0,098 |
| SP02-Fenster | J5 | 0,00 / 27,50 / -10,00 / 0,00 / -107,50 / 0,00 | <0,001 |

Gerundete Posen erläutern die Fundstelle; für Reproduktion gelten die ungerundeten Berichtswerte.
Vorkommen im Ablauf und Kollisionsfreiheit dieser Zeugen sind nicht geprüft. Home/`working` ist
`[20,35,65,0,80,15]` und liegt im SP02-Fenster. Die MB01-Posen `parking_supported`,
`manual_reposition` und `parked_aside` verwenden `[0,0,90,0,90,0]`. **J3 = 90° überschreitet SP02 ≤
65°**; ihre Namen belegen keine geeignete Parklage des bestückten Arms.

Die unveränderten CF01-Grenzen sind beladen 0,5 rad/s, leer 1 rad/s, jeweils 2 rad/s² und 20 rad/s³,
ausdrücklich `qualified: false`. Die Punktmassenabschätzung summiert gekoppelte tangentiale,
zentripetale und achsenänderungsbedingte Beschleunigungsanteile konservativ über Dreiecksgrenzen.
Die zusätzlichen Momentenhüllen für J2/J3/J5 betragen beladen 4,051 / 2,090 / 0,622 Nm, leer 8,187 /
4,288 / 1,296 Nm. Das sind synthetische Hüllen, keine gleichzeitig auftretenden Bahnhöchstwerte.
Ruck begrenzt die Änderungsrate, er ist kein weiterer Momentenfaktor. Eigen-/Rotorträgheiten, reale
Bahn, Elastizität, Reibung und fahrende Basis fehlen. Es entstehen weder neue Bahnen noch
verlangsamte Vorführprofile.

Mit Konzeptfaktor 1,5 liegen die Summenhüllen aus Schwerkraft und dynamischem
Zuschlag beladen bei J2/J4/J5 über den veröffentlichten Nennreferenzen:
20,963 > 20 / 3,250 > 2,5 / 2,588 > 2,5 Nm. Leer überschreiten die Hüllen an
J1 bis J5 diese Referenzen; die Einzelwerte stehen unter
`combined_load_demands` im Bericht. Damit ist ausreichende Nennmomentreserve
nicht nachgewiesen. Umgekehrt beweisen solche konservativen, nicht zwingend
gleichzeitig auftretenden Obergrenzen keine tatsächliche Überlast oder
Unmöglichkeit. Reale Massen, Trägheiten, Bahnkorrelation und thermisches
Lastprofil müssen vor der Antriebsfreigabe geklärt werden; Profile und
Grenzwerte bleiben unverändert.

## Lagerkräfte und Bezug der Rechnung

Die registrierte Ausgangsfläche ist der Bezug für den äußeren Kraft-/Momentenvektor. In der
gemeinsamen Nullgeometrie liegt J2s Fläche bei y = −52 mm, sein Gelenkrahmen dagegen bei y = +52 mm.
J3 verwendet y = 37 statt 34 mm, J5 y = −36 statt +32 mm. Ein beliebiger Gelenkursprung darf die
Ausgangsfläche nicht als Momentenbezug ersetzen. Das innere Lagerzentrum ist unbekannt; sein
tatsächliches Kippmoment bleibt `null`.

Home, beladener Planungsfall; Kippmoment an der Ausgangsfläche:

| Gelenk | Antrieb Nm | Radial N | Axialbetrag N | Kippmoment Nm |
|---|---:|---:|---:|---:|
| J1 | 0,000 | 0,000 | 41,972 | 6,246 |
| J2 | 6,246 | 30,008 | 0,000 | 1,917 |
| J3 | 3,057 | 22,065 | 0,000 | 0,780 |
| J4 | 0,013 | 16,321 | 2,878 | 1,353 |
| J5 | 0,000 | 11,082 | 0,000 | 0,430 |
| J6 | 0,000 | 0,000 | 6,570 | 0,000 |

Der Bericht enthält diese Größen auch für Park- und Lastzeugen. Für ein Gegenlager wird beispielhaft
`B = (axis cross M_perp)/s`, `A = -F-B` angesetzt; axial bleibt das Servo lagebestimmend, das
Gegenlager schwimmend. Das Antriebsmoment um die Gelenkachse verschwindet dadurch nicht. Die
Beispiele verwenden `s = Modultiefe + zwei Quellplattendicken`: J2/J3/J5 79,5 / 73,0 / 75,5 mm. Das
sind **keine vorhandenen oder gemessenen Lagerabstände**. Beispielhafte Radialreaktionen
Gegenlager/Servo in Home: 24,119/5,889 N, 10,681/11,384 N, 5,700/5,382 N. Lagerzentren, Ausrichtung,
Vorspannung, Überbestimmung und Wärmeausdehnung müssen vor einer tatsächlichen Kräfteaufteilung
geklärt werden.

| Servo | Herstellerangabe zur Ausgangslagerung | Veröffentlichte Axial-/Radialwerte |
|---|---|---|
| X2 | Rillenkugellager | Zug/Druck je 0,25 kN; radial 1 kN |
| X4-L | `XRBT 305`; Kreuzrollen-Familie nur über unabhängigen Katalog plausibilisiert | axial `C` 1,0 kN; radial `Cr` 1,3 kN |
| X6 | Kreuzrollenlager | Zug 1,8 kN, Druck 0,8 kN; radial 2 kN |

`C`/`Cr` sind im X4-Dokument nicht definiert. Weder Tragzahlinterpretation noch zulässige eingebaute
Betriebslast ist bewiesen. Zulässiges Kippmoment, Kombinationsgleichung, Vorspannung und
Lebensdauerbasis fehlen bei allen drei Modulen. Kleine rechnerische Kräfte gegenüber Tabellenwerten
sind deshalb kein Tragfähigkeitsnachweis. Der Bericht erhält diese Unterscheidung.

Herstellerbelege, jeweils PDF-Seiten ab 1 gezählt:
[X2-Parameterblatt](../cad/vendor/myactuator/RMD-X2-P28-7-E/260920/vendor-document-2.pdf), S. 1;
[X6-Parameterblatt](../cad/vendor/myactuator/RMD-X6-P20-60-E/260920/vendor-document-2.pdf), S. 1;
[X4-L-Spezifikation](../cad/vendor/myactuator/RMD-X4-P36-36-E-L/261019/vendor-document-1.pdf), S.
8–10, Thermik S. 12. Herkunft und Bytepins stehen in der Konzeptquelle;
[Hersteller-Downloadseite](https://www.myactuator.com/downloads-xseries), geprüft 20.11.2026.

## Lageralternativen, Maße und analytischer Bauraum

Es gibt drei Nick-, zwei Roll- und zwei Basisalternativen. Bevorzugung bezeichnet nur den nächsten
zu untersuchenden Aufbau; `capacity_and_fit_accepted` bleibt offen.

| Gruppe | Alternative | Zusatzteile und Bewertung |
|---|---|---|
| J2/J3/J5 | Bestehendes Ausgangslager, fliegend | Kein Zusatzgewicht, keine Plattenrevision; zulässiges Kippmoment und Steifigkeit offen. |
| J2/J3/J5 | **Ein gegenüberliegendes 6001-2RSH je Gelenk** | Einfachste zusätzliche Radialstütze; eigene Zapfen, Sitze und Retention erforderlich. |
| J2/J3/J5 | Zwei gegensinnig angeordnete 7201 BEP | Größere axiale Führung, mehr Einstell-/Schmieraufwand; keine universell paarbaren Lager, Vorspannung offen. |
| J4/J6 | **Bestehendes Ausgangslager** | Bedingte Präferenz, bis distales Kippmoment und Steifigkeit geklärt sind. |
| J4/J6 | Separates 61806-2RS1 um Hohlzapfen | Axial beabstandete Stütze; Kabelweg und Rohrwand offen. 30-mm-Lagerbohrung ist kein freier 30-mm-Kabelkanal. |
| J1 | **Bestehendes X4-Ausgangslager** | Bedingte Präferenz; Kippmoment des gesamten Arms prüfen. Senkrechte Achse benötigt keine Schwerkraft-Haltesicherung. |
| J1 | Separates Paar 61806-2RS1 | Neue Hohlwelle und axial beabstandete Sitze; keine vorhandene Basispassung. MB01-/TR01-Beschleunigung eigener offener Lastfall. |

| Kaufteilbezeichnung | d × D × B mm | C / C0 kN | Ringmasse | Einzelpreis brutto / netto EUR |
|---|---|---|---:|---:|
| SKF 6001-2RSH | 12 × 28 × 8 | 5,40 / 2,36 | 22 g | 2,77 / 2,33 |
| SKF 61806-2RS1 | 30 × 42 × 7 | 4,10 / 2,90 | 25 g | 15,95 / 13,40 |
| SKF 7201 BEP | 12 × 32 × 10; 40° Kontaktwinkel | 7,61 / 3,80 | 35,6 g | 25,51 / 21,44 |

Preise: Abruf 20.11.2026, einzelne Ringe, Versand ausgeschlossen; Brutto/Netto wie im Shop
angezeigt. Normenfassungen und gewählte Wellen-/Sitztoleranzen bleiben `null`; die belegten
Artikelbezeichnungen ersetzen keine Passungsauswahl. Nominelle Wellen-/Sitzdurchmesser sind d/D,
keine tolerierten Fertigungsmaße. Die Gesamtmasse mit Zapfen, Hülsen, Trägern und Retention bleibt
`null`.

Belege: [SKF-Originalausdruck
6001](https://nabico.co.ke/product_datasheets/22973/22973-6001-2RSH%20-%20Deep%20groove%20ball%20bearings%20_%20SKF.pdf),
S. 2–4, gehostet bei Nabico; [Preis 6001](https://motionparts.de/products/6001-2rsh-skf).
[SKF-Originalausdruck 61806](https://docs.rs-online.com/1f16/A700000007139341.pdf), S. 1–2, Stand
30.09.2020, gehostet bei RS; [Preis 61806](https://motionparts.de/products/61806-2rs1-skf). [SKF
7201
BEP](https://www.skf.com/uk/products/rolling-bearings/ball-bearings/angular-contact-ball-bearings/single-row-angular-contact-ball-bearings/productid-7201%20BEP)
und [Preis
7201](https://tools.de/products/schraegkugellager-7201-bep-von-skf-12-mm-innen-32-mm-aussen). Der
6001-Ausdruck nennt auch 20,6 g Logistikmasse; technische 22 g sind der verwendete Planwert. Beim
61806 nennt ein anderer SKF-Katalogindex 4,49 kN; die Rechnung bindet ausdrücklich den PDF-Wert 4,10
kN. Aktuelle Fertigungsrevision und reale Masse müssen vor Beschaffung bestätigt werden.

| Gelenke | Modultiefe mm | Ausgangsplatte Innen-/Außen-Ø mm | Plattendicke mm | Freier axialer/radialer Raum |
|---|---:|---|---:|---|
| J1/J3 | 61,0 | 12 / 35,0 | 6 | `null` / `null` |
| J2 | 67,5 | 12 / 53,0 | 6 | `null` / `null` |
| J4/J5/J6 | 63,5 | 12 / 31,4 | 6 | `null` / `null` |

Registrierte Gehäuse-/Ausgangsgrenzen stehen je Gelenk vollständig im Bericht. Die Hüllen,
Plattenöffnungen und Gelenkgrenzen belegen keinen freien Lagersitz. Schon die Ringbreiten 7/8/10 mm
übersteigen 6 mm für eine bündige Aufnahme; Retainer, Borde und Schrauben kommen hinzu. Zwei
Winkelkontaktlager sind 20 mm, zwei Dünnringlager 14 mm reine Ringbreite, kein Gabelabstand.

Zusatzkonzepte **erfordern Plattenrevision**: J2 `A2_housing_plate`/ `A2_output_plate` und
Schulterwangen; J3 `A3_housing_plate`/`A3_output_plate`; J5 `A5_housing_plate`/`A5_output_plate` und
Handgelenkwangen; J4/J6 ihre `A4_*`-/`A6_*`-Platten; J1 `A1_housing_plate`/`A1_output_plate` und
Basisaufnahme. Resultierende Abstände, freier Kabelkanal und SP02-Freigang bleiben `null` bzw.
unbestätigt. Keine Clips oder Schlauchschleifen zugunsten eines Lagerteils verschieben.

## Spannungsverlust, Thermik und einfache Halteoptionen

Rücktreibmomente X6/X4/X2: 1,6 / 0,2 / 0,4 Nm, typische Reibwerte, **keine garantierten
Haltemomente**. Der Konzeptvergleich verwendet zusätzlich Faktor 2 Abstand; auch ein Unterschreiten
beweist kein stromloses Halten. J2/J3 haben bereits im Servo-Fall Posen mit überschrittenem
Reibwert, im beladenen Planungsfall auch J5. J4 erreicht über den Robotergrenzen
1,104…1,278 Nm gegenüber typisch 0,4 Nm; auch das Rollgelenk benötigt eine
Spannungsverlustbewertung. Probe, Quetschstellen und Nachbargeräte sind daher
betroffen. Kurzschluss-/Dynamikbremsung der Treiber ist unbelegt: Herstellerfähigkeit `null`,
angerechneter Bremsbeitrag null.

Der Bericht quantifiziert alle sechs Gelenke über beide Winkelräume und benannte Posen. Aus Home
ergibt das Modell bei künstlich fixierten übrigen Gelenken für J2 eine Absenkung der Flanschreferenz
um 270,232 mm bis zur Softwaregrenze 100°; für J3 77,076 mm bis zum quasistatischen
Reibgleichgewicht bei rund 123,45°. **Beides sind hypothetische Modellendpunkte, keine Anschläge
oder erste Kontaktlagen.** Softwaregrenzen halten einen stromlosen Arm nicht fest. Ein im
Suchfenster ausgewiesener Nullweg an dessen Rand bedeutet deshalb keine stromlose Sicherung.
Beschleunigung und Energiefreisetzung beruhen nur auf Punktmassen und konstanter Reibung;
Überschwingen und gekoppelte Absenkung mehrerer Gelenke fehlen. Tatsächliche Anschlag-/Kontaktpose
und realer Fallweg bleiben `null`. Der vorgeschriebene physische Sicherheitsbefund ist damit offen.

**Neue Aufgabenvorgabe:** Auch normale Übergaben mit Probe enthalten begründete Halte. Im
Erstprototyp übernimmt sie die aktive Servohaltung; Haltemoment und Haltedauer sind eigene
thermische Lastfälle. Der Konzeptfaktor 1,5 ergibt im beladenen gesamten Winkelraum für J2/J3/J5
14,887 / 6,510 / 1,655 Nm, gegenüber veröffentlichten Nennwerten 20 / 10,5 / 2,5 Nm. Das Verhältnis
ist keine statische thermische Freigabe; Haltedauer und eingebautes statisches Dauermoment bleiben
`null`. Verfahren ohne Zusatzhardware ist bis zu deren Klärung als unbedingte Betriebslösung
ausgeschlossen.

Besonders X4: 10,5 Nm beziehen sich auf ±90°-Schwenken mit 5-s-Positionshalten, nicht auf
unbegrenztes Stillhalten. Der Hersteller beobachtet bei 10,5 Nm nach 9 min 11 s 100 °C
Motortemperatur und bei 8,5 Nm nach 90 min 98 °C am Motor sowie 90 °C an der Platine. Das sind
Versuchsbeobachtungen unter den jeweiligen Herstellerbedingungen, keine sichere Haltezeit dieses
Arms; keine Interpolation. Zweck und Dauer der Übergabehalte sowie gewünschte thermische Entlastung
bleiben Eigentümer- und Prüfstandsfragen.

| Reihenfolge | Option | Verhalten und Aufwand |
|---|---|---|
| a | Gegengewicht an J2/J3 | Passiv, keine Elektrik; zusätzliche Masse/Trägheit und Befestigung. Gesamtes Fenster mit und ohne Probe prüfen. J3-Ausgleich belastet auch J2. |
| a | Feder / Gasfeder | Weniger konzentrierte Ausgleichsmasse möglich; Anlenkung, Kraftkennlinie, Hysterese, Temperatur und Versagen zu prüfen. Kein belegter Gesamtausgleich. |
| b | Aktive Haltung, bestätigtes abgestütztes Parken | Minimale Zusatzteile; thermisch offen, unerwarteter Spannungsverlust ungesichert. Keine SP02-konforme Parklage qualifiziert. |
| c | Formschlüssiger Parkbolzen | Nur bei bestätigtem vollständigem Eingriff in einer definierten Pose wirksam; keine Fangfunktion im Arbeitsbereich. Manuell erst entlasten, dann entriegeln. |
| d | Bremse | **Nur Folgemodell.** Zusätzliche Mechanik, Elektrik, Schaltlogik und Prüfungen; kein Teil der Erstprototyp-Empfehlung. |

Das abgeleitete Gegengewichtsbeispiel spiegelt vorhandene Nicksegmente. J3 erhält rechnerisch 2,452
kg, J2 anschließend 5,287 kg; zusammen 7,739 kg. Die Referenzpose liegt außerhalb SP02. Trotz
Nullmoment an J2/J3 in dieser Referenz bleiben beladen im SP02-Fenster Zeugenrestmomente von rund
1,808 Nm an beiden Gelenken; die oberen Hüllen und alle Posen stehen im Bericht. Damit verfehlt
**dieses Beispiel** das Modellkriterium für stromloses Nicht-Absinken, auch ohne Probe; die
Vergleichsgrenzen mit Faktor 2 Abstand liegen bei 0,8 Nm für J2 und 0,1 Nm für J3. Die zusätzliche
Trägheit steht dem Ziel zügiger Bewegungen entgegen. Kein Gegengewicht ist eingebaut; Freigang,
sichere Befestigung und Federrestmoment generell bleiben offen. Thermische Entlastung und stromloses
Halten getrennt prüfen.

[ACE
GS-15-50](https://www.ace-ace.de/de/produkte/geschwindigkeitsregulierung/industrie-gasdruckfedern/gs-8-bis-gs-70/gs-15/gs-15-50.html)
ist eine belegte Federreferenz: 50 mm Hub, 127 mm ausgefahren, maximal 400 N, 66 g, 30–40 %
Progression, 51,04 EUR netto Herstellerlistenpreis am 20.11.2026, Brutto hier `null`. Füllkraft,
Endstücke, Befestigung und Drehmomentkurve sind nicht gewählt. Externer Endanschlag erforderlich;
nicht als Verriegelung ansetzen. [Ganter GN
617-8-AK-NI](https://www.ganternorm.com/de/produkte/3.1-Rasten-Arretieren-Sperren-mit-Bolzen-und-Kugeln/Rastbolzen-Arretierbolzen/GN-617-Rastbolzen-Edelstahl-ohne-Rastsperre)
belegt einen 8-mm-Parkbolzen, M16×1,5, Nennlänge 69 mm;
[Normblatt](https://live-katalog.ganternorm.com/pdf/ganter/de/617.pdf?dispositiontype=attachment),
S. 1. Seine Federkraft ist keine zulässige Gelenkhaltekraft. Preis, Einbauradius, Führungsspalt,
Aufnahmefestigkeit und qualifiziertes Haltemoment bleiben `null`.

## Bremse und Positionsversatz des späteren Modells

Die generische [Kendrion 86
62109H00-0060](https://www.kendrion.com/en/productfinder/group/product/brakes/86-62109h00-0060)
belegt 22 Nm statisch, Ø115 × 56 mm, 1,1 kg, 24 V / 17 W, Nabenelement Ø30 mm mit Passfedernut und
stromlos wirkendes Permanentmagnetprinzip. Preis und belegte Handlüftung bleiben offen. Die
vorgeschlagene Anbindung hinter einem MYACTUATOR-Getriebe ist **nicht herstellerbestätigt**; sie
bräuchte separate Ausgangswelle, Kupplung und feste Aufnahme. Systemseitiges Fail-safe, Schaltzeiten
und Positionsversatz sind nicht nachgewiesen. Die Wirklage einer angebotenen integrierten
MYACTUATOR-Bremse bleibt ebenfalls `null`.

Eine motorseitige Bremse lässt Getriebe → Ausgangslager → Platte → Glied → weitere Gelenke → Flansch
zwischen Bremsstelle und Werkzeug. Eine direkt an der Gelenkwelle wirkende Ausgangsbremse überbrückt
das **lokale** Getriebespiel; Ausgangsaufnahme, Struktur und alle distalen Gelenke bleiben in der
Kette. Anlegeversatz und Nachgiebigkeit bleiben Messgrößen, nicht konstruktiv null.

15′ = 0,25° ergeben bei Momentenumkehr die Bogenabschätzung `delta = lever * backlash_rad`. Home,
Bezug auf `flange_reference`:

| Gelenk | Senkrechter Hebel mm | Spielbeitrag mm |
|---|---:|---:|
| J1 | 287,06 | 1,253 |
| J2 | 287,59 | 1,255 |
| J3 | 226,12 | 0,987 |
| J4 | 114,24 | 0,498 |
| J5 | 116,00 | 0,506 |
| J6 | 0,00 | 0,000 |

Die lokale linearisierte Summe ist 4,499 mm, kein globaler realer Gesamtfehler. Bei der gestreckten
J2-Zeugenpose beträgt sie 6,061 mm. J6s Nullbeitrag gilt nur für die achsnahe Flanschreferenz;
seitliche Werkzeuge und reale SP02-TCP-/Schwerpunktlagen benötigen eine neue Auswertung.
Nachgiebigkeit und Versatz beim Abschalten/Freigeben bleiben `null`.

Beim Erstprototyp sind diese Werte **Messziele**, kein Akzeptanzfilter der Konzeptwahl. Nur für das
spätere Bremse-Modell wird ≤0,2 mm physischer Werkzeugversatz beim Anlegen/Lösen unter Last als
`status: proposed` zur Eigentümerentscheidung gestellt. Kompensationsbedarf wird markiert, keine
Nachführung implementiert. Ausgangsgeber erfassen den Winkel einschließlich Spiel, aber keine
Verformung dahinter; X2/X4 nominal 18 Bit, X6 17 Bit. Die X4-PDFs zeigen 17/18 Bit ohne eindeutige
Eingangs-/Ausgangszuordnung; diese Zuordnung ist vor Umsetzung gesondert zu bestätigen.

Spätere Steuerungsanforderung: Sollposition halten, Bremse anlegen und Wirkung bestätigen, erst dann
Servomoment abbauen; vor dem Lösen Moment wieder aufbauen. Ein Servo kann hinter einer angelegten
Ausgangsbremse nicht nachführen. Kompensation ersetzt keinen physischen Versatznachweis an einer
Probe in Kontakt. Bremsen nur an begründeten Griff-/Übergabe-/Ablage-/Parkhalten vorsehen, nie an
Transit- oder Freiraummarken. Schaltzeiten gehören zur Haltedauer.

## Budget und begrenzter Harmonic-Ausstieg

Die unveränderten **700 EUR** umfassen Motorplatten, Struktur, Lagerung und Haltesicherung
gemeinsam. Die bevorzugten drei 6001-Ringe ergeben abgeleitet 8,31 EUR brutto; das ist nur ein
bekannter Teilbetrag.

| Mechanikposition | Bekannter Bruttobetrag EUR |
|---|---:|
| Drei Radialgegenlager, nur Ringe | 8,31 |
| Motorplatten und Struktur | `null` |
| Wellen und Hülsen | `null` |
| Lagergehäuse, Retention und Befestigungen | `null` |
| Halte-/Parkhardware | `null` |
| Gewichtsausgleich | `null` |
| Mehrmaterial | `null` |
| **Gesamt / Einhaltung 700 EUR** | **`null` / offen** |

691,69 EUR verbleiben rechnerisch für unbekannte Positionen; das ist keine Budgetfreigabe. Die
günstigste vollständig tragfähige Kombination unter 700 EUR und die Differenz zur Präferenz bleiben
`null`, solange Tragfähigkeit und Gesamtkosten fehlen. Bei Überschreitung die Position nicht
erhöhen, sondern eine vollständig belegte günstigere Kombination oder eine Eigentümerentscheidung
vorlegen. Bremsenversorgung, Ansteuerung, Verkabelung und Abschaltung gehören zur getrennten
Elektrikposition; deren Betrag bleibt hier offen.

Der [RH-Harmonic-Familienartikel
MBS-MYA-07](https://www.mybotshop.de/MYACTUATOR-RH-Serie-Harmonic-Module-dual-encoder) nennt
Varianten und Preis auf Anfrage, keinen ausgewählten Ersatz samt Preis. Exakter Artikel,
Lastgrenzen, Bremslage und Budgetdifferenz bleiben `null`; keine Anfrage, Bestellung oder
Kontoanlage. Der Ausstieg bleibt begrenzt und wird ohne Angebot nicht numerisch schön gerechnet.

## Sechs Eigentümerentscheidungen

1. **Lagerkonzept je Gruppe:** Ein einfaches Radialgegenlager für J2/J3/J5
   bevorzugen, vorhandene Ausgangslager an J4/J6 und J1 nur bedingt weiterführen.
   Empfehlung: Konzeptpräferenz bestätigen; Fertigungsentscheidung erst nach
   Kippmoment-, Steifigkeits- und Einbaunachweis in Phase 2. Kein bereits
   akzeptiertes Konzept ohne Plattenrevision behaupten.
2. **Toleranz des Bremse-Modells:** Empfehlung: ≤0,2 mm beim Anlegen/Lösen als
   Vorschlag untersuchen. Für den Erstprototyp Spiel und Nachgiebigkeit messen;
   noch keine solche Abnahmegrenze oder Positionsneutralität zusichern.
3. **Werkzeugmasse:** Empfehlung: 0,50 kg plus 0,02 kg Gefäß/Probe vorläufig als
   Planwerte entscheiden und alle realen SP02-Teilmasse-/Schwerpunktlagen messen.
   Bei Abweichung neu rechnen; Planwerte sind keine garantierte Lastobergrenze.
4. **Spannungsverlust:** Restrisiko für den Zeitgewinn akzeptieren oder Bremse
   vor einem Prototypbetrieb verlangen? Empfehlung: derzeit keine Freigabe,
   bis tatsächlicher Kontakt-/Anschlagweg und Schutzmaßnahmen bekannt sind.
   Eine verlangte Bremse bedeutet einen gesonderten, erneut zu entscheidenden
   Ausbauauftrag; die vorliegende Erstprototyp-Empfehlung bleibt bremsenfrei.
5. **Faltbarkeit und Parken:** Empfehlung: eine bestätigte abgestützte Parklage
   innerhalb SP02 auslegen; die vorhandene MB01-Pose nicht übernehmen.
   Zulässiges manuelles Rücktreiben und Rückspeisung in Treiber vom Hersteller
   bestätigen lassen. Im Bremse-Modell Handlüftung samt sicherer Lastübernahme
   gegen stromloses Halten priorisieren und deren Kosten offenlegen.
6. **Budget:** Empfehlung: 700-EUR-Grenze beibehalten und Platten-/Struktur-,
   Wellen-, Halte- und Ausgleichskosten ergänzen. Bei Überschreitung zuerst
   einfachere belegte Kombination bewerten; aktuell ist keine Gesamtsumme belegt.

## Prüfung und Übergang zu Phase 2

Einstieg: `python3 scripts/joint_bearings_holding.py`, Reproduktion mit `--check`. Die
Quell-/Rechenprüfungen decken Pins, unabhängige Handrechnung, Hüllen, Kräfteaufteilung, Spiel,
Budget und erhaltene `null`-Werte ab; genaue Testergebnisse gehören zum jeweiligen Arbeitsbericht.
Ein erfolgreicher Modelltest wäre kein physischer Lager-, Halte-, Sicherheits- oder biologischer
Nachweis.

Der Galeriecheck scheiterte bereits auf dem **unveränderten Ausgangsstand `84c61cb`** mit
`Image dependency changed: model/robot.json`; der Ausgangsbefund ist unter
`exports/joint-bearings-holding/gallery-baseline.log` erhalten. Phase 1 repariert diese bestehende
Bindung nicht und behauptet keinen grünen Galerienachweis. Historische Medien und ihre Provenienz
bleiben unverändert.

Bei der Übernahme am 21. November 2026 scheitert der Galeriecheck auch auf dem unveränderten
Integrations-Ausgangsstand `ce2e308`, nun mit `Source changed:
model/synthetic-cf01-workspace.shared.json`. Dieser eigenständige Befund bleibt offen. Der
CF01-Bewegungsquellen-Pin der Konzeptquelle wird an diesen master angepasst; die dortigen
Bewegungsgrenzen bleiben unverändert. Der neu berechnete Bericht ändert keine Last- oder
Bewertungsergebnisse.

Offen sind reale Massen/Schwerpunkte, Haltezyklen, zulässige kombinierte Lagerlasten, innere
Lagerzentren, Passungen, Nachgiebigkeit, Rücktreib-/Rückspeiseverhalten, Parkkontakt und
tatsächliche Spannungsverlustfolgen. Solange keine Alternative Bauraum und Last ohne Plattenrevision
nachweist, den Befund als Entscheidungs- und Abbruchbedingung berichten; keine Platte improvisieren.

Phase 2 beginnt erst mit der Eigentümerentscheidung und einem eigenen Auftrag: portable semantische
Operation „Lagerstelle“ in Quelle/Schema und allen FreeCAD-/SolidCraft-/ROS-Ableitungen, konkrete
Plattenrevisionen, Wellen und Sitze, SP02-Kabel-/Schlauchfreigang, native Kollisions- und
Lastprüfungen sowie Prüfstandsmessungen. Danach neue Build-Berichte und Quell-/Artefaktpins
erzeugen, alle betroffenen Aufstellungen und Galeriebindungen neu validieren. Die anfängliche
Phase-1-Arbeit endete ohne Merge oder Push. Der Eigentümer hat deren Übernahme nach master und
Push am 21. November 2026 gesondert beauftragt; Phase 2 bleibt offen. Ein neuer Pages-Stand ist
nicht Teil dieser Veröffentlichung.
