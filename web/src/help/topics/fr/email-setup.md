---
title: Configurer l'e-mail avec Emailit
summary: La clé, les enregistrements DNS et l'expéditeur qui permettent à Delve d'envoyer les e-mails de confirmation, de mot de passe et de table.
---
Delve envoie ses e-mails par [Emailit](https://emailit.com) : confirmations d'adresses, réinitialisations de mot de passe, e-mails
« vous êtes dedans » et, si on les demande, avis de table et de panneau. Tant que vous ne le configurez pas, Delve
n'envoie rien, et la ligne **E-mail** de **Préférences → Connexions** ne peut écrire que dans le journal.

1. Dans Emailit, créez une clé d'API du type **Sending Only**, limitée à votre domaine. Collez-la comme **Clé Emailit**.
2. Ajoutez votre domaine dans Emailit et mettez ses enregistrements dans votre DNS, `<domaine>` étant votre domaine :
   - un enregistrement SPF : type TXT sur `emailit.<domaine>`, valeur `v=spf1 include:_spf.emailit.com ~all` ;
   - un enregistrement DKIM : type TXT sur `emailit._domainkey.<domaine>`, avec la valeur qu'Emailit vous montre ;
   - un enregistrement de rebond : type MX sur `emailit.<domaine>`, vers `feedback-smtp.ffdc-1.emailit.com` ;
   - en option, un enregistrement DMARC : type TXT sur `_dmarc.<domaine>`, valeur `v=DMARC1; p=none;`.
3. Appuyez sur **Check DNS** dans Emailit et attendez que chaque enregistrement soit vert.
4. Dans Delve, choisissez **Emailit** sous **Envoi par**, remplissez l'**Expéditeur** (sur votre domaine, comme
   `Delve <delve@example.org>`) et l'**Adresse publique** (où Delve se trouve sur internet, comme
   `https://delve.example` ; les liens des e-mails commencent par elle), puis **Enregistrez**.
5. Vérifiez que votre propre adresse est renseignée et confirmée dans votre profil, puis appuyez sur **Tester** : un e-mail d'essai part vers elle.

Emailit met chaque compte en essai. Demandez l'accès en production ; tant qu'il n'est pas accordé, seules les adresses
des membres de votre espace de travail Emailit reçoivent du courrier.

La ligne dit aussi combien d'e-mails sont partis aujourd'hui et montre les derniers échecs, avec leur raison. Elle ne
montre jamais l'adresse de quelqu'un. Une `EMAILIT_API_KEY` dans l'environnement l'emporte sur une clé enregistrée.
