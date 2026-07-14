"""Application errors with defined exit-code semantics (spec §8.3)."""


class KBError(Exception):
    """Runtime failure — reported to the user, exit code 1."""


class NotFoundError(KBError):
    """A referenced book or universe does not exist — usage error, exit code 2."""


class ImageSafetyError(KBError):
    """The image provider's content-safety filter refused the request.

    Permanent for a given prompt — retrying never helps; the scene must be
    softened instead (``kb edit <slug> --page N --image "..."``).
    """
