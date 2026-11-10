The picture is page {{number}} of a published adventure module. Its text layer lost a few characters on the lines
below: a glyph the book's font draws as a picture, such as the ½ or ¼ of a Hit Dice value ("HD ½"), or a table cell
that holds only such a glyph. Where the line has a field with no value ("HD ;") or an empty cell ("|  |"), the page
prints something there.

<lines>
{{lines}}
</lines>

Find each line on the page and write it as the page prints it, filling only what the text layer lost. Change nothing
else: keep every word, number and mark of the line as it is given, even where you think the book is wrong, and keep
the table's bars. Leave out a line you can't find or can't read on the page.

Answer with JSON only, one entry per line you read:

[{"n": 1, "line": "the line as printed"}]
