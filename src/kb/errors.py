"""Application errors with defined exit-code semantics (spec §8.3)."""


class KBError(Exception):
    """Runtime failure — reported to the user, exit code 1."""


class NotFoundError(KBError):
    """A referenced book or universe does not exist — usage error, exit code 2."""
