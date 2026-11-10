---
title: Créer des cartes
summary: Dessinez ou écrivez les cartes de donjon d'un module dans l'éditeur de cartes, et importez ou dessinez des cartes du monde.
---
Les cartes d'un module sont ses donjons et ses bâtiments. En jeu, elles ne montrent aux joueurs que ce que leurs
personnages ont vu.

## Où vivent les cartes

**Cartes** liste les modules qui ont des cartes ; chaque carte s'ouvre dans l'éditeur. Une carte qu'une campagne joue
renvoie aussi à sa vue du DM dans cette campagne.

Sur la page d'un module, l'onglet **Cartes** liste ses cartes. Donnez à une **Nouvelle carte** un nom et un **Rôle** :
**Carte** pour une carte à jouer, **Bibliothèque** pour des pièces partagées que d'autres cartes incluent. Choisissez
**Ajouter une carte**. **Mettre par défaut** fixe la carte qu'utilise un texte quand il n'en nomme aucune.

**Générer une carte** en dessine une d'après une description, en brouillon : **Garder** ou **Écarter**.

## L'éditeur

L'éditeur montre le code de la carte et son dessin côte à côte ; sur un téléphone, ce sont deux onglets, **Code** et
**Dessin**. Dessinez avec les outils et le code s'écrit pour vous, ou écrivez le code et regardez le dessin suivre.
Survolez un outil pour voir son nom et son fonctionnement, par exemple **Salle rectangulaire**, **Couloir** ou
**Porte**. L'éditeur liste les erreurs et les avertissements au fur et à mesure.

- **Enregistrer**, ou Ctrl+S. **Imprimer** ouvre une vue d'impression ; enregistrez d'abord.
- **Sortie** mène à une autre carte du module : marcher dessus y déplace le groupe.
- Une porte peut être **Piégée**, et une sortie **Secrète** : les joueurs ne voient ni l'une ni l'autre.
- **Image de référence** charge une image, comme la carte du livre, pour la décalquer. Elle reste dans votre
  navigateur.

<figure><img src="/help/map-editor.webp" alt="L'éditeur de cartes : le texte de la carte à gauche, son dessin à droite, les outils de dessin au-dessus" width="1280" height="800" loading="lazy"></figure>

## Le langage des cartes

Une carte est un court texte. Celle-ci a deux salles reliées par un passage, avec une porte verrouillée vers le puits :

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

Un titre à clé dans le texte du module, comme `## 2. Well Room`, se lie de lui-même à la salle du même nom, ici
`well_room`.

## Les cartes propres à une campagne

Sur la page d'une campagne, **Cartes**, **Les cartes propres à cette campagne** contient les cartes faites pour cette
seule table, comme un quartier que les joueurs ont inventé. Donnez un **Nom de la nouvelle carte** et choisissez
**Créer la carte**. Elle ne change jamais le module.

## Cartes du monde

Les cartes du monde servent aux voyages : terres, lieux, routes et rivières. Elles appartiennent à un module, à une
campagne ou à un univers, chacune sous ses **Cartes du monde** ou ses **Cartes**.

1. Choisissez **Importer une carte du monde** : **Un fichier GeoJSON**, ou **Une image avec sa légende**, en donnant
   sa grille et ce que représente un hexagone ou un carré.
2. Une carte lue d'après une image reste **En vérification**, invisible pour les joueurs, jusqu'à ce que vous
   choisissiez **Vérifier**, leviez ses doutes et choisissiez **Accepter la carte**.
3. **Modifier** dessine des lieux, des routes, des rivières, des régions, des lacs et des mers, et peint le terrain
   avec le **Pinceau de terrain**.

Sur la carte du monde d'une campagne, **Ce que le groupe sait au départ** fixe ce que les joueurs voient d'abord :
**Tout**, **Rien**, **Certaines régions**, ou **Une zone tracée sur la carte**.
