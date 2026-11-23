import unittest
try:
    from repair import is_affected, reopen_rows
except ImportError:
    from universal.repair import is_affected, reopen_rows


class RepairSelectionTests(unittest.TestCase):
    def test_partial_with_unresolved_slots(self):
        self.assertTrue(is_affected({'status': 'partial_validated', 'unresolved_slots': [{'slot': '2024-?'}], 'profile': 'domestic'}))

    def test_partial_without_unresolved_slots_stays(self):
        self.assertFalse(is_affected({'status': 'partial_validated', 'unresolved_slots': [], 'profile': 'domestic'}))

    def test_domestic_no_validated_reports(self):
        self.assertTrue(is_affected({'status': 'held', 'reason_code': 'NO_VALIDATED_REPORTS', 'profile': 'domestic', 'unresolved_slots': []}))

    def test_foreign_no_validated_reports_stays(self):
        self.assertFalse(is_affected({'status': 'held', 'reason_code': 'NO_VALIDATED_REPORTS', 'profile': 'foreign_annual'}))

    def test_connected_and_identity_holds_stay(self):
        self.assertFalse(is_affected({'status': 'connected', 'reason_code': 'OK', 'profile': 'domestic'}))
        self.assertFalse(is_affected({'status': 'held', 'reason_code': 'IDENTITY_NAME_MISMATCH', 'profile': 'domestic'}))

    def test_reopen_clears_only_affected_rows(self):
        rows = [
            {'symbol': 'NVDA', 'status': 'partial_validated', 'unresolved_slots': [{'slot': '2024-?'}], 'profile': 'domestic', 'reports': {'2023': {'FY': 'https://www.sec.gov/x'}}, 'ledger': [{}], 'linked_slots': 1, 'reason': 'unresolved_partial_validated'},
            {'symbol': 'TSM', 'status': 'held', 'reason_code': 'NO_VALIDATED_REPORTS', 'profile': 'foreign_annual', 'reports': {}, 'ledger': []},
            {'symbol': 'AAPL', 'status': 'connected', 'reason_code': 'OK', 'profile': 'domestic', 'reports': {'2025': {'FY': 'u'}}, 'ledger': [{}]},
        ]
        out, opened = reopen_rows(rows)
        self.assertEqual(opened, ['NVDA'])
        self.assertEqual(out[0]['status'], 'pending')
        self.assertEqual(out[0]['reports'], {})
        self.assertEqual(out[0]['ledger'], [])
        self.assertNotIn('reason', out[0])
        self.assertEqual(out[1]['status'], 'held')
        self.assertEqual(out[2]['reports'], {'2025': {'FY': 'u'}})


if __name__ == '__main__':
    unittest.main()
