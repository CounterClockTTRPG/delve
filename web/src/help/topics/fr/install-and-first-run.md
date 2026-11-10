---
title: Installer Delve et le premier lancement
summary: Installez Delve, lancez-le, créez le compte du propriétaire, et ouvrez-le depuis vos autres appareils.
---
Delve tourne comme un seul programme, sur un seul port de votre machine. Vous en êtes le propriétaire : vous l'avez
installé, vous avez donc tous les droits.

## Installer et lancer

Il vous faut Python 3.12 ou plus récent, [uv](https://docs.astral.sh/uv/) et Node.js. Claude est le DM via la ligne
de commande `claude` (Claude Code) sur votre propre abonnement : installez-la donc et connectez-vous d'abord. `claude`
doit être dans le `PATH` du shell qui lance Delve.

1. Dans le dossier de Delve, lancez `make install`. Cela installe ce dont Delve a besoin et construit ses données de
   règles.
2. Lancez `make run`. Cela construit l'application web et démarre Delve sur le port 7810. Pour utiliser un autre port,
   lancez-le avec `uv run delve serve --port <other>` ; `--host` change l'adresse sur laquelle il écoute.
3. Sur cette machine, ouvrez <http://localhost:7810/>.

Relancez `make install` après avoir récupéré une nouvelle version de Delve : Delve refuse de démarrer quand ses
données de règles manquent ou ne sont pas à jour.

## Créer le compte du propriétaire

Tant qu'il n'y a pas de compte propriétaire, un navigateur sur cette machine est le propriétaire et n'a pas besoin de
se connecter. Créez le compte avant d'ouvrir Delve à internet (par un tunnel ou un proxy).

- Dans le navigateur de cette machine, ouvrez la page de connexion et remplissez **Créer le compte du propriétaire**,
  ou
- dans un terminal, lancez `uv run delve account add <username> --owner`. Il demande le mot de passe.

Le compte propriétaire a tous les droits, depuis n'importe quel appareil.

<figure><img src="/help/first-owner.webp" alt="La page de connexion avec Créer le compte du propriétaire en dessous, entouré" width="480" height="800" loading="lazy"></figure>

## Vos autres appareils

Sur votre propre réseau, un autre de vos appareils peut se passer de connexion grâce au jeton du propriétaire. Lancez
`uv run delve token` : il affiche un lien pour chacune des adresses réseau de la machine. Ouvrez-en un une fois sur
l'autre appareil. Par internet, le jeton du propriétaire est refusé, et vous vous connectez avec votre compte
propriétaire.

Le jeton du propriétaire n'expire jamais. Si un lien a circulé, créez-en un nouveau avec **Créer un nouveau jeton du
propriétaire** sous **Préférences → Stockage**, ou avec `uv run delve token --new`. L'ancien jeton et ses liens
cessent aussitôt de fonctionner.

## Où vivent vos données

Tout est dans `~/.local/share/delve`, ou dans le dossier que nomme `DELVE_DATA_DIR`. Voir
[Stockage et sauvegarde](/help/storage-and-backup).
