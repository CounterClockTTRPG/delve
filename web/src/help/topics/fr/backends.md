---
title: Choisir les backends
summary: Quel modèle Claude et quel effort chaque tâche utilise, quel service peint les images, et la langue de l'installation.
---
**Préférences → Backends** choisit qui fait chacune des tâches de Delve. Les organisateurs peuvent aussi le changer.
Un changement prend effet au beat suivant.

## Les tâches

Chaque tâche a un **Fournisseur**, un **Modèle** et un **Effort**. **Par défaut du fournisseur** laisse le choix au
fournisseur.

| Tâche | Ce qu'elle fait |
|---|---|
| **DM** | Narration et règles, à chaque beat |
| **Tâches annexes** | Demander au DM, suggestions, prompts d'images |
| **Traduction** | Les mots des joueurs vers l'anglais, ceux du DM depuis l'anglais |
| **Conversion de modules** | Des PDF en modules, des donjons générés |
| **Conversion approfondie** | Des PDF en modules, vérifiés d'après les images des pages (Claude CLI seulement) |
| **Romans** | Campagnes et modules écrits comme des romans |
| **Portraits** | Personnages et PNJ |
| **Scènes** | Lieux et moments de l'histoire |
| **Possessions** | Places fortes, montures, navires et autres |

## Claude

Les tâches de texte utilisent **Claude (claude -p)**, la ligne de commande `claude` sur votre abonnement. Il n'est
proposé que quand `claude` est dans le `PATH` du shell qui a lancé Delve. Ses modèles sont **Opus (le plus capable)**,
**Sonnet** et **Haiku (le plus rapide)**. Un effort plus élevé réfléchit plus longtemps. **Auto** utilise un effort
faible pour les beats de routine et un effort élevé là où les règles se compliquent.

## Les images

- **portraitgen (gratuit)** dessine des portraits dans le navigateur, sans frais. Il ne fait que des portraits.
- **Replicate** et **assetgen** apparaissent une fois que vous les connectez sous [Connexions](/help/connections).
  Chaque modèle montre son service et son prix, ou **gratuit**.

Un modèle payant pour les scènes ou les possessions ne peint que quand l'hôte d'une table active les **Images
payantes**.

<p class="note">Un fournisseur marqué (développement) sert à tester Delve : ses images sont fausses et son DM suit un
script. Ne le choisissez pas pour jouer.</p>

## Quand un choix ne peut pas être utilisé

- Si un fournisseur a un problème pour l'instant (assetgen est en panne, par exemple), la tâche garde votre choix et
  affiche **Inutilisable :** et pourquoi. Elle fonctionne de nouveau dès que le fournisseur refonctionne.
- Si un fournisseur a disparu (vous avez retiré sa connexion), les tâches qui l'avaient choisi reviennent à leur
  valeur par défaut, et l'onglet le dit en haut.

## Le reste de l'onglet

Cet onglet contient aussi le **Style d'image** (voir [Apparences et styles d'image](/help/looks-and-image-styles)) et
la **Langue** des boutons et des libellés de cette installation. Choisissez **Enregistrer** quand vous avez fini.

<figure><img src="/help/backends-jobs.webp" alt="Backends et modèles : chaque tâche avec son Fournisseur, son Modèle et son Effort" width="984" height="800" loading="lazy"></figure>
