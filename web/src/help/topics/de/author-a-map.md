---
title: Karten erstellen
summary: Zeichne oder schreib die Verlieskarten eines Moduls im Karteneditor, und importiere oder zeichne Weltkarten.
---
Die Karten eines Moduls sind seine Verliese und Gebäude. Im Spiel zeigen sie den Spielern nur, was ihre Charaktere
gesehen haben.

## Wo Karten liegen

**Karten** listet die Module, die Karten haben; jede Karte öffnet sich im Editor. Eine Karte, die eine Kampagne
spielt, verlinkt auch auf ihre DM-Ansicht in dieser Kampagne.

Auf der Seite eines Moduls listet der Reiter **Karten** seine Karten. Gib einer **Neue Karte** einen Namen und eine
**Rolle**: **Karte** für eine zum Spielen, **Bibliothek** für gemeinsame Teile, die andere Karten einbinden. Wähle
**Karte hinzufügen**. **Zum Standard machen** legt die Karte fest, die ein Text nutzt, wenn er keine nennt.

**Eine Karte zeichnen lassen** zeichnet eine aus einer Beschreibung, als Entwurf: **Behalten** oder **Verwerfen**.

## Der Editor

Der Editor zeigt den Code der Karte und ihre Zeichnung nebeneinander; auf dem Handy sind es zwei Reiter, **Code** und
**Zeichnung**. Zeichne mit den Werkzeugen, und der Code wird für dich geschrieben, oder schreib den Code und sieh zu,
wie die Zeichnung folgt. Halte die Maus über ein Werkzeug für seinen Namen und wie es funktioniert, etwa
**Rechteckiger Raum**, **Gang** oder **Tür**. Der Editor listet Fehler und Warnungen, während du arbeitest.

- **Speichern**, oder Strg+S. **Drucken** öffnet eine Druckansicht; speichere vorher.
- **Ausgang** führt zu einer anderen Karte des Moduls: Wer darauf tritt, bringt die Gruppe dorthin.
- Eine Tür kann **Mit Falle** sein und ein Ausgang **Geheim**: Die Spieler sehen beides nicht.
- **Vorlagenbild** lädt ein Bild, etwa die Karte des Buchs, zum Nachzeichnen. Es bleibt in deinem Browser.

<figure><img src="/help/map-editor.webp" alt="Der Karteneditor: links der Text der Karte, rechts ihre Zeichnung, darüber die Zeichenwerkzeuge" width="1280" height="800" loading="lazy"></figure>

## Die Kartensprache

Eine Karte ist ein kurzer Text. Diese hier hat zwei Räume, verbunden durch einen Gang, mit einer verschlossenen Tür
zum Brunnen:

```dmap
include "core.dmap"

map "The Old Well" {
  grid { cell 32 px units feet 10 bounds 24 x 12 }
}

room "entrance" {
  rect 1,3 6 x 6
  label "1"
}

corridor "passage" {
  width 1
  segment line from 7,6 to 14,6
}

room "well_room" {
  rect 14,2 8 x 8
  label "2"
  feature well at 18,6
}

door at 7,6 { connects room.entrance, corridor.passage type wooden state closed }
door at 14,6 { connects corridor.passage, room.well_room type wooden state locked }
```

Eine Schlüsselüberschrift im Text des Moduls, etwa `## 2. Well Room`, verlinkt sich selbst mit dem Raum desselben
Namens, hier `well_room`.

## Die eigenen Karten einer Kampagne

Auf der Seite einer Kampagne enthält unter **Karten** der Bereich **Die eigenen Karten dieser Kampagne** Karten, die
nur für diesen Tisch gemacht sind, etwa ein Stadtviertel, das die Spieler erfunden haben. Gib den **Name der neuen
Karte** an und wähle **Die Karte erstellen**. Das Modul ändert sie nie.

## Weltkarten

Weltkarten sind fürs Reisen: Land, Orte, Straßen und Flüsse. Sie gehören zu einem Modul, einer Kampagne oder einer
Welt, jeweils unter deren **Weltkarten** oder **Karten**.

1. Wähle **Eine Weltkarte importieren**: **Einer GeoJSON-Datei** oder **Einem Bild mit seiner Legende**, mit seinem
   Raster und dem, was ein Hexfeld oder Quadrat misst.
2. Eine aus einem Bild gelesene Karte bleibt **In Prüfung**, unsichtbar für die Spieler, bis du **Prüfen** wählst,
   ihre Zweifel klärst und **Die Karte annehmen**.
3. **Bearbeiten** zeichnet Orte, Straßen, Flüsse, Regionen, Seen und Meere und malt Gelände mit dem
   **Geländepinsel**.

Auf der Weltkarte einer Kampagne legt **Was die Gruppe zu Beginn weiß** fest, was die Spieler zuerst sehen: **Alles**,
**Nichts**, **Einige Regionen** oder **Eine auf der Karte gezeichnete Fläche**.
