---
title: Module besorgen und bearbeiten
summary: Wandle das PDF eines Buchs um, importiere eine .dscn, lass Claude eines schreiben oder fang leer an; dann prüfe und korrigiere es.
---
Eine Kampagne spielt ein Modul: ein Abenteuer mit seinen Texten, Karten, NSCs und Begegnungen. Wähle unter **Module**
**Neues Modul**. Es gibt vier Wege, eines zu erstellen:

- **Ein leeres Modul**: Gib ihm einen Titel, wähle **Modul erstellen** und schreib den Rest in seinem Editor.
- **Eine .dscn importieren**: Ein aus Delve exportiertes Modul, von hier oder von einer anderen Installation, kommt
  mit seinen Karten, Texten und Einträgen zurück.
- **Aus einem PDF**: Claude macht aus dem Buch eines Moduls Texte, NSCs und Begegnungen, Bilder und Karten und behält
  dabei die eigenen Worte des Buchs. Wähle **Gründlich (Standard)** oder **Schnell**, dann **Bereit zum Spielen** oder
  **Ein Entwurf zum Weiterarbeiten** und **Umwandeln**.
- **Beschreibe das Modul, das du willst**: Schreib **Dein Wunsch** („ein Verlies mit Kobolden, ohne Handlung“) und
  wähle **Generieren**. Claude schreibt ein kleines Modul mit einer skizzierten Karte. Bei einem größeren Wunsch
  stellt es vielleicht zuerst ein paar Fragen.

Du kannst auch ein PDF oder eine `.dscn`-Datei irgendwo auf die Seite ziehen.

Ein leeres Modul und eines, das Claude schreibt, sind auf ihrer Karte als **Eigenbau** markiert; eines, das aus einem
Buch umgewandelt wurde, nicht, und ein Import behält seine eigenen Schlagwörter. Um das zu ändern, setz oder entferne
den Haken bei **Eigenbau** unter den **Details** des Moduls.

<figure><img src="/help/new-module-ways.webp" alt="Neues Modul: ein leeres Modul, aus einem PDF, ein beschriebenes Modul oder ein .dscn-Import, und darunter die Umwandlungen" width="960" height="716" loading="lazy"></figure>

## Während ein Buch umgewandelt wird

Ein großes Buch dauert eine Weile: **Gründlich** kann Stunden brauchen. Die Seite zeigt den Schritt und die fertigen
Seiten, übersteht ein Neuladen, und **Abbrechen** stoppt es, ohne ein halbes Modul zu hinterlassen. Es läuft immer
nur eine Umwandlung; die nächste wartet in der Warteschlange. **Module** zeigt eine laufende Umwandlung ganz oben, und
eine Mitteilung sagt dir, wenn sie fertig ist.

## Prüfen, was die Umwandlung hinterlassen hat

Die Seite des Moduls fasst seine Warnungen in einer Zeile zusammen, etwa „17 Warnungen“. Öffne sie, um sie nach Art
zu sehen, jede verlinkt mit dem, worum es geht. Sieh zuerst nach bei:

- **Aus der Raumlegende skizzierte Karten**: Claude hat die Karte aus der Raumliste gezeichnet, also ist ihr Aufbau
  erfunden. Vergleiche sie mit **Die Seite des Buchs zeigen**.
- **Den Spielern gezeigt: prüfe sie**: Alles andere ist zu Beginn nur für den DM.
- **Zu beschreibende Bilder**: Sag, was jedes Bild zeigt, damit der DM weiß, wann er es einsetzt.

Ein Entwurf kann keine Kampagne starten. Wenn er stimmt, wähle **Als bereit markieren**.

## Ein Modul lesen und bearbeiten

Die Seite des Moduls hat Reiter: **Text**, **NSCs**, **Begegnungen**, **Fraktionen**, **Quests**, **Vorgefertigte**,
**Anhänge**, **Karten** und **Details**.

- In **Text** ist eine Überschrift wie `## 2. The Hall` eine Schlüsselüberschrift: Sie verlinkt sich selbst mit diesem
  Raum auf der Karte. Ein Zitat direkt nach einer Überschrift ist Vorlesetext. Speichere mit **Speichern** oder Strg+S.
- Jeder Text, Eintrag und Anhang ist **Nur DM** oder für die Spieler. Hake mehrere an und wähle **Nur DM** oder **Für
  die Spieler**, um sie auf einmal zu ändern. So öffnest du die Handouts eines Buchs für die Spieler.
- In **Anhänge** schneidet **Zuschneiden…** ein Bild zu: Zeichne den Teil, der bleibt, dreh es um eine Vierteldrehung,
  oder wähle **Teil hinzufügen**, um eine Tafel mit mehreren NSC in ein Bild pro NSC zu teilen. Die Spieler sehen nur
  den Zuschnitt; **Zurücksetzen** gibt das ganze Bild zurück. Eine Konvertierung kann selbst Zuschnitte vorschlagen:
  Prüfe sie und wähle **Passt**.
- Unter **Korrekturkommentare** sagst du in einfachen Worten, was falsch ist. Claude schlägt im Hintergrund eine
  Korrektur vor; **Prüfen** sie, dann **Behalten** oder **Ablehnen**.

Eine Kampagne behält die Revision des Moduls, mit der sie begonnen hat. Um deine Änderungen hineinzuholen, wähle **Auf
die neueste Revision aktualisieren** auf der Seite der Kampagne.

**.dscn exportieren** speichert das ganze Modul als Datei; **Das Modul drucken** öffnet es zum Drucken, einschließlich
des Materials nur für den DM. Hat der Besitzer eine gemeinsame Bibliothek eingerichtet
([Speicher und Sicherung](/help/storage-and-backup)), listet der Reiter **Bibliothek** ihre Module zum
**Herunterladen**.
