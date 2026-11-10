---
title: Konten und Registrierung
summary: Spieler hinzufügen, Organisatoren ernennen, die Registrierung öffnen, Leute hereinlassen und ihnen Links zum Zurücksetzen geben.
---
Jedes Konto dieses Delve steht auf der Seite Spieler: Öffne **Einstellungen**, den Reiter **Spieler**, dann **Spieler
öffnen**. Auch Organisatoren können diese Seite nutzen; manche Aktionen sind nur dir vorbehalten.

## Wer was darf

- Spieler erreichen ihre eigenen Tische, die Spielbildschirme, die **Einstellungen** und die Regelwerke.
- Organisatoren starten außerdem Kampagnen, kümmern sich um Module und Hausregeln, legen die Backends fest und
  verwalten hier die Konten der Spieler.
- Besitzer dürfen alles. Nur ein Besitzer wählt **Zum Organisator machen** oder **Zum Besitzer machen** (und
  **Organisatorrolle entziehen**, **Besitzerrolle entziehen**), und nur ein Besitzer deaktiviert das Konto eines
  Organisators oder Besitzers oder setzt es zurück. Das letzte Besitzerkonto bleibt Besitzer.

## Woher Konten kommen

- Von einem Einladungslink: Wer den Einladungslink eines Tisches öffnet, kann ein Konto erstellen.
- Von dieser Seite: Gib einen **Benutzername**, einen **Anzeigename** und eine **Sprache** ein und wähle dann **Einen
  Spieler hinzufügen**. Delve zeigt einen Link, der das Passwort setzt. Schick ihn dem Spieler: Er funktioniert
  einmal, innerhalb von 24 Stunden.
- Von der Registrierung: Leute beantragen selbst ein Konto (siehe unten).
- Von der Kommandozeile: `uv run delve account add <username>` erstellt ein Konto und fragt nach seinem Passwort.
  Füge `--organiser` oder `--owner` für diese Rechte hinzu.

## Registrierung mit Freigabe

Die Registrierung ist aus, bis du **Leute ein Konto beantragen lassen** anhakst. Solange sie an ist, bietet die
Anmeldeseite **Kein Konto? Beantrage eines** an. Jedes neue Konto wartet unter **Wartet auf Freigabe**, mit der Zeile,
die die Person darüber geschrieben hat, wer sie ist. Das Menü zeigt, wie viele warten.

- **Hereinlassen**: Das Konto kann sich ab jetzt anmelden.
- **Abweisen**: Das Konto wird gelöscht, und sein Benutzername ist wieder frei.

Wer wartet und sich über den Einladungslink eines Tisches anmeldet, wird dadurch hereingelassen. Jede Adresse darf
3-mal pro Stunde fragen, und höchstens 20 Registrierungen warten gleichzeitig.

<figure><img src="/help/players-waiting.webp" alt="Eine Registrierung unter Wartet auf Freigabe, mit ihrer Notiz, Hereinlassen eingekreist und Abweisen daneben" width="984" height="170" loading="lazy"></figure>

## Vergessene Passwörter und Probleme

- **Passwort vergessen?** auf der Anmeldeseite fragt nach einem Benutzernamen oder, wenn Delve Mails verschickt,
  nach einer E-Mail-Adresse. Ein Konto mit bestätigter Adresse bekommt seinen Link zum Zurücksetzen per Mail,
  höchstens 3 pro Stunde; auf dich wartet keine Anfrage. Die Anfrage jedes anderen Kontos wartet hier, unter **Haben
  um ein neues Passwort gebeten**, bis du seinen **Link zurücksetzen** erstellst oder sie verwirfst.
- **Link zurücksetzen** erstellt einen neuen Link zum Setzen des Passworts für das Konto; sein älterer, ungenutzter
  Link funktioniert dann nicht mehr. Ein Zurücksetzen trennt auch jedes damit verknüpfte Google-Konto.
- **Deaktivieren** sperrt das Konto und meldet es überall ab; **Aktivieren** holt es zurück. Dein eigenes Konto kannst
  du nicht deaktivieren. Konten werden nie gelöscht, außer einer Registrierung, die du abweist.

## Google-Konten

Sobald du die Anmeldung mit Google unter [Verbindungen](/help/connections) eingerichtet hast, können sich Leute mit
Google registrieren und anmelden. Auch eine Registrierung mit Google wartet auf Freigabe. Wer ein Konto hat, kann im
Reiter **Profil** **Dein Google-Konto verknüpfen** wählen. Delve ordnet ein Google-Konto nur dem Konto zu, das es
verknüpft hat oder sich damit registriert hat, nie über seine E-Mail-Adresse.
