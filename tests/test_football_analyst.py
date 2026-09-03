import unittest
import io
from unittest.mock import patch

import football_analyst
from football_analyst import analyze_match, normalize_quotes


class FootballAnalystTests(unittest.TestCase):
    def test_extracts_only_explicit_visible_quote_rows(self):
        rows = football_analyst.extract_visible_quotes(
            "Esito finale\nInter 2,10\nMilan 3.40\nAggiornato 2026-08-19\nSaldo 500"
        )
        self.assertEqual([(row["selection"], row["decimal"]) for row in rows], [("Inter", 2.1), ("Milan", 3.4)])

    def test_normalizes_and_selects_best_bookmaker_quote(self):
        quotes = normalize_quotes(
            [
                {"bookmaker": "Snai", "market": "1x2", "selection": "1", "odds": "2.10"},
                {"bookmaker": "GoldBet", "market": "1x2", "selection": "1", "odds": 2.2},
                {"bookmaker": "bad", "market": "1x2", "selection": "X", "odds": 1},
            ]
        )
        self.assertEqual(len(quotes), 2)
        result = analyze_match({"home": "Roma", "away": "Lazio", "quotes": [q.__dict__ for q in quotes]})
        self.assertEqual(result["markets"][0]["best"]["1"]["bookmaker"], "goldbet")
        self.assertTrue(result["advisory_only"])
        self.assertFalse(result["execution"]["bet_placement"])

    def test_missing_data_is_explicit_and_does_not_invent_stats(self):
        result = analyze_match({"home": "A", "away": "B"})
        self.assertEqual(result["stats"]["home_form"]["matches"], 0)
        self.assertIsNone(result["stats"]["home_form"]["goals_for"])
        self.assertTrue(any("Nessuna quota" in warning for warning in result["warnings"]))

    def test_multifactor_analysis_uses_history_stats_and_returns_probabilities(self):
        result = analyze_match({
            "home": "Inter", "away": "Milan",
            "home_history": [
                {"home_goals": 3, "away_goals": 0},
                {"home_goals": 2, "away_goals": 1},
                {"home_goals": 1, "away_goals": 1},
            ],
            "away_history": [
                {"away_goals": 1, "home_goals": 2},
                {"away_goals": 0, "home_goals": 1},
                {"away_goals": 2, "home_goals": 2},
            ],
            "team_stats": {
                "home": {"xg_for": 2.0, "xg_against": 0.8, "rest_days": 6},
                "away": {"xg_for": 1.1, "xg_against": 1.4, "rest_days": 3},
            },
            "head_to_head": [{"home_goals": 2, "away_goals": 0}],
        })
        self.assertEqual(result["stats"]["home_form"]["matches"], 3)
        self.assertGreater(result["probabilities"]["home"], result["probabilities"]["away"])
        self.assertIn("over_2_5", result["probabilities"])
        self.assertIn("btts", result["probabilities"])
        self.assertGreater(result["confidence"], 0.5)
        self.assertTrue(result["advisory_only"])
        self.assertFalse(result["execution"]["bet_placement"])

    def test_historical_csv_collector_is_bounded_and_maps_results(self):
        csv_data = "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,HST,AS,AST\n01/01/26,Inter,Milan,2,0,H,12,6,4,1\n"

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, size): return csv_data.encode()[:size]

        result = football_analyst.collect_historical_results("Inter", "Milan", opener=lambda request, timeout: Response())
        self.assertEqual(result["home_history"][0]["home_goals"], 2)
        self.assertEqual(result["away_history"][0]["away_goals"], 0)
        self.assertIn("football-data.co.uk", result["sources"][0])


if __name__ == "__main__":
    unittest.main()
