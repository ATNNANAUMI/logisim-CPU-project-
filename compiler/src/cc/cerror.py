"""Errors and warnings for the C compiler.

Every message can carry a file, line and column, and prints like gcc:
    prog.c:12:5: error: 'x' undeclared
"""


class CError(Exception):
    """One problem, tied to a place in a source file when there is one."""

    def __init__(self, message, file=None, line=None, col=None):
        super().__init__(message)
        self.message = message
        self.file = file
        self.line = line
        self.col = col

    def where(self):
        if self.file and self.line:
            col = f"{self.col}:" if self.col else ""
            return f"{self.file}:{self.line}:{col} "
        if self.file:
            return f"{self.file}: "
        return ""

    def __str__(self):
        return self.where() + "error: " + self.message

    def as_warning(self):
        return self.where() + "warning: " + self.message


class CErrors(Exception):
    """Several problems found in one run, reported together."""

    def __init__(self, errors):
        super().__init__(f"{len(errors)} error(s)")
        self.errors = list(errors)

    def __str__(self):
        return "\n".join(str(e) for e in self.errors)


def error_at(tok, message):
    """A CError placed at a token (anything with file/line/col). A token
    that came out of a macro expansion is reported where the macro was used."""
    if tok is None:
        return CError(message)
    tok = getattr(tok, "origin", None) or tok
    return CError(message, tok.file, tok.line, tok.col)
