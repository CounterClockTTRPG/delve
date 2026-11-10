---
title: Delve instalēšana un pirmā palaišana
summary: Instalē Delve, palaid to, izveido īpašnieka kontu un atver to no citām savām ierīcēm.
---
Delve darbojas kā viena programma uz viena porta tavā datorā. Tu esi tās īpašnieks: tu to instalēji, tāpēc tev ir
visas tiesības.

## Instalē un palaid

Tev vajag Python 3.12 vai jaunāku, [uv](https://docs.astral.sh/uv/) un Node.js. Claude ir DM caur komandrindu
`claude` (Claude Code) ar tavu paša abonementu, tāpēc vispirms to instalē un piesakies: `claude` jābūt tās čaulas
`PATH`, kas palaiž Delve.

1. Delve mapē palaid `make install`. Tas instalē to, kas Delve vajadzīgs, un sagatavo tās noteikumu datus.
2. Palaid `make run`. Tas sagatavo tīmekļa lietotni un palaiž Delve uz porta 7810. Lai izmantotu citu portu, palaid to
   ar `uv run delve serve --port <other>`; `--host` maina adresi, kurā tā klausās.
3. Šajā datorā atver <http://localhost:7810/>.

Palaid `make install` vēlreiz pēc tam, kad esi lejupielādējis jaunu Delve versiju: Delve atsakās startēt, ja tās
noteikumu dati trūkst vai ir novecojuši.

## Izveido īpašnieka kontu

Kamēr nav īpašnieka konta, pārlūks šajā datorā ir īpašnieks, un tam nevajag pieteikties. Izveido kontu, pirms atver
Delve internetam (caur tuneli vai starpniekserveri).

- Pārlūkā šajā datorā atver pieteikšanās lapu un aizpildi **Izveidot īpašnieka kontu**, vai
- terminālī palaid `uv run delve account add <username> --owner`. Tas prasa paroli.

Īpašnieka kontam ir visas tiesības no jebkuras ierīces.

<figure><img src="/help/first-owner.webp" alt="Pieteikšanās lapa ar apvilktu Izveidot īpašnieka kontu zem tās" width="480" height="800" loading="lazy"></figure>

## Tavas citas ierīces

Tavā tīklā cita tava ierīce var izlaist pieteikšanos ar īpašnieka marķieri. Palaid `uv run delve token`: tas izdrukā
saiti katrai datora tīkla adresei. Atver vienu no tām vienreiz citā ierīcē. Caur internetu īpašnieka marķieris netiek
pieņemts, un tu piesakies ar savu īpašnieka kontu.

Īpašnieka marķieris nekad nebeidzas. Ja saite nonākusi svešās rokās, izveido jaunu ar **Izveidot jaunu īpašnieka
marķieri** sadaļā **Iestatījumi → Krātuve** vai ar `uv run delve token --new`. Vecais marķieris un tā saites uzreiz
pārstāj darboties.

## Kur glabājas tavi dati

Viss ir mapē `~/.local/share/delve` vai mapē, ko nosauc `DELVE_DATA_DIR`. Skati
[Krātuve un rezerves kopijas](/help/storage-and-backup).
