---
title: Connecter Delve à d'autres services
summary: Des images de Replicate ou de votre propre serveur, la connexion avec Google, et le nom sur la politique de confidentialité.
---
Seul le propriétaire voit **Préférences → Connexions**. Un jeton que vous y enregistrez reste dans les fichiers de
cette machine, et Delve ne le montre plus jamais : il dit seulement s'il y en a un. Un changement prend effet
aussitôt, sans redémarrage.

- **Replicate** peint des portraits, des scènes et des possessions, contre paiement. Collez son **Jeton**. Un
  `REPLICATE_API_TOKEN` dans l'environnement l'emporte sur un jeton enregistré.
- **assetgen** est votre propre serveur d'images, sur cette machine ou sur votre réseau. Donnez son **URL**, et un
  jeton s'il en faut un.
- **Connexion avec Google** permet de se connecter et de s'inscrire avec Google. Dans la console Google Cloud, créez
  un client OAuth de type Application Web, et enregistrez les adresses sous **URI de redirection à enregistrer** comme
  ses URI de redirection autorisées. Puis collez ici l'**ID client** et le **Code secret du client**.
- **E-mail** envoie confirmations, réinitialisations de mot de passe et avis de table par Emailit. Collez sa **Clé
  Emailit**, donnez l'**Expéditeur** et votre **Adresse publique**, puis appuyez sur **Tester**.
  [Configurer l'e-mail avec Emailit](/help/email-setup) détaille la clé et les enregistrements DNS.
- **Confidentialité et conditions** indique qui gère ce Delve, tel que le montrent la
  [politique de confidentialité](/privacy) et les [conditions](/terms) publiques. Remplissez **Votre nom** et une
  **Adresse de contact**.

Chaque ligne a **Enregistrer**. Replicate, assetgen et la connexion avec Google ont aussi **Retirer** une fois
configurés, et Replicate, assetgen et E-mail ont un bouton **Tester** : utilisez-le pour vérifier la connexion avant
que les joueurs en dépendent (pour l'e-mail, un e-mail de test part vers votre propre adresse confirmée). Une fois un service d'images connecté, choisissez quelles tâches l'utilisent sous
[Backends](/help/backends).

Google ne renvoie un navigateur que vers des adresses https et vers cette machine : les boutons Google s'affichent donc
là, et pas sur les adresses de votre réseau local, où les joueurs utilisent leur mot de passe.

<figure><img src="/help/connections-tab.webp" alt="Connexions : Replicate et assetgen, chacun avec Enregistrer et Tester" width="976" height="590" loading="lazy"></figure>
