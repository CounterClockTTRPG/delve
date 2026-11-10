---
title: Opslag en back-up
summary: Wat Delve op deze machine bewaart, de back-upopslag die het elke dag kopieert, en de bibliotheek die je deelt met vrienden.
---
Delve bewaart alles op deze machine, in zijn gegevensmap: `~/.local/share/delve`, of de map die
`DELVE_DATA_DIR` noemt. Die bevat de database (accounts, campagnes, modules, Voorkeuren), het eigenaarstoken, de
tokens van de verbindingen en elk geüpload bestand.

**Voorkeuren → Opslag**, die alleen de eigenaar ziet, voegt twee opslagplaatsen elders toe. Elk is een eigen container of bucket:
Delve weigert ze allebei in dezelfde te zetten.

## Een opslag kiezen

Kies voor elke opslag een **Aanbieder**:

- **Azure Blob Storage**: plak de **SAS-URL** van de container.
- **Cloudflare R2**: je **Account-id**, de **Bucket**, de **Toegangssleutel-id** en de **Geheime toegangssleutel**.
- **S3-compatibel**: het **Eindpunt**, de **Bucket**, de **Toegangssleutel-id** en de **Geheime toegangssleutel**.

Kies **Opslaan**, en dan **Testen**: het toont wat de sleutel mag doen. Een SAS-URL toont wanneer hij verloopt. De geheimen
blijven in de bestanden van deze machine; Delve toont ze nooit meer, en geen back-up bevat ze.

## De back-upopslag

De **Back-upopslag** is alleen van jou. Zijn sleutel heeft lezen, oplijsten, aanmaken, schrijven en verwijderen nodig.

- Elke dag op het uur bij **Dagelijks back-up om** (eerst 04:00, de tijd van deze machine) kopieert Delve de modules,
  campagnes en werelden die veranderd zijn. Het houdt van elk de laatste kopie. Een back-up die gemist werd terwijl Delve uit stond, loopt
  zodra het start.
- **Nu back-up maken** maakt er meteen een. **Laatste back-up** zegt hoe het ging; wat mislukte, wordt de volgende keer opnieuw geprobeerd.
- **Terugzetten** toont de back-ups van deze installatie, of van een andere installatie die dezelfde opslag gebruikt. Vink aan wat je
  terug wilt en kies **Selectie terugzetten**. Een campagne brengt haar module mee. Delve vraagt het voor het iets vervangt
  dat hier al is.

<p class="note">De back-up bevat modules, campagnes en werelden, niet de accounts, Voorkeuren of tokens. Die staan
alleen in de gegevensmap.</p>

<figure><img src="/help/backup-store.webp" alt="Opslag: de back-upopslag en de bibliotheekopslag, elk met zijn aanbieder en SAS-URL" width="1280" height="800" loading="lazy"></figure>

## De bibliotheekopslag

De **Bibliotheekopslag** deel je met vrienden: de modules die je publiceert, en die je downloadt, onder **Bibliotheek** op
de pagina Modules. Het recht van zijn sleutel bepaalt wat deze installatie er mag doen: **Lezen** (bladeren en downloaden),
**Publiceren** (modules toevoegen, en nieuwe versies van je eigen) of **Beheren** (ook die van iedereen wijzigen en verwijderen).
