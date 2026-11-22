# Colab CLI (remote GPU/TPU runs)

The Google Colab CLI rents a Colab VM (CPU, T4/L4/A100/H100 GPU, TPU) and runs
local scripts on it. It is **Linux/macOS only**, so on this machine it is
installed inside WSL (`kali-linux`) and reached from Windows through
`scripts/colab.ps1` / `scripts/colab.cmd`.

## One-time sign-in

```powershell
wsl -d kali-linux -- colab sessions
```

The first call prints a Google authorization URL, reads a pasted code, and caches
the token (the OAuth client is the one bundled with the CLI, so no setup is
needed). Sign in with the account that owns the Colab quota.

Verify:

```powershell
wsl -d kali-linux -- colab whoami
```

## Usage from Windows

Use the wrapper from the project root. It keeps the current directory, maps
`C:\...` to `/mnt/c/...`, and accepts relative paths such as `src\train_lstm.py`.

```powershell
.\scripts\colab.cmd new -s train --gpu T4      # rent a T4 VM
.\scripts\colab.cmd install -s train torch pandas scikit-learn joblib xgboost
.\scripts\colab.cmd exec -s train -f src\train_lstm.py
.\scripts\colab.cmd download -s train config/lstm_residual_arakan.pt config\lstm_residual_arakan.pt
.\scripts\colab.cmd stop -s train              # always release the VM
```

`.\scripts\colab.cmd --help` (or `help <command>`) lists every command. The
wrapper works from any directory; `COLAB_WSL_DISTRO` overrides the distro name.

Useful one-shot form that provisions, runs, and tears down automatically:

```powershell
.\scripts\colab.cmd run --gpu T4 src\train_all_sites.py
```

### Running this project's training remotely

Two adaptations are needed before `src/train_*.py` will run on a Colab VM:

1. **Data is local.** Upload the inputs first (the VM starts empty in
   `/content`):
   ```powershell
   .\scripts\colab.cmd upload -s train data\processed\features_arakan.csv /content/data/processed/features_arakan.csv
   .\scripts\colab.cmd upload -s train config\xgb_baseline_arakan.pkl /content/config/xgb_baseline_arakan.pkl
   ```
2. **`__file__` is undefined.** `colab exec`/`run` send source text to the
   kernel, so `BASE = Path(__file__).resolve().parents[1]` raises `NameError`.
   Change the three `BASE = ...` lines to:
   ```python
   BASE = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd()
   ```
   That keeps local runs unchanged and lets the remote kernel resolve
   `/content` as the project root.

## Notes

- Remote working directory is `/content`; `exec -f` uploads the script content
  and runs it in the kernel, so no manual upload is needed.
- `colab exec` keeps kernel state between calls in the same session.
- Idle VMs consume compute units: `colab stop -s <name>` when finished.
- Installed version: `google-colab-cli 0.7.5` (`uv tool install`, Python 3.12
  venv at `~/.local/share/uv/tools/google-colab-cli`). The OAuth token is cached
  at `~/.config/colab-cli/token.json` inside WSL; delete it to force a fresh
  sign-in.
- Upgrade with:
  `wsl -d kali-linux -- /home/slade/.local/bin/uv tool upgrade google-colab-cli`
- The agent skill `colab-operator` is installed in
  `~/.config/opencode/skills/colab-operator/SKILL.md`.
