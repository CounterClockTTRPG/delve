---
title: Installing Delve and the first run
audience: owner
summary: Install Delve, start it, make the owner account, and open it from your other devices.
screens: /login
order: 1
related: accounts-and-sign-up, backends, connections
---
Delve runs as one program on one port on your machine. You are its owner: you installed it, so you hold every right.

## Install and start

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and Node.js. Claude is the DM through the `claude`
command line (Claude Code) on your own subscription, so install it and log in first: `claude` must be on the `PATH`
of the shell that starts Delve.

1. In Delve's folder, run `make install`. It installs what Delve needs and builds its rules data.
2. Run `make run`. It builds the web app and starts Delve on port 7810. To use another port, start it with
   `uv run delve serve --port <other>`; `--host` changes the address it listens on.
3. On this machine, open <http://localhost:7810/>.

Run `make install` again after you pull a new version of Delve: Delve refuses to start when its rules data is
missing or out of date.

## Make the owner account

Until there is an owner account, a browser on this machine is the owner and needs no login. Make the account before
you open Delve to the internet (through a tunnel or a proxy).

- In the browser on this machine, open the login page and fill in **Make the owner account**, or
- in a terminal, run `uv run delve account add <username> --owner`. It asks for the password.

The owner account has every right, from any device.

<figure><img src="/help/first-owner.webp" alt="The login page with Make the owner account below it, ringed" width="480" height="800" loading="lazy"></figure>

## Your other devices

On your own network, another device of yours can skip the login with the owner token. Run `uv run delve token`: it
prints a link for each of the machine's network addresses. Open one once on the other device. Over the internet the
owner token is refused, and you log in with your owner account.

The owner token never expires. If a link got out, make a new one with **Make a new owner token** under
**Preferences → Storage**, or with `uv run delve token --new`. The old token and its links stop working at once.

## Where your data lives

Everything is in `~/.local/share/delve`, or in the folder that `DELVE_DATA_DIR` names. See
[Storage and backup](/help/storage-and-backup).
