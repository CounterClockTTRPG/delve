# The terrain colours of a map picture

The picture is a contact sheet made from a map. Each row is one colour of the map, numbered on the left, with a few
of the map's cells that have that colour.

Say which terrain each colour shows. The terrain classes are: {classes}. Say `outside` for a colour that isn't part
of the map's land or water: its frame, its legend, its title or its margin. Use the map's own look: drawn trees are
forest, peaks are mountain, mounds are hills, tufts in wet ground are swamp, blue is sea or lake.

The colours:
{clusters}

Answer with JSON only, one entry per colour, as `{"<colour number>": "<terrain class>"}`.
