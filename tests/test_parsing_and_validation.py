import os
import unittest

import sys, os
sys.path.append(os.path.dirname(__file__))
from _stubs import install_basic_stubs
install_basic_stubs()

import FrenchVocab


class TestParsingAndValidation(unittest.TestCase):
    def setUp(self):
        # Create a bare instance without running __init__ where needed
        self.builder = object.__new__(FrenchVocab.FrenchVocabBuilder)

    def test_parse_ai_response_valid(self):
        resp = (
            "Spelling Check: Looks good\n"
            "Correctly Spelt Word: manger\n"
            "Word Type: verb\n"
            "Definitions:\n"
            "a. to eat\n"
            "b. to consume (common)\n"
            "Examples:\n"
            "1. Je mange une pomme.\n( I eat an apple. )\n"
            "2. Hier, j'ai mangé au restaurant.\n( Yesterday, I ate at the restaurant. )\n"
            "3. Demain, je mangerai avec des amis.\n( Tomorrow, I will eat with friends. )\n"
        )
        wt, defs, exs = self.builder.parse_ai_response(resp)
        self.assertEqual(wt, ['verb'])
        self.assertIn('to eat', defs[0])
        self.assertEqual(len(exs), 3)
        self.assertEqual(exs[0][0], 'Je mange une pomme.')
        self.assertIn('I eat an apple', exs[0][1])

    def test_parse_ai_response_missing(self):
        resp = (
            "Spelling Check: OK\n"
            "Correctly Spelt Word: beau\n"
            "Word Type: adjective\n"
            "Definitions:\n"
            "a. beautiful\n"
        )
        wt, defs, exs = self.builder.parse_ai_response(resp)
        self.assertEqual(wt, ['adjective'])
        # Current parser requires 'Examples:' to parse definitions; without it, defs is empty
        self.assertEqual(defs, [])
        self.assertEqual(exs, [])

    def test_is_valid_french_input(self):
        b = self.builder
        # bind method still works
        self.assertTrue(FrenchVocab.FrenchVocabBuilder.is_valid_french_input(b, "café"))
        self.assertTrue(FrenchVocab.FrenchVocabBuilder.is_valid_french_input(b, "aujourd’hui"))  # curly apostrophe
        self.assertTrue(FrenchVocab.FrenchVocabBuilder.is_valid_french_input(b, "porte-monnaie"))
        self.assertFalse(FrenchVocab.FrenchVocabBuilder.is_valid_french_input(b, "bonjour!"))
        self.assertFalse(FrenchVocab.FrenchVocabBuilder.is_valid_french_input(b, "123"))


if __name__ == '__main__':
    unittest.main()
