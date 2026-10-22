import json
from pathlib import Path
import tempfile
import unittest

from blackflow.config import Config
from blackflow.maa_worker import make_overlay
from blackflow.progress import WorkerProgress


class ReportedEncounterTests(unittest.TestCase):
    def test_preparation_exit_uses_text_and_never_falls_back_to_side_event(self):
        with tempfile.TemporaryDirectory() as folder:
            make_overlay(Config.load(), 'prepare', Path(folder))
            resource = Path(folder) / 'resource'
            strategy = json.loads((resource / 'roguelike/BlackFlow/strategy.json').read_text(encoding='utf-8'))
            module = next(m for m in strategy['modules'] if m['id'] == 'mechanic_flight')
            rule = next(r for r in module['encounter_rules'] if r['event_name'] == '险路尽头')
            self.assertEqual(rule['option_text'], ['说服同伴'])
            self.assertFalse(rule['allow_fallback'])
            self.assertNotIn('choose', rule)
            tasks = json.loads((resource / 'tasks/tasks.json').read_text(encoding='utf-8'))
            self.assertEqual(tasks['BlackFlow@Roguelike@ExitThenAbandon-Enter']['next'], ['AutoUtopia@RecoveryWait'])
            self.assertEqual(tasks['BlackFlow@Roguelike@ExitThenAbandon-Enter']['action'], 'DoNothing')

    def test_stop_guard_is_scoped_to_preparation_and_does_not_break_explicit_abandon(self):
        for phase in ('formal', 'abandon'):
            with tempfile.TemporaryDirectory() as folder:
                make_overlay(Config.load(), phase, Path(folder))
                tasks = json.loads((Path(folder)/'resource/tasks/tasks.json').read_text(encoding='utf-8'))
                self.assertNotIn('BlackFlow@Roguelike@ExitThenAbandon-Enter', tasks)

    def test_error_context_preserves_reported_floor_event_and_selection(self):
        p = WorkerProgress()
        p.observe(20003, {'what':'BlackFlowRoutingDecision','details':{'floor':2}})
        p.observe(20003, {'what':'RoguelikeEvent','details':{'name':'险路尽头'}})
        options = [{'enabled':False,'text':'召集同伴'}, {'enabled':True,'text':'离开黑池'},
                   {'enabled':True,'text':'帮助倒下的探险家同伴'}]
        p.observe(20003, {'what':'RoguelikeEncounterOptions','details':{'options':options}})
        p.observe(20003, {'what':'RoguelikeEventSelected','details':{'option_text':'帮助倒下的探险家同伴'}})
        p.observe(20001, {'subtask':'ProcessTask','details':{'task':'StageEncounterResult'}})
        p.observe(10000, {'taskchain':'Roguelike'})
        self.assertIn('第2层', p.summary())
        self.assertIn('险路尽头', p.summary())
        self.assertIn('帮助倒下的探险家同伴', p.summary())
        self.assertEqual(p.snapshot()['options'], options)
        p.observe(20003, {'what':'RoguelikeEvent','details':{'name':'下一事件'}})
        self.assertEqual(p.snapshot()['options'], [])
        self.assertEqual(p.selection, '')


if __name__ == '__main__':
    unittest.main()
