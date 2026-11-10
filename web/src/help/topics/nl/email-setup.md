---
title: E-mail instellen met Emailit
summary: De sleutel, de DNS-records en de afzender waarmee Delve bevestigings-, wachtwoord- en tafelmails verstuurt.
---
Delve verstuurt e-mail via [Emailit](https://emailit.com): bevestigingen van adressen, wachtwoordherstel, "je bent binnen"-mails en,
als mensen erom vragen, tafel- en prikbordberichten. Zolang je het niet instelt, verstuurt Delve niets, en de rij
**E-mail** in **Voorkeuren → Verbindingen** kan alleen naar het logboek schrijven.

1. Maak in Emailit een API-sleutel van het type **Sending Only**, beperkt tot je domein. Plak hem als **Emailit-sleutel**.
2. Voeg je domein toe in Emailit en zet zijn records in je DNS, waarbij `<domein>` je domein is:
   - een SPF-record: type TXT op `emailit.<domein>`, waarde `v=spf1 include:_spf.emailit.com ~all`;
   - een DKIM-record: type TXT op `emailit._domainkey.<domein>`, met de waarde die Emailit je toont;
   - een bounce-record: type MX op `emailit.<domein>`, naar `feedback-smtp.ffdc-1.emailit.com`;
   - eventueel een DMARC-record: type TXT op `_dmarc.<domein>`, waarde `v=DMARC1; p=none;`.
3. Druk in Emailit op **Check DNS** en wacht tot elk record groen is.
4. Kies in Delve **Emailit** bij **Verstuurt via**, vul de **Afzender** in (op je domein, zoals
   `Delve <delve@example.org>`) en het **Openbaar adres** (waar Delve op internet staat, zoals
   `https://delve.example`; links in mails beginnen ermee), en **Opslaan**.
5. Zorg dat je eigen adres in je profiel is ingevuld en bevestigd, en druk op **Testen**: er gaat een testmail naartoe.

Emailit start elk account in een proefperiode. Vraag om productietoegang; tot ze die geven, ontvangen alleen de adressen
van de leden van je Emailit-werkruimte mail.

De rij zegt ook hoeveel mails er vandaag zijn gegaan en toont de laatste mislukkingen, met hun reden. Hij toont nooit
iemands adres. Een `EMAILIT_API_KEY` in de omgeving gaat boven een opgeslagen sleutel.
