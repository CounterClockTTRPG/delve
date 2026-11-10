---
title: Connecting Delve to other services
audience: owner
summary: Pictures from Replicate or your own server, Google login, email, and the name on the privacy policy.
screens: /preferences
order: 3
related: backends, accounts-and-sign-up, looks-and-image-styles
---
Only the owner sees **Preferences → Connections**. A token you save there stays in this machine's files, and Delve
never shows it again: it only says whether one is set. A change takes effect at once, with no restart.

- **Replicate** paints portraits, scenes and possessions, for money. Paste its **Token**. A `REPLICATE_API_TOKEN` in
  the environment wins over a saved token.
- **assetgen** is your own picture server, on this machine or your network. Give its **URL**, and a token if it needs
  one.
- **Google login** lets people log in and sign up with Google. In Google Cloud's console, make an OAuth client of the
  type Web application, and register the addresses under **Redirect URIs to register** as its authorised redirect
  URIs. Then paste the **Client ID** and **Client secret** here.
- **Email** sends confirmations, password resets and table notices through Emailit. Paste its **Emailit key**, give
  the **Sender** and your **Public address**, and press **Test**. [Setting up email with Emailit](/help/email-setup)
  walks through the key and the DNS records.
- **Privacy and terms** is who runs this Delve, as the public [privacy policy](/privacy) and [terms](/terms) show it.
  Fill in **Your name** and a **Contact email**.

Each row has **Save**. Replicate, assetgen and Google login also have **Remove** once they are set, and Replicate,
assetgen and Email have a **Test**: use it to check the connection before players rely on it (Email's sends a test email
to your own confirmed address). Once a picture service is connected, choose which jobs use it under
[Backends](/help/backends).

Google sends a browser back only to https addresses and to this machine, so the Google buttons show there and not on
your local network's addresses, where players use their passwords.

<figure><img src="/help/connections-tab.webp" alt="Connections: Replicate and assetgen, each with Save and Test" width="976" height="590" loading="lazy"></figure>
