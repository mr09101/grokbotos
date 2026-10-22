import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import displays, sway  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402

OUTS = [
    {"name": "Virtual-1", "make": "QEMU", "model": "", "active": True, "focused": True, "scale": 1.0,
     "rect": {"x": 0, "y": 0, "width": 1280, "height": 800},
     "current_mode": {"width": 1280, "height": 800, "refresh": 60000},
     "modes": [{"width": 1280, "height": 800, "refresh": 60000}, {"width": 1920, "height": 1080, "refresh": 60000}]},
    {"name": "Virtual-2", "make": "QEMU", "model": "", "active": True, "scale": 2.0,
     "rect": {"x": 1280, "y": 0, "width": 960, "height": 540},
     "current_mode": {"width": 1920, "height": 1080, "refresh": 60000}, "modes": []},
]


class DisplaysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cmds = []
        def call(t, payload=b""):
            if t == sway.GET_OUTPUTS:
                return OUTS
            self.cmds.append(payload.decode())
            return [{"success": True}]
        self.p = [mock.patch.object(sway, "call", call),
                  mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp})]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_list(self):
        r = displays.display_list({})
        self.assertEqual([o["name"] for o in r["outputs"]], ["Virtual-1", "Virtual-2"])
        self.assertEqual(r["outputs"][0]["mode"], {"width": 1280, "height": 800, "refresh": 60.0})
        self.assertEqual(r["saved"], {})

    def test_set_scale_position_saved(self):
        r = displays.display_set({"name": "Virtual-2", "scale": 1.3, "x": -960, "y": 0})
        self.assertEqual(self.cmds, ['output "Virtual-2" scale 1.25 position -960 0'])
        self.assertEqual(r["command"], self.cmds[0])
        conf = open(os.path.join(self.tmp, "grokbot", "outputs.conf")).read()
        self.assertIn('output "Virtual-2" scale 1.25 position -960 0', conf)
        self.assertEqual(displays.load_saved()["Virtual-2"]["scale"], 1.25)
        displays.display_set({"name": "Virtual-2", "scale": 2})
        self.assertEqual(displays.load_saved()["Virtual-2"], {"scale": 2.0, "x": -960, "y": 0})

    def test_mode_must_be_offered(self):
        with self.assertRaises(BackendError):
            displays.display_set({"name": "Virtual-1", "mode": {"width": 800, "height": 600}})
        displays.display_set({"name": "Virtual-1", "mode": {"width": 1920, "height": 1080, "refresh": 60}})
        self.assertEqual(self.cmds[-1], 'output "Virtual-1" mode 1920x1080@60Hz')

    def test_last_screen_and_bad_input(self):
        displays.display_set({"name": "Virtual-2", "enabled": False})
        self.assertEqual(self.cmds[-1], 'output "Virtual-2" disable')
        for bad in ({"name": "nope"}, {"name": 'a" ; exec x'}, {"name": "Virtual-1"},
                    {"name": "Virtual-1", "scale": 9}):
            with self.assertRaises(BackendError):
                displays.display_set(bad)

    def test_refuse_last_active(self):
        one = [dict(OUTS[0])]
        with mock.patch.object(sway, "call", lambda t, p=b"": one if t == sway.GET_OUTPUTS else [{"success": True}]):
            with self.assertRaises(BackendError):
                displays.display_set({"name": "Virtual-1", "enabled": False})

    def test_sway_error(self):
        with mock.patch.object(sway, "call", lambda t, p=b"": OUTS if t == sway.GET_OUTPUTS else [{"success": False, "error": "x"}]):
            with self.assertRaises(BackendError):
                displays.display_set({"name": "Virtual-1", "scale": 2})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "grokbot", "outputs.conf")))


if __name__ == "__main__":
    unittest.main()
