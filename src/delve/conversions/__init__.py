"""Conversions (plan 5): a PDF or a request becomes a module, in the background, with its progress as events. Plan 7's
jobs (`start_job`, `finish`) make no module: a world map read from a picture, or a draft of a dungeon map.

`delve.modules.books` does the work, purely; this package runs it with the DM provider, stores the job and makes the
module. It imports `delve.modules`, `delve.dm`, `delve.storage` and `delve.domain`, and nothing of `delve.web` or
`delve.play`.
"""

from delve.conversions.runner import (
    CONVERSION_TIMEOUT,
    ConversionRunning,
    ConversionServices,
    answer_questions,
    cancel,
    check_pdf,
    close_folders,
    close_lost,
    close_orphans,
    complete_with,
    conversion_json,
    finish,
    look_for,
    module_questions,
    progress_for,
    queue,
    set_queue_paused,
    start_generate,
    start_job,
    start_pdf,
    start_queue,
    tell_dm,
    wait,
)

__all__ = [
    "CONVERSION_TIMEOUT",
    "ConversionRunning",
    "ConversionServices",
    "answer_questions",
    "cancel",
    "check_pdf",
    "close_folders",
    "close_lost",
    "close_orphans",
    "complete_with",
    "conversion_json",
    "finish",
    "look_for",
    "module_questions",
    "progress_for",
    "queue",
    "set_queue_paused",
    "start_generate",
    "start_job",
    "start_pdf",
    "start_queue",
    "tell_dm",
    "wait",
]
