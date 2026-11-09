"""Ledger invariants independent of device command implementation."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from manual_tasks import Journal, TaskError
from manual_workflow import ObservationError
from lab_workflow import Workflow
from lab_workflow_ledger import begin_withdrawal,confirm_withdrawal,remaining,StageState


class LedgerInvariants(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.journal=Journal(Path(self.folder.name)/'ledger.sqlite3')
        self.flow=Workflow.create(self.journal,run_id='SYN.LAB.LEDGER')
        self.state=self.flow.state

    def tearDown(self):
        self.journal.close();self.folder.cleanup()

    def test_distinct_intents_are_required_and_unknown_is_not_a_zero_debit(self):
        root=self.state;pending={'intent_id':'withdrawal-1'}
        begin_withdrawal(root,'nanodrop',pending,'Sample01',{'kind':'discarded_after_cleanup'})
        with self.assertRaises(TaskError):
            begin_withdrawal(root,'nanodrop',pending,'Sample01',{'kind':'other'})
        root['bookings']['withdrawal-1']['outcome']='unknown'
        self.assertIsNone(remaining(root,'Sample01'))
        # The planned 1.5 uL is not an upper bound: an explicitly confirmed
        # deviation of 2 uL is booked once against the known original volume.
        confirm_withdrawal(root,'nanodrop',pending,'Sample01',2,'Confirmed synthetic deviation')
        self.assertEqual(remaining(root,'Sample01'),38)
        with self.assertRaises(TaskError):
            confirm_withdrawal(root,'nanodrop',pending,'Sample01',2,'Repeated receipt')
        self.assertEqual(remaining(root,'Sample01'),38)

    def test_remaining_volume_is_read_only_and_mass_is_invalidated_at_intent(self):
        root=self.state;vessel=root['inventory']['vessels']['Tube01']
        vessel['mass_confirmation_valid']=True
        view=StageState(root,'nanodrop')
        with self.assertRaises(TaskError):view['samples']['Sample01']['remaining_volume_ul']=400
        begin_withdrawal(root,'nanodrop',{'intent_id':'pending'},'Sample01',{'kind':'discarded_after_cleanup'})
        self.assertFalse(vessel['mass_confirmation_valid'])
        self.assertTrue(vessel['volume_uncertain'])
        self.assertEqual(vessel['content_revision'],0)

    def test_cf01_inventory_conserves_each_original_once_before_projection(self):
        inventory={'rack':[s['sample_id'] for s in self.state['definition']['manifest']['samples']],
                   'rotor':[None]*12,'gripper':None}
        self.assertEqual(len(Workflow._cf_locations(self.state,inventory)),12)
        for kind in ['duplicate','short','foreign']:
            observed=copy.deepcopy(inventory)
            if kind=='duplicate':observed['rotor'][0]='Sample01'
            elif kind=='short':observed['rack'].pop()
            else:observed['rack'][0]='OtherSample'
            with self.subTest(kind=kind),self.assertRaises(ObservationError):
                Workflow._cf_locations(self.state,observed)


if __name__=='__main__':unittest.main()
