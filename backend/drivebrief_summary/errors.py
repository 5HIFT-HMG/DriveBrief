class SummaryError(Exception):
    """Only safe, fixed diagnostic messages may cross the CLI boundary."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
