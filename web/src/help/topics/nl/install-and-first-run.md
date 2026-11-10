---
title: Delve installeren en de eerste keer starten
summary: Installeer Delve, start het, maak het eigenaarsaccount, en open het vanaf je andere toestellen.
---
Delve draait als één programma op één poort op je machine. Jij bent de eigenaar: jij installeerde het, dus jij hebt alle rechten.

## Installeren en starten

Je hebt Python 3.12 of nieuwer nodig, [uv](https://docs.astral.sh/uv/) en Node.js. Claude is de DM via de opdrachtregel
`claude` (Claude Code) op je eigen abonnement, dus installeer die en log eerst in: `claude` moet op het `PATH` staan
van de shell die Delve start.

1. Voer in de map van Delve `make install` uit. Het installeert wat Delve nodig heeft en bouwt zijn regelgegevens.
2. Voer `make run` uit. Het bouwt de webapp en start Delve op poort 7810. Om een andere poort te gebruiken, start je het met
   `uv run delve serve --port <other>`; `--host` verandert het adres waarop het luistert.
3. Open op deze machine <http://localhost:7810/>.

Voer `make install` opnieuw uit nadat je een nieuwe versie van Delve binnenhaalt: Delve weigert te starten als zijn regelgegevens
ontbreken of verouderd zijn.

## Maak het eigenaarsaccount

Zolang er geen eigenaarsaccount is, is een browser op deze machine de eigenaar en hoeft hij niet in te loggen. Maak het account voor
je Delve openstelt voor het internet (via een tunnel of een proxy).

- Open in de browser op deze machine de inlogpagina en vul **Maak het eigenaarsaccount** in, of
- voer in een terminal `uv run delve account add <username> --owner` uit. Het vraagt om het wachtwoord.

Het eigenaarsaccount heeft alle rechten, vanaf elk toestel.

<figure><img src="/help/first-owner.webp" alt="De inlogpagina met Maak het eigenaarsaccount eronder, omcirkeld" width="480" height="800" loading="lazy"></figure>

## Je andere toestellen

Op je eigen netwerk kan een ander toestel van jou het inloggen overslaan met het eigenaarstoken. Voer `uv run delve token` uit: het
drukt een link af voor elk netwerkadres van de machine. Open er een keer een op het andere toestel. Via het internet wordt het
eigenaarstoken geweigerd, en log je in met je eigenaarsaccount.

Het eigenaarstoken verloopt nooit. Als een link uitgelekt is, maak je een nieuw met **Nieuw eigenaarstoken maken** onder
**Voorkeuren → Opslag**, of met `uv run delve token --new`. Het oude token en zijn links werken meteen niet meer.

## Waar je gegevens staan

Alles staat in `~/.local/share/delve`, of in de map die `DELVE_DATA_DIR` noemt. Zie
[Opslag en back-up](/help/storage-and-backup).
