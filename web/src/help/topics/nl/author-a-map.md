---
title: Kaarten maken
summary: Teken of schrijf de kerkerkaarten van een module in de kaarteditor, en importeer of teken wereldkaarten.
---
De kaarten van een module zijn haar kerkers en gebouwen. Tijdens het spel tonen ze de spelers alleen wat hun personages gezien hebben.

## Waar kaarten staan

**Kaarten** toont de modules die kaarten hebben; elke kaart opent in de editor. Een kaart die een campagne speelt, linkt ook naar haar
DM-weergave in die campagne.

Op de pagina van een module toont de tab **Kaarten** haar kaarten. Geef een **Nieuwe kaart** een naam en een **Rol**: **Kaart** voor een kaart om
te spelen, **Bibliotheek** voor gedeelde stukken die andere kaarten insluiten. Kies **Kaart toevoegen**. **Standaard maken** stelt de kaart in die een
tekst gebruikt als ze er geen noemt.

**Een kaart laten tekenen** tekent er een uit een beschrijving, als ontwerp: **Houden** of **Weggooien**.

## De editor

De editor toont de code van de kaart en haar tekening naast elkaar; op een telefoon zijn het twee tabs, **Code** en
**Tekening**. Teken met de tools en de code wordt voor je geschreven, of schrijf de code en zie de tekening volgen.
Houd de muis boven een tool voor zijn naam en hoe hij werkt, zoals **Rechthoekige kamer**, **Gang** of **Deur**. De editor toont
fouten en waarschuwingen terwijl je werkt.

- **Opslaan**, of Ctrl+S. **Afdrukken** opent een afdrukweergave; sla eerst op.
- **Uitgang** leidt naar een andere kaart van de module: erop stappen brengt de groep daarheen.
- Een deur kan **Met val** zijn, en een uitgang **Geheim**: spelers zien geen van beide.
- **Voorbeeldafbeelding** laadt een afbeelding, zoals de kaart uit het boek, om over te trekken. Ze blijft in je browser.

<figure><img src="/help/map-editor.webp" alt="De kaarteditor: de tekst van de kaart links, haar tekening rechts, de tekentools erboven" width="1280" height="800" loading="lazy"></figure>

## De kaarttaal

Een kaart is een korte tekst. Deze heeft twee kamers verbonden door een doorgang, met een deur op slot naar de put:

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

Een genummerde kop in de tekst van de module, zoals `## 2. Well Room`, linkt zichzelf aan de kamer met dezelfde naam, hier
`well_room`.

## De eigen kaarten van een campagne

Op de pagina van een campagne, **Kaarten**, bevat **Eigen kaarten van deze campagne** kaarten die alleen voor die tafel gemaakt zijn, zoals een wijk
die de spelers verzonnen. Geef haar een **Naam van de nieuwe kaart** en kies **Maak de kaart**. Ze verandert de module nooit.

## Wereldkaarten

Wereldkaarten zijn om te reizen: land, plaatsen, wegen en rivieren. Ze horen bij een module, een campagne of een wereld, elk
onder zijn **Wereldkaarten** of **Kaarten**.

1. Kies **Een wereldkaart importeren**: **Een GeoJSON-bestand**, of **Een afbeelding met haar schaal**, met haar raster en wat één
   hexagon of vierkant is.
2. Een kaart die uit een afbeelding gelezen is, blijft **Te beoordelen**, onzichtbaar voor spelers, tot je **Beoordelen** kiest, haar twijfels
   oplost en **De kaart aanvaarden** kiest.
3. **Bewerken** tekent plaatsen, wegen, rivieren, gebieden, meren en zeeën, en schildert terrein met het **Terreinpenseel**.

Op de wereldkaart van een campagne stelt **Wat de groep bij het begin weet** in wat de spelers eerst zien: **Alles**,
**Niets**, **Enkele gebieden**, of **Een gebied getekend op de kaart**.
