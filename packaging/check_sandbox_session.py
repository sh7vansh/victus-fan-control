"""Check host reads and rejection of unprivileged daemon startup."""

import json
import subprocess
import sys
sys.path.insert(0, '/app/share/victus-fan-control')
from fan_control.native import helper_argv

snapshot_argv = helper_argv('--snapshot')
assert '/usr/bin/python3' not in snapshot_argv
assert '/usr/bin/cat' not in snapshot_argv
state = json.loads(subprocess.check_output(snapshot_argv, text=True))
assert isinstance(state['choices'], list)
assert len(state['rpm']) == 2
assert helper_argv('--daemon', '--allow-uid', '0', privileged=True)[-3:] == ['--daemon', '--allow-uid', '0']
result = subprocess.run(helper_argv('--daemon', '--allow-uid', '0'), input='', capture_output=True, text=True)
assert result.returncode != 0 and 'Administrator authentication' in result.stderr
print('Sandbox compiled-helper check passed: real host snapshot, no host interpreter, unprivileged writes rejected')
