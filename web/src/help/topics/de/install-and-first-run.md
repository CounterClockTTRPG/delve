---
title: Delve installieren und der erste Start
summary: Installiere Delve, starte es, erstelle das Besitzerkonto und öffne es von deinen anderen Geräten aus.
---
Delve läuft als ein Programm auf einem Port auf deinem Rechner. Du bist sein Besitzer: Du hast es installiert, also
hast du alle Rechte.

## Installieren und starten

Du brauchst Python 3.12 oder neuer, [uv](https://docs.astral.sh/uv/) und Node.js. Claude ist der DM über die
Kommandozeile `claude` (Claude Code) mit deinem eigenen Abo, also installiere sie und melde dich zuerst an: `claude`
muss im `PATH` der Shell liegen, die Delve startet.

1. Führe im Ordner von Delve `make install` aus. Es installiert, was Delve braucht, und baut seine Regeldaten.
2. Führe `make run` aus. Es baut die Web-App und startet Delve auf Port 7810. Für einen anderen Port starte es mit
   `uv run delve serve --port <other>`; `--host` ändert die Adresse, auf der es lauscht.
3. Öffne auf diesem Rechner <http://localhost:7810/>.

Führe `make install` erneut aus, nachdem du eine neue Version von Delve geholt hast: Delve startet nicht, wenn seine
Regeldaten fehlen oder veraltet sind.

## Das Besitzerkonto erstellen

Solange es kein Besitzerkonto gibt, ist ein Browser auf diesem Rechner der Besitzer und braucht keine Anmeldung.
Erstelle das Konto, bevor du Delve für das Internet öffnest (über einen Tunnel oder einen Proxy).

- Öffne im Browser auf diesem Rechner die Anmeldeseite und fülle **Das Besitzerkonto erstellen** aus, oder
- führe in einem Terminal `uv run delve account add <username> --owner` aus. Es fragt nach dem Passwort.

Das Besitzerkonto hat alle Rechte, von jedem Gerät aus.

<figure><img src="/help/first-owner.webp" alt="Die Anmeldeseite mit Das Besitzerkonto erstellen darunter, eingekreist" width="480" height="800" loading="lazy"></figure>

## Deine anderen Geräte

In deinem eigenen Netzwerk kann ein anderes Gerät von dir die Anmeldung mit dem Besitzer-Token überspringen. Führe
`uv run delve token` aus: Es gibt für jede Netzwerkadresse des Rechners einen Link aus. Öffne einen davon einmal auf
dem anderen Gerät. Über das Internet wird das Besitzer-Token abgelehnt, und du meldest dich mit deinem Besitzerkonto
an.

Das Besitzer-Token läuft nie ab. Ist ein Link nach außen gelangt, erstelle mit **Neues Besitzer-Token erstellen**
unter **Einstellungen → Speicher** oder mit `uv run delve token --new` ein neues. Das alte Token und seine Links
funktionieren sofort nicht mehr.

## Wo deine Daten liegen

Alles liegt in `~/.local/share/delve` oder in dem Ordner, den `DELVE_DATA_DIR` nennt. Siehe
[Speicher und Sicherung](/help/storage-and-backup).
