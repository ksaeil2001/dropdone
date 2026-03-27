import json, sys, os

host_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(host_dir, 'dropdone_host.json')
launcher  = os.path.join(host_dir, 'dropdone_host_run.bat')

with open(json_path, 'r', encoding='utf-8-sig') as f:
    data = json.load(f)

data['path'] = launcher

with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=4, ensure_ascii=False)

print('    path =', launcher)
