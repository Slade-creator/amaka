# Google Colab CLI wrapper for Windows.
#
# The Colab CLI only supports Linux/macOS, so this forwards every command to the
# `colab` binary installed inside WSL, keeping the current Windows directory and
# translating Windows paths (C:\...) to their WSL equivalents (/mnt/c/...).
#
# Usage (from the project root):
#   .\scripts\colab.ps1 new --gpu T4
#   .\scripts\colab.ps1 exec -f src\train_lstm.py
#   .\scripts\colab.ps1 stop
#
# Override the distro or binary with:
#   $env:COLAB_WSL_DISTRO = "Ubuntu"
#   $env:COLAB_WSL_BIN    = "/home/<user>/.local/bin/colab"

$distro = if ($env:COLAB_WSL_DISTRO) { $env:COLAB_WSL_DISTRO } else { "kali-linux" }
$colabBin = if ($env:COLAB_WSL_BIN) { $env:COLAB_WSL_BIN } else { "/home/slade/.local/bin/colab" }
$cwd = (Get-Location).ProviderPath

$passthrough = @(
    foreach ($arg in $args) {
        if ($arg -match '^(?<drive>[A-Za-z]):(?<rest>[\\/].*)$') {
            # Absolute Windows path -> WSL mount path.
            "/mnt/$($Matches['drive'].ToLower())$(($Matches['rest']) -replace '\\', '/')"
        }
        elseif ($arg -notmatch '^-') {
            # Relative paths written with backslashes (src\train_lstm.py).
            $arg -replace '\\', '/'
        }
        else {
            $arg
        }
    }
)

& wsl.exe -d $distro --cd $cwd -- $colabBin @passthrough
exit $LASTEXITCODE
