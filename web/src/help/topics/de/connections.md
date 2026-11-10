---
title: Delve mit anderen Diensten verbinden
summary: Bilder von Replicate oder deinem eigenen Server, Anmeldung mit Google und der Name in der Datenschutzerklärung.
---
Nur der Besitzer sieht **Einstellungen → Verbindungen**. Ein Token, das du dort speicherst, bleibt in den Dateien
dieses Rechners, und Delve zeigt es nie wieder: Es sagt nur, ob eines gesetzt ist. Eine Änderung gilt sofort, ohne
Neustart.

- **Replicate** malt Porträts, Szenen und Besitztümer, gegen Bezahlung. Füge sein **Token** ein. Ein
  `REPLICATE_API_TOKEN` in der Umgebung geht vor einem gespeicherten Token.
- **assetgen** ist dein eigener Bildserver, auf diesem Rechner oder in deinem Netzwerk. Gib seine **URL** an, und ein
  Token, falls er eines braucht.
- **Anmeldung mit Google** lässt Leute sich mit Google anmelden und registrieren. Erstelle in der Konsole von Google
  Cloud einen OAuth-Client vom Typ Webanwendung und registriere die Adressen unter **Zu registrierende
  Weiterleitungs-URIs** als seine autorisierten Weiterleitungs-URIs. Füge dann hier **Client-ID** und
  **Clientschlüssel** ein.
- **E-Mail** verschickt Bestätigungen, Passwort-Zurücksetzen und Tischnachrichten über Emailit. Füge seinen
  **Emailit-Schlüssel** ein, gib den **Absender** und deine **Öffentliche Adresse** an und drücke **Testen**.
  [E-Mail mit Emailit einrichten](/help/email-setup) führt durch Schlüssel und DNS-Einträge.
- **Datenschutz und Bedingungen** sagt, wer dieses Delve betreibt, wie es die öffentliche
  [Datenschutzerklärung](/privacy) und die [Bedingungen](/terms) zeigen. Fülle **Dein Name** und eine
  **Kontakt-E-Mail** aus.

Jede Zeile hat **Speichern**. Replicate, assetgen und die Anmeldung mit Google haben außerdem **Entfernen**, sobald sie
gesetzt sind, und Replicate, assetgen und E-Mail haben **Testen**: Nutze es, um die Verbindung zu prüfen, bevor sich
Spieler darauf verlassen (bei E-Mail geht eine Test-E-Mail an deine eigene bestätigte Adresse). Sobald ein Bilddienst verbunden ist, wählst du unter [Backends](/help/backends), welche Aufgaben ihn
nutzen.

Google schickt einen Browser nur an https-Adressen und an diesen Rechner zurück, also erscheinen die Google-Schaltflächen
dort und nicht auf den Adressen deines lokalen Netzwerks, wo die Spieler ihre Passwörter benutzen.

<figure><img src="/help/connections-tab.webp" alt="Verbindungen: Replicate und assetgen, jeweils mit Speichern und Testen" width="976" height="590" loading="lazy"></figure>
