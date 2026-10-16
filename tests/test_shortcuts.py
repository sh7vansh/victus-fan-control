import subprocess
import unittest
from unittest.mock import patch

from fan_control import shortcuts


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.schema = shortcuts.SHORTCUT_SCHEMA + ":" + shortcuts.SHORTCUT_PATH
        self.existing = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
        self.settings = {
            (self.schema, "name"): "",
            (shortcuts.MEDIA_KEYS, "custom-keybindings"): [self.existing],
            (shortcuts.SHORTCUT_SCHEMA + ":" + self.existing, "binding"): "<Super>space",
        }
        self.read = patch.object(shortcuts, "read_setting", side_effect=lambda schema, key: self.settings[(schema, key)])
        self.write = patch.object(shortcuts, "write_setting", side_effect=lambda schema, key, value: self.settings.__setitem__((schema, key), value))
        self.commands = patch.object(shortcuts, "gsettings", return_value=shortcuts.MEDIA_KEYS + " calculator-static ['XF86Calculator']")
        self.read.start()
        self.write.start()
        self.commands.start()
        self.addCleanup(patch.stopall)

    def test_first_launch_preserves_other_shortcuts_and_registers_launcher(self):
        shortcuts.ensure_omen_shortcut()
        self.assertEqual(self.settings[(shortcuts.MEDIA_KEYS, "custom-keybindings")], [self.existing, shortcuts.SHORTCUT_PATH])
        self.assertEqual(self.settings[(self.schema, "command")], shortcuts.COMMAND)
        self.assertEqual(self.settings[(self.schema, "binding")], "Launch2")

    def test_disabled_or_edited_shortcut_is_not_restored(self):
        shortcuts.ensure_omen_shortcut()
        self.settings[(self.schema, "binding")] = ""
        self.settings[(shortcuts.MEDIA_KEYS, "custom-keybindings")] = [self.existing]
        shortcuts.ensure_omen_shortcut()
        self.assertEqual(self.settings[(self.schema, "binding")], "")
        self.assertEqual(self.settings[(shortcuts.MEDIA_KEYS, "custom-keybindings")], [self.existing])

    def test_existing_custom_omen_assignment_is_preserved(self):
        self.settings[(shortcuts.SHORTCUT_SCHEMA + ":" + self.existing, "binding")] = "XF86Launch2"
        original = self.settings.copy()
        shortcuts.ensure_omen_shortcut()
        self.assertEqual(self.settings, original)

    def test_existing_desktop_omen_assignment_is_preserved(self):
        original = self.settings.copy()
        with patch.object(shortcuts, "gsettings", return_value=shortcuts.MEDIA_KEYS + " calculator ['Launch2']"):
            shortcuts.ensure_omen_shortcut()
        self.assertEqual(self.settings, original)

    def test_missing_host_schemas_do_not_break_startup(self):
        with patch.object(shortcuts, "read_setting", side_effect=subprocess.CalledProcessError(1, "gsettings")):
            shortcuts.ensure_omen_shortcut()
        self.assertEqual(self.settings[(self.schema, "name")], "")

    def test_setup_skips_other_desktops(self):
        with patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "KDE"}), patch.object(shortcuts.threading, "Thread") as thread:
            shortcuts.setup_omen_shortcut()
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
