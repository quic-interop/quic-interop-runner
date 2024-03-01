from enum import Enum


class TestResult(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"

    def symbol(self):
        if self == TestResult.SUCCEEDED:
            return "✓"
        elif self == TestResult.FAILED:
            return "✕"
        elif self == TestResult.UNSUPPORTED:
            return "?"
