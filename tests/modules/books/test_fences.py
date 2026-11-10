"""Claude's answer without its fence (`books.fences`), shared by the converter and the classifier."""

import pytest

from delve.modules.books.fences import unfenced


@pytest.mark.parametrize(
    ("reply", "answer"),
    [
        ('{"kind": "map"}', '{"kind": "map"}'),
        ('```json\n{"kind": "map"}\n```', '{"kind": "map"}'),
        ('  ```\n{"kind": "map"}```  ', '{"kind": "map"}'),
        ('Here it is:\n\n```json\n{"kind": "map"}\n```\n\nI hope it helps.', '{"kind": "map"}'),
        ("# A text\n\nWith prose.\n\n```\ncode\n```\n\nAnd more prose after it.", None),
    ],
    ids=["bare", "fenced", "fenced-unmarked", "prose-around-json", "a-text-with-a-code-block"],
)
def test_unfenced(reply, answer):
    assert unfenced(reply) == (reply.strip() if answer is None else answer)
