from __future__ import annotations

import datetime

from .prompt_files import load_writer_prompt
from .writer.tool_specs import WRITER_TOOLS


def get_writer_execution_discipline() -> str:
    return load_writer_prompt("execution_discipline")


WRITER_EXECUTION_DISCIPLINE_ZH = get_writer_execution_discipline()


def current_date_prompt() -> str:
    return "now: " + datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
