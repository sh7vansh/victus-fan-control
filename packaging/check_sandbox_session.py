"""Exercise the real Flatpak host pipe without authentication or hardware writes."""

from pathlib import Path
import sys
sys.path.insert(0, '/app/share/victus-fan-control')

from gi.repository import GLib
from fan_control.authorization import AuthorizationSession
from fan_control.hardware import WriteRequest

peer = '''
import json, sys
print('{"ready":true}', flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get('operation') == 'ping':
        continue
    print(json.dumps({'id':request['id'], 'ok':True}), flush=True)
'''
launches = []
def argv():
    launches.append(True)
    return ['/usr/bin/flatpak-spawn', '--host', '--watch-bus', '/usr/bin/python3', '-I', '-u', '-c', peer]

loop = GLib.MainLoop()
session = AuthorizationSession(argv_factory=argv)
requests = iter((WriteRequest(Path('/sys/firmware/acpi/platform_profile'), 'quiet'),
                 WriteRequest(Path('/sys/devices/platform/hp-wmi/hwmon/hwmon1/pwm1_enable'), '0'),
                 WriteRequest(Path('/sys/devices/platform/hp-wmi/hwmon/hwmon1/pwm1_enable'), '2')))
failures = []
def exited(process, result):
    process.wait_finish(result)
    if not process.get_successful():
        failures.append('Host pipe did not close cleanly')
    loop.quit()

def advance(error=None):
    if error:
        failures.append(str(error))
        session.close()
        loop.quit()
        return
    request = next(requests, None)
    if request:
        session.change(request, advance)
    else:
        assert len(launches) == 1
        process = session.process
        process.wait_async(None, exited)
        session.close()

advance()
loop.run()
assert not failures, failures
print('Sandbox session passed: three requests, one host process, clean pipe shutdown, no authentication or hardware writes')
