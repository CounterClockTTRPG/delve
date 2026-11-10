# OSRIC 3.0 tables

Delve is an independent product published under the OSRIC 3.0 Third-Party License and is not affiliated with Mythmere
Games LLC.

This work includes material taken from the System Reference Document 5.1 ("SRD 5.1") by Wizards of the Coast LLC and
available at https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is licensed under the Creative
Commons Attribution 4.0 International License available at https://creativecommons.org/licenses/by/4.0/legalcode.

"OSRIC" is a trademark of Matthew Finch and Stuart Marshall; "OSRIC 3" is a trademark of Mythmere Games.

## What is here

The files are the rules of OSRIC 3.0 (Player Guide and Gamemaster Guide) as data: tables of numbers and names, each
citing its section in its `_source`. They hold verbatim text only of monsters (`monsters.json`), spells
(`spells.json`) and magic items (`magic_items.json`), as the license allows, and none of the guides' own prose.

The tables are copied from the owner's OSRIC engine (MIT) by `scripts/osric_snapshot.py`, which leaves out the
passages that matched the guides' text. The bestiary is read from the Gamemaster Guide's PDF by
`scripts/osric_bestiary.py`. Regenerate them with those scripts; don't edit them by hand.
