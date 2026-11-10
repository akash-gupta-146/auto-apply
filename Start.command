#!/bin/bash
# The one file to double-click. The first time it installs everything; every time it opens the control panel.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/jobapply" ]; then
  echo "First time here: installing. This can take several minutes. Please wait..."
  echo
  if ! bash ./setup.sh || [ ! -x ".venv/bin/jobapply" ]; then
    echo
    echo "The install did not finish. The lines above say why. Fix that, then double-click Start.command again."
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
  fi
  echo
fi

".venv/bin/jobapply" panel
status=$?
echo
read -n 1 -s -r -p "The control panel has closed. Press any key to close this window..."
echo
exit $status
