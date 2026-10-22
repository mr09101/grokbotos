"""files.* (home folder only, read and write are separate scopes) and
media.keys.* (long poll + press)."""
import base64
import json
import os
import threading
import time
import unittest

import test_grokbotd as tg

O = "http://files.app.localhost:7311"


class FilesTests(tg.Base):
    def setUp(self):
        self.h = self.tmp.name
        os.makedirs(os.path.join(self.h, "Documents"), exist_ok=True)
        with open(os.path.join(self.h, "Documents", "a.txt"), "w") as f:
            f.write("안녕 hello")
        with open(os.path.join(self.h, "consent-answer"), "w") as f:
            f.write("once\n")   # local writes to files-write ask
        try:
            os.unlink(os.path.join(self.h, "cfg", "grokbot", "api-permissions.json"))
        except FileNotFoundError:
            pass

    def grant(self, modes):
        with open(os.path.join(self.h, "cfg", "grokbot", "api-permissions.json"), "w") as f:
            json.dump({"origins": {O: modes}}, f)

    def o(self, method, params=None):
        return self.http("/v1/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                         {"Origin": O})[2]

    def ok(self, method, params=None):
        r = self.rpc_unix(method, params)
        self.assertIn("result", r, (method, r))
        return r["result"]

    def err(self, method, params):
        r = self.rpc_unix(method, params)
        self.assertIn("error", r, (method, r))
        return r["error"]["message"]

    def test_list_read_hide_dotfiles(self):
        r = self.ok("files.list", {"path": "/"})
        names = [e["name"] for e in r["entries"]]
        self.assertIn("Documents", names)
        self.assertFalse([n for n in names if n.startswith(".")])
        self.assertEqual(self.ok("files.read", {"path": "~/Documents/a.txt"})["data"], "안녕 hello")
        b = self.ok("files.read", {"path": "/Documents/a.txt", "encoding": "base64"})["data"]
        self.assertEqual(base64.b64decode(b).decode(), "안녕 hello")
        self.assertEqual(self.ok("files.stat", {"path": "Documents/a.txt"})["mime"], "text/plain")

    def test_confinement(self):
        os.makedirs(os.path.join(self.h, ".config"), exist_ok=True)
        os.symlink("/etc", os.path.join(self.h, "etc-link"))
        for p in ("/../etc/passwd", "/.config", "/cfg/../.config/x", "/etc-link/passwd"):
            self.err("files.read", {"path": p})
        self.assertIn("hidden", self.err("files.write", {"path": "/.bashrc", "data": "x"}))
        self.assertIn("leaves", self.err("files.write", {"path": "/etc-link/x", "data": "x"}))
        self.assertNotIn("etc-link", [e["name"] for e in self.ok("files.list")["entries"]])

    def test_write_move_mkdir_trash(self):
        self.ok("files.mkdir", {"path": "/Notes"})
        self.ok("files.write", {"path": "/Notes/n.txt", "data": "one"})
        self.assertIn("exists", self.err("files.write", {"path": "/Notes/n.txt", "data": "two"}))
        self.ok("files.write", {"path": "/Notes/n.txt", "data": "two", "overwrite": True})
        self.ok("files.move", {"path": "/Notes/n.txt", "to": "/Notes/m.txt"})
        self.assertEqual(self.ok("files.read", {"path": "/Notes/m.txt"})["data"], "two")
        self.assertIn("itself", self.err("files.move", {"path": "/Notes", "to": "/Notes/sub"}))
        self.ok("files.trash", {"path": "/Notes/m.txt"})
        found = [r for r, _, fs in os.walk(self.h) if r.endswith(os.path.join("Trash", "files")) and "m.txt" in fs]
        self.assertEqual(len(found), 1)
        info = open(os.path.join(os.path.dirname(found[0]), "info", "m.txt.trashinfo")).read()
        self.assertIn("Path=", info)
        self.err("files.trash", {"path": "/"})

    def test_read_and_write_are_separate_grants(self):
        self.grant({"files": "allow"})
        self.assertIn("result", self.o("files.list", {"path": "/Documents"}))
        self.assertEqual(self.o("files.write", {"path": "/x.txt", "data": "x"})["error"]["code"], -32001)
        self.grant({"files": "allow", "files-write": "allow"})
        self.assertIn("result", self.o("files.write", {"path": "/x.txt", "data": "x"}))
        self.grant({"files-write": "allow"})
        self.assertEqual(self.o("files.read", {"path": "/x.txt"})["error"]["code"], -32001)


class MediaKeyTests(tg.Base):
    def test_press_without_waiter_and_with(self):
        self.assertFalse(self.rpc_unix("media.keys.press", {"key": "next"})["result"]["delivered"])
        got = {}

        def w():
            got["r"] = self.rpc_unix("media.keys.wait", {"timeout": 5})
        t = threading.Thread(target=w)
        t.start()
        for _ in range(50):
            time.sleep(0.05)
            if self.rpc_unix("media.keys.press", {"key": "play-pause"})["result"]["delivered"]:
                break
        t.join(6)
        self.assertEqual(got["r"]["result"]["key"], "play-pause")
        self.assertIsNone(self.rpc_unix("media.keys.wait", {"timeout": 0})["result"]["key"])
        self.assertIn("error", self.rpc_unix("media.keys.press", {"key": "rm"}))

    def test_wait_is_audited_once_per_subscription(self):
        def n():
            return len([x for x in self.audit() if x.get("method") == "media.keys.wait"])
        before = n()
        for _ in range(4):   # back-to-back polls = one subscription
            self.rpc_unix("media.keys.wait", {"timeout": 0})
        self.assertLessEqual(n() - before, 1)


if __name__ == "__main__":
    unittest.main()
