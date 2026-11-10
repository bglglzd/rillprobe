class ContractError(ValueError):
    """An observable contract violation, with a stable machine-readable code."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
