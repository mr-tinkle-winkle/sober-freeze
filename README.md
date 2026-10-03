# sober-freeze

Freeze and thaw Sober (Roblox on Linux) -- or whatever app is focused -- with the cgroup freezer
(`systemctl --user freeze`): the app keeps its state but gets no CPU until thawed. Toggle command,
**hold-to-freeze** key, **auto-unfreeze**, and a small GUI. Same flake shape as `sober-console`
/ `afterglow`.

## Add it to your flake

```nix
inputs = {
    # ...
    sober-freeze = {
        url = "github:mr-tinkle-winkle/sober-freeze";
        inputs.nixpkgs.follows = "nixpkgs-unstable";
    };
};

# in nixosSystem's modules = [ ... ]:
inputs.sober-freeze.nixosModules.default
{
    services.sober-freeze = {
        enable = true;
        user = "mrtw";
        holdKey = "KEY_SCROLLLOCK";        # optional: hold to freeze Sober, release to thaw
        # holdOverrideToFocused = true;    # optional: the hold key freezes the focused app instead
    };
}
```

This **replaces** the old `sober-freeze` script from `configuration.nix` -- delete that
let-binding and its `environment.systemPackages` entry (two packages with the same name collide).

The module installs the package, and runs a per-user service (`sober-freeze daemon`) that does the
auto-unfreezing and listens for the hold key. With `holdKey` set it also adds `user` to the `input`
group (log out and in once).

## Commands

```
sober-freeze                          # toggle Sober (same as before)
sober-freeze freeze | thaw | toggle | status
sober-freeze toggle --override-to-focused     # act on the focused window's app instead of Sober
                                              # (--overrideToFocused also works)
sober-freeze thaw --all               # thaw everything sober-freeze froze
sober-freeze list                     # what is frozen, and for how long
sober-freeze auto-unfreeze [on|off|toggle|status] [--seconds N]
sober-freeze gui
sober-freeze daemon [--hold-key KEY_X] [--hold-override-to-focused]   # what the service runs
```
`-q` suppresses the desktop notification. Bind `sober-freeze` / `sober-freeze toggle
--override-to-focused` to KDE shortcuts for plain toggling.

## Hold to freeze

**Keyboard:** KDE shortcuts only fire on key *press*, so hold-to-freeze is done by the daemon, which
reads the key from `/dev/input` (passively -- the key still reaches the focused window, so choose one
Sober doesn't use: `KEY_SCROLLLOCK`, `KEY_PAUSE`, or a combo like `KEY_LEFTCTRL+KEY_F9`). While all
keys are down the target is frozen; releasing any thaws *the same target it froze* (even if focus
moved). If the keyboard disappears or the daemon stops mid-hold, it thaws.

**StreamController:** it has separate key-down / key-up events. Where the Run Command action lets you
set both: key down `sober-freeze freeze -q`, key up `sober-freeze thaw -q`. If it only offers one
command box, a tiny custom action using `on_key_down` / `on_key_up` is needed. If StreamController is a
Flatpak, prefix with `flatpak-spawn --host`.

## Auto-unfreeze

On by default, **20 s**. Anything frozen through sober-freeze (toggle, CLI, GUI, hold) is thawed
that long after it was frozen -- Roblox drops the connection if Sober stays frozen too long. Turn it
off or change the delay with `sober-freeze auto-unfreeze off|on|toggle --seconds N` or in the GUI; it
lives in `~/.config/sober-freeze/config.toml` and the daemon picks changes up within a second
(turning it on while something is already frozen thaws it as soon as the delay has passed since it
was frozen). It needs the daemon: if it isn't running, `freeze` tells you and the GUI shows it.

## Focused-window mode: what it really freezes

`--override-to-focused` finds the focused window's process with `kdotool`, then freezes that
process's **whole systemd unit** -- which can be more than the window (all windows of a Flatpak, helper
processes; for some launchers possibly the launcher too, e.g. a game started by Steam may sit in
Steam's unit). Guard rails: only `app-*` units, nothing that looks like the desktop session
(plasma, kwin, portals, dbus, pipewire...), and never the unit the command itself runs from -- so
running it from a terminal refuses to freeze that terminal. Run from a keybind or the Stream Deck
so the target window is the one focused. The GUI's focused button waits 3 s so you can switch to it.
If you switch away from a frozen app, `thaw --all` (or the GUI list) thaws it.

## What is and isn't verified

Written without a KDE session, Sober or `/dev/input`. **Tested (41 automated tests):** toggle /
freeze / thaw logic against a fake systemd, the override and its refusals, the auto-unfreeze
watchdog (including live setting changes), the hold key state machine, CLI parsing (both flag
spellings, bare command), config, the daemon lock, the GUI (offscreen). **Not verified:** the real
`systemctl freeze` on your units (needs systemd >= 255, as your old script did), `kdotool` returning
the right pid for the focused window, evdev reading, the Nix build (the flake parses; it was never
built).

## Development

```
nix develop
QT_QPA_PLATFORM=offscreen pytest -q
python -m sober_freeze gui
```
