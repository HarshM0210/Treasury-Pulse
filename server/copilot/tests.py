"""Intent parser tests (no database, no LLM):  python manage.py test copilot"""
from django.test import SimpleTestCase

from copilot.intent import detect_intent

ENTITIES = [
    {"id": 3, "code": "NY", "city": "New York"}, {"id": 5, "code": "LONDON", "city": "London"},
    {"id": 8, "code": "PARIS", "city": "Paris"}, {"id": 9, "code": "SAO_PAULO", "city": "Sao Paulo"},
    {"id": 7, "code": "HK", "city": "Hong Kong"},
]
CPS = ["vendor_Y", "client_A", "interbank_ABC"]


def d(q):
    return detect_intent(q, ENTITIES, CPS)


class IntentTests(SimpleTestCase):
    # tests carried over from the standalone module
    def test_forecast_entity_horizon(self):
        got = d("Show 14-day forecast for entity 2")
        self.assertEqual((got["intent"], got["entity_id"], got["horizon"]), ("forecast", 2, 14))

    def test_what_if(self):
        self.assertEqual(d("What-if payment delay scenario")["intent"], "what_if")

    def test_currency(self):
        self.assertEqual(d("Show USD transactions")["currency"], "USD")

    # entity names
    def test_entity_by_city(self):
        self.assertEqual(d("forecast for New York")["entity_id"], 3)
        self.assertEqual(d("how is São Paulo doing?")["entity_id"], 9)
        self.assertEqual(d("cash inflows in Hong Kong")["entity_id"], 7)

    def test_short_code_is_whole_word_only(self):
        self.assertIsNone(d("any alerts?")["entity_id"])

    # what-if levers
    def test_payment_delay(self):
        got = d("What if we delay payments by 3 days in London?")
        self.assertEqual(got["intent"], "what_if")
        self.assertEqual(got["what_if_params"], {"payment_delay_days": 3})
        self.assertEqual(got["entity_id"], 5)

    def test_capex(self):
        self.assertEqual(d("postpone capex by 20 days for Paris")["what_if_params"], {"capex_postpone_days": 20})

    def test_fx_negative_words(self):
        self.assertEqual(d("What if EUR weakens 10% for Paris?")["what_if_params"], {"fx_shock_pct": -10.0})

    def test_rate_bps_and_percent(self):
        self.assertEqual(d("rates +100 bps for London")["what_if_params"], {"rate_shock_bps": 100})
        self.assertEqual(d("what if interest rates rise by 1% in NY")["what_if_params"], {"rate_shock_bps": 100})

    def test_rating_shift(self):
        got = d("Downgrade vendor_Y to D for London")
        self.assertEqual(got["what_if_params"]["rating_shift"], {"counterparty": "vendor_Y", "new_rating": "D"})

    def test_horizon_not_mistaken_for_delay(self):
        got = d("show the forecast for the next 14 days")
        self.assertEqual((got["intent"], got["horizon"], got["what_if_params"]), ("forecast", 14, {}))

    # other intents
    def test_other_intents(self):
        self.assertEqual(d("Which entities face a shortfall?")["intent"], "alerts")
        self.assertEqual(d("Where is idle cash we could deploy?")["intent"], "surplus")
        self.assertEqual(d("Tell me about client_A")["intent"], "counterparties")
        self.assertEqual(d("why did settlements fail?")["intent"], "settlement_causes")
        self.assertEqual(d("Monthly trend for London")["intent"], "monthly_trend")
        self.assertEqual(d("upcoming payments this week")["intent"], "upcoming")
