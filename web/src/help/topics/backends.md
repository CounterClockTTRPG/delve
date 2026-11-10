---
title: Choosing the backends
audience: owner
summary: Which Claude model and effort each job uses, which service paints the pictures, and the install's language.
screens: /preferences
order: 4
related: connections, looks-and-image-styles, install-and-first-run
---
**Preferences → Backends** chooses who does each of Delve's jobs. Organisers can change it too. A change takes effect
at the next beat.

## The jobs

Each job has a **Provider**, a **Model** and an **Effort**. **Provider default** leaves the choice to the provider.

| Job | What it does |
|---|---|
| **DM** | Narration and rules, every beat |
| **Helper tasks** | Ask the DM, suggestions, image prompts |
| **Translation** | Players' words into English, the DM's out of it |
| **Module conversion** | PDFs into modules, generated dungeons |
| **Thorough conversion** | PDFs into modules, checked against the page images (Claude CLI only) |
| **Novels** | Campaigns and modules written as novels |
| **Portraits** | Characters and NPCs |
| **Scenes** | Places and moments in the story |
| **Possessions** | Strongholds, mounts, ships and the like |

## Claude

The text jobs use **Claude (claude -p)**, the `claude` command line on your subscription. It is offered only when
`claude` is on the `PATH` of the shell that started Delve. Its models are **Opus (most capable)**, **Sonnet** and
**Haiku (fastest)**. A higher effort thinks longer. **Auto** uses a low effort for routine beats and a high one where
the rules get hard.

## Pictures

- **portraitgen (free)** draws portraits in the browser, at no cost. It does portraits only.
- **Replicate** and **assetgen** appear once you connect them under [Connections](/help/connections). Each model shows
  its service and its price, or **free**.

A paid model for scenes or possessions paints only when a table's host turns on **Paid images**.

<p class="note">A provider marked (development) is for testing Delve: its pictures are fake and its DM is scripted.
Don't choose it for play.</p>

## When a choice can't be used

- If a provider has a problem for now (assetgen is down, say), the job keeps your choice and shows **Can't be used:**
  and why. It works again once the provider does.
- If a provider is gone (you removed its connection), the jobs that chose it fall back to their default, and the tab
  says so at the top.

## The rest of the tab

This tab also holds the **Image style** (see [Looks and image styles](/help/looks-and-image-styles)) and the
**Language** of buttons and labels on this install. Choose **Save** when you are done.

<figure><img src="/help/backends-jobs.webp" alt="Backends and models: each job with its Provider, Model and Effort" width="984" height="800" loading="lazy"></figure>
