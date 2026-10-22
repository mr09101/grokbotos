"""Consent-based write API: per-scope modes, the prompt, camera/mic
sessions, revoke, audit.list, CLI. Runs the real daemon (test_grokbotd.Base)
with fake tools and a fake consent prompt."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import test_grokbotd as tg

sys.path.insert(0, tg.LIB)
import grokbot_consent  # noqa: E402
import grokbot_status  # noqa: E402
from grokbotd import consent, perms, policy  # noqa: E402


class ConsentDaemonTests(tg.Base):
    def setUp(self):
        for f in ("consent.log", "tools.log", "consent-answer", "pwfile.seen",
                  os.path.join("cfg", "grokbot", "api-grants.json"),
                  os.path.join("cfg", "grokbot", "api-permissions.json")):
            try:
                os.unlink(os.path.join(self.tmp.name, f))
            except FileNotFoundError:
                pass

    def me(self):
        return self.rpc_unix("permissions.whoami")["result"]["principal"]

    def answer(self, a):
        with open(os.path.join(self.tmp.name, "consent-answer"), "w") as f:
            f.write(a + "\n")

    def prompts(self):
        try:
            with open(os.path.join(self.tmp.name, "consent.log")) as f:
                return [json.loads(x) for x in f if x.strip()]
        except FileNotFoundError:
            return []

    def tools(self):
        try:
            with open(os.path.join(self.tmp.name, "tools.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def origin_rpc(self, origin, method, params=None):
        return self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                         {"Origin": origin})

    def sys_grant(self, doc):
        with open(os.path.join(self.tmp.name, "cfg", "grokbot", "api-permissions.json"), "w") as f:
            json.dump(doc, f)

    # ---- local caller ----

    def test_local_allow_scope_runs_silently_and_is_audited(self):
        r = self.rpc_unix("audio.set", {"volume_percent": 55})
        self.assertIn("result", r, r)
        self.assertIn("wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 55%", self.tools())
        self.assertEqual(self.prompts(), [])
        e = [x for x in self.audit() if x.get("method") == "audio.set"][-1]
        self.assertEqual((e["decision"], e["scope"], e["access"], e["mode"]), ("allow", "audio", "write", "allow"))
        self.assertEqual(e["params"], {"target": "output", "volume_percent": 55})

    def test_ask_deny_once_always(self):
        r = self.rpc_unix("network.wifi.disconnect")
        self.assertEqual(r["error"]["code"], -32001)
        self.assertEqual(r["error"]["data"]["consent"], "user")
        p = self.prompts()[-1]
        self.assertEqual((p["scope"], p["method"], p["principal"]), ("network", "network.wifi.disconnect",
                                                                    self.me()))
        self.assertTrue(p["allow_always"])
        self.assertNotIn("nmcli device disconnect", self.tools())
        self.assertEqual([x for x in self.audit() if x.get("method") == "network.wifi.disconnect"][-1]
                         ["consent"], "deny")
        self.answer("once")
        r = self.rpc_unix("network.wifi.disconnect")
        self.assertEqual(r["result"], {"disconnected": True, "device": "wlan0"})
        self.assertEqual(len(self.prompts()), 2)
        self.answer("always")
        self.rpc_unix("network.wifi.disconnect")
        self.answer("deny")
        r = self.rpc_unix("network.wifi.disconnect")  # stored allow: no prompt
        self.assertIn("result", r)
        self.assertEqual(len(self.prompts()), 3)
        g = self.rpc_unix("permissions.list", {"principal": self.me()})["result"]
        self.assertEqual(g["principals"][0]["scopes"]["network"]["stored"]["mode"], "allow")

    def test_local_reads_ignore_stored_ask(self):
        self.answer("once")
        me = self.me()
        self.assertIn("result", self.rpc_unix("permissions.set", {"principal": me, "scope": "audio", "mode": "deny"}))
        n = len(self.prompts())
        self.assertIn("result", self.rpc_unix("audio.status"))
        self.assertEqual(len(self.prompts()), n)
        self.assertEqual(self.rpc_unix("audio.set", {"muted": True})["error"]["code"], -32001)
        w = self.rpc_unix("audit.list", {"access": "write", "limit": 1000})["result"]["entries"]
        self.assertTrue(w and all(e["access"] == "write" for e in w))

    def test_wifi_password_never_logged_or_on_argv(self):
        self.answer("once")
        r = self.rpc_unix("network.wifi.connect", {"ssid": "Home:Net", "password": "hunter2hunter2"})
        self.assertIn("result", r, r)
        self.assertNotIn("hunter2", self.tools())
        with open(os.path.join(self.tmp.name, "pwfile.seen")) as f:
            self.assertEqual(f.read(), "802-11-wireless-security.psk:hunter2hunter2\n")
        with open(os.path.join(self.tmp.name, "state", "grokbot", "audit.jsonl")) as f:
            self.assertNotIn("hunter2", f.read())
        self.assertNotIn("hunter2", json.dumps(self.prompts()))
        self.assertEqual([f for f in os.listdir(self.env["XDG_RUNTIME_DIR"]) if f.startswith("wifi-")], [])

    def test_wifi_list_parses_escaped_and_dedups(self):
        r = self.rpc_unix("network.wifi.list")["result"]["networks"]
        self.assertEqual([(n["ssid"], n["in_use"], n["signal"]) for n in r],
                         [("Home:Net", True, 80), ("Cafe", False, 60)])

    def test_power_always_asks_and_never_stores(self):
        self.answer("always")
        r = self.rpc_unix("power.action", {"action": "suspend"})
        self.assertEqual(r["result"], {"action": "suspend", "scheduled": True})
        self.assertFalse(self.prompts()[-1]["allow_always"])
        time.sleep(1.0)
        self.assertIn("systemctl suspend", self.tools())
        self.rpc_unix("power.action", {"action": "reboot"})
        self.assertEqual(len(self.prompts()), 2)  # asked again
        self.assertIsNone(self.rpc_unix("permissions.list", {"principal": self.me()})["result"]["principals"][0]["scopes"]["power"]["stored"])
        self.answer("once")
        r = self.rpc_unix("permissions.set", {"principal": self.me(), "scope": "power",
                                              "mode": "allow"})
        self.assertEqual(r["error"]["code"], -32000)

    def test_power_denied_by_default_answer(self):
        r = self.rpc_unix("power.action", {"action": "poweroff"})
        self.assertEqual(r["error"]["code"], -32001)
        time.sleep(0.8)
        self.assertNotIn("systemctl poweroff", self.tools())

    def test_screenshot(self):
        self.answer("once")
        r = self.rpc_unix("capture.screenshot")["result"]
        self.assertEqual((r["name"], r["size_bytes"]), ("screenshot-test.png", 3))

    def test_idle(self):
        r = self.rpc_unix("lock.set_idle", {"lock_s": 120})["result"]
        self.assertEqual(r, {"screen_off_s": 300, "lock_s": 120})
        with open(os.path.join(self.tmp.name, "cfg", "grokbot", "idle.conf")) as f:
            self.assertIn("lock = 120", f.read())
        self.assertIn("pkill -u", self.tools())

    # ---- camera / microphone ----

    def test_camera_session_prompt_indicator_stop(self):
        r = self.rpc_unix("camera.session.start", {"purpose": "video call"})
        self.assertEqual(r["error"]["code"], -32001)
        self.answer("always")
        sid = self.rpc_unix("camera.session.start", {"purpose": "video call"})["result"]["id"]
        self.assertFalse(self.prompts()[-1]["allow_always"])
        st = self.rpc_unix("privacy.status")["result"]
        self.assertTrue(st["camera"])
        self.assertFalse(st["microphone"])
        self.rpc_unix("camera.session.start")
        self.assertEqual(len(self.prompts()), 3)  # every session prompts
        self.assertEqual(self.rpc_unix("media.session.stop", {"id": sid})["result"], {"stopped": True})
        self.assertEqual(self.rpc_unix("media.session.stop", {"id": sid})["error"]["code"], -32000)

    # ---- web origins ----

    def test_origin_without_grant_is_denied_without_prompt(self):
        o = "http://x.app.localhost:%d" % self.port
        code, _, body = self.origin_rpc(o, "audio.set", {"muted": True})
        self.assertEqual((code, body["error"]["data"]["mode"]), (403, "deny"))
        code, _, _ = self.origin_rpc(o, "power.action", {"action": "reboot"})
        self.assertEqual(code, 403)
        self.assertEqual(self.prompts(), [])

    def test_origin_ask_mode_prompts_with_origin(self):
        o = "http://notes.app.localhost:%d" % self.port
        self.sys_grant({"origins": {o: {"audio": "ask", "power": "allow"}}})
        self.answer("once")
        code, h, body = self.origin_rpc(o, "audio.set", {"muted": True})
        self.assertEqual(code, 200, body)
        self.assertEqual(h.get("Access-Control-Allow-Origin"), o)
        self.assertEqual(self.prompts()[-1]["principal"], "origin:" + o)
        # "allow" for power is capped to ask
        self.origin_rpc(o, "power.action", {"action": "lock"})
        self.assertEqual(self.prompts()[-1]["scope"], "power")

    def test_legacy_capability_list_grants_reads_only_and_no_star(self):
        o = "http://old.app.localhost:%d" % self.port
        self.sys_grant({"origins": {o: ["system.read", "*"]}})
        self.assertEqual(self.origin_rpc(o, "system.info")[0], 200)
        self.assertEqual(self.origin_rpc(o, "windows.list")[0], 403)
        self.assertEqual(self.origin_rpc(o, "audio.set", {"muted": True})[0], 403)

    def test_permissions_request_and_rate_limit_and_revoke(self):
        o = "http://req%d.app.localhost:%d" % (int(time.time() * 1000) % 100000, self.port)
        self.answer("always")
        code, _, body = self.origin_rpc(o, "permissions.request", {"scope": "display", "reason": "dim"})
        self.assertEqual(body["result"]["mode"], "allow")
        code, _, body = self.origin_rpc(o, "display.brightness")
        self.assertEqual(code, 200)
        code, _, body = self.origin_rpc(o, "permissions.request", {"scope": "audio"})
        self.assertEqual(body["result"]["mode"], "allow")
        self.answer("deny")
        code, _, body = self.origin_rpc(o, "permissions.request", {"scope": "audio"})
        self.assertEqual(body["result"]["mode"], "allow")  # already allowed: no prompt
        self.rpc_unix("permissions.revoke", {"principal": "origin:" + o, "scope": "audio"})
        code, _, body = self.origin_rpc(o, "permissions.request", {"scope": "audio"})
        self.assertEqual((code, body["error"]["code"]), (403, -32001))  # cooldown
        # the origin cannot list or change permissions on its own
        self.assertEqual(self.origin_rpc(o, "permissions.list")[0], 403)
        self.assertEqual(self.origin_rpc(o, "audit.list")[0], 403)
        rc, out, err = self.cli("revoke", o)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.origin_rpc(o, "display.brightness")[0], 403)

    def test_no_origin_http_gets_nothing(self):
        code, _, body = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "permissions.request",
                                              "params": {"scope": "audio"}})
        self.assertEqual(code, 403)
        code, _, _ = self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": "power.action",
                                           "params": {"action": "reboot"}})
        self.assertEqual(code, 403)
        self.assertEqual(self.prompts(), [])

    def test_always_ask_scope_reads_do_not_prompt_once_granted(self):
        o = "http://pw.app.localhost:7311"
        self.sys_grant({"origins": {o: {"power": "ask"}}})
        r = self.origin_rpc(o, "power.status")[2]
        self.assertIn("result", r, r)
        self.assertEqual(self.prompts(), [])  # VM b3-06: read prompted on every poll
        self.answer("once")
        self.origin_rpc(o, "power.action", {"action": "suspend"})
        self.assertEqual(len(self.prompts()), 1)  # actions still ask
        self.sys_grant({"origins": {}})

    def test_identical_concurrent_prompts_share_one_answer(self):
        import threading
        self.sys_grant({"origins": {"http://q.app.localhost:7311": {"network": "ask"}}})
        self.answer("deny")
        # slow fake prompt so the calls overlap
        out = []
        ts = [threading.Thread(target=lambda: out.append(self.origin_rpc("http://q.app.localhost:7311",
                                                                          "network.status")[2]))
              for _ in range(5)]
        open(os.path.join(self.tmp.name, "consent-delay"), "w").close()
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertEqual(len(out), 5)
        self.assertTrue(all(x["error"]["code"] == -32001 for x in out))
        os.unlink(os.path.join(self.tmp.name, "consent-delay"))
        self.assertLess(len(self.prompts()), 5)
        self.sys_grant({"origins": {}})

    def test_once_is_one_call_and_session_is_remembered_in_memory(self):
        o = "http://sess.app.localhost:7311"
        self.sys_grant({"origins": {o: {"network": "ask"}}})
        self.answer("once")
        self.assertIn("result", self.origin_rpc(o, "network.status")[2])
        self.assertIn("result", self.origin_rpc(o, "network.status")[2])
        self.assertEqual(len(self.prompts()), 2)  # once = this call only
        p = self.prompts()[-1]
        self.assertTrue(p["allow_session"] and p["allow_once"] and p["allow_always"])
        self.answer("session")
        self.assertIn("result", self.origin_rpc(o, "network.status")[2])
        self.answer("deny")
        self.assertIn("result", self.origin_rpc(o, "network.status")[2])
        self.assertEqual(len(self.prompts()), 3)  # remembered for the session
        g = self.rpc_unix("permissions.list", {"principal": "origin:" + o})["result"]["principals"][0]
        self.assertTrue(g["scopes"]["network"]["session"])
        self.assertIsNone(g["scopes"]["network"]["stored"])  # nothing on disk
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "cfg", "grokbot", "api-grants.json")))
        self.assertEqual(self.rpc_unix("permissions.revoke", {"principal": "origin:" + o})["result"]["revoked"],
                         ["network"])
        self.assertEqual(self.origin_rpc(o, "network.status")[2]["error"]["code"], -32001)
        self.sys_grant({"origins": {}})

    def test_request_offers_session_and_always_not_once(self):
        o = "http://req2.app.localhost:7311"
        self.sys_grant({"origins": {o: {"lock": "deny"}}})
        self.answer("session")
        r = self.origin_rpc(o, "permissions.request", {"scope": "audio"})[2]["result"]
        self.assertEqual((r["mode"], r["until"]), ("allow", "session"))
        p = self.prompts()[-1]
        self.assertEqual((p["allow_once"], p["allow_session"]), (False, True))
        self.answer("once")  # not offered: counts as deny
        r = self.origin_rpc(o, "permissions.request", {"scope": "display"})[2]["result"]
        self.assertEqual(r["mode"], "deny")
        self.answer("session")  # sensitive scopes: no session, once = may ask
        r = self.origin_rpc(o, "permissions.request", {"scope": "camera"})[2]["result"]
        self.assertEqual(r["mode"], "ask")
        self.assertEqual((self.prompts()[-1]["allow_session"], self.prompts()[-1]["allow_always"]), (False, False))
        self.sys_grant({"origins": {}})

    def test_camera_prompt_has_no_always_or_session(self):
        self.answer("session")
        r = self.rpc_unix("camera.session.start", {"purpose": "t"})
        p = self.prompts()[-1]
        self.assertFalse(p["allow_always"] or p["allow_session"])
        self.assertIn("result", r)  # clamped to once
        self.rpc_unix("media.session.stop", {"id": r["result"]["id"]})

    # ---- audit / CLI ----

    def test_audit_list_and_cli(self):
        self.rpc_unix("audio.set", {"muted": False})
        self.rpc_unix("network.wifi.disconnect")  # denied
        r = self.rpc_unix("audit.list", {"decision": "deny", "limit": 5})["result"]
        self.assertTrue(r["entries"])
        self.assertTrue(all(e["decision"] == "deny" for e in r["entries"]))
        rc, out, _ = self.cli("audit", "-n", "50", "method=audio.set")
        self.assertEqual(rc, 0)
        self.assertIn("audio.set", out)
        self.assertNotIn("network.wifi", out)
        rc, out, _ = self.cli("grants")
        self.assertEqual(rc, 0)
        self.assertIn("camera", out)
        self.answer("once")
        rc, out, err = self.cli("--json", "grant", "http://z.app.localhost:7311", "audio", "ask")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.prompts()[-1]["method"], "permissions.set")
        self.assertEqual(self.prompts()[-1]["client"], "grokbot-os CLI")
        self.answer("deny")
        rc, _, _ = self.cli("grant", "http://z.app.localhost:7311", "audio", "allow")
        self.assertEqual(rc, 2)


class UnitTests(unittest.TestCase):
    def test_prompt_fails_closed(self):
        old = os.environ.get("GROKBOT_CONSENT_CMD")
        os.environ["GROKBOT_CONSENT_CMD"] = "/nonexistent/prompt"
        try:
            self.assertEqual(consent.prompt("local:uid=1", None, "audio", "audio.set", ["a", "b"], {}, True),
                             ("deny", "no_prompt"))
            os.environ["GROKBOT_CONSENT_CMD"] = "echo always"
            self.assertEqual(consent.prompt("p", None, "camera", "m", ["a", "b"], {}, False)[0], "once")
            os.environ["GROKBOT_CONSENT_CMD"] = "echo yes-please"
            self.assertEqual(consent.prompt("p", None, "audio", "m", ["a", "b"], {}, True),
                             ("deny", "bad_answer"))
        finally:
            if old is None:
                del os.environ["GROKBOT_CONSENT_CMD"]
            else:
                os.environ["GROKBOT_CONSENT_CMD"] = old

    def test_prompt_text(self):
        t = grokbot_consent.lines({"principal": "origin:http://a.app.localhost:7311", "client": "Notes",
                                   "scope": "camera", "scope_ko": "카메라", "scope_en": "Camera",
                                   "method": "camera.session.start", "description": ["카메라 사용", "Use the camera"],
                                   "summary": {"purpose": "call"}, "allow_always": False})
        self.assertIn("http://a.app.localhost:7311", t["who"][1])
        self.assertIn("Notes", t["who"][0])
        self.assertEqual(t["scope"], ("카메라", "Camera"))
        self.assertTrue(t["sensitive"])
        self.assertFalse(t["always"])
        self.assertIn('purpose="call"', t["call"])
        self.assertFalse(t["session"])
        self.assertTrue(t["once"])

    def test_indicator_items(self):
        def call(m):
            if m == "privacy.status":
                return {"sessions": [{"kind": "microphone", "principal": "origin:http://m.app.localhost:7311",
                                      "client": None}]}
            return None
        items = grokbot_status.items(call, now=0)
        self.assertEqual(items[0]["id"], "inuse-microphone")
        self.assertTrue(items[0]["alert"])
        self.assertIn("m.app.localhost", items[0]["tooltip"])
        self.assertEqual([i["id"] for i in grokbot_status.items(lambda m: None, now=0)], ["clock"])

    def test_tcp_peer_uid(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "net"))
            with open(os.path.join(d, "net", "tcp"), "w") as f:
                f.write("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid\n"
                        "   0: 0100007F:1C8F 0100007F:A000 01 00000000:00000000 00:00000000 00000000  1000 0 4242\n"
                        "   1: 0100007F:A000 0100007F:1C8F 01 00000000:00000000 00:00000000 00000000  1001 0 4343\n")
            self.assertEqual(policy.tcp_peer_uid(0xA000, 7311, d), 1001)
            self.assertIsNone(policy.tcp_peer_uid(0xA001, 7311, d))
            self.assertEqual(policy.tcp_peer(0xA000, 7311, d), (1001, 4343))

    def test_always_ask_scopes_cannot_be_allow(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["GROKBOT_API_GRANTS"] = os.path.join(d, "g.json")
            try:
                for s in ("camera", "microphone", "power"):
                    with self.assertRaises(ValueError):
                        perms.set_mode("origin:http://a", s, "allow", by="t")
                with self.assertRaises(ValueError):
                    perms.set_mode("origin:http://a", "everything", "allow", by="t")
                perms.set_mode("origin:http://a", "audio", "allow", by="t")
                self.assertEqual(os.stat(os.path.join(d, "g.json")).st_mode & 0o777, 0o600)
                self.assertEqual(perms.mode_for("origin:http://a", "audio", "write"), ("allow", "user"))
                self.assertEqual(perms.revoke("origin:http://a"), ["audio"])
            finally:
                del os.environ["GROKBOT_API_GRANTS"]


if __name__ == "__main__":
    unittest.main()
