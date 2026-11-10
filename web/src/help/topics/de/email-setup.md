---
title: E-Mail mit Emailit einrichten
summary: Der Schlüssel, die DNS-Einträge und der Absender, mit denen Delve Bestätigungs-, Passwort- und Tisch-Mails verschickt.
---
Delve verschickt E-Mails über [Emailit](https://emailit.com): Bestätigungen von Adressen, Passwort-Zurücksetzen, „Du bist drin“-Mails
und, wenn Leute sie wünschen, Tisch- und Brettnachrichten. Bis du es einrichtest, verschickt Delve nichts, und die
Zeile **E-Mail** unter **Einstellungen → Verbindungen** kann nur ins Protokoll schreiben.

1. Erstelle in Emailit einen API-Schlüssel vom Typ **Sending Only**, beschränkt auf deine Domain. Füge ihn als **Emailit-Schlüssel** ein.
2. Füge deine Domain in Emailit hinzu und trage ihre Einträge in dein DNS ein, wobei `<domain>` deine Domain ist:
   - ein SPF-Eintrag: Typ TXT bei `emailit.<domain>`, Wert `v=spf1 include:_spf.emailit.com ~all`;
   - ein DKIM-Eintrag: Typ TXT bei `emailit._domainkey.<domain>`, mit dem Wert, den Emailit dir zeigt;
   - ein Bounce-Eintrag: Typ MX bei `emailit.<domain>`, auf `feedback-smtp.ffdc-1.emailit.com`;
   - optional ein DMARC-Eintrag: Typ TXT bei `_dmarc.<domain>`, Wert `v=DMARC1; p=none;`.
3. Drücke in Emailit auf **Check DNS** und warte, bis jeder Eintrag grün ist.
4. Wähle in Delve **Emailit** bei **Versand über**, fülle den **Absender** aus (auf deiner Domain, etwa
   `Delve <delve@example.org>`) und die **Öffentliche Adresse** (wo Delve im Internet erreichbar ist, etwa
   `https://delve.example`; Links in Mails beginnen damit) und **Speichere**.
5. Sorge dafür, dass deine eigene Adresse im Profil eingetragen und bestätigt ist, und drücke **Testen**: Eine Testmail geht an sie.

Emailit startet jedes Konto in einer Testphase. Bitte um Produktionszugang; bis du ihn bekommst, erhalten nur die
Adressen der Mitglieder deines Emailit-Arbeitsbereichs Mails.

Die Zeile sagt auch, wie viele Mails heute rausgingen, und zeigt die letzten Fehlschläge mit ihrem Grund. Sie zeigt nie
die Adresse von jemandem. Ein `EMAILIT_API_KEY` in der Umgebung hat Vorrang vor einem gespeicherten Schlüssel.
