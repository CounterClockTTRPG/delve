"""YAML from a bundle, without aliases (DEL-152): `safe_load` expands every `*alias`, so a few hundred bytes of
nested aliases become gigabytes once the data is stored or walked. Bundles never need them."""
from __future__ import annotations

import yaml


class _NoAliasLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):  # noqa: ANN001, ANN201 - PyYAML's own signature
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.composer.ComposerError(None, None, "YAML aliases (*name) are not allowed", event.start_mark)
        return super().compose_node(parent, index)


def load_yaml(text: str | bytes):  # noqa: ANN201 - whatever the YAML holds
    """`yaml.safe_load`, refusing aliases with a `yaml.YAMLError`."""
    return yaml.load(text, Loader=_NoAliasLoader)  # noqa: S506 - a SafeLoader
