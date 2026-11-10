---
title: Getting and editing modules
audience: organiser
summary: Convert a book's PDF, import a .dscn, have Claude write one, or start empty; then check it and fix it.
screens: /modules, /modules/new, /modules/:moduleId
order: 1
related: start-a-campaign, author-a-map
---
A campaign plays a module: an adventure with its texts, maps, NPCs and encounters. Under **Modules**, choose
**New module**. There are four ways to make one:

- **An empty module**: give it a title, choose **Make the module**, and write the rest in its editor.
- **Import a .dscn**: a module exported from Delve, here or on another install, comes back with its maps, texts and
  records.
- **From a PDF**: Claude turns a module's book into texts, NPCs and encounters, images and maps, keeping the book's
  own words. Choose **Thorough (default)** or **Quick**, then **Ready to play** or **A draft to work on**, and
  **Convert**.
- **Describe the module you want**: write **Your request** ("a dungeon with kobolds, no plot") and choose
  **Generate**. Claude writes a small module with a sketched map. For a bigger request it may ask a few questions
  first.

You can also drop a PDF or a `.dscn` file anywhere on the page.

An empty module and one Claude writes are marked **Homebrew** on their card; one converted from a book isn't, and an
import keeps its own tags. To change it, tick or clear **Homebrew** under the module's **Details**.

<figure><img src="/help/new-module-ways.webp" alt="New module: an empty module, from a PDF, a described module, or a .dscn import, and the conversions below" width="960" height="716" loading="lazy"></figure>

## While a book converts

A big book takes a while: **Thorough** can take hours. The page shows the step and the pages done, survives a reload,
and **Cancel** stops it without leaving half a module. One conversion runs at a time; the next waits in the queue.
**Modules** shows a running conversion at the top, and a notice tells you when it is done.

## Check what the conversion left

The module's page folds its warnings into one line, such as "17 warnings". Open it to see them by kind, each linked to
what it is about. Look first at:

- **Maps sketched from the room key**: Claude drew the map from the room list, so its layout is invented. Compare it
  with **Show the book's page**.
- **Shown to the players: check them**: everything else starts DM only.
- **Images to describe**: say what each picture shows, so the DM knows when to use it.

A draft can't start a campaign. When it is right, choose **Mark as ready**.

## Reading and editing a module

The module's page has tabs: **Text**, **NPCs**, **Encounters**, **Factions**, **Quests**, **Pregens**,
**Attachments**, **Maps** and **Details**.

- In **Text**, a heading such as `## 2. The Hall` is a keyed heading: it links itself to that room on the map. A quote
  straight after a heading is read-aloud text. Save with **Save** or Ctrl+S.
- Each text, record and attachment is **DM only** or for the players. Tick several and choose **DM only** or **For
  the players** to change them at once. This is how you open a book's handouts to the players.
- In **Attachments**, **Crop…** cuts a picture: draw the part to keep, turn it a quarter, or **Add piece** to split a
  plate of several NPCs into a picture each. The players see only the cut; **Reset** gives back the whole picture. A
  conversion may propose crops of its own: check each and choose **Looks right**.
- Under **Fix-it comments**, say in plain words what is wrong. Claude proposes a fix in the background; **Review** it,
  then **Keep** or **Reject**.

A campaign keeps the revision of the module it started with. To bring your edits into it, choose **Upgrade to the
latest revision** on the campaign's page.

**Export .dscn** saves the whole module as a file; **Print the module** opens it for printing, DM-only material
included. If the owner has set up a shared library ([Storage and backup](/help/storage-and-backup)), the
**Library** tab lists its modules to **Download**.
