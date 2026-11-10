---
title: Accounts en aanvragen
summary: Voeg spelers toe, maak organisatoren, open aanvragen, laat mensen binnen en geef ze herstellinks.
---
Elk account van deze Delve staat op de pagina Spelers: open **Voorkeuren**, de tab **Spelers**, en dan **Spelers openen**.
Organisatoren kunnen deze pagina ook gebruiken; sommige acties zijn alleen voor jou.

## Wie wat mag

- Spelers bereiken hun eigen tafels, de speelschermen, **Voorkeuren** en de Regelsystemen.
- Organisatoren beginnen ook campagnes, zorgen voor modules en huisregels, stellen de backends in, en beheren hier de
  accounts van spelers.
- Eigenaars mogen alles. Alleen een eigenaar kiest **Organisator maken** of **Eigenaar maken** (en **Organisator
  intrekken**, **Eigenaar intrekken**), en alleen een eigenaar schakelt het account van een organisator of een eigenaar uit of herstelt het. Het
  laatste eigenaarsaccount blijft eigenaar.

## Waar accounts vandaan komen

- Uit een uitnodigingslink: iedereen die de uitnodigingslink van een tafel opent, kan een account maken.
- Van deze pagina: vul een **Gebruikersnaam**, een **Weergavenaam** en een **Taal** in, en kies dan **Speler toevoegen**. Delve
  toont een link die het wachtwoord instelt. Stuur die naar de speler: hij werkt één keer, binnen 24 uur.
- Uit aanvragen: mensen vragen zelf een account aan (zie hieronder).
- Van de opdrachtregel: `uv run delve account add <username>` maakt een account en vraagt om zijn wachtwoord. Voeg
  `--organiser` of `--owner` toe voor die rechten.

## Aanvragen met goedkeuring

Aanvragen staat uit tot je **Mensen een account laten aanvragen** aanvinkt. Zolang het aan staat, biedt de inlogpagina **Geen account?
Vraag er een aan** aan. Elk nieuw account wacht onder **Wacht op goedkeuring**, met de regel die zijn persoon schreef over wie hij
is. Het menu toont hoeveel er wachten.

- **Binnenlaten**: het account kan vanaf nu inloggen.
- **Weigeren**: het account wordt verwijderd, en zijn gebruikersnaam is weer vrij.

Wie wacht en inlogt via de uitnodigingslink van een tafel, wordt daardoor binnengelaten. Elk adres mag 3 keer per uur vragen, en
er wachten hoogstens 20 aanvragen tegelijk.

<figure><img src="/help/players-waiting.webp" alt="Eén aanvraag onder Wacht op goedkeuring, met haar notitie, Binnenlaten omcirkeld en Weigeren ernaast" width="984" height="170" loading="lazy"></figure>

## Vergeten wachtwoorden en problemen

- **Wachtwoord vergeten?** op de inlogpagina vraagt een gebruikersnaam of, als Delve mail verstuurt, een e-mailadres.
  Een account met een bevestigd adres krijgt zijn herstellink per mail, hoogstens 3 per uur; er wacht geen vraag op
  jou. De vraag van elk ander account wacht hier, onder **Vroegen om een nieuw wachtwoord**, tot je zijn **Herstellink**
  maakt of de vraag wegklikt.
- **Herstellink** maakt een nieuwe link om het wachtwoord in te stellen voor het account; zijn oudere ongebruikte link werkt niet meer. Een herstel
  ontkoppelt ook elk Google-account dat eraan gekoppeld is.
- **Uitschakelen** stopt het account en logt het overal uit; **Inschakelen** brengt het terug. Je kunt je eigen account niet uitschakelen.
  Accounts worden nooit verwijderd, behalve een aanvraag die je weigert.

## Google-accounts

Zodra je Inloggen met Google hebt ingesteld onder [Verbindingen](/help/connections), kunnen mensen een account aanvragen en inloggen met Google. Een
aanvraag met Google wacht nog altijd op goedkeuring. Wie een account heeft, kan **Je Google-account koppelen** kiezen op zijn
tab **Profiel**. Delve koppelt een Google-account alleen aan het account dat het koppelde of ermee aanvroeg, nooit via zijn
e-mailadres.
