---
title: E-pasta iestatīšana ar Emailit
summary: Atslēga, DNS ieraksti un sūtītājs, ar kuriem Delve sūta apstiprinājuma, paroles un galda e-pastus.
---
Delve sūta e-pastus caur [Emailit](https://emailit.com): adrešu apstiprinājumus, paroles atiestatīšanu, e-pastus "tu esi iekšā"
un, ja cilvēki to vēlas, galda un dēļa paziņojumus. Kamēr tu to neiestati, Delve nesūta neko, un rinda **E-pasts**
sadaļā **Iestatījumi → Savienojumi** var rakstīt tikai žurnālā.

1. Emailit izveido API atslēgu ar veidu **Sending Only**, ierobežotu uz tavu domēnu. Ielīmē to kā **Emailit atslēga**.
2. Pievieno savu domēnu Emailit un ieraksti tā ierakstus savā DNS, kur `<domēns>` ir tavs domēns:
   - SPF ieraksts: veids TXT pie `emailit.<domēns>`, vērtība `v=spf1 include:_spf.emailit.com ~all`;
   - DKIM ieraksts: veids TXT pie `emailit._domainkey.<domēns>`, ar vērtību, ko Emailit tev parāda;
   - atteikuma ieraksts: veids MX pie `emailit.<domēns>`, uz `feedback-smtp.ffdc-1.emailit.com`;
   - pēc izvēles DMARC ieraksts: veids TXT pie `_dmarc.<domēns>`, vērtība `v=DMARC1; p=none;`.
3. Emailit nospied **Check DNS** un gaidi, līdz katrs ieraksts ir zaļš.
4. Delve izvēlies **Emailit** pie **Sūta caur**, aizpildi **Sūtītājs** (tavā domēnā, piemēram,
   `Delve <delve@example.org>`) un **Publiskā adrese** (kur Delve atrodas internetā, piemēram,
   `https://delve.example`; saites e-pastos sākas ar to) un **Saglabāt**.
5. Pārliecinies, ka tava paša adrese profilā ir ievadīta un apstiprināta, un nospied **Pārbaudīt**: uz to aiziet testa e-pasts.

Emailit katru kontu sāk izmēģinājuma režīmā. Pieprasi piekļuvi ražošanai; kamēr to nedod, e-pastus saņem tikai tava
Emailit darba vietas dalībnieku adreses.

Rinda arī pasaka, cik e-pastu šodien aizgāja, un parāda pēdējās neveiksmes ar to iemeslu. Tā nekad nerāda neviena adresi.
`EMAILIT_API_KEY` vidē ir svarīgāka par saglabāto atslēgu.
