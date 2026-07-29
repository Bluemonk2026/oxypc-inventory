#!/usr/bin/env bash
# Build the macOS OxyQC agent.
#
# Must run ON a Mac. PyInstaller does not cross-compile: it bundles the host's
# Python runtime and a platform-specific bootloader, so the Windows build box
# cannot produce this artifact — that is why only Diagnose_Device_Agent.exe is
# committed and this script exists.
#
#   chmod +x build_mac_agent.sh && ./build_mac_agent.sh
#
# Output: dist/Diagnose_Device_Agent  (a Unix executable, no .exe suffix)
#
# Apple Silicon vs Intel: the binary matches the host architecture. To ship one
# file for both, build on Apple Silicon with a universal2 Python and add
#   --target-arch universal2
# to the pyinstaller call below.
set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: this must run on macOS (found: $(uname -s))." >&2
  echo "Build Diagnose_Device_Agent.exe on Windows with:" >&2
  echo "  python -m PyInstaller --noconfirm Diagnose_Device_Agent.spec" >&2
  exit 1
fi

python3 -m pip install --quiet --upgrade pyinstaller

# --windowed matches the Windows spec's console=False: the agent is a background
# HTTP service on 127.0.0.1:8765 and must never open a terminal window on a
# technician's station.
python3 -m PyInstaller --noconfirm --onefile --windowed \
  --name Diagnose_Device_Agent \
  oxyqc_agent.py

echo
echo "Built: $(pwd)/dist/Diagnose_Device_Agent"
echo "Verify with:  ./dist/Diagnose_Device_Agent &  then  curl -s localhost:8765/ping"
echo "Expect the /ping response to report the AGENT_VERSION set in oxyqc_agent.py."
echo
echo "NOTE: port 8765 must be free. Anything else bound to 0.0.0.0:8765 will"
echo "shadow the agent's 127.0.0.1 bind and answer in its place."
