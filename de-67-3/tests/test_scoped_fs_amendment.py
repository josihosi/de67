import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import mutation_guard as g

def document():
 return 'Status: Refrozen\n'+''.join(f'<!-- DE67:DFS-SLICE:BEGIN id=R-{c}-S001 claim=R-{c} -->\n- [ ] 🔴 R-{c} — Behavior {c}\nOld tactic {c}.\n<!-- DE67:DFS-SLICE:END id=R-{c}-S001 claim=R-{c} -->\n' for c in ['A','B'])
class AmendTests(unittest.TestCase):
 def check(self,transform,claims=('R-A',)):
  with tempfile.TemporaryDirectory() as d:
   a,b=Path(d)/'before',Path(d)/'after';a.write_text(document());b.write_text(transform(document()));return g.validate_scoped_dfs_amendment(a,b,claims)
 def test_replaces_obsolete_tactic_without_legacy_headings_or_status_ritual(self):
  self.assertEqual(self.check(lambda s:s.replace('Old tactic A.','Specific corrected behavior.')),('R-A-S001',))
 def test_unrelated_slice_protected(self):
  with self.assertRaises(g.GuardError):self.check(lambda s:s.replace('Old tactic B.','Oops'))
 def test_status_and_claim_id_protected(self):
  for old,new in [('[ ] 🔴 R-A','[x] R-A'),('R-A-S001','R-A-S002'),('Status: Refrozen','Status: Draft')]:
   with self.assertRaises(g.GuardError):self.check(lambda s:s.replace(old,new))
 def test_explicit_existing_scope_required(self):
  for claims in [(),('R-MISSING',)]:
   with self.assertRaises(g.GuardError):self.check(lambda s:s.replace('Old tactic A.','Repair'),claims)
 def test_accepted_claim_cannot_be_amended(self):
  with tempfile.TemporaryDirectory() as d:
   a,b=Path(d)/'a',Path(d)/'b';a.write_text(document().replace('[ ] 🔴 R-A','[x] R-A'));b.write_text(a.read_text().replace('Old tactic A.','Repair'))
   with self.assertRaises(g.GuardError):g.validate_scoped_dfs_amendment(a,b,('R-A',))
 def test_no_change_rejected(self):
  with self.assertRaises(g.GuardError):self.check(lambda s:s)
if __name__=='__main__':unittest.main()
