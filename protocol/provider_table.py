class ProviderTable:
    def __init__(self):
        self.table = {}

    def update(self, provider_id, energy):
        self.table[provider_id] = energy

    def get_best_provider(self):
        if not self.table:
            return None
        return max(self.table, key=self.table.get)
