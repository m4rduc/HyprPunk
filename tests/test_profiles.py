"""Non-destructive regression checks: python3 tests/test_profiles.py.

Controllers use a temporary HOME and an allowlisted PATH. System/session commands
are stubs. Only selected installer function definitions are evaluated, never main.
"""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "install.sh").read_text()
LOCALES = {"us": "en_US.UTF-8", "fr": "fr_FR.UTF-8", "gb": "en_GB.UTF-8"}


def installer_function(name):
    return re.search(r"^" + name + r"\(\) \{\n.*?^\}", INSTALLER, re.M | re.S)[0]


class Profiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hyprpunk-test-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "calls"
        self.log.touch()
        self.state = self.home / "state/hyprpunk"
        self.state.mkdir(parents=True)
        self.env = {
            "HOME": str(self.home), "PATH": str(self.bin), "LC_ALL": "C",
            "XDG_STATE_HOME": str(self.home / "state"),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "HYPRLAND_INSTANCE_SIGNATURE": "test-only", "TEST_LOG": str(self.log),
        }
        for command in ("bash", "readlink", "dirname", "mkdir", "sed", "mv", "ln",
                        "unlink", "mktemp", "basename", "timeout"):
            (self.bin / command).symlink_to(shutil.which(command))
        for command in ("localectl", "systemctl", "dbus-update-activation-environment",
                        "hyprctl", "pgrep", "tmux", "sudo", "bootctl", "git", "rm",
                        "grub-mkconfig"):
            self.stub(command, """
printf '%s' "${0##*/}" >> "$TEST_LOG"
printf ' <%s>' "$@" >> "$TEST_LOG"
printf '\\n' >> "$TEST_LOG"
case "${0##*/}" in
  pgrep | tmux) exit 1 ;;
  localectl)
    if [[ "$1" == status ]]; then
      printf ' X11 Layout: %s\\n X11 Model: pc105\\n X11 Options: caps:escape\\n X11 Variant: %s\\n' "${TEST_LAYOUT:-gb}" "${TEST_VARIANT:-}"
      exit "${TEST_STATUS_FAIL:-0}"
    elif [[ "$*" == *set-x11-keymap* ]]; then
      exit "${TEST_X11_FAIL:-${TEST_LOCAL_FAIL:-0}}"
    else
      exit "${TEST_CONSOLE_FAIL:-${TEST_LOCAL_FAIL:-0}}"
    fi ;;
  bootctl)
    printf '%s\\n' "${TEST_BOOT_STATUS:-}"
    exit "${TEST_BOOT_FAIL:-0}" ;;
  sudo)
    if [[ "$1" == localectl ]]; then
      shift
      localectl "$@"
    else
      exit "${TEST_SUDO_FAIL:-0}"
    fi ;;
  git)
    case "$*" in
      *'rev-parse --verify HEAD') exit "${TEST_HEAD_FAIL:-0}" ;;
      *'remote get-url origin') printf '%s\\n' "${TEST_ORIGIN:-}" ;;
      *'branch --show-current') printf '%s\\n' "${TEST_BRANCH:-}" ;;
    esac ;;
esac
""")

    def stub(self, command, body):
        path = self.bin / command
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)

    def run_cmd(self, args, *, input="", ok=True):
        result = subprocess.run(args, env=self.env, text=True, input=input,
                                capture_output=True, cwd=ROOT)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def controller(self, kind, *args, **kwargs):
        script = ROOT / f"scripts/Scripts/{kind}.sh"
        return self.run_cmd(["bash", str(script), *args], **kwargs)

    def functions(self, names, body, **kwargs):
        definitions = "\n".join(installer_function(name) for name in names)
        return self.run_cmd(["bash", "-eu", "-c", definitions + "\n" + body], **kwargs)

    def test_keyboard_profiles_and_persistence(self):
        snapshots = {}
        for profile in LOCALES:
            with self.subTest(profile=profile):
                self.controller("keyboard-layoutctl", "set", profile)
                self.assertEqual(self.controller("keyboard-layoutctl", "get").stdout.strip(), profile)
                generated = self.home / ".local/state/hyprpunk/keyboard"
                snapshots[profile] = [(generated / name).read_text()
                                      for name in ("tmux.conf", "kitty.conf", "lesskey")]
                self.assertEqual((generated / "yazi/keymap.toml").is_symlink(), profile == "fr")
                self.log.write_text("")
                self.controller("keyboard-layoutctl", "ensure")
                self.assertNotIn("localectl", self.log.read_text())
                self.controller("keyboard-layoutctl", "init")
                self.assertEqual((self.state / "keyboard-layout").read_text().strip(), profile)
        self.assertEqual(snapshots["us"], snapshots["gb"])
        self.assertIn('bind-key -T copy-mode-vi h send -X cursor-left', snapshots["gb"][0])
        self.assertIn('bind-key -T copy-mode-vi j send -X cursor-left', snapshots["fr"][0])
        self.assertIn('map ctrl+m send_key f12', snapshots["fr"][1])
        self.assertIn('localectl <--no-convert> <set-x11-keymap> <gb> <pc105> <> <caps:escape>', self.log.read_text())
        self.assertIn('localectl <--no-convert> <set-keymap> <uk>', self.log.read_text())
        for expected in ("us", "fr", "gb"):
            self.controller("keyboard-layoutctl", "toggle")
            self.assertEqual((self.state / "keyboard-layout").read_text().strip(), expected)

    def test_invalid_profiles_and_fallbacks(self):
        self.assertEqual(self.controller("keyboard-layoutctl", "get").stdout.strip(), "us")
        for kind in ("keyboard-layoutctl", "locale-profilectl"):
            self.assertEqual(set(self.controller(kind, "list").stdout.split()), set(LOCALES))
        self.controller("keyboard-layoutctl", "set", "gb")
        self.assertEqual(self.controller("keyboard-layoutctl", "set", "xx", ok=False).returncode, 2)
        self.assertEqual((self.state / "keyboard-layout").read_text().strip(), "gb")
        self.controller("locale-profilectl", "init", "gb", "gb")
        for command in ("set-language", "set-regional"):
            self.assertEqual(self.controller("locale-profilectl", command, "xx", ok=False).returncode, 2)
        self.assertEqual((self.state / "locale-language").read_text().strip(), "gb")
        self.assertEqual((self.state / "locale-regional").read_text().strip(), "gb")

    def test_keyboard_system_failure_is_visible(self):
        self.env["TEST_LOCAL_FAIL"] = "1"
        result = self.controller("keyboard-layoutctl", "set", "gb")
        self.assertIn("Warning: the login screen", result.stderr)
        self.assertIn("Warning: the UK console", result.stderr)
        self.assertEqual((self.state / "keyboard-layout").read_text().strip(), "gb")

    def test_keyboard_init_failures_do_not_complete_installer_step(self):
        (self.home / "Scripts").mkdir()
        (self.home / "Scripts/keyboard-layoutctl.sh").symlink_to(ROOT / "scripts/Scripts/keyboard-layoutctl.sh")
        body = '''
declare -A COMPLETED_STEPS=()
DOTFILES_REPO=https://github.com/m4rduc/HyprPunk.git
DOTFILES_BRANCH=feat/uk-keyboard-locale
DOTFILES_DIR="$HOME/dotfiles"
LOG_DIR="$HOME/state/hyprpunk"
STATE_FILE="$LOG_DIR/install.state"
keyboard_layout=gb locale_language=gb locale_regional=gb
save_state
run_step configure_keyboard "Configuring the keyboard" configure_keyboard
'''
        state_file = self.state / "install.state"
        for failure in ("TEST_X11_FAIL", "TEST_CONSOLE_FAIL", "TEST_STATUS_FAIL"):
            with self.subTest(failure=failure):
                self.env[failure] = "1"
                result = self.functions(["save_state", "run_step", "configure_keyboard"], body, ok=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Warning:", result.stderr)
                self.assertNotIn("completed=configure_keyboard", state_file.read_text())
                # Normal desktop switching still saves the choice and warns.
                self.assertIn("Warning:", self.controller("keyboard-layoutctl", "set", "gb").stderr)
                del self.env[failure]
        (self.bin / "localectl").unlink()
        result = self.functions(["save_state", "run_step", "configure_keyboard"], body, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("completed=configure_keyboard", state_file.read_text())

    def test_keyboard_init_success_completes_installer_step(self):
        (self.home / "Scripts").mkdir()
        (self.home / "Scripts/keyboard-layoutctl.sh").symlink_to(ROOT / "scripts/Scripts/keyboard-layoutctl.sh")
        for profile in LOCALES:
            self.env["TEST_PROFILE"] = profile
            self.functions(["save_state", "run_step", "configure_keyboard"], '''
declare -A COMPLETED_STEPS=()
DOTFILES_REPO=https://github.com/m4rduc/HyprPunk.git
DOTFILES_BRANCH=feat/uk-keyboard-locale
DOTFILES_DIR="$HOME/dotfiles"
LOG_DIR="$HOME/state/hyprpunk"
STATE_FILE="$LOG_DIR/install.state"
keyboard_layout="$TEST_PROFILE" locale_language=gb locale_regional=gb
run_step configure_keyboard "Configuring the keyboard" configure_keyboard
''')
            self.assertIn("completed=configure_keyboard", (self.state / "install.state").read_text())

    def test_system_xkb_variant_preserved_only_for_same_layout(self):
        for profile, variant in (("us", "intl"), ("gb", "extd"), ("fr", "oss")):
            self.env.update(TEST_LAYOUT=profile, TEST_VARIANT=variant)
            for command in ("set", "init"):
                self.log.write_text("")
                self.controller("keyboard-layoutctl", command, profile)
                self.assertIn(f'<set-x11-keymap> <{profile}> <pc105> <{variant}> <caps:escape>', self.log.read_text())
                if profile == "gb":
                    self.assertIn('<set-keymap> <uk>', self.log.read_text())
            other = "us" if profile != "us" else "gb"
            self.log.write_text("")
            self.controller("keyboard-layoutctl", "set", other)
            self.assertIn(f'<set-x11-keymap> <{other}> <pc105> <> <caps:escape>', self.log.read_text())

    def test_locale_combinations_and_persistence(self):
        for language, language_locale in LOCALES.items():
            for regional, regional_locale in LOCALES.items():
                with self.subTest(language=language, regional=regional):
                    self.controller("locale-profilectl", "set-language", language)
                    self.controller("locale-profilectl", "set-regional", regional)
                    self.log.write_text("")
                    self.controller("locale-profilectl", "ensure")
                    self.controller("locale-profilectl", "init")
                    for command, expected in (("get-language", language), ("get-regional", regional)):
                        self.assertEqual(self.controller("locale-profilectl", command).stdout.strip(), expected)
                    calls = self.log.read_text()
                    self.assertIn(f"<LANG={language_locale}>", calls)
                    self.assertIn(f"<LC_MESSAGES={language_locale}>", calls)
                    for category in ("CTYPE", "NUMERIC", "TIME", "COLLATE", "MONETARY", "PAPER",
                                     "NAME", "ADDRESS", "TELEPHONE", "MEASUREMENT", "IDENTIFICATION"):
                        self.assertIn(f"<LC_{category}={regional_locale}>", calls)
                    self.assertIn("<unset-environment> <LC_ALL>", calls)

    @unittest.skipUnless(shutil.which("lua"), "Lua is unavailable")
    def test_lua_profiles(self):
        lua = shutil.which("lua")
        script = '''
package.path = "hyprland/.config/hypr/?.lua;" .. package.path
__require = require
local keyboard = dofile("hyprland/.config/hypr/keyboard_state.lua")
assert(keyboard.name == arg[1] and keyboard.xkb == arg[1])
assert(keyboard.left .. keyboard.down .. keyboard.up .. keyboard.right == arg[2])
vim = {env = {HOME = os.getenv("HOME"), XDG_STATE_HOME = os.getenv("XDG_STATE_HOME")}}
local nvim = dofile("nvim/.config/nvim/lua/config/keyboard.lua")
assert(nvim.name == arg[1])
assert(nvim.left .. nvim.down .. nvim.up .. nvim.right == arg[2])
local locale = dofile("hyprland/.config/hypr/locale_state.lua")
assert(locale.language == arg[3] and locale.regional == arg[3])
'''
        fixture = self.home / "profiles.lua"
        fixture.write_text(script)
        for profile, locale in LOCALES.items():
            self.controller("keyboard-layoutctl", "set", profile)
            self.controller("locale-profilectl", "init", profile, profile)
            self.run_cmd([lua, str(fixture), profile, "jklm" if profile == "fr" else "hjkl", locale])

    def test_installer_prompts_and_saved_source(self):
        for profile in LOCALES:
            for name in ("keyboard_layout", "locale_language", "locale_regional"):
                result = self.functions(["ask_" + name], f'ask_{name}; printf "%s" "${name}"', input=profile.upper() + "\n")
                self.assertEqual(result.stdout, profile)
        body = '''
declare -A COMPLETED_STEPS=([configure_keyboard]=1)
DOTFILES_REPO=https://github.com/m4rduc/HyprPunk.git
DOTFILES_BRANCH=feat/uk-keyboard-locale
DOTFILES_DIR="$HOME/dotfiles"
LOG_DIR="$HOME/state/hyprpunk"
STATE_FILE="$LOG_DIR/install.state"
keyboard_layout=gb locale_language=gb locale_regional=gb
save_state
keyboard_layout=us locale_language=us locale_regional=us
load_state
[[ "$keyboard_layout/$locale_language/$locale_regional" == gb/gb/gb ]]
[[ "${COMPLETED_STEPS[configure_keyboard]}" == 1 ]]
'''
        self.functions(["save_state", "load_state"], body)
        result = self.functions(["save_state", "load_state"], body + '\nDOTFILES_BRANCH=master\nload_state', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Installation source changed", result.stderr)

    def test_fork_clone_and_wrong_source_rejected(self):
        defaults = "\n".join(line for line in INSTALLER.splitlines() if line.startswith(("DOTFILES_REPO=", "DOTFILES_BRANCH=")))
        body = defaults + '\nDOTFILES_BRANCH=feat/uk-keyboard-locale\nDOTFILES_DIR="$HOME/dotfiles"\nclone_dotfiles'
        self.functions(["validate_dotfiles_source", "clone_dotfiles"], body)
        self.assertIn('<clone> <--branch> <feat/uk-keyboard-locale> <https://github.com/m4rduc/HyprPunk.git>', self.log.read_text())
        (self.home / "dotfiles/.git").mkdir(parents=True)
        self.log.write_text("")
        self.env["TEST_ORIGIN"] = "https://github.com/tuconnaisyouknow/HyprPunk.git"
        self.env["TEST_BRANCH"] = "feat/uk-keyboard-locale"
        result = self.functions(["validate_dotfiles_source", "clone_dotfiles"], body, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("leaving them untouched", result.stderr)
        self.assertNotIn("rm ", self.log.read_text())

    def test_resume_validates_checkout_before_skipping_clone(self):
        (self.home / "dotfiles/.git").mkdir(parents=True)
        marker = self.home / "dotfiles/preserved-work"
        marker.write_text("keep me")
        metadata = ("dotfiles_repo=https://github.com/m4rduc/HyprPunk.git\n"
                    "dotfiles_branch=feat/uk-keyboard-locale\n")
        body = '''
declare -A COMPLETED_STEPS=()
DOTFILES_REPO=https://github.com/m4rduc/HyprPunk.git
DOTFILES_BRANCH=feat/uk-keyboard-locale
DOTFILES_DIR="$HOME/dotfiles"
LOG_DIR="$HOME/state/hyprpunk"
STATE_FILE="$LOG_DIR/install.state"
initialize_state
run_step clone_dotfiles "Downloading the dotfiles" clone_dotfiles
'''
        names = ["validate_dotfiles_source", "load_state", "save_state", "initialize_state", "run_step", "clone_dotfiles"]
        for source in ("", metadata, metadata.splitlines(keepends=True)[0]):
            for completed in ("", "completed=clone_dotfiles\n"):
                for case in ("valid", "wrong-repo", "wrong-branch", "detached", "invalid-head"):
                    with self.subTest(source=source, completed=completed, case=case):
                        original = "version=1\nkeyboard_layout=gb\nlocale_language=gb\nlocale_regional=gb\n" + source + completed
                        state_file = self.state / "install.state"
                        state_file.write_text(original)
                        self.env.update(TEST_ORIGIN="https://github.com/m4rduc/HyprPunk.git",
                                        TEST_BRANCH="feat/uk-keyboard-locale", TEST_HEAD_FAIL="0")
                        if case == "wrong-repo":
                            self.env["TEST_ORIGIN"] = "https://github.com/tuconnaisyouknow/HyprPunk.git"
                        elif case == "wrong-branch":
                            self.env["TEST_BRANCH"] = "master"
                        elif case == "detached":
                            self.env["TEST_BRANCH"] = ""
                        elif case == "invalid-head":
                            self.env["TEST_HEAD_FAIL"] = "1"
                        self.log.write_text("")
                        result = self.functions(names, body, ok=False)
                        self.assertEqual(result.returncode == 0, case == "valid", result.stderr)
                        if case == "valid":
                            self.assertIn(metadata, state_file.read_text())
                            self.assertIn("remote> <get-url> <origin>", self.log.read_text())
                            if completed:
                                self.assertIn("already completed, skipping", result.stdout)
                        else:
                            self.assertEqual(state_file.read_text(), original)
                            self.assertIn("leaving them untouched", result.stderr)
                        self.assertEqual(marker.read_text(), "keep me")
                        self.assertNotIn("<clone>", self.log.read_text())
                        self.assertNotIn("rm ", self.log.read_text())

    def test_resume_missing_or_incomplete_checkout_is_not_replaced(self):
        metadata = ("dotfiles_repo=https://github.com/m4rduc/HyprPunk.git\n"
                    "dotfiles_branch=feat/uk-keyboard-locale\n")
        body = '''
declare -A COMPLETED_STEPS=()
DOTFILES_REPO=https://github.com/m4rduc/HyprPunk.git
DOTFILES_BRANCH=feat/uk-keyboard-locale
DOTFILES_DIR="$HOME/dotfiles"
LOG_DIR="$HOME/state/hyprpunk"
STATE_FILE="$LOG_DIR/install.state"
initialize_state
run_step clone_dotfiles "Downloading the dotfiles" clone_dotfiles
'''
        names = ["validate_dotfiles_source", "load_state", "save_state", "initialize_state", "run_step", "clone_dotfiles"]
        for incomplete in (False, True):
            if incomplete:
                (self.home / "dotfiles").mkdir()
            for source in ("", metadata):
                for completed in ("", "completed=clone_dotfiles\n"):
                    original = "version=1\nkeyboard_layout=gb\nlocale_language=gb\nlocale_regional=gb\n" + source + completed
                    state_file = self.state / "install.state"
                    state_file.write_text(original)
                    self.log.write_text("")
                    result = self.functions(names, body, ok=False)
                    permitted = not incomplete and bool(source) and not completed
                    self.assertEqual(result.returncode == 0, permitted, result.stderr)
                    if not permitted:
                        self.assertEqual(state_file.read_text(), original)
                        self.assertNotIn("<clone>", self.log.read_text())
                    self.assertNotIn("rm ", self.log.read_text())
        # The clone step itself also refuses an incomplete directory, without state.
        result = self.functions(["validate_dotfiles_source", "clone_dotfiles"], body.split("initialize_state")[0] + "clone_dotfiles", ok=False)
        self.assertNotEqual(result.returncode, 0)

    def test_grub_requires_confirmation_and_skips_other_loaders(self):
        for loader in ("Limine 10.0", "systemd-boot 258", "GRUB 2.14", "n/a", ""):
            self.env["TEST_BOOT_STATUS"] = f"Current Boot Loader:\n      Product: {loader}\n\nAvailable Boot Loaders on ESP:\n      Product: GRUB\n"
            for answer in ("y\n", "n\n", "\n", ""):
                with self.subTest(loader=loader, answer=answer):
                    result = self.functions(["confirm_grub_bootloader"], "confirm_grub_bootloader", input=answer, ok=False)
                    permitted = loader in ("GRUB 2.14", "n/a", "") and answer == "y\n"
                    self.assertEqual(result.returncode == 0, permitted)
        self.env["TEST_BOOT_STATUS"] = ""
        self.env["TEST_BOOT_FAIL"] = "1"
        self.assertNotEqual(self.functions(["confirm_grub_bootloader"], "confirm_grub_bootloader", ok=False).returncode, 0)
        # Even with grub-mkconfig installed, Limine must reach no privileged action.
        self.env["TEST_BOOT_STATUS"] = "Current Boot Loader:\n Product: Limine\n\n"
        self.env["TEST_BOOT_FAIL"] = "0"
        self.log.write_text("")
        self.functions(["confirm_grub_bootloader", "install_grub_theme"], 'DOTFILES_DIR="$HOME/dotfiles"\ninstall_grub_theme', input="y\n")
        self.assertNotIn("sudo", self.log.read_text())
        self.assertNotIn("grub-mkconfig", self.log.read_text())

    def test_system_upgrade_is_interactive_and_failure_propagates(self):
        self.functions(["update_system"], "update_system")
        self.assertIn("sudo <pacman> <-Syu>", self.log.read_text())
        self.assertNotIn("--noconfirm", self.log.read_text())
        self.env["TEST_SUDO_FAIL"] = "1"
        self.assertNotEqual(self.functions(["update_system"], "update_system", ok=False).returncode, 0)

    @unittest.skipUnless(Path("/usr/lib/qt6/bin/qmltestrunner").exists(), "Qt Quick Test is unavailable")
    def test_qml_option_mapping_and_british_calendar(self):
        qml = ROOT / "quickshell/.config/quickshell/hyprpunk"
        session = (qml / "Session.qml").read_text()
        control = (qml / "ControlCenter.qml").read_text()
        bar = (qml / "Bar.qml").read_text()
        locale_function = re.search(r"    function localeOf\(profile\) \{.*?\n    \}", session, re.S)[0]
        profiles = re.search(r"readonly property var localeProfiles: (\[.*?\])", control, re.S)[1]
        calendar = re.search(r"readonly property var regionalLocale: (.*)", bar)[1]
        calendar = calendar.replace("Session.regionalLocale", "localeOf('gb')")
        subtitle = re.search(r'subtitle: (controlCenter.keyboardLayout .*UK QWERTY.*)', control)[1]
        subtitle = subtitle.replace("controlCenter.keyboardLayout", "profile")
        fixture = self.home / "tst_profiles.qml"
        fixture.write_text('''import QtQuick
import QtTest
TestCase {
    name: "ProfileMappings"
''' + locale_function + "\n    property var profiles: " + profiles + '''
    function keyboardLabel(profile) { return ''' + subtitle + '''; }
    function test_profiles() {
        compare(profiles.length, 3);
        for (const profile of profiles)
            compare(localeOf(profile.id), profile.locale);
        compare(localeOf("invalid"), "en_US.UTF-8");
        compare(keyboardLabel("gb"), "UK QWERTY");
        compare(keyboardLabel("us"), "US QWERTY");
        compare(keyboardLabel("fr"), "FR AZERTY");
        const regional = ''' + calendar + ''';
        compare(regional.name, "en_GB");
        compare(regional.firstDayOfWeek, 1);
        compare(regional.currencySymbol(Locale.CurrencyIsoCode), "GBP");
        compare(regional.toString(new Date(2026, 10, 1), regional.dateFormat(Locale.ShortFormat)), "01/11/2026");
    }
}
''')
        self.env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                        XDG_RUNTIME_DIR=str(self.home))
        self.run_cmd(["/usr/lib/qt6/bin/qmltestrunner", "-input", str(fixture)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
