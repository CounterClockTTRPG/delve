---
title: Krātuve un rezerves kopijas
summary: Ko Delve glabā šajā datorā, rezerves kopiju krātuve, kas to kopē katru dienu, un bibliotēka, ko dala ar draugiem.
---
Delve visu glabā šajā datorā, savā datu mapē: `~/.local/share/delve` vai mapē, ko nosauc `DELVE_DATA_DIR`. Tur ir
datubāze (konti, kampaņas, moduļi, Iestatījumi), īpašnieka marķieris, savienojumu pilnvaras un katrs augšupielādētais
fails.

**Iestatījumi → Krātuve**, ko redz tikai īpašnieks, pievieno divas krātuves citur. Katra ir savs konteiners vai
spainis: Delve atsakās likt abas vienā.

## Krātuves izvēle

Katrai krātuvei izvēlies **Pakalpojumu sniedzējs**:

- **Azure Blob Storage**: ielīmē konteinera **SAS URL**.
- **Cloudflare R2**: tavs **Konta ID**, **Spainis**, **Piekļuves atslēgas ID** un **Slepenā piekļuves atslēga**.
- **Saderīgs ar S3**: **Galapunkts**, **Spainis**, **Piekļuves atslēgas ID** un **Slepenā piekļuves atslēga**.

Izvēlies **Saglabāt**, tad **Pārbaudīt**: tas parāda, ko piekļuves dati drīkst darīt. SAS URL rāda, kad tas beidzas.
Noslēpumi paliek šī datora failos; Delve tos vairs nekad nerāda, un neviena rezerves kopija tos nesatur.

## Rezerves kopiju krātuve

**Rezerves kopiju krātuve** ir tikai tava. Tās piekļuves datiem vajag tiesības lasīt, uzskaitīt, izveidot, rakstīt un
dzēst.

- Katru dienu laikā, kas norādīts laukā **Katru dienu veidot kopiju** (sākumā 04:00, pēc šī datora laika), Delve
  nokopē moduļus, kampaņas un pasaules, kas mainījušās. Tā patur katra jaunāko kopiju. Kopija, kas palaista garām,
  kamēr Delve bija izslēgta, tiek veidota, kad tā startē.
- **Veidot kopiju tagad** uzreiz izveido vienu. **Pēdējā rezerves kopija** pasaka, kā tai gāja; to, kas neizdevās,
  mēģina vēlreiz nākamajā reizē.
- **Atjaunot** uzskaita šīs instalācijas rezerves kopijas vai citas instalācijas kopijas, kas izmanto to pašu
  krātuvi. Atzīmē, ko atgūt, un izvēlies **Atjaunot atlasītos**. Kampaņa paņem līdzi savu moduli. Delve pajautā,
  pirms aizstāj kaut ko, kas jau ir šeit.

<p class="note">Rezerves kopijā ir moduļi, kampaņas un pasaules, nevis konti, Iestatījumi vai pilnvaras. Tie ir tikai
datu mapē.</p>

<figure><img src="/help/backup-store.webp" alt="Krātuve: rezerves kopiju krātuve un bibliotēkas krātuve, katra ar savu pakalpojumu sniedzēju un SAS URL" width="1280" height="800" loading="lazy"></figure>

## Bibliotēkas krātuve

**Bibliotēkas krātuve** ir kopīga ar draugiem: moduļi, ko tu publicē, un tie, ko lejupielādē, sadaļā **Bibliotēka**
lapā Moduļi. Tās piekļuves datu tiesības nosaka, ko šī instalācija tur drīkst: **Lasīt** (pārlūkot un lejupielādēt),
**Publicēt** (pievienot moduļus un jaunas savu moduļu versijas) vai **Pārvaldīt** (arī mainīt un dzēst ikviena
moduļus).
