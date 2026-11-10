---
title: Delve verbinden met andere diensten
summary: Afbeeldingen van Replicate of je eigen server, inloggen met Google, en de naam in het privacybeleid.
---
Alleen de eigenaar ziet **Voorkeuren → Verbindingen**. Een token dat je daar opslaat, blijft in de bestanden van deze machine, en Delve
toont het nooit meer: het zegt alleen of er een ingesteld is. Een wijziging geldt meteen, zonder herstart.

- **Replicate** schildert portretten, scènes en bezittingen, tegen betaling. Plak zijn **Token**. Een `REPLICATE_API_TOKEN` in
  de omgeving gaat boven een opgeslagen token.
- **assetgen** is je eigen beeldserver, op deze machine of je netwerk. Geef zijn **URL**, en een token als hij er een
  nodig heeft.
- **Inloggen met Google** laat mensen inloggen en een account aanvragen met Google. Maak in de console van Google Cloud een OAuth-client van het
  type Web application, en registreer de adressen onder **Te registreren redirect-URI's** als zijn toegestane redirect-URI's.
  Plak daarna hier de **Client-ID** en het **Clientgeheim**.
- **E-mail** verstuurt bevestigingen, wachtwoordherstel en tafelberichten via Emailit. Plak zijn **Emailit-sleutel**, geef
  de **Afzender** en je **Openbaar adres**, en druk op **Testen**. [E-mail instellen met Emailit](/help/email-setup)
  loopt door de sleutel en de DNS-records.
- **Privacy en voorwaarden** is wie deze Delve beheert, zoals het openbare [privacybeleid](/privacy) en de [voorwaarden](/terms) het tonen.
  Vul **Je naam** en een **Contactadres** in.

Elke rij heeft **Opslaan**. Replicate, assetgen en Inloggen met Google hebben ook **Verwijderen** zodra ze ingesteld zijn, en Replicate,
assetgen en E-mail hebben **Testen**: gebruik het om de verbinding na te kijken voor spelers erop rekenen (bij E-mail
gaat er een testmail naar je eigen bevestigde adres). Zodra een beelddienst verbonden is, kies je welke taken hem gebruiken onder
[Backends](/help/backends).

Google stuurt een browser alleen terug naar https-adressen en naar deze machine, dus de Google-knoppen verschijnen daar en niet op
de adressen van je lokale netwerk, waar spelers hun wachtwoord gebruiken.

<figure><img src="/help/connections-tab.webp" alt="Verbindingen: Replicate en assetgen, elk met Opslaan en Testen" width="976" height="590" loading="lazy"></figure>
