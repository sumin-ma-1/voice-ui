# speech/command_parser.py
# - No target extraction
# - No context extraction
# - The whole command becomes the query on unknown
#
# Office phrases are delegated to ``office_command_parser`` after ``focus`` so phrases like
# ``open excel`` stay COM while ``focus excel`` activates a window title.

from speech.office_command_parser import parse_office_command
from speech.command_parser_rules import parse_focus_command, parse_generic_command


def parse_command(text):

    raw = text.strip()

    focus_cmd = parse_focus_command(raw)
    if focus_cmd is not None:
        return focus_cmd

    office_cmd = parse_office_command(raw)
    if office_cmd is not None:
        return office_cmd

    return parse_generic_command(raw)
