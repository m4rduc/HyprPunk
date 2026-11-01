# UK compatibility branch

The changes extend the existing profiles and GNU Stow installation. US and French remain available.
The application set, animations, themes, custom lock screen, SDDM, Zsh, Oh My Zsh and Starship are retained.
No additional runtime dependencies or privileged helpers are introduced.

## Install this branch on fresh Arch

Run these commands as your normal wheel/sudo user **on the fresh target system**, after completing the
minimal Arch installation and connecting to the network. Do not run them on an existing desktop.
The checkout below is separate from `~/.dotfiles`, which the installer creates itself.

```bash
git clone --branch feat/uk-keyboard-locale https://github.com/m4rduc/HyprPunk.git ~/HyprPunk
cd ~/HyprPunk
DOTFILES_BRANCH=feat/uk-keyboard-locale bash install.sh
```

Select `gb` for keyboard, interface language and regional formats. Review the `pacman -Syu` transaction.
Limine detected through `bootctl status` skips GRUB theming. If the loader cannot be identified and the
GRUB question appears, answer **N** on a Limine system. Unknown detection never enables theming by itself.
Re-run the same installer command with the same branch to resume after a failed step; logs and progress
are in `~/.local/state/hyprpunk/`. Do not switch installation sources midway through a run.

The default source in the installer is `m4rduc/HyprPunk`, branch `master`. The explicit branch setting above
is necessary while this PR is unmerged. Once merged, a fresh installation can use `master` for both commands.

### X1 Carbon installation notes

For the ThinkPad X1 Carbon Gen 10, finish the Intel graphics/base-system setup, LUKS2, Btrfs, Snapper,
Limine and `Europe/London` time zone separately. This patch does not configure them, Secure Boot, TPM2,
fingerprint authentication, EFI entries or disk partitions. Display settings still use upstream's
preferred-mode selection; inspect scaling on the 2880 × 1800 screen after login.

Set and verify the UK keyboard in the base system and initramfs before relying on it to enter an encrypted
disk passphrase. The desktop controller sets `gb` for XKB and `uk` for the normal Linux console. It does not
rebuild the initramfs or change a bootloader's keyboard handling. See [systemd's localectl documentation](https://www.freedesktop.org/software/systemd/man/latest/localectl.html).

## Development checks

Run `python3 tests/test_profiles.py` from the repository. It uses temporary home directories and an
allowlisted command path with system/session commands replaced by stubs. It evaluates selected installer
function definitions only; it never executes the installer. Lua and the headless Qt mapping check run when
their tools are available. No packages are installed by the tests.

Checks performed for this change:

- Bash syntax for the installer and both controllers; Lua syntax for every repository Lua file.
- US, UK and French controller selection, persistence, invalid-input rejection, UK console mapping,
  French terminal remaps, and identical US/UK generated QWERTY bindings.
- All nine interface/regional locale combinations, including saved state and user environment assignments.
- Hyprland and Neovim Lua profile loading, plus headless Qt tests of the actual QML option expressions,
  UK calendar date format, Monday-first week and GBP currency.
- Parsing of all four changed QML files with `qmlformat`; this is not a full Quickshell runtime check.
- Compilation of US/UK/French XKB maps; UK symbol checks against the compiled map and installed `uk.map.gz`.
- Generation of all three locales into a temporary directory with `localedef --no-archive`; checks of UK
  currency, number/date/time formats, A4 and measurement settings. System locale files were not changed.
- Installer prompt/state handling, matching fork/branch clone arguments and rejection of a mismatched clone.
- Mocked bootloader detection: Limine and systemd-boot skip even with GRUB tools present; GRUB and unknown
  detection require explicit confirmation; declined prompts, EOF and failed detection default to skip.
- Interactive system upgrade arguments and failure propagation. Quickshell and Super+U upgrades retain
  `yay` prompts and hold Kitty open to inspect results.
- Diff review to ensure application packages, Stow modules, visual configuration and shortcut keys are retained.

ShellCheck is unavailable in the development environment. The Quickshell module is also unavailable, so
full QML import/type validation and a real Hyprland/SDDM/Quickshell session remain untested.

## Checks after installation

1. Check `locale -a` includes `en_GB.utf8`, `en_US.utf8` and `fr_FR.utf8`. In a new Kitty terminal, inspect
   `locale`, `locale -k LC_MONETARY LC_PAPER LC_MEASUREMENT`, and `date +'%x %X'`. With both profiles set to
   `gb`, expect British English, GBP, A4 and day/month/year dates. `LC_ALL` should not override the profiles.
2. Check `~/Scripts/keyboard-layoutctl.sh get` returns `gb`; `localectl status` should report X11 `gb`
   and VC `uk`. In Kitty, a GUI text field, a TTY and SDDM's visible username field, type `£ @ " # \ |`.
   Do not use a password field as the symbol test. Confirm the custom lock screen accepts normal login.
3. Check `hjkl` movement in Hyprland, Neovim, Tmux, Yazi, less and Zsh vi mode; check `Ctrl+'` clipboard,
   workspace number keys, window movement/resizing and Quickshell panel navigation. Switch to French and
   check its `jklm` mappings and Kitty Ctrl+M behavior, then US, then UK again.
4. Cycle the Keyboard tile and select each interface/regional option independently. An English interface
   with French regional formats should remain supported. Return both to UK and verify the calendar's
   Monday-first week and English month/day names. Restart already-open applications after locale changes.
5. Restart Quickshell, log out/in, then reboot. Confirm UK keyboard and both locale choices persist in
   Hyprland, new terminals, the calendar and the greeter. Restart Neovim to rebuild plugin-specific mappings.
6. Check the installer log reports GRUB theming skipped on Limine. Confirm normal boot and snapshot behavior
   using the base installation's own checks. Actual GRUB theme writes were not tested on a live GRUB system.
7. Open the update pill and Super+U: confirm `yay` shows its review/confirmation prompts and Kitty remains
   open afterwards to inspect errors. Cancelling at a prompt is sufficient to check the UI without upgrading.

Upstream package lists and AUR installation flags are retained, so package availability, AUR build scripts
and future upstream package/configuration changes still need review during a fresh install. The existing
Zsh `u` alias remains unchanged and uses `--noconfirm` when explicitly invoked. The existing polkit rule still
allows an active local session to change the system keymap. No authentication rules were added or broadened.

The bootloader check reads only the current-loader section of [bootctl status](https://www.freedesktop.org/software/systemd/man/latest/bootctl.html).
Some bootloaders or legacy BIOS boots do not expose that information; the default-no confirmation covers
those cases. Runtime behavior on the target laptop has not been verified by these development checks.
