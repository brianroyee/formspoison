import unittest

from submitter import _matches_choice_option


class SubmitterChoiceMatchingTests(unittest.TestCase):
    def test_partial_match_for_longer_option_label(self):
        self.assertTrue(_matches_choice_option("Robotics", "Robotics & Intelligent Systems (NeuroBots)"))

    def test_normalized_exact_match(self):
        self.assertTrue(_matches_choice_option("Python Programming - Data Science", "Python Programming - Data Science"))

    def test_non_matching_value_does_not_match(self):
        self.assertFalse(_matches_choice_option("Robotics", "Cloud Computing"))


if __name__ == "__main__":
    unittest.main()
