# com/office_dispatcher.py
# Routes Office COM commands; action names live in ``automation.action_space``.

from automation.action_space import OFFICE_ACTIONS


class OfficeDispatcher:
    """Every ``action`` in ``OFFICE_ACTIONS`` must be implemented in ``OfficeController.execute``."""

    OFFICE_ACTIONS = OFFICE_ACTIONS

    def is_office_command(self, command):
        return command.get("action") in OFFICE_ACTIONS
