---
title: Die Backends wählen
summary: Welches Claude-Modell und welchen Aufwand jede Aufgabe nutzt, welcher Dienst die Bilder malt und die Sprache der Installation.
---
**Einstellungen → Backends** wählt, wer jede Aufgabe von Delve übernimmt. Auch Organisatoren können das ändern. Eine
Änderung gilt ab dem nächsten Beat.

## Die Aufgaben

Jede Aufgabe hat einen **Anbieter**, ein **Modell** und einen **Aufwand**. **Standard** überlässt die Wahl dem
Anbieter.

| Aufgabe | Was sie tut |
|---|---|
| **DM** | Erzählung und Regeln, in jedem Beat |
| **Hilfsaufgaben** | Frag den DM, Vorschläge, Bildanweisungen |
| **Übersetzung** | Die Worte der Spieler ins Englische, die des DM aus dem Englischen |
| **Modulumwandlung** | PDFs zu Modulen, generierte Verliese |
| **Gründliche Umwandlung** | PDFs zu Modulen, mit den Seitenbildern abgeglichen (nur Claude CLI) |
| **Romane** | Kampagnen und Module als Romane geschrieben |
| **Porträts** | Charaktere und NSCs |
| **Szenen** | Orte und Momente der Geschichte |
| **Besitztümer** | Festungen, Reittiere, Schiffe und dergleichen |

## Claude

Die Textaufgaben nutzen **Claude (claude -p)**, die Kommandozeile `claude` mit deinem Abo. Sie wird nur angeboten,
wenn `claude` im `PATH` der Shell liegt, die Delve gestartet hat. Ihre Modelle sind **Opus (am leistungsfähigsten)**,
**Sonnet** und **Haiku (am schnellsten)**. Ein höherer Aufwand denkt länger nach. **Automatisch** nutzt einen
niedrigen Aufwand für Routine-Beats und einen hohen, wo die Regeln schwierig werden.

## Bilder

- **portraitgen (kostenlos)** zeichnet Porträts im Browser, ohne Kosten. Es macht nur Porträts.
- **Replicate** und **assetgen** erscheinen, sobald du sie unter [Verbindungen](/help/connections) verbindest. Jedes
  Modell zeigt seinen Dienst und seinen Preis, oder **kostenlos**.

Ein bezahltes Modell für Szenen oder Besitztümer malt nur, wenn der Gastgeber eines Tisches **Bezahlte Bilder**
einschaltet.

<p class="note">Ein Anbieter, der mit (development) markiert ist, dient zum Testen von Delve: Seine Bilder sind
Platzhalter, und sein DM folgt einem Skript. Wähle ihn nicht zum Spielen.</p>

## Wenn eine Wahl nicht nutzbar ist

- Hat ein Anbieter gerade ein Problem (zum Beispiel ist assetgen nicht erreichbar), behält die Aufgabe deine Wahl und
  zeigt **Nicht nutzbar:** und den Grund. Sie funktioniert wieder, sobald der Anbieter es tut.
- Ist ein Anbieter weg (du hast seine Verbindung entfernt), fallen die Aufgaben, die ihn gewählt hatten, auf ihren
  Standard zurück, und der Reiter sagt das ganz oben.

## Der Rest des Reiters

Dieser Reiter enthält auch den **Bildstil** (siehe [Erscheinungsbild und Bildstile](/help/looks-and-image-styles))
und die **Sprache** der Schaltflächen und Beschriftungen auf dieser Installation. Wähle **Speichern**, wenn du fertig
bist.

<figure><img src="/help/backends-jobs.webp" alt="Backends und Modelle: jede Aufgabe mit ihrem Anbieter, Modell und Aufwand" width="984" height="800" loading="lazy"></figure>
