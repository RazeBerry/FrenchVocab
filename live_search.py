import re
import unicodedata
from typing import Dict, List, Tuple

class LiveSearch:
    def __init__(self, word_entries: Dict[str, Dict]):
        self.word_entries = word_entries

    def remove_accents(self, input_str: str) -> str:
        nfkd_form = unicodedata.normalize('NFKD', input_str)
        return ''.join([c for c in nfkd_form if not unicodedata.combining(c)])

    def search(self, query: str) -> List[Tuple[str, str, str]]:
        normalized_query = self.remove_accents(query.lower())
        results = []

        for word, entry in self.word_entries.items():
            normalized_word = self.remove_accents(word.lower())
            if normalized_word.startswith(normalized_query):
                word_type = entry['type']
                first_definition = entry['definitions'].split(';')[0].strip()
                results.append((word, word_type, first_definition))

        return sorted(results)

    def update_entries(self, word_entries: Dict[str, Dict]):
        self.word_entries = word_entries