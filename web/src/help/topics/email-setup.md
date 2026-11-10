---
title: Setting up email with Emailit
audience: owner
summary: The key, the DNS records and the sender that let Delve send confirmation, password and table emails.
screens: /preferences
order: 4
related: connections, accounts-and-sign-up
---
Delve sends email through [Emailit](https://emailit.com): confirmations of addresses, password resets, "you're in"
mails and, if people ask for them, table and board notices. Until you set it up, Delve sends nothing, and the
**Email** row in **Preferences → Connections** can only write to the log.

1. In Emailit, make an API key of the type **Sending Only**, restricted to your domain. Paste it as the **Emailit key**.
2. Add your domain in Emailit and put its records in your DNS, with `<domain>` standing for your domain:
   - an SPF record: type TXT at `emailit.<domain>`, value `v=spf1 include:_spf.emailit.com ~all`;
   - a DKIM record: type TXT at `emailit._domainkey.<domain>`, with the value Emailit shows you;
   - a bounce record: type MX at `emailit.<domain>`, pointing to `feedback-smtp.ffdc-1.emailit.com`;
   - optionally a DMARC record: type TXT at `_dmarc.<domain>`, value `v=DMARC1; p=none;`.
3. Press **Check DNS** in Emailit and wait until every record is green.
4. In Delve, choose **Emailit** under **Sends through**, fill in the **Sender** (on your domain, such as
   `Delve <delve@example.org>`) and the **Public address** (where Delve lives on the internet, such as
   `https://delve.example`; the links in emails start with it), and **Save**.
5. Make sure your own address is set and confirmed in your profile, then press **Test**: a test email goes to it.

Emailit starts every account in a trial. Ask them for production access; until they give it, only the addresses of
your Emailit workspace's members receive mail.

The row also says how many emails went today and shows the latest failures, with their reason. It never shows anyone's
address. An `EMAILIT_API_KEY` in the environment wins over a saved key.
