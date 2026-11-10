---
title: Comptes et inscriptions
summary: Ajoutez des joueurs, nommez des organisateurs, ouvrez les inscriptions, admettez des gens et donnez-leur des liens de réinitialisation.
---
Tous les comptes de ce Delve sont sur la page Joueurs : ouvrez **Préférences**, l'onglet **Joueurs**, puis **Ouvrir
Joueurs**. Les organisateurs peuvent aussi utiliser cette page ; certaines actions ne sont qu'à vous.

## Qui peut faire quoi

- Les joueurs accèdent à leurs propres tables, aux écrans de jeu, aux **Préférences** et aux Systèmes de règles.
- Les organisateurs lancent aussi des campagnes, s'occupent des modules et des règles maison, règlent les backends et
  gèrent ici les comptes des joueurs.
- Les propriétaires peuvent tout faire. Seul un propriétaire choisit **Nommer organisateur** ou **Nommer
  propriétaire** (et **Retirer le rôle d'organisateur**, **Retirer le rôle de propriétaire**), et seul un propriétaire
  désactive ou réinitialise le compte d'un organisateur ou d'un propriétaire. Le dernier compte propriétaire reste
  propriétaire.

## D'où viennent les comptes

- D'un lien d'invitation : toute personne qui ouvre le lien d'invitation d'une table peut créer un compte.
- De cette page : remplissez un **Nom d'utilisateur**, un **Nom affiché** et une **Langue**, puis choisissez **Ajouter
  un joueur**. Delve montre un lien qui fixe le mot de passe. Envoyez-le au joueur : il fonctionne une fois, dans les
  24 heures.
- Des inscriptions : les gens demandent eux-mêmes un compte (voir plus bas).
- De la ligne de commande : `uv run delve account add <username>` crée un compte et demande son mot de passe. Ajoutez
  `--organiser` ou `--owner` pour ces droits.

## Inscriptions avec approbation

Les inscriptions sont fermées tant que vous ne cochez pas **Laisser les gens demander un compte**. Tant qu'elles sont
ouvertes, la page de connexion propose **Pas de compte ? Demandez-en un**. Chaque nouveau compte attend sous **En
attente d'approbation**, avec la ligne que la personne a écrite sur qui elle est. Le menu montre combien attendent.

- **Admettre** : le compte peut se connecter dès maintenant.
- **Refuser** : le compte est supprimé, et son nom d'utilisateur est de nouveau libre.

Une personne en attente qui se connecte par le lien d'invitation d'une table est admise par ce lien. Chaque adresse
peut demander 3 fois par heure, et au plus 20 inscriptions attendent à la fois.

<figure><img src="/help/players-waiting.webp" alt="Une inscription sous En attente d'approbation, avec sa note, Admettre entouré et Refuser à côté" width="984" height="170" loading="lazy"></figure>

## Mots de passe oubliés et problèmes

- **Mot de passe oublié ?** sur la page de connexion demande un nom d'utilisateur ou, quand Delve envoie des
  courriels, une adresse e-mail. Un compte avec une adresse confirmée reçoit son lien de réinitialisation par courriel,
  au plus 3 par heure ; aucune demande ne vous attend. La demande de tout autre compte attend ici, sous **Ont demandé un
  nouveau mot de passe**, jusqu'à ce que vous créiez son **Lien de réinitialisation** ou l'écartiez.
- **Lien de réinitialisation** crée un nouveau lien pour fixer le mot de passe du compte ; son ancien lien non utilisé
  cesse de fonctionner. Une réinitialisation délie aussi tous les comptes Google liés au compte.
- **Désactiver** arrête le compte et le déconnecte partout ; **Activer** le rétablit. Vous ne pouvez pas désactiver
  votre propre compte. Les comptes ne sont jamais supprimés, sauf une inscription que vous refusez.

## Comptes Google

Une fois la connexion avec Google mise en place sous [Connexions](/help/connections), les gens peuvent s'inscrire et
se connecter avec Google. Une inscription par Google attend quand même l'approbation. Une personne qui a un compte
peut choisir **Lier votre compte Google** dans son onglet **Profil**. Delve n'associe un compte Google qu'au compte qui
l'a lié ou qui s'est inscrit avec lui, jamais par son adresse e-mail.
