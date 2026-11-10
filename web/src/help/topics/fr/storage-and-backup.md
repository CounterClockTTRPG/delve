---
title: Stockage et sauvegarde
summary: Ce que Delve garde sur cette machine, le stockage des sauvegardes qui le copie chaque jour, et la bibliothèque partagée avec des amis.
---
Delve garde tout sur cette machine, dans son dossier de données : `~/.local/share/delve`, ou le dossier que nomme
`DELVE_DATA_DIR`. On y trouve la base de données (comptes, campagnes, modules, Préférences), le jeton du
propriétaire, les jetons des connexions et chaque fichier envoyé.

**Préférences → Stockage**, que seul le propriétaire voit, ajoute deux stockages ailleurs. Chacun est son propre
conteneur ou bucket : Delve refuse de mettre les deux dans le même.

## Choisir un stockage

Pour chaque stockage, choisissez un **Fournisseur** :

- **Azure Blob Storage** : collez l'**URL SAS** du conteneur.
- **Cloudflare R2** : votre **Identifiant de compte**, le **Bucket**, l'**Identifiant de clé d'accès** et la **Clé
  d'accès secrète**.
- **Compatible S3** : le **Point de terminaison**, le **Bucket**, l'**Identifiant de clé d'accès** et la **Clé d'accès
  secrète**.

Choisissez **Enregistrer**, puis **Tester** : cela montre ce que l'identifiant a le droit de faire. Une URL SAS montre
quand elle expire. Les secrets restent dans les fichiers de cette machine ; Delve ne les montre plus jamais, et aucune
sauvegarde ne les contient.

## Le stockage des sauvegardes

Le **Stockage des sauvegardes** n'est qu'à vous. Son identifiant doit pouvoir lire, lister, créer, écrire et
supprimer.

- Chaque jour à l'heure indiquée dans **Sauvegarder chaque jour à** (04:00 au départ, heure de cette machine), Delve
  copie les modules, les campagnes et les univers qui ont changé. Il garde la dernière copie de chacun. Une sauvegarde
  manquée pendant que Delve était arrêté se fait à son démarrage.
- **Sauvegarder maintenant** en lance une tout de suite. **Dernière sauvegarde** dit comment elle s'est passée ; ce
  qui a échoué est retenté la fois suivante.
- **Restaurer** liste les sauvegardes de cette installation, ou d'une autre installation qui utilise le même
  stockage. Cochez ce qu'il faut ramener et choisissez **Restaurer la sélection**. Une campagne ramène son module avec
  elle. Delve demande avant de remplacer quoi que ce soit qui se trouve déjà ici.

<p class="note">La sauvegarde contient les modules, les campagnes et les univers, pas les comptes, les Préférences ni
les jetons. Ceux-là ne sont que dans le dossier de données.</p>

<figure><img src="/help/backup-store.webp" alt="Stockage : le stockage des sauvegardes et le stockage de la bibliothèque, chacun avec son fournisseur et son URL SAS" width="1280" height="800" loading="lazy"></figure>

## Le stockage de la bibliothèque

Le **Stockage de la bibliothèque** est partagé avec des amis : les modules que vous publiez, et ceux que vous
téléchargez, sous **Bibliothèque** sur la page Modules. Le droit de son identifiant décide de ce que cette
installation peut y faire : **Lire** (parcourir et télécharger), **Publier** (ajouter des modules, et de nouvelles
versions des vôtres) ou **Gérer** (modifier et supprimer aussi ceux de n'importe qui).
