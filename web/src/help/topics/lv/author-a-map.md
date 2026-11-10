---
title: Karšu veidošana
summary: Zīmē vai raksti moduļa pazemes kartes karšu redaktorā, un importē vai zīmē pasaules kartes.
---
Moduļa kartes ir tā pazemes labirinti un ēkas. Spēlē tās spēlētājiem rāda tikai to, ko viņu tēli ir redzējuši.

## Kur kartes glabājas

**Kartes** uzskaita moduļus, kuriem ir kartes; katra karte atveras redaktorā. Karte, ko spēlē kāda kampaņa, ved arī
uz tās DM skatu šajā kampaņā.

Moduļa lapā cilne **Kartes** uzskaita tā kartes. Dod **Jauna karte** nosaukumu un **Loma**: **Karte** tai, ko spēlēt,
**Bibliotēka** kopīgām daļām, ko iekļauj citas kartes. Izvēlies **Pievienot karti**. **Padarīt par noklusējuma**
iestata karti, ko teksts izmanto, ja nenosauc nevienu.

**Ģenerēt karti** uzzīmē karti pēc apraksta, kā melnrakstu: **Paturēt** to vai **Atmest**.

## Redaktors

Redaktors rāda kartes kodu un tās zīmējumu blakus; telefonā tās ir divas cilnes, **Kods** un **Zīmējums**. Zīmē ar
rīkiem, un kods tiek uzrakstīts tavā vietā, vai raksti kodu un vēro, kā zīmējums seko. Novieto kursoru virs rīka, lai
redzētu tā nosaukumu un kā tas darbojas, piemēram, **Taisnstūra telpa**, **Gaitenis** vai **Durvis**. Redaktors
uzskaita kļūdas un brīdinājumus, kamēr strādā.

- **Saglabāt** vai Ctrl+S. **Drukāt** atver drukas skatu; vispirms saglabā.
- **Izeja** ved uz citu moduļa karti: uzkāpjot uz tās, grupa pārvietojas turp.
- Durvis var būt **Ar lamatām**, bet izeja **Slepena**: spēlētāji neredz ne vienu, ne otru.
- **Parauga attēls** ielādē attēlu, piemēram, grāmatas karti, ko pārzīmēt. Tas paliek tavā pārlūkā.

<figure><img src="/help/map-editor.webp" alt="Karšu redaktors: kartes teksts kreisajā pusē, tās zīmējums labajā, virs tā zīmēšanas rīki" width="1280" height="800" loading="lazy"></figure>

## Karšu valoda

Karte ir īss teksts. Šajā ir divas telpas, ko savieno eja, ar aizslēgtām durvīm uz akas telpu:

```dmap
include "core.dmap"

map "The Old Well" {
  grid { cell 32 px units feet 10 bounds 24 x 12 }
}

room "entrance" {
  rect 1,3 6 x 6
  label "1"
}

corridor "passage" {
  width 1
  segment line from 7,6 to 14,6
}

room "well_room" {
  rect 14,2 8 x 8
  label "2"
  feature well at 18,6
}

door at 7,6 { connects room.entrance, corridor.passage type wooden state closed }
door at 14,6 { connects corridor.passage, room.well_room type wooden state locked }
```

Atslēgas virsraksts moduļa tekstā, piemēram, `## 2. Well Room`, pats piesaistās tāda paša nosaukuma telpai, šeit
`well_room`.

## Kampaņas pašas kartes

Kampaņas lapā, **Kartes**, sadaļā **Šīs kampaņas pašas kartes** glabājas kartes, kas veidotas tikai šim galdam,
piemēram, pilsētas kvartāls, ko izdomāja spēlētāji. Ieraksti **Jaunās kartes nosaukums** un izvēlies **Izveidot
karti**. Tā nekad nemaina moduli.

## Pasaules kartes

Pasaules kartes ir ceļošanai: zeme, vietas, ceļi un upes. Tās pieder modulim, kampaņai vai pasaulei, katra zem
savām **Pasaules kartes** vai **Kartes**.

1. Izvēlies **Importēt pasaules karti**: **GeoJSON fails** vai **Attēls ar mērogu**, norādot tā režģi un ko nozīmē
   viens sešstūris vai kvadrāts.
2. Karte, kas nolasīta no attēla, paliek statusā **Tiek pārskatīta**, spēlētājiem neredzama, līdz tu izvēlies
   **Pārskatīt**, atrisini tās šaubas un **Pieņemt karti**.
3. **Rediģēt** zīmē vietas, ceļus, upes, novadus, ezerus un jūras un krāso apvidu ar **Apvidus ota**.

Kampaņas pasaules kartē **Ko grupa zina sākumā** nosaka, ko spēlētāji redz sākumā: **Visu**, **Neko**, **Dažus
novadus** vai **Kartē uzzīmētu apgabalu**.
