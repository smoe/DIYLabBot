# Kellerplan und ergänzende Angaben zum ersten OG

Erfassungsstand: 12. November 2026. Arbeitsnotizen aus den privat bereitgestellten
Planfotos und den Angaben des Eigentümers. Die Fotos werden nicht ins Repository
übernommen. Die folgende Abschrift ist keine vermessene Geometrie.

## Keller · Plan HIS 5540

Quelle: ursprüngliches Keller-Planfoto im Chat. Raumkennungen sind hier mit
Punkt geschrieben; der Plan verwendet teilweise Kommas.

| Kennung | Im Plan lesbare Bezeichnung |
|---|---|
| 0.001 | Kältetechnik |
| 0.002 | Lager |
| 0.003A | Server / Prozesszentrum |
| 0.003B | ELT |
| 0.004 | IT/BMA/TK-Anlage |
| 0.005A | ELT |
| 0.005B | Batterieraum |
| 0.006 | Lager |
| 0.007 | Flüssigstickstoff |
| 0.008 | RLT-Zentrale |
| 0.009 | Lager |
| 0.010 | FMR Aufzug |
| 0.011 | Kühlraum |
| 0.012 | Lager |
| 0.013 | Lager |
| 0.014A | Keine Nutzungsbezeichnung lesbar |
| 0.014B | Garderobe |
| 0.014C | Garderobe |
| 0.015 | Technik / Druckluft |
| 0.016 | Sanitärzentrale |
| 0.017 | Heizung |
| 0.018 | Keine Nutzungsbezeichnung lesbar |
| 0.019 | Umlaufender Erschließungsbereich; keine Nutzungsbezeichnung gedruckt |
| 0.020 | Keine Nutzungsbezeichnung lesbar |

„Kompressoren“ steht separat im unteren rechten Planbereich. Eine eindeutige
Zuordnung dieser Beschriftung zu 0.020 ist anhand des Fotos nicht gesichert.
Der Aufzug ist separat von 0.010 dargestellt. Aus „FMR Aufzug“ wird daher
keine Kabinenfläche abgeleitet. Maße, Geschosshöhe und metrische Registrierung
zu EG/OG sind offen.

## Erstes OG · Raum 1.008

Quelle: zusätzliches Planfoto HIS 5540 und ausdrückliche Eigentümerangaben.

- Planbezeichnung: „Teeküche/Aufenthalt“.
- Tatsächliche Nutzung laut Eigentümer: Küche.
- Ursprünglich als große gemeinsame Küche für alle Stockwerke vorgesehen;
  diese stockwerksübergreifende Nutzung wird so nicht gelebt.
- Am Fenster stehen zusammengeschobene Tische mit Stühlen ringsum.
- Zwei ergänzende Innenfotos zeigen den Blick von der Tür zum Fenster und
  den Gegenblick aus der Raummitte zum Flur. Die Originalfotos bleiben außerhalb
  des Repositories.
- Vom Eingang zum Fenster betrachtet: links eine orange-rote Küchenzeile mit
  runder Edelstahlspüle nahe der Tür, Mikrowelle, Wasserkocher und Oberschränken
  mit offenem Tassenregal; rechts eine weitere orange-rote Zeile mit Arbeitsfläche,
  Kaffeemaschine und kleinem Tischbackofen.
- Am Fenster stehen helle zusammengeschobene Tische, blaue Polsterstühle und
  ein Bürodrehstuhl am türseitigen Tischende; Pflanzen stehen auf der Fensterbank.
- Zwei helle Unterbaugeräte sind nahe der Tür unter der linken Zeile sichtbar.
  Eine eindeutige Kühlschrankzuordnung ist aus den Fotos nicht bestätigt.
- Maße, genaue Möbelpositionen und die vollständige Anzahl der Sitzplätze
  bleiben offen. Die Fotos liefern keine metrische Kalibrierung.

Die OG1-Angaben beschreiben den Bestand als Referenz für die gewünschte
Modellmöblierung, keinen realen Umbauauftrag. Sie werden nicht
auf die Räume 2.008 oder 3.008 übertragen. Das bestehende Gebäudemodell verwendet
für OG1–3 noch die F03-Vorlage; diese Notizen ändern dessen Geometrie nicht.

## Bürozuordnungen · erstes bis drittes OG

Quelle: ausdrückliche Eigentümerangaben im Chat vom 12. November 2026.

| Raum | Bestätigte Nutzung |
|---|---|
| 1.002 | Doktorandenbüro |
| 2.002 | Doktorandenbüro |
| 3.002 | Doktorandenbüro |
| 3.009 | Büro des Eigentümers |

Diese Zuordnungen dienen als Grundlage für die gewünschte Ausstattung der
Denk- und Schreibbereiche mit Bürostühlen. Anzahl und Aufstellung der
Arbeitsplätze sowie konkrete Möbelmaße sind noch offen; aus der gleichen
Raumnummer wird keine identische Einrichtung der drei Doktorandenbüros
abgeleitet. Die darauf aufbauende Modellmöblierung ist unten beschrieben.

## Modellmöblierung · Küche und Büros

Die Aufstellung in `model/furnishings/building-social.json` referenziert die
wiederverwendbaren Teile aus `model/furniture/social.catalog.json`. Die gemeinsame
Auswertung `scripts/building_furnishings.py` erzeugt portable Operationen für
FreeCAD und SolidCraft. Die Küche erhält die orange-roten Zeilen, eine runde
Spüle, Mikrowelle, Wasserkocher, Kaffeemaschine, einen schematischen Tischbackofen,
Tassenregal und Tischgruppe mit acht blauen Stühlen, jeweils vier gleichmäßig
an jeder Längsseite; beide Stirnseiten bleiben frei (Eigentümervorgabe vom
13. November 2026, unabhängig von der Fotointerpretation). Im ergänzten
Unterbaukühlschrank versteckt sich ein Pinguin mit Teetasse. Das Unterbaugerät
ist eine Modellannahme; seine Identifikation auf den Fotos bleibt offen.

Die Doktorandenbüros erhalten als Darstellungsannahme jeweils vier Schreibtische
mit Bürodrehstühlen, 3.009 einen Arbeitsplatz. Es sind keine bestätigten
Bestandszählungen. Tisch-, Stuhl- und Geräteabmessungen sind illustrative Werte.

**Einpassungsgrenze:** OG1 verwendet noch die F03-Schablone. Für 1.008 wird
vorläufig der gemeinsame Bereich von `R3_008A` und `R3_008B` verwendet; nur dessen
innere Trennwand wird in der möblierten OG1-Darstellung ausgelassen. Die gleiche
Wand im zweiten und dritten OG sowie die führende F03-Geometrie bleiben erhalten.
Diese Bereichszuordnung ist eine Annahme, keine bestätigte OG1-Raumkontur.
Die lokale Einrichtung wird gleichmäßig in die verfügbare Darstellfläche
skaliert. Die berichtete `presentation_scale` ist keine metrische Registrierung;
es liegt keine Prüfung realer Möbel-, Tür- oder Verkehrsflächen vor.

Aufbau: `python3 scripts/build_building_stack.py --backend both`.
Die zusätzlichen Ansichten `Kitchen1008`, `Kitchen1008_EasterEgg`,
`PhD1002`, `PhD2002`, `PhD3002` und `Office3009` zeigen die Einrichtung ohne
verdeckende Gebäudeteile. Die Easter-Egg-Ansicht blendet die separat modellierte
Kühlschranktür und ihren Griff aus; eine Türbewegung ist nicht implementiert.
