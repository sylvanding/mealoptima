class WarningCollector:
    def __init__(self):
        self.warnings = []

    def get_warnings(self):
        return self.warnings

    def add(self, message):
        self.warnings.append(message)

    def print_all(self):
        if self.warnings:
            print("\n".join(self.warnings))
