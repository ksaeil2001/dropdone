import json
import os


EXTENSION_ID = 'aanekpdighliaaaekihmhnapnbdoiacl'


host_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(host_dir)
json_path = os.path.join(host_dir, 'dropdone_host.json')
launcher = os.path.join(host_dir, 'dropdone_host_run.bat')
host_py = os.path.join(host_dir, 'dropdone_host.py')
installed_exe = os.path.join(root_dir, 'DropDone', 'DropDone.exe')
built_exe = os.path.join(root_dir, 'dist', 'DropDone', 'DropDone.exe')


if os.path.exists(installed_exe):
    launcher_content = f'@echo off\r\n"{installed_exe}" --native-host\r\n'
elif os.path.exists(built_exe):
    launcher_content = f'@echo off\r\n"{built_exe}" --native-host\r\n'
else:
    launcher_content = f'@echo off\r\npython "{host_py}"\r\n'

with open(launcher, 'w', encoding='ascii', newline='') as f:
    f.write(launcher_content)

with open(json_path, 'r', encoding='utf-8-sig') as f:
    data = json.load(f)

data['path'] = launcher
data['allowed_origins'] = [f'chrome-extension://{EXTENSION_ID}/']

with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=4, ensure_ascii=False)

print('    path =', launcher)
print('    allowed_origin =', data['allowed_origins'][0])
