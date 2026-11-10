"""A message composed from the words of a language (DEL-314): a subject, a text part and an HTML part.

The words a host or a poster wrote (`note`, `message`, `excerpt`) go into the text as they are and into the HTML
escaped, their line breaks kept. Nothing is fetched from elsewhere: no images, no tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Literal

from delve.mail import texts

Kind = Literal["confirm", "reset", "approved", "test", "schedule", "host", "board"]

ALWAYS = {"confirm", "reset", "approved", "test"}
"""These go whatever the account's switches say, and carry no off link."""
SWITCH = {"schedule": "mail_host", "host": "mail_host", "board": "mail_board"}
"""The account switch each other kind follows."""

USER_WORDS = ("note", "message", "excerpt")


@dataclass(frozen=True)
class Composed:
    subject: str
    text: str
    html: str


def _prefix(kind: Kind, values: dict[str, str]) -> str:
    # A schedule mail is `skipped` or `moved`, named by `values["change"]`.
    return f"email.{kind}.{values['change']}" if kind == "schedule" else f"email.{kind}"


def _html_value(key: str, value: str) -> str:
    out = escape(value, quote=False)
    return out.replace("\r\n", "\n").replace("\n", "<br>") if key in USER_WORDS else out


def _paragraphs(body: str) -> str:
    return "".join(f"<p>{part.replace(chr(10), '<br>')}</p>" for part in body.split("\n\n") if part)


def compose(kind: Kind, language: str, values: dict[str, str], *, link: str | None, off_link: str | None) -> Composed:
    """The subject, text and HTML of a message of `kind` in `language`.

    A schedule mail may carry the host's `values["note"]` after its body. A host's message ends with how to answer: `values["replyable"]` set means a reply to the email reaches the host.
    A host's message with the host's own `values["subject"]` takes it as its subject, after the table's name.
    """
    prefix = _prefix(kind, values)
    plain = {key: value for key, value in values.items()}
    safe = {key: _html_value(key, value) for key, value in values.items()}
    subject_key = "email.host.subjectLine" if kind == "host" and values.get("subject") else f"{prefix}.subject"
    subject = texts.text(language, subject_key, **plain)

    body = texts.text(language, f"{prefix}.body", **plain)
    html_body = escape(texts.template(language, f"{prefix}.body"), quote=False).format(**safe)
    extra: list[tuple[str, str]] = []  # (text, html) lines after the body
    if kind == "host":
        key = "email.host.reply" if values.get("replyable") else "email.host.noReply"
        extra.append((texts.text(language, key, **plain), escape(texts.text(language, key, **plain), quote=False)))

    text_lines = [body, ""]
    html_parts = [_paragraphs(html_body)]
    if kind == "schedule" and values.get("note"):  # the host's own line, as written
        text_lines += [values["note"], ""]
        html_parts.append(f"<p>{safe['note']}</p>")
    if link:
        label = texts.text(language, f"{prefix}.action", **plain)
        text_lines += [f"{label}: {link}", ""]
        html_parts.append(
            f'<p><a href="{escape(link)}">{escape(label, quote=False)}</a><br>{escape(link, quote=False)}</p>'
        )
    for plain_line, html_line in extra:
        text_lines += [plain_line, ""]
        html_parts.append(f"<p>{html_line}</p>")
    footer = texts.text(language, "email.footer")
    text_lines.append(footer)
    foot_html = [escape(footer, quote=False)]
    if off_link:
        off = texts.text(language, "email.footer.off", link=off_link)
        text_lines.append(off)
        foot_html.append(escape(off, quote=False))
    html_parts.append('<p style="color:#6b6b6b;font-size:12px">' + "<br>".join(foot_html) + "</p>")

    page = (
        '<!doctype html><html><body style="margin:0;background:#f4f1ea;font-family:Georgia,serif;color:#222">'
        '<div style="max-width:560px;margin:0 auto;padding:16px">'
        '<div style="font-size:22px;font-weight:bold;padding:8px 0;border-bottom:2px solid #8a6d3b">Delve</div>'
        + "".join(html_parts)
        + "</div></body></html>"
    )
    # One line, whatever a table's or a host's name holds.
    return Composed(subject=" ".join(subject.split()), text="\n".join(text_lines) + "\n", html=page)
