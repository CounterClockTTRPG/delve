Below, between `<records>` and `</records>`, are the {{kind}} drafted from a role-playing adventure module, one
per line: `id | name | role | the first sentence of its summary`. Each part of the book was read on its
own, so one person or group may be here more than once, under another name or with another part of its story.

Group the records that are the same {{what}}. Group only what the lines show to be one: a father and his son, or two
smugglers of one crew, are two. Leave a record that is no one else alone.

Answer with one JSON list and nothing else: a list of groups, each a list of ids, the record to keep first. A record is
in one group at most; one you leave out stays as it is. With nothing to group, answer `[]`.

```
[["ned", "ned-shakeshaft", "the-spy"], ["the-bosun", "bosun-2"]]
```

<records>
{{records}}
</records>
