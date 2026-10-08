{
  description = "RoutingAGen: RoutingA text with Jinja data substitutions";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      dependencies = ps: with ps; [
        jinja2 pyyaml requests more-itertools dnspython atomicwrites
      ];
      pythonFor = pkgs: pkgs.python3.withPackages dependencies;
      testPythonFor = pkgs: pkgs.python3.withPackages (ps: dependencies ps ++ [ ps.pytest ]);
    in {
      packages = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "routingagen";
            version = "0.1.0";
            src = pkgs.lib.fileset.toSource {
              root = ./.;
              fileset = pkgs.lib.fileset.unions [
                ./home/routingagen.py ./home/config.yml ./pyproject.toml
                (pkgs.lib.fileset.fileFilter (file: file.hasExt "py") ./home/tests)
              ];
            };
            nativeBuildInputs = [ pkgs.makeWrapper ];
            nativeCheckInputs = [ (testPythonFor pkgs) pkgs.ruff ];
            PYTHONDONTWRITEBYTECODE = "1";
            doCheck = true;
            checkPhase = ''
              ruff check home
              ruff format --check home
              pytest -q
            '';
            installPhase = ''
              mkdir -p $out/libexec $out/bin
              cp home/routingagen.py home/config.yml $out/libexec/
              makeWrapper ${pythonFor pkgs}/bin/python $out/bin/routingagen \
                --set PYTHONDONTWRITEBYTECODE 1 \
                --add-flags $out/libexec/routingagen.py
            '';
            meta = {
              description = "Render RoutingA text without interpreting its syntax";
              license = pkgs.lib.licenses.agpl3Only;
              mainProgram = "routingagen";
              platforms = systems;
            };
          };
        });
      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${system}.default;
          meta.description = "Render home/config.yml into rules";
        };
      });
      checks = forAllSystems (system: { default = self.packages.${system}.default; });
      devShells = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in { default = pkgs.mkShell {
          packages = [ (testPythonFor pkgs) pkgs.ruff ];
          PYTHONDONTWRITEBYTECODE = "1";
        }; });
    };
}
