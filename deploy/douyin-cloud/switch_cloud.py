from pathlib import Path
import re,subprocess
p=Path('/etc/nginx/sites-enabled/siyumenghai-main');s=p.read_text()
backup=Path('/etc/nginx/siyumenghai-main.before-cloud-douyin-20261013')
if backup.exists():raise SystemExit('Backup already exists; inspect before retry')
backup.write_text(s)
block='''    location ^~ /api/douyin/ {
        limit_req zone=douyin_cloud_api burst=8 nodelay;
        limit_req_status 429;
        client_max_body_size 16k;
        proxy_pass http://127.0.0.1:2037;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_connect_timeout 5s;
        proxy_read_timeout 180s;
        proxy_buffering off;
        add_header Cache-Control no-store always;
    }'''
new,n=re.subn(r'    location \^~ /api/douyin/ \{[^}]*\}',lambda m:block,s)
assert n==1 and 'proxy_pass http://127.0.0.1:22033;' in s
prefix='''# Empty keys exclude media playback and health probes from parse rate limits.
map $uri $douyin_cloud_limit_key {
    default $binary_remote_addr;
    ~^/api/douyin/media/ "";
    /api/douyin/health "";
}
limit_req_zone $douyin_cloud_limit_key zone=douyin_cloud_api:1m rate=30r/m;
'''
p.write_text(prefix+new)
result=subprocess.run(['nginx','-t'],capture_output=True,text=True)
if result.returncode:
 p.write_text(s);print(result.stderr);raise SystemExit(1)
subprocess.run(['systemctl','reload','nginx'],check=True)
print('nginx config validated and cloud route activated; prior config retained')
