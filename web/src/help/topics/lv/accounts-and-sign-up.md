---
title: Konti un kontu pieprasīšana
summary: Pievieno spēlētājus, padari par organizatoriem, atver kontu pieprasīšanu, ielaid cilvēkus un dod viņiem atiestatīšanas saites.
---
Visi šīs Delve konti ir lapā Spēlētāji: atver **Iestatījumi**, cilni **Spēlētāji**, tad **Atvērt Spēlētājus**.
Organizatori arī var izmantot šo lapu; dažas darbības ir tikai tavas.

## Kurš ko drīkst

- Spēlētāji tiek pie saviem galdiem, spēles ekrāniem, **Iestatījumi** un noteikumu kopām.
- Organizatori turklāt sāk kampaņas, rūpējas par moduļiem un mājas noteikumiem, iestata aizmugursistēmas un šeit
  pārvalda spēlētāju kontus.
- Īpašnieki drīkst visu. Tikai īpašnieks izvēlas **Padarīt par organizatoru** vai **Padarīt par īpašnieku** (un
  **Atņemt organizatora tiesības**, **Atņemt īpašnieka tiesības**), un tikai īpašnieks atspējo vai atiestata
  organizatora vai īpašnieka kontu. Pēdējais īpašnieka konts paliek īpašnieks.

## No kurienes rodas konti

- No uzaicinājuma saites: ikviens, kas atver galda uzaicinājuma saiti, var izveidot kontu.
- No šīs lapas: aizpildi **Lietotājvārds**, **Attēlojamais vārds** un **Valoda**, tad izvēlies **Pievienot
  spēlētāju**. Delve parāda saiti, ar kuru iestata paroli. Nosūti to spēlētājam: tā derīga vienu reizi, 24 stundu
  laikā.
- No kontu pieprasīšanas: cilvēki paši pieprasa kontu (skati zemāk).
- No komandrindas: `uv run delve account add <username>` izveido kontu un prasa tā paroli. Pievieno `--organiser` vai
  `--owner`, lai dotu šīs tiesības.

## Kontu pieprasīšana ar apstiprināšanu

Kontu pieprasīšana ir izslēgta, līdz tu atzīmē **Ļaut cilvēkiem pieprasīt kontu**. Kamēr tā ir ieslēgta,
pieteikšanās lapa piedāvā **Nav konta? Pieprasi to**. Katrs jaunais konts gaida sadaļā **Gaida apstiprinājumu**, ar
rindu, ko tā cilvēks uzrakstīja par sevi. Izvēlne rāda, cik gaida.

- **Ielaist**: konts no šī brīža var pieteikties.
- **Atraidīt**: konts tiek izdzēsts, un tā lietotājvārds atkal ir brīvs.

Kāds, kurš gaida un piesakās caur galda uzaicinājuma saiti, ar to tiek ielaists. No katras adreses var pieprasīt 3
reizes stundā, un vienlaikus gaida ne vairāk kā 20 pieprasījumi.

<figure><img src="/help/players-waiting.webp" alt="Viens pieprasījums sadaļā Gaida apstiprinājumu, ar savu piezīmi, apvilktu Ielaist un blakus Atraidīt" width="984" height="170" loading="lazy"></figure>

## Aizmirstas paroles un problēmas

- **Aizmirsi paroli?** pieteikšanās lapā prasa lietotājvārdu vai, kamēr Delve sūta e-pastus, e-pasta adresi.
  Konts ar apstiprinātu adresi saņem atiestatīšanas saiti pa e-pastu, ne vairāk kā 3 stundā; tevi negaida neviens
  pieprasījums. Jebkura cita konta pieprasījums gaida šeit, sadaļā **Lūdza jaunu paroli**, līdz tu izveido tā
  **Atiestatīšanas saiti** vai to noraidi.
- **Atiestatīšanas saite** izveido kontam jaunu paroles iestatīšanas saiti; tā vecākā neizmantotā saite pārstāj
  darboties. Atiestatīšana arī atsaista katru ar to sasaistīto Google kontu.
- **Atspējot** aptur kontu un izraksta to visur; **Iespējot** to atjauno. Savu kontu atspējot nevar. Konti nekad
  netiek dzēsti, izņemot pieprasījumu, ko tu atraidi.

## Google konti

Kad esi iestatījis pieteikšanos ar Google sadaļā [Savienojumi](/help/connections), cilvēki var pieprasīt kontu un
pieteikties ar Google. Google pieprasījums joprojām gaida apstiprinājumu. Kāds, kam ir konts, savā cilnē **Profils**
var izvēlēties **Sasaistīt savu Google kontu**. Delve Google kontu piesaista tikai kontam, kas to sasaistīja vai ar
to pieprasīja kontu, nekad pēc e-pasta.
