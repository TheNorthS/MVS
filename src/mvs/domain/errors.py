class ShellError(Exception):
    """Public, deliberately safe error; never constructed from transport exception text."""

    def __init__(self, code: str, message: str, **details: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.details}
