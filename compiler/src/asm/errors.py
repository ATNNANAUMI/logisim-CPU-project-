"""Errors and warnings, shared by the assembler and the linker.

Every message can carry a file name and line number, and prints as
    main.asm:12: unknown name 'prnt'
"""


class AsmError(Exception):
    """One problem, tied to a source line when there is one."""

    def __init__(self, message, file=None, line=None):
        super().__init__(message)
        self.message = message
        self.file = file
        self.line = line

    def where(self):
        if self.file and self.line:
            return f"{self.file}:{self.line}: "
        if self.file:
            return f"{self.file}: "
        return ""

    def __str__(self):
        return self.where() + self.message

    def as_warning(self):
        return self.where() + "warning: " + self.message


class AsmErrors(Exception):
    """Several problems found in one run, reported together."""

    def __init__(self, errors):
        super().__init__(f"{len(errors)} error(s)")
        self.errors = list(errors)

    def __str__(self):
        return "\n".join(str(e) for e in self.errors)
