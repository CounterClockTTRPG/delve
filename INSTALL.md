# Installing Delve

Delve runs on one machine, as one process on one port, and you play in a browser: on that machine, on other devices
of your network, or over the internet behind a proxy. Claude is the DM, through the Claude Code command line on your
own Claude subscription. These steps are for Linux and macOS; on Windows, use WSL 2.

## Quick install (Linux)

    git clone https://github.com/CounterClockTTRPG/delve.git
    cd delve
    ./install.sh

The script checks what you have and offers, step by step, to install what's missing: git, make and curl through your
package manager (apt, dnf, pacman or zypper, with sudo), uv and its Python, Node.js 24 through nvm, and Claude Code,
and to log you in to Claude. Then it installs Delve with the OSRIC ruleset, builds the web app, offers to add the
sample adventure, The Lady of the Weir, and to start Delve, now or as a systemd service that starts with your
computer. It says what it runs before it runs it. `./install.sh --check` only reports; `./install.sh --yes` takes the
recommended answer everywhere (it doesn't log in to Claude or start Delve). The rest of this guide is the same by
hand, and for macOS.

## 1. What you need

| | Version | Check |
|---|---|---|
| [Python](https://www.python.org/) | 3.12 or newer | `python3 --version` |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | any recent | `uv --version` |
| [Node.js](https://nodejs.org/) with npm | 20 or newer (24 is what Delve is built with) | `node --version` |
| [git](https://git-scm.com/) | any | `git --version` |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`) | current | `claude --version` |
| `make` | any | `make --version` |

Optional:
- **tesseract** (`apt install tesseract-ocr`, `brew install tesseract`): reads scanned pages when you turn a module's
  PDF into a Delve module, and labels on pictures of world maps. Without it, Delve reads only a PDF's text layer.
- A [Replicate](https://replicate.com/) token, for painted portraits and scenes (they cost money). Without one,
  portraits are drawn for free in the browser.

### Claude Code

Delve's DM, its translations and its conversions all run through `claude`. Install it and log in once, as the user who
will run Delve:

    npm install -g @anthropic-ai/claude-code
    claude            # log in with your Claude account, then quit with /exit

`claude` must be on the `PATH` of whatever starts Delve (your shell, or the systemd service below). Without it Delve
still starts, but `/api/health` and Preferences → Backends say the DM is unavailable.

## 2. Get Delve and install it

    git clone https://github.com/CounterClockTTRPG/delve.git
    cd delve
    make install

`make install` does three things:
1. `uv sync`: makes `.venv` with Delve and its Python dependencies.
2. `uv run delve pack install packs/osric`: installs **OSRIC 3.0**, the ruleset in this repository, into the data
   directory (below). Aun, Delve's own setting, is built in.
3. `npm ci` in `web/`: the web app's dependencies.

## 3. Start it

    make run

This builds the web app and starts Delve on port **7810**. Open <http://localhost:7810/> on the same machine.

- Another port: `uv run delve serve --port 8000`. Delve listens on every address by default; `--host 127.0.0.1`
  keeps it to this machine.
- Delve keeps everything in `~/.local/share/delve` (mode 0700): the database `delve.db`, the installed packs, the
  owner token and the stored files. Set `DELVE_DATA_DIR` to keep them elsewhere. Back this folder up; Preferences →
  Storage can also back it up every day to Azure Blob Storage or an S3-compatible store.
- Stop it with Ctrl-C.

## 4. The first time

1. **Make the owner account.** Until there is one, a browser on the same machine needs no login, and the login page
   offers **Make the owner account**. Or from a shell, which asks for the password:

       uv run delve account add <username> --owner

   Do this before you open Delve to anyone else, and certainly before any tunnel or proxy: once the owner account
   exists, every browser logs in.
2. **Check the DM.** Under Preferences → **Backends**, each job (the DM, helper tasks, translation, conversions)
   should say Claude (claude -p). A red line says what's missing.
3. **Get a first module.** The repository comes with a sample adventure, **The Lady of the Weir**: an evening's
   play for OSRIC in Aun, for four to six 1st–2nd level characters. Import `samples/lady-of-the-weir.dscn` under
   **Modules** → **New module** → **Import a .dscn**. (Changed the folder `samples/lady-of-the-weir`? Pack it again
   with `(cd samples/lady-of-the-weir && python3 -m zipfile -c ../lady-of-the-weir.dscn *)`.)

   Or write one (**An empty module**), describe one for Claude to make (**Describe the module you want**), or turn a
   module's PDF into one (**From a PDF**).
4. **Play.** Under **Campaigns**, start a campaign from the module (ruleset OSRIC, setting Aun), open it under
   **Play**, and write what your characters do. "Make us a party of four" is a fine first act. **Help**, in the side
   bar, explains the rest.

## 5. Playing with friends

- **On your network:** friends open `http://<this machine's address>:7810/` (`uv run delve token` prints this
  machine's addresses). The host shares a table's **join link** from the play screen, and each friend makes an
  account or logs in through it.
- **Over the internet:** put Delve behind an HTTPS reverse proxy or a tunnel (for example cloudflared) on the same
  machine, and tell Delve its public name, so it answers to it:

      DELVE_ALLOWED_HOSTS=delve.example.org uv run delve serve

  The proxy must send `X-Forwarded-For` and `X-Forwarded-Proto` (cloudflared and Caddy do; for nginx, set them). The
  owner token is refused over the internet: log in with the owner account there.

## 6. Run it as a service (Linux, systemd)

With a socket unit, systemd holds the port while Delve restarts, so a restart refuses no one, and the owner's
**Restart Delve now** (Preferences → Packs) works. Make the two files below, with your own path to the checkout and to
`uv`:

`~/.config/systemd/user/delve.socket`

    [Unit]
    Description=Delve's port, held across restarts

    [Socket]
    ListenStream=0.0.0.0:7810

    [Install]
    WantedBy=sockets.target

`~/.config/systemd/user/delve.service`

    [Unit]
    Description=Delve
    Requires=delve.socket
    After=delve.socket

    [Service]
    Type=simple
    WorkingDirectory=%h/delve
    ExecStart=%h/.local/bin/uv run delve serve --port 7810
    Restart=on-failure
    RestartSec=3
    TimeoutStopSec=10
    # claude, uv and node must be on this PATH.
    Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
    # Environment=DELVE_ALLOWED_HOSTS=delve.example.org

    [Install]
    WantedBy=default.target

Then:

    make build                                   # the web app, once and after each update
    systemctl --user daemon-reload
    systemctl --user enable --now delve.socket
    systemctl --user enable delve.service
    loginctl enable-linger "$USER"               # keep it running when you log out
    journalctl --user -u delve -f                # its log

Restart it with `systemctl --user restart delve`. Stop it entirely by stopping both the socket and the service; with
the socket alone running, the next request starts Delve again.

## 7. Rulesets and settings

Rulesets and settings are **packs**. This repository brings OSRIC 3.0 (`packs/osric`) and Aun, Delve's own setting.
The owner installs other packs under Preferences → **Packs** (a `.delvepack` file), or from a shell:

    uv run delve pack install path/to/pack-folder       # or a .delvepack file, or a git URL
    uv run delve pack list

A pack holds code that runs on your machine: install only packs you trust. Restart Delve after installing or removing
one. The code and tests name some packs that are not part of this repository (`adnd2e`, `greyhawk`,
`forgotten-realms`); none of their content is here, and Delve plays without them.

## 8. Updating

    git pull
    make install          # new dependencies and the OSRIC pack's update
    make build
    systemctl --user restart delve        # or stop and start `make run`

Delve brings its database up to date when it starts. A database made by a newer Delve is refused rather than
damaged.

## 9. Checking an install, and developing

    make ci               # ruff, import-linter, the Python tests, the web typecheck, tests and build

`make ci` needs no `claude`: the tests use a fake DM. `make e2e-browser` runs the browser checks in Chromium
(`npx playwright install chromium` once, in `web/`). See the README's **Development** section and `docs/` for the
design.

## Troubleshooting

- **"Port 7810 is in use"**: another Delve runs, or the systemd socket holds the port. Use `--port`, or
  `systemctl --user stop delve.socket delve.service`.
- **The DM never answers, or Backends is red**: run `claude --version` as the user that runs Delve; with the service,
  check its `Environment=PATH=`.
- **"Log in to go on." on this machine**: there is an owner account now; log in with it.
- **A campaign says its ruleset or setting isn't installed**: install that pack, then restart Delve.
- **The page looks old after an update**: run `make build` again and reload the page.
