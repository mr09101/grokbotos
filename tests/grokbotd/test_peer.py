"""Unix socket callers are identified by the kernel (SO_PEERCRED pid ->
systemd unit / executable / script) and grants bind to that identity,
not to the self-reported x-client label."""
import json
import os
import subprocess
import sys
import textwrap
import unittest

import test_grokbotd as tg

sys.path.insert(0, tg.LIB)
import grokbot_consent  # noqa: E402
from grokbotd import peer, perms  # noqa: E402

CALLER = textwrap.dedent("""
    import json, socket, sys
    s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])
    f = s.makefile("rwb")
    req = {"jsonrpc": "2.0", "id": 1, "method": sys.argv[2], "params": json.loads(sys.argv[3])}
    if len(sys.argv) > 4:
        req["x-client"] = sys.argv[4]
    f.write((json.dumps(req) + "\\n").encode()); f.flush()
    print(f.readline().decode())
""")


class PeerParsing(unittest.TestCase):
    def test_unit_of(self):
        u = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/%s\n"
        self.assertEqual(peer.unit_of(u % "grokbot-mcp.service"), "grokbot-mcp.service")
        self.assertEqual(peer.unit_of(u % "app-grokbot\\x2dsysmon-1a2b3c4d5e.scope"), "app-grokbot\\x2dsysmon.scope")
        self.assertEqual(peer.unit_of(u % "app-foot-1234.scope"), "app-foot.scope")
        self.assertIsNone(peer.unit_of("0::/user.slice/user-1000.slice/session-3.scope\n"))
        self.assertIsNone(peer.unit_of("0::/user.slice/user-1000.slice/user@1000.service\n"))
        self.assertIsNone(peer.unit_of("0::/\n"))
        self.assertIsNone(peer.unit_of(""))
        # system units (CI agent, system services) do not name the program
        self.assertIsNone(peer.unit_of("0::/system.slice/hosted-compute-agent.service\n"))
        self.assertIsNone(peer.unit_of("0::/system.slice/app-x-1234.scope\n"))
        # another user's manager is not the peer's
        self.assertIsNone(peer.unit_of(u % "grokbot-mcp.service", 1001))
        self.assertEqual(peer.unit_of(u % "grokbot-mcp.service", 1000), "grokbot-mcp.service")

    def test_script_of(self):
        self.assertEqual(peer.script_of(["python3", "-u", "x.py"], "/home/a"), "/home/a/x.py")
        self.assertEqual(peer.script_of(["python3", "-m", "http.server"], "/"), "module:http.server")
        self.assertEqual(peer.script_of(["sh", "-c", "echo"], "/"), "inline")
        self.assertEqual(peer.script_of(["python3"], "/"), "interactive")
        self.assertEqual(peer.script_of(["bash", "../b/../c.sh"], "/a/x"), "/a/c.sh")

    def test_identify_self_and_gone(self):
        p, d = peer.identify(os.getpid(), os.getuid())
        self.assertTrue(p.startswith("local:uid=%d:" % os.getuid()), p)
        self.assertEqual(d["pid"], os.getpid())
        self.assertTrue(perms.is_local(p))
        self.assertEqual(peer.identify(2 ** 22 + 7, os.getuid())[0], "local:uid=%d:unknown" % os.getuid())

    def test_storable_and_describe(self):
        u = os.getuid()
        self.assertFalse(perms.storable("local:uid=%d" % u))
        self.assertFalse(perms.storable("local:uid=%d:unknown" % u))
        self.assertFalse(perms.storable("local:uid=%d:unit=x.service" % (u + 1)))
        self.assertTrue(perms.storable("local:uid=%d:unit=x.service" % u))
        self.assertTrue(perms.storable("origin:http://a.app.localhost:7311"))
        self.assertEqual(peer.describe("local:uid=1:unit=grokbot-mcp.service"), "grokbot-mcp.service")
        self.assertEqual(peer.describe("local:uid=1:exe=/usr/bin/python3:script=/opt/a/tool.py"), "tool.py")
        self.assertEqual(peer.describe("local:uid=1:exe=/usr/bin/foo"), "foo")

    def test_prompt_names_the_program(self):
        ko, en = grokbot_consent.who({"principal": "local:uid=1:exe=/usr/bin/python3:script=/opt/a/tool.py",
                                      "client": "Grok Bot"})
        self.assertIn("tool.py", en)
        self.assertIn("says it is: Grok Bot", en)
        ko, en = grokbot_consent.who({"principal": "local:uid=1:unknown"})
        self.assertIn("unidentified", en)


