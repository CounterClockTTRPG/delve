---
title: Delve savienošana ar citiem pakalpojumiem
summary: Attēli no Replicate vai tava paša servera, pieteikšanās ar Google un vārds privātuma politikā.
---
**Iestatījumi → Savienojumi** redz tikai īpašnieks. Pilnvara, ko tur saglabā, paliek šī datora failos, un Delve to
vairs nekad nerāda: tā tikai pasaka, vai pilnvara ir iestatīta. Izmaiņas stājas spēkā uzreiz, bez restartēšanas.

- **Replicate** glezno portretus, ainas un īpašumus, par maksu. Ielīmē tā **Pilnvara**. `REPLICATE_API_TOKEN` vidē ir
  svarīgāks par saglabāto pilnvaru.
- **assetgen** ir tavs paša attēlu serveris, šajā datorā vai tavā tīklā. Norādi tā **URL** un pilnvaru, ja tam tāda
  vajadzīga.
- **Pieteikšanās ar Google** ļauj cilvēkiem pieteikties un pieprasīt kontu ar Google. Google Cloud konsolē izveido
  OAuth klientu ar veidu Tīmekļa lietojumprogramma un reģistrē adreses no **Reģistrējamie novirzīšanas URI** kā tā
  atļautos novirzīšanas URI. Tad ielīmē šeit **Klienta ID** un **Klienta noslēpums**.
- **E-pasts** sūta apstiprinājumus, paroles atiestatīšanu un galda paziņojumus caur Emailit. Ielīmē tā **Emailit atslēga**,
  norādi **Sūtītājs** un savu **Publiskā adrese** un nospied **Pārbaudīt**.
  [E-pasta iestatīšana ar Emailit](/help/email-setup) izskaidro atslēgu un DNS ierakstus.
- **Privātums un noteikumi** ir tas, kurš uztur šo Delve, tā, kā to rāda publiskā [privātuma politika](/privacy) un
  [noteikumi](/terms). Aizpildi **Tavs vārds** un **Saziņas e-pasts**.

Katrā rindā ir **Saglabāt**. Replicate, assetgen un pieteikšanās ar Google, kad tie iestatīti, ir arī **Noņemt**, bet
Replicate, assetgen un E-pastam ir **Pārbaudīt**: izmanto to, lai pārbaudītu savienojumu, pirms spēlētāji uz to
paļaujas (E-pastam tas nosūta testa e-pastu uz tavu apstiprināto adresi). Kad
attēlu pakalpojums ir pievienots, izvēlies, kuri darbi to izmanto, sadaļā
[Aizmugursistēmas](/help/backends).

Google sūta pārlūku atpakaļ tikai uz https adresēm un uz šo datoru, tāpēc Google pogas ir redzamas tur, nevis tava
lokālā tīkla adresēs, kur spēlētāji izmanto savas paroles.

<figure><img src="/help/connections-tab.webp" alt="Savienojumi: Replicate un assetgen, katrs ar Saglabāt un Pārbaudīt" width="976" height="590" loading="lazy"></figure>
