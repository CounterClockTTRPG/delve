---
title: Aizmugursistēmu izvēle
summary: Kuru Claude modeli un piepūli izmanto katrs darbs, kurš pakalpojums glezno attēlus un kāda ir instalācijas valoda.
---
**Iestatījumi → Aizmugursistēmas** izvēlas, kurš veic katru no Delve darbiem. To var mainīt arī organizatori.
Izmaiņas stājas spēkā nākamajā gājienā.

## Darbi

Katram darbam ir **Pakalpojumu sniedzējs**, **Modelis** un **Piepūle**. **Pakalpojumu sniedzēja noklusējums** atstāj
izvēli pakalpojumu sniedzējam.

| Darbs | Ko tas dara |
|---|---|
| **DM** | Stāstījums un noteikumi, katrā gājienā |
| **Palīguzdevumi** | Jautāt DM, ieteikumi, attēlu uzvednes |
| **Tulkošana** | Spēlētāju vārdi angliski, DM vārdi no angļu valodas |
| **Moduļu konvertēšana** | PDF pārvēršana moduļos, ģenerēti pazemes labirinti |
| **Rūpīga konvertēšana** | PDF pārvēršana moduļos, salīdzinot ar lappušu attēliem (tikai Claude CLI) |
| **Romāni** | Kampaņas un moduļi, uzrakstīti kā romāni |
| **Portreti** | Tēli un NPC |
| **Ainas** | Vietas un mirkļi stāstā |
| **Īpašumi** | Cietokšņi, jājamdzīvnieki, kuģi un tamlīdzīgi |

## Claude

Teksta darbi izmanto **Claude (claude -p)**, komandrindu `claude` ar tavu abonementu. Tā tiek piedāvāta tikai tad,
ja `claude` ir tās čaulas `PATH`, kas palaida Delve. Tās modeļi ir **Opus (visspējīgākais)**, **Sonnet** un **Haiku
(ātrākais)**. Lielāka piepūle nozīmē ilgāku domāšanu. **Automātiski** izmanto zemu piepūli ikdienas gājieniem un augstu
tur, kur noteikumi kļūst sarežģīti.

## Attēli

- **portraitgen (free)** zīmē portretus pārlūkā, bez maksas. Tas veido tikai portretus.
- **Replicate** un **assetgen** parādās, tiklīdz tos pievieno sadaļā [Savienojumi](/help/connections). Katrs modelis
  rāda savu pakalpojumu un cenu vai **bez maksas**.

Maksas modelis ainām vai īpašumiem glezno tikai tad, ja galda saimnieks ieslēdz **Maksas attēli**.

<p class="note">Pakalpojumu sniedzējs ar atzīmi (development) ir paredzēts Delve testēšanai: tā attēli ir viltoti, un
tā DM darbojas pēc scenārija. Neizvēlies to spēlei.</p>

## Kad izvēli nevar izmantot

- Ja pakalpojumu sniedzējam pagaidām ir problēma (teiksim, assetgen nedarbojas), darbs patur tavu izvēli un rāda
  **Nevar izmantot:** un iemeslu. Tas atkal darbojas, tiklīdz darbojas pakalpojumu sniedzējs.
- Ja pakalpojumu sniedzēja vairs nav (tu noņēmi tā savienojumu), darbi, kas to izvēlējās, atgriežas pie sava
  noklusējuma, un cilnes augšā tas ir pateikts.

## Pārējā cilne

Šajā cilnē ir arī **Attēlu stils** (skati [Izskati un attēlu stili](/help/looks-and-image-styles)) un pogu un
uzrakstu **Valoda** šajā instalācijā. Kad esi gatavs, izvēlies **Saglabāt**.

<figure><img src="/help/backends-jobs.webp" alt="Aizmugursistēmas un modeļi: katrs darbs ar savu pakalpojumu sniedzēju, modeli un piepūli" width="984" height="800" loading="lazy"></figure>