class PeerDaemon(tg.Base):
    def setUp(self):
        for f in ("consent.log", "consent-answer", os.path.join("cfg", "grokbot", "api-grants.json")):
            try:
                os.unlink(os.path.join(self.tmp.name, f))
            except FileNotFoundError:
                pass
        self.scripts = {}
        for n in ("tool_a", "tool_b"):
            path = os.path.join(self.tmp.name, n + ".py")
            with open(path, "w") as f:
                f.write(CALLER)
            self.scripts[n] = path

    def answer(self, a):
        with open(os.path.join(self.tmp.name, "consent-answer"), "w") as f:
            f.write(a + "\n")

    def prompts(self):
        try:
            with open(os.path.join(self.tmp.name, "consent.log")) as f:
                return [json.loads(x) for x in f if x.strip()]
        except FileNotFoundError:
            return []

    def run_as(self, name, method, params=None, client=None):
        argv = [sys.executable, self.scripts[name], self.sock, method, json.dumps(params or {})]
        if client:
            argv.append(client)
        return json.loads(subprocess.run(argv, capture_output=True, text=True, check=True).stdout)

    def test_each_program_has_its_own_identity(self):
        a = self.run_as("tool_a", "permissions.whoami")["result"]
        b = self.run_as("tool_b", "permissions.whoami", client="tool_a")["result"]
        self.assertTrue(a["principal"].endswith(":script=" + self.scripts["tool_a"]), a)
        self.assertNotEqual(a["principal"], b["principal"])  # the label does not matter
        self.assertEqual(b["client_label"], "tool_a")
        self.assertTrue(a["storable"] and a["local"])
        self.assertEqual(a["exe"], os.path.realpath(sys.executable))

    def test_always_grant_binds_to_that_program_only(self):
        self.answer("always")
        r = self.run_as("tool_a", "network.wifi.disconnect")
        self.assertIn("result", r, r)
        self.assertEqual(len(self.prompts()), 1)
        self.assertIn("tool_a.py", self.prompts()[0]["principal"])
        self.answer("deny")
        self.assertIn("result", self.run_as("tool_a", "network.wifi.disconnect"))
        self.assertEqual(len(self.prompts()), 1)  # remembered for A
        r = self.run_as("tool_b", "network.wifi.disconnect", client="tool_a")
        self.assertEqual(r["error"]["code"], -32001)  # B was asked, even claiming to be A
        self.assertEqual(len(self.prompts()), 2)
        self.assertIn("tool_b.py", self.prompts()[1]["principal"])
        lst = self.run_as("tool_a", "permissions.list")["result"]["principals"]
        mine = [p for p in lst if p["principal"].endswith("tool_a.py")]
        self.assertEqual(mine[0]["scopes"]["network"]["write"], "allow")

    def test_bare_legacy_grant_is_not_applied(self):
        path = os.path.join(self.tmp.name, "cfg", "grokbot", "api-grants.json")
        with open(path, "w") as f:
            json.dump({"version": 1, "grants": {"local:uid=%d" % os.getuid(): {"network": {"mode": "allow"}}}}, f)
        self.answer("deny")
        r = self.run_as("tool_a", "network.wifi.disconnect")
        self.assertEqual(r["error"]["code"], -32001)
        self.assertEqual(len(self.prompts()), 1)

    def test_audit_has_pid(self):
        self.run_as("tool_a", "system.info")
        e = self.rpc_unix("audit.list", {"limit": 5})["result"]["entries"]
        hit = [x for x in e if x.get("method") == "system.info"]
        self.assertTrue(hit and hit[-1].get("pid"), e)


if __name__ == "__main__":
    unittest.main()
