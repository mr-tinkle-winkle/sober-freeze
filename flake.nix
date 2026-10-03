{
  description = "sober-freeze - freeze / thaw Sober (or the focused app): toggle, hold-to-freeze, auto-unfreeze";

  inputs = {
    # Overridden by the parent flake's `inputs.nixpkgs.follows = "nixpkgs-unstable"`
    # (same pattern as afterglow / sober-console) -- this default is only used if
    # sober-freeze is ever built standalone.
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-linux" ];

      mkPackage = pkgs:
        let
          python = pkgs.python3;
        in
        python.pkgs.buildPythonApplication {
          pname = "sober-freeze";
          version = "0.1.0";
          format = "pyproject";
          src = ./.;

          nativeBuildInputs = [
            python.pkgs.setuptools
            pkgs.makeWrapper
            pkgs.qt6.wrapQtAppsHook
          ];

          # The GUI is a plain Qt window (xcb or wayland platform plugin).
          buildInputs = [
            pkgs.qt6.qtbase
            pkgs.qt6.qtwayland
            pkgs.xcb-util-cursor
          ];

          propagatedBuildInputs = with python.pkgs; [
            pyside6
            evdev
            tomli-w
          ];

          pythonImportsCheck = [ "sober_freeze" ];

          # As in afterglow's / sober-console's flakes: wrapQtAppsHook doesn't reliably wrap the
          # shebang entry-point script, so wrapQtApp is called explicitly, with wrapProgram on top:
          #   systemctl  (systemd)  -- freeze / thaw / unit lookup
          #   kdotool               -- which window is focused (--override-to-focused)
          #   notify-send (libnotify) -- the "Frozen" / "Thawed" popups
          postFixup = ''
            wrapQtApp "$out/bin/sober-freeze"
            wrapProgram "$out/bin/sober-freeze" \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.systemd pkgs.kdotool pkgs.libnotify pkgs.coreutils ]}

            mkdir -p "$out/share/applications"
            printf '%s\n' \
              '[Desktop Entry]' \
              'Type=Application' \
              'Name=Sober Freeze' \
              'Comment=Freeze / thaw Sober or the focused app' \
              "Exec=$out/bin/sober-freeze gui" \
              'Icon=media-playback-pause' \
              'Categories=Utility;' \
              > "$out/share/applications/sober-freeze.desktop"
          '';

          # The pytest suite (tests/) needs Qt's offscreen platform; run it from `nix develop`.
          doCheck = false;

          meta = {
            description = "Freeze / thaw Sober (or the focused app): toggle, hold-to-freeze, auto-unfreeze";
            homepage = "https://github.com/mr-tinkle-winkle/sober-freeze";
            mainProgram = "sober-freeze";
            platforms = pkgs.lib.platforms.linux;
          };
        };
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = mkPackage pkgs;
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = [
              (pkgs.python3.withPackages (ps: [
                ps.pyside6
                ps.evdev
                ps.tomli-w
                ps.pytest
                ps.setuptools
              ]))
              pkgs.qt6.qtbase
              pkgs.qt6.qtwayland
              pkgs.kdotool
            ];
            shellHook = ''
              export QT_PLUGIN_PATH="${pkgs.qt6.qtbase}/lib/qt-6/plugins:${pkgs.qt6.qtwayland}/lib/qt-6/plugins''${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
              echo "sober-freeze dev shell. Try: QT_QPA_PLATFORM=offscreen pytest -q   or   python -m sober_freeze gui"
            '';
          };
        });

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.sober-freeze;
          pkg = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
        in
        {
          options.services.sober-freeze = {
            enable = lib.mkEnableOption "sober-freeze (freeze/thaw Sober, hold-to-freeze, auto-unfreeze)";

            user = lib.mkOption {
              type = lib.types.str;
              description = ''
                User the background service runs for. Also granted /dev/input read access when
                `holdKey` is set (needed to see the key being held -- same requirement as
                sober-console, afterglow and puppetry).
              '';
            };

            holdKey = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              example = "KEY_SCROLLLOCK";
              description = ''
                evdev key name, or a combo like `KEY_LEFTCTRL+KEY_F9`: hold to freeze, release
                to thaw. The key is read passively, so it still reaches the focused window --
                pick one Sober doesn't use. null = no hold key (the CLI / GUI still work).
              '';
            };

            holdOverrideToFocused = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "The hold key freezes the focused window's app instead of Sober.";
            };
          };

          config = lib.mkIf cfg.enable {
            environment.systemPackages = [ pkg ];

            users.users.${cfg.user}.extraGroups = lib.mkIf (cfg.holdKey != null) [ "input" ];

            # Background part: the auto-unfreeze watchdog (+ the hold-key listener). Started
            # with the graphical session so kdotool / notifications have a display.
            systemd.user.services.sober-freeze = {
              description = "sober-freeze: auto-unfreeze watchdog and hold-to-freeze key";
              wantedBy = [ "graphical-session.target" ];
              partOf = [ "graphical-session.target" ];
              after = [ "graphical-session.target" ];
              unitConfig.ConditionUser = cfg.user;
              serviceConfig = {
                ExecStart = lib.concatStringsSep " " ([ "${pkg}/bin/sober-freeze" "daemon" ]
                  ++ lib.optionals (cfg.holdKey != null) [ "--hold-key" (lib.escapeShellArg cfg.holdKey) ]
                  ++ lib.optional cfg.holdOverrideToFocused "--hold-override-to-focused");
                Restart = "on-failure";
                RestartSec = 3;
              };
            };
          };
        };
    };
}
