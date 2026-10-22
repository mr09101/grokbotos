"""Finding #4: audit log flooding."""
import json
import os
import tempfile
import unittest

import test_grokbotd as tg  # noqa: F401  (sys.path)
from grokbotd import audit


class AuditUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "audit.jsonl")
        os.environ["GROKBOT_AUDIT_LOG"] = self.path
        audit._window.update(start=0.0, counts={})

    def tearDown(self):
        os.environ.pop("GROKBOT_AUDIT_LOG", None)
        self.tmp.cleanup()

    def lines(self, p):
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f]

    def test_transport_rejects_are_aggregated_and_separate(self):
        audit.record(transport="unix", principal="local:uid=1", decision="allow", method="x")
        for _ in range(1000):
            audit.record(transport="http", principal="origin:http://a", decision="deny", error="content_type")
        rej = self.lines(audit.rejects_path())
        self.assertEqual(len(rej), 1)
        self.assertEqual(len(self.lines(self.path)), 1)  # the real record is untouched
        audit._window["start"] -= 61
        audit.record(transport="http", principal="origin:http://a", decision="deny", error="content_type")
        rej = self.lines(audit.rejects_path())
        self.assertEqual(rej[1]["count"], 999)
        self.assertTrue(rej[1]["aggregated"])
        self.assertEqual(len(rej), 3)

    def test_many_principals_share_one_bucket(self):
        for i in range(500):
            audit.record(transport="http", principal="origin:http://x%d" % i, decision="deny", error="preflight")
        rej = self.lines(audit.rejects_path())
        self.assertEqual(len(rej), audit.MAX_KEYS + 1)
        self.assertEqual(rej[-1]["principal"], "*other*")
        audit.flush()
        summary = self.lines(audit.rejects_path())[-1]
        self.assertEqual((summary["principal"], summary["count"]), ("*other*", 500 - audit.MAX_KEYS - 1))

    def test_long_values_are_capped(self):
        audit.record(transport="http", principal="p", decision="deny", error="bad_host", host="h" * 5000)
        audit.record(transport="unix", principal="p", decision="allow", params={"a": "b" * 5000})
        self.assertLessEqual(len(self.lines(audit.rejects_path())[0]["host"]), audit.MAX_FIELD + 1)
        self.assertLessEqual(len(self.lines(self.path)[0]["params"]["a"]), audit.MAX_FIELD + 1)

    def test_more_generations(self):
        old = audit.MAX_BYTES
        audit.MAX_BYTES = 200
        try:
            for i in range(40):
                audit.record(transport="unix", principal="p", decision="allow", n=i)
        finally:
            audit.MAX_BYTES = old
        gens = [p for p in os.listdir(self.tmp.name) if p.startswith("audit.jsonl.")]
        self.assertEqual(len(gens), audit.GENERATIONS)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)


class AuditFloodTests(tg.Base):
    def test_no_cors_flood_does_not_rotate_main_log(self):
        self.rpc_unix("system.info")
        before = self.audit()
        for _ in range(300):
            self.http("/v1/rpc", None, {"Origin": "http://evil.example/" + "x" * 1000,
                                        "Content-Type": "text/plain"}, method="POST")
        self.assertEqual(len(self.audit()), len(before))
        self.assertLessEqual(len(self.audit_rejects()), 3)
