"""Validator diagnostic report contract."""

import json

class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.details = {}

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def emit(self, as_json=False):
        payload = {
            "status": "failed" if self.errors else "passed",
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.details:
            payload["details"] = self.details
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("agent-system validation:", payload["status"])
            for message in self.errors:
                print("ERROR:", message)
            for message in self.warnings:
                print("WARN:", message)
            if self.details:
                print(json.dumps(self.details, ensure_ascii=False, indent=2))
        return 1 if self.errors else 0
