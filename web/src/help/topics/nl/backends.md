---
title: De backends kiezen
summary: Welk Claude-model en welke inspanning elke taak gebruikt, welke dienst de afbeeldingen schildert, en de taal van de installatie.
---
**Voorkeuren → Backends** kiest wie elk van de taken van Delve doet. Organisatoren kunnen het ook wijzigen. Een wijziging geldt
vanaf de volgende beat.

## De taken

Elke taak heeft een **Aanbieder**, een **Model** en een **Inspanning**. **Standaard** laat de keuze aan de aanbieder.

| Taak | Wat ze doet |
|---|---|
| **DM** | Vertelling en regels, elke beat |
| **Hulptaken** | Vraag de DM, suggesties, beeldprompts |
| **Vertaling** | Wat spelers zeggen naar het Engels, wat de DM zegt eruit |
| **Moduleconversie** | Pdf's omzetten in modules, gegenereerde kerkers |
| **Grondige conversie** | Pdf's omzetten in modules, nagekeken tegen de paginabeelden (alleen Claude CLI) |
| **Romans** | Campagnes en modules geschreven als roman |
| **Portretten** | Personages en NPC's |
| **Scènes** | Plaatsen en momenten in het verhaal |
| **Bezittingen** | Burchten, rijdieren, schepen en dergelijke |

## Claude

De teksttaken gebruiken **Claude (claude -p)**, de `claude`-opdrachtregel op je abonnement. Die wordt alleen aangeboden als
`claude` op het `PATH` staat van de shell die Delve startte. Zijn modellen zijn **Opus (krachtigst)**, **Sonnet** en
**Haiku (snelst)**. Een hogere inspanning denkt langer. **Automatisch** gebruikt een lage inspanning voor gewone beats en een hoge waar
de regels moeilijk worden.

## Afbeeldingen

- **portraitgen (free)** tekent portretten in de browser, zonder kosten. Het maakt alleen portretten.
- **Replicate** en **assetgen** verschijnen zodra je ze verbindt onder [Verbindingen](/help/connections). Elk model toont
  zijn dienst en zijn prijs, of **gratis**.

Een betaald model voor scènes of bezittingen schildert alleen als de gastgever van een tafel **Betaalde afbeeldingen** aanzet.

<p class="note">Een aanbieder gemarkeerd met (development) is om Delve te testen: zijn afbeeldingen zijn nep en zijn DM volgt een script.
Kies hem niet om te spelen.</p>

## Als een keuze niet bruikbaar is

- Als een aanbieder voorlopig een probleem heeft (assetgen ligt plat, bijvoorbeeld), houdt de taak je keuze en toont ze **Niet bruikbaar:**
  en waarom. Ze werkt weer zodra de aanbieder werkt.
- Als een aanbieder weg is (je verwijderde zijn verbinding), vallen de taken die hem kozen terug op hun standaard, en de tab
  zegt dat bovenaan.

## De rest van de tab

Deze tab bevat ook de **Beeldstijl** (zie [Uiterlijk en beeldstijlen](/help/looks-and-image-styles)) en de
**Taal** van knoppen en labels op deze installatie. Kies **Opslaan** als je klaar bent.

<figure><img src="/help/backends-jobs.webp" alt="Backends en modellen: elke taak met haar Aanbieder, Model en Inspanning" width="984" height="800" loading="lazy"></figure>
