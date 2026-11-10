from delve.mail import texts
from delve.mail.compose import compose


def test_a_message_is_in_the_recipients_language():
    mail = compose("approved", "nl", {"username": "ana"}, link="https://d.example/login", off_link=None)
    assert mail.subject == texts.text("nl", "email.approved.subject")
    assert "https://d.example/login" in mail.text and "https://d.example/login" in mail.html


def test_a_hosts_words_are_escaped_in_html_and_kept_in_text():
    mail = compose(
        "host",
        "en",
        {"host": "Ana", "table": "Ruins", "message": "<b>hi</b>\nthere"},
        link=None,
        off_link="https://d.example/mail/off/t",
    )
    assert "<b>hi</b>\nthere" in mail.text
    assert "&lt;b&gt;hi&lt;/b&gt;<br>there" in mail.html and "https://d.example/mail/off/t" in mail.text


def test_an_always_kind_has_no_off_line():
    mail = compose("reset", "en", {"username": "ana", "name": "Ana"}, link="https://x/l", off_link=None)
    assert "Turn them off" not in mail.text


def test_every_language_has_every_email_key():
    assert texts.keys("en")
    for language in ("nl", "fr", "de", "lv"):
        assert texts.keys("en") == texts.keys(language)


def test_an_unknown_language_falls_back_to_english_and_a_missing_key_raises():
    assert texts.text("xx", "email.footer") == texts.text("en", "email.footer")
    try:
        texts.text("en", "email.nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_schedule_variants_and_host_reply_line():
    moved = compose(
        "schedule",
        "en",
        {"change": "moved", "table": "Ruins", "old": "Mon", "new": "Tue", "zone": "Europe/Brussels"},
        link=None,
        off_link=None,
    )
    assert "Ruins: the session of Mon moves to Tue (Europe/Brussels)" in moved.text
    host = {"host": "Ana", "table": "Ruins", "message": "hi"}
    assert "aren't read" in compose("host", "en", host, link=None, off_link=None).text
    assert (
        "Reply to this email to answer Ana"
        in compose("host", "en", {**host, "replyable": "1"}, link=None, off_link=None).text
    )


def test_a_language_delve_doesnt_have_is_english_and_names_no_file():
    english = texts.text("en", "email.footer")
    texts._load.cache_clear()
    for language in ("../../etc/passwd", "xx", "EN", "en/../nl", "nl\x00"):
        assert texts.text(language, "email.footer") == english
    assert texts._load.cache_info().currsize == 1  # English alone: the others were never a file name or a cache key


def test_a_hosts_own_subject_is_the_subject_after_the_tables_name():
    values = {"host": "Ana", "table": "Ruins", "message": "hi", "subject": "Your character"}
    assert compose("host", "en", values, link=None, off_link=None).subject == "Ruins: Your character"
    assert compose("host", "nl", values, link=None, off_link=None).subject == "Ruins: Your character"


def test_a_subject_is_one_line_whatever_the_names_hold():
    values = {"host": "Ana", "table": "The\nRuins", "message": "hi", "subject": "Your  character"}
    assert compose("host", "en", values, link=None, off_link=None).subject == "The Ruins: Your character"
    values = {"change": "skipped", "table": "Tue\r\n day", "old": "2026-11-07 20:00", "zone": "UTC"}
    assert "\n" not in compose("schedule", "en", values, link=None, off_link=None).subject
