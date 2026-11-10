---
title: Multi-classing
source: pg
section: "1.3.11"
---
A multi-classed character holds two or three classes at once and rises in all of them together, written "fighter/thief" or "fighter/magic-user/cleric". Humans never multi-class. Which combinations are open depends on the ancestry (`race_lookup`), and the character starts at the oldest starting age among its classes.

- **Experience.** Every award is split evenly between the classes; fractions are lost. A class that has reached its level limit still takes its share, which is simply wasted.
- **Hit points.** When a class gains a level, roll that class's hit die, add the Constitution adjustment, then divide by the number of classes, dropping any fraction.
- **Attacks and saves.** For each roll, the character uses whichever class table is better at that moment, even switching table by save type.
- **Armour, weapons and spells** differ by ancestry (`race_lookup`):
  - elves and half-elves take the loosest armour and weapon rules of their classes, so an elven fighter/magic-user casts in plate;
  - gnomes and halflings must keep to leather or lighter to use any non-fighter ability, so a gnome fighter/illusionist may wear plate but cannot cast in it;
  - a dwarf fighter/thief keeps to a thief's arms and armour but attacks as a fighter;
  - half-orcs take the loosest weapon rule.
- **Thief abilities** everywhere work only with gear a single-classed thief could use (an assassin's skills with an assassin's armour; half-orcs may still read languages).
