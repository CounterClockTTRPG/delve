---
title: Speicher und Sicherung
summary: Was Delve auf diesem Rechner aufbewahrt, der Sicherungsspeicher, der es jeden Tag kopiert, und die mit Freunden geteilte Bibliothek.
---
Delve bewahrt alles auf diesem Rechner auf, in seinem Datenverzeichnis: `~/.local/share/delve` oder dem Ordner, den
`DELVE_DATA_DIR` nennt. Dort liegen die Datenbank (Konten, Kampagnen, Module, Einstellungen), das Besitzer-Token, die
Tokens der Verbindungen und jede hochgeladene Datei.

**Einstellungen → Speicher**, das nur der Besitzer sieht, fügt zwei Speicher anderswo hinzu. Jeder ist ein eigener
Container oder Bucket: Delve weigert sich, beide in denselben zu legen.

## Einen Speicher wählen

Wähle für jeden Speicher einen **Anbieter**:

- **Azure Blob Storage**: Füge die **SAS-URL** des Containers ein.
- **Cloudflare R2**: deine **Konto-ID**, den **Bucket**, die **Zugriffsschlüssel-ID** und den **Geheimer
  Zugriffsschlüssel**.
- **S3-kompatibel**: den **Endpunkt**, den **Bucket**, die **Zugriffsschlüssel-ID** und den **Geheimer
  Zugriffsschlüssel**.

Wähle **Speichern**, dann **Testen**: Es zeigt, was der Zugang darf. Eine SAS-URL zeigt, wann sie abläuft. Die
Geheimnisse bleiben in den Dateien dieses Rechners; Delve zeigt sie nie wieder, und keine Sicherung enthält sie.

## Der Sicherungsspeicher

Der **Sicherungsspeicher** gehört nur dir. Sein Zugang braucht Lesen, Auflisten, Erstellen, Schreiben und Löschen.

- Jeden Tag zur Zeit unter **Täglich sichern um** (anfangs 04:00, in der Zeit dieses Rechners) kopiert Delve die
  Module, Kampagnen und Welten, die sich geändert haben. Es behält von jedem die neueste Kopie. Eine Sicherung, die
  verpasst wurde, während Delve aus war, läuft beim Start.
- **Jetzt sichern** führt sofort eine aus. **Letzte Sicherung** sagt, wie sie lief; was fehlgeschlagen ist, wird beim
  nächsten Mal erneut versucht.
- **Wiederherstellen** listet die Sicherungen dieser Installation oder einer anderen Installation, die denselben
  Speicher nutzt. Hake an, was zurückkommen soll, und wähle **Auswahl wiederherstellen**. Eine Kampagne bringt ihr
  Modul mit. Delve fragt, bevor es etwas ersetzt, das schon hier ist.

<p class="note">Die Sicherung enthält Module, Kampagnen und Welten, nicht die Konten, Einstellungen oder Tokens. Die
liegen nur im Datenverzeichnis.</p>

<figure><img src="/help/backup-store.webp" alt="Speicher: der Sicherungsspeicher und der Bibliotheksspeicher, jeder mit seinem Anbieter und seiner SAS-URL" width="1280" height="800" loading="lazy"></figure>

## Der Bibliotheksspeicher

Der **Bibliotheksspeicher** ist mit Freunden geteilt: die Module, die du veröffentlichst, und die, die du
herunterlädst, unter **Bibliothek** auf der Seite Module. Das Recht seines Zugangs bestimmt, was diese Installation
dort darf: **Lesen** (durchsuchen und herunterladen), **Veröffentlichen** (Module hinzufügen, und neue Versionen deiner
eigenen) oder **Verwalten** (auch die von allen ändern und löschen).
