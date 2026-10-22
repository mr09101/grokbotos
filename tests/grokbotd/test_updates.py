"""OS updates: the root helper (grokbot_update.py), the post-boot health
check (grokbot_health.py) and grokbotd's update.* methods. bootc,
systemctl and /proc are faked; nothing touches the real machine."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import test_grokbotd as tg

sys.path.insert(0, tg.LIB)
import grokbot_health  # noqa: E402
import grokbot_update  # noqa: E402

FAKE_BOOTC = r'''#!/usr/bin/python3
import json, os, sys
st = os.environ["FAKE_BOOTC_STATE"]
d = json.load(open(st))
open(st + ".log", "a").write(" ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
def img(dg, v): return {"image": {"image": {"image": "10.0.2.2:5000/grokbotos:latest", "transport": "registry"},
                       "version": v, "timestamp": "2026-10-22T00:00:00Z", "imageDigest": dg}}
if d.get("fail") in a: print("boom", file=sys.stderr); sys.exit(1)
if a[0] == "status":
    s = {"booted": dict(img(d["booted"], d["booted_v"]))}
    if d.get("remote") and d.get("checked"): s["booted"]["cachedUpdate"] = img(d["remote"], d["remote_v"])["image"]
    if d.get("staged"): s["staged"] = img(d["staged"], d["remote_v"])
    if d.get("rollback"): s["rollback"] = img(d["rollback"], "old")
    s["rollbackQueued"] = d.get("rollbackQueued", False)
    print(json.dumps({"apiVersion": "org.containers.bootc/v1", "spec": {"image": {"image": "10.0.2.2:5000/grokbotos:latest"}}, "status": s}))
elif a[:2] == ["upgrade", "--check"]:
    d["checked"] = True; print("Update available" if d.get("remote") else "No changes")
elif a == ["upgrade"]:
    d["staged"] = d.get("remote"); print("Staged")
elif a == ["rollback"]:
    d["rollbackQueued"] = True; print("Next boot: rollback")
json.dump(d, open(st, "w"))
'''


class Fakes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.bootc = os.path.join(t, "bootc")
        with open(self.bootc, "w") as f:
            f.write(FAKE_BOOTC)
        os.chmod(self.bootc, 0o755)
        self.state = os.path.join(t, "bootc.json")
        self.set(booted="sha256:a", booted_v="1", rollback="sha256:z")
        self.sysctl = os.path.join(t, "systemctl")
        with open(self.sysctl, "w") as f:
            f.write('#!/bin/bash\necho "$*" >>"%s/systemctl.log"\n' % t)
        os.chmod(self.sysctl, 0o755)
        self.env = {"FAKE_BOOTC_STATE": self.state, "GROKBOT_BOOTC": self.bootc,
                    "GROKBOT_SYSTEMCTL": self.sysctl, "GROKBOT_UPDATE_RUN": os.path.join(t, "run"),
                    "GROKBOT_HEALTH_DIR": os.path.join(t, "health"),
                    "GROKBOT_HEALTH_CONF": os.path.join(t, "health.conf"),
                    "GROKBOT_HEALTH_CMDLINE": os.path.join(t, "cmdline"),
                    "GROKBOT_HEALTH_PROC": os.path.join(t, "proc"),
                    "GROKBOT_HEALTH_RUNUSER": os.path.join(t, "runuser")}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        for mod in (grokbot_update, grokbot_health):
            for k, attr in (("GROKBOT_UPDATE_RUN", "RUN"), ("GROKBOT_BOOTC", "BOOTC"),
                            ("GROKBOT_HEALTH_DIR", "STATE_DIR"), ("GROKBOT_HEALTH_CONF", "CONF"),
                            ("GROKBOT_HEALTH_CMDLINE", "CMDLINE"), ("GROKBOT_HEALTH_PROC", "PROC"),
                            ("GROKBOT_HEALTH_RUNUSER", "RUNUSER"), ("GROKBOT_SYSTEMCTL", "SYSTEMCTL")):
                if hasattr(mod, attr):
                    setattr(mod, attr, self.env[k])
        with open(self.env["GROKBOT_HEALTH_CMDLINE"], "w") as f:
            f.write("root=UUID=x quiet\n")
        os.makedirs(self.env["GROKBOT_HEALTH_PROC"])

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def set(self, **kw):
        d = {}
        if os.path.exists(self.state):
            d = json.load(open(self.state))
        d.update(kw)
        json.dump(d, open(self.state, "w"))

    def bootc_log(self):
        try:
            return open(self.state + ".log").read()
        except FileNotFoundError:
            return ""

    def run_json(self, name):
        return json.load(open(os.path.join(self.env["GROKBOT_UPDATE_RUN"], name)))


class UpdateHelperTests(Fakes):
    def test_check_apply_rollback(self):
        self.assertEqual(grokbot_update.main(["check"]), 0)
        self.assertFalse(self.run_json("check.json")["available"])
        self.set(remote="sha256:b", remote_v="2")
        grokbot_update.main(["check"])
        c = self.run_json("check.json")
        self.assertEqual((c["available"], c["version"], c["digest"]), (True, "2", "sha256:b"))
        st = self.run_json("status.json")
        self.assertEqual((st["booted"]["digest"], st["rollback"]["digest"]), ("sha256:a", "sha256:z"))
        self.assertEqual(grokbot_update.main(["apply"]), 0)
        st = self.run_json("status.json")
        self.assertEqual(st["staged"]["digest"], "sha256:b")
        self.assertFalse(self.run_json("check.json")["available"])
        self.assertTrue(self.run_json("last.json")["ok"])
        self.assertEqual(grokbot_update.main(["rollback"]), 0)
        self.assertTrue(self.run_json("status.json")["rollback_queued"])
        self.assertIn("upgrade --check\nstatus --format=json\nupgrade\n", self.bootc_log())
        self.assertNotIn("reboot", self.bootc_log())
        self.assertEqual(os.stat(os.path.join(self.env["GROKBOT_UPDATE_RUN"], "status.json")).st_mode & 0o777, 0o644)

    def test_failure_is_recorded(self):
        self.set(fail="upgrade")
        self.assertEqual(grokbot_update.main(["apply"]), 1)
        last = self.run_json("last.json")
        self.assertEqual((last["action"], last["ok"]), ("apply", False))
        self.assertIn("boom", last["message"])

    def test_unknown_action(self):
        self.assertEqual(grokbot_update.main(["rm"]), 2)


class HealthTests(Fakes):
    def session(self, sway=True, api=True):
        # /proc scan and the api.sock probe are faked (tests may run as any uid)
        grokbot_health._uids_running = lambda name: {1000} if sway else set()
        grokbot_health._api_up = lambda uid: api

    def run_check(self):
        clock = iter(range(0, 100000, 10))
        return grokbot_health.run(clock=lambda: next(clock), sleep=lambda s: None)

    def health(self):
        return json.load(open(os.path.join(self.env["GROKBOT_HEALTH_DIR"], "state.json")))

    def sysctl_log(self):
        try:
            return open(os.path.join(self.tmp.name, "systemctl.log")).read()
        except FileNotFoundError:
            return ""

    def test_healthy_marks_last_good(self):
        self.session()
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.health()["last_good"], "sha256:a")
        self.assertNotIn("rollback", self.bootc_log().replace("status", ""))

    def test_bad_update_rolls_back_once(self):
        self.session()
        self.run_check()                       # image a is good
        self.set(booted="sha256:b", booted_v="2", rollback="sha256:a")
        self.session(api=False)                # b: grokbotd never answers
        self.run_check()
        h = self.health()
        self.assertEqual((h["rolled_back"]["from"], h["rolled_back"]["to"]), ("sha256:b", "sha256:a"))
        self.assertIn("grokbotd does not answer", h["rolled_back"]["why"])
        self.assertIn("rollback", self.bootc_log())
        self.assertIn("reboot", self.sysctl_log())
        # loop guard: booting b again (e.g. the user rolled forward) never rolls back twice
        open(self.state + ".log", "w").close()
        open(os.path.join(self.tmp.name, "systemctl.log"), "w").close()
        self.assertEqual(self.run_check(), 1)
        self.assertNotIn("rollback", self.bootc_log())
        self.assertNotIn("reboot", self.sysctl_log())

    def test_never_rolls_back_from_last_good_or_first_boot(self):
        self.session(sway=False)
        self.assertEqual(self.run_check(), 1)   # first boot ever, no last_good
        self.assertNotIn("rollback", self.bootc_log())
        self.session()
        self.run_check()
        self.session(api=False)
        self.assertEqual(self.run_check(), 1)   # a is last-good
        self.assertNotIn("rollback", self.bootc_log())

    def test_no_rollback_deployment(self):
        self.session()
        self.run_check()
        self.set(booted="sha256:b", rollback=None)
        self.session(api=False)
        self.assertEqual(self.run_check(), 1)
        self.assertNotIn("rollback", self.bootc_log())

    def test_disabled(self):
        with open(self.env["GROKBOT_HEALTH_CMDLINE"], "w") as f:
            f.write("quiet grokbot.health=off\n")
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(self.bootc_log(), "")


class UpdateApiTests(tg.Base):
    def setUp(self):
        rd = self.env["GROKBOT_UPDATE_RUN"]
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, "status.json"), "w") as f:
            json.dump({"booted": {"digest": "sha256:a", "version": "1"}, "staged": None,
                       "rollback": {"digest": "sha256:z", "version": "0"}}, f)
        with open(os.path.join(rd, "check.json"), "w") as f:
            json.dump({"available": True, "version": "2", "digest": "sha256:b", "checked_at": 1}, f)
        for f in ("consent.log", "tools.log", "consent-answer"):
            try:
                os.unlink(os.path.join(self.tmp.name, f))
            except FileNotFoundError:
                pass

    def answer(self, a):
        with open(os.path.join(self.tmp.name, "consent-answer"), "w") as f:
            f.write(a + "\n")

    def test_status_is_readable_without_prompt(self):
        r = self.rpc_unix("update.status")["result"]
        self.assertEqual((r["available"], r["available_version"], r["booted"]["digest"]), (True, "2", "sha256:a"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "consent.log")))

    def test_apply_prompts_every_time_and_starts_the_unit(self):
        self.answer("always")   # not offered: clamped to once
        for _ in range(2):
            r = self.rpc_unix("update.apply")
            self.assertEqual(r["result"]["unit"], "grokbot-update@apply.service")
        prompts = [json.loads(x) for x in open(os.path.join(self.tmp.name, "consent.log")) if x.strip()]
        self.assertEqual(len(prompts), 2)
        self.assertFalse(prompts[-1]["allow_always"] or prompts[-1]["allow_session"])
        self.assertIn("systemctl start --no-block grokbot-update@apply.service",
                      open(os.path.join(self.tmp.name, "tools.log")).read())
        self.answer("deny")
        self.assertEqual(self.rpc_unix("update.rollback")["error"]["code"], -32001)

    def test_notify_once(self):
        from grokbotd import updates
        sent = []
        old = dict(os.environ)
        os.environ.update({k: self.env[k] for k in ("GROKBOT_UPDATE_RUN", "GROKBOT_HEALTH_DIR", "XDG_STATE_HOME")})
        try:
            updates._systemctl = lambda *a, **k: (0, "inactive")
            self.assertTrue(updates.notify_once(lambda *a: sent.append(a)))
            self.assertFalse(updates.notify_once(lambda *a: sent.append(a)))
            os.makedirs(self.env["GROKBOT_HEALTH_DIR"], exist_ok=True)
            with open(os.path.join(self.env["GROKBOT_HEALTH_DIR"], "state.json"), "w") as f:
                json.dump({"rolled_back": {"from": "sha256:b", "from_version": "2", "at": 5, "why": "x"}}, f)
            self.assertTrue(updates.notify_once(lambda *a: sent.append(a)))
            self.assertEqual(len(sent), 2)
            self.assertIn("rolled back", sent[1][0])
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
