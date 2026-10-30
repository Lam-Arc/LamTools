# user:“测试，提交打包发布”+(校验公开产物、备份和原子切换下载清单与官网，失败恢复原指针)。

import base64,datetime,hashlib,json,os,pathlib,shutil,subprocess,time,urllib.request

VERSION='0.3.28'

ROOT=pathlib.Path('/var/www/lamtools')

BACKUPS=pathlib.Path('/var/backups/ainarit')

STAMP=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

API='https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v'+VERSION

HEADERS={'User-Agent':'Sunday-release-verifier','Accept':'application/vnd.github+json'}

def get_json(url,asset=False):

    with urllib.request.urlopen(urllib.request.Request(url,headers={**HEADERS,**({'Accept':'application/octet-stream'} if asset else {})}),timeout=120) as response:

        return json.load(response)

release=get_json(API)

assert release['tag_name']=='v'+VERSION and not release['draft'] and not release['prerelease']

assets={row['name']:row for row in release['assets']}

names=[f'Sunday_{VERSION}_x64-setup.exe',f'Sunday_{VERSION}_amd64.AppImage',f'Sunday_{VERSION}_amd64.deb',f'Sunday_{VERSION}_site.tar.gz']

assert all(name in assets for name in [*names,'desktop-update.json']), sorted(assets)

manifest=get_json(assets['desktop-update.json']['url'],True)

assert manifest['version']==VERSION

site_link=ROOT/'site'

assert site_link.is_symlink(), 'public site must remain a symlink'

old_site=os.readlink(site_link)

assert pathlib.Path(old_site).resolve().is_relative_to(ROOT/'site-releases')

current=json.loads((ROOT/'desktop-update.json').read_text())

def parts(v):return tuple(map(int,v.split('.')))

assert parts(current['version']) <= parts(VERSION), 'refusing to replace a newer public release'

print('INSPECT',json.dumps({'previous_version':current['version'],'previous_site':old_site,'target':VERSION}),flush=True)

BACKUPS.mkdir(parents=True,exist_ok=True)

backup=BACKUPS/('release-'+VERSION+'-'+STAMP)

backup.mkdir()

shutil.copy2(ROOT/'desktop-update.json',backup/'desktop-update.json')

(backup/'old-site.txt').write_text(old_site)

latest_path=ROOT/'Sunday-latest-x64-setup.exe'

old_latest=None

if latest_path.is_symlink():

    old_latest=('symlink',os.readlink(latest_path))

elif latest_path.exists():

    assert latest_path.is_file(), 'latest alias must be a file or symlink'

    os.link(latest_path,backup/'previous-latest.exe')

    old_latest=('file',str(backup/'previous-latest.exe'))

(backup/'old-latest.json').write_text(json.dumps(old_latest))

subprocess.run(['tar','-czf',str(backup/'public-root.tar.gz'),'-C','/var/www','ainarit'],check=True)

subprocess.run(['tar','-czf',str(backup/'preview.tar.gz'),'-C','/var/www','ainarit-preview'],check=True)



def download(asset,expected):

    from concurrent.futures import ThreadPoolExecutor,as_completed

    import tempfile

    target=ROOT/asset['name']

    if target.is_file() and target.stat().st_size==asset['size'] and hashlib.sha256(target.read_bytes()).hexdigest()==expected:

        print('REUSE',asset['name'],flush=True)

        return target

    assert not target.exists(), 'existing asset differs; preserve it for investigation'

    with urllib.request.urlopen(urllib.request.Request(asset['url'],headers={**HEADERS,'Accept':'application/octet-stream'}),timeout=120) as response:

        address=response.geturl()

    assert address.startswith('https://'), 'only official HTTPS redirects are accepted'

    block=1024*1024

    count=(asset['size']+block-1)//block

    partial=target.with_name(target.name+'.partial-'+STAMP)

    with tempfile.TemporaryDirectory(prefix='sunday-0.3.28-parts-',dir=ROOT) as workspace:

        folder=pathlib.Path(workspace)

        def fetch(index):

            begin=index*block; end=min(asset['size'],begin+block)-1

            part=folder/str(index)

            for attempt in range(3):

                try:

                    request=urllib.request.Request(address,headers={'User-Agent':'Sunday-release-verifier','Range':f'bytes={begin}-{end}'})

                    received=0;deadline=time.monotonic()+300

                    with urllib.request.urlopen(request,timeout=120) as response,part.open('wb') as sink:

                        assert response.status==206 and response.headers.get('Content-Range')==f'bytes {begin}-{end}/{asset["size"]}', 'upstream did not honor the exact range'

                        while True:

                            if time.monotonic()>deadline:raise TimeoutError('range transfer exceeded budget')

                            chunk=response.read(65536)

                            if not chunk:break

                            received+=len(chunk)

                            assert received<=end-begin+1

                            sink.write(chunk)

                    assert received==end-begin+1, 'incomplete range'

                    return index

                except (OSError,TimeoutError):

                    if attempt==1:raise

        try:

            with ThreadPoolExecutor(max_workers=8) as pool:

                futures=[pool.submit(fetch,index) for index in range(count)]

                complete=0

                for future in as_completed(futures):

                    future.result();complete+=1

                    if complete==count or complete%8==0:

                        print('TRANSFER_PARTS',asset['name'],complete,count,flush=True)

            digest=hashlib.sha256();received=0

            with partial.open('wb') as sink:

                for index in range(count):

                    with (folder/str(index)).open('rb') as part:

                        for chunk in iter(lambda:part.read(1024*1024),b''):

                            received+=len(chunk);digest.update(chunk);sink.write(chunk)

            assert received==asset['size'] and digest.hexdigest()==expected, 'whole-file digest/size mismatch'

            partial.replace(target)

            print('DOWNLOAD_VERIFIED',asset['name'],received,expected,flush=True)

            return target

        finally:

            partial.unlink(missing_ok=True)



verified={}

for name in names:

    row=assets[name]

    expected=str(row.get('digest') or '').removeprefix('sha256:')

    if name.endswith('_x64-setup.exe'):expected=manifest['sha256'];assert row['size']==manifest['size']


    assert len(expected)==64, 'missing public digest for '+name

    verified[name]=(None if name.endswith(('.AppImage','.deb')) else download(row,expected),expected)

site_dir=ROOT/'site-releases'/('0.3.28-desktop-'+STAMP)

site_dir.mkdir()

subprocess.run(['tar','-xzf',str(verified[names[3]][0]),'-C',str(site_dir)],check=True)

assert (site_dir/'index.html').is_file() and (site_dir/'preview.html').is_file()

new_manifest=dict(manifest)

new_manifest.update(download_url='https://ainarit.com/downloads/'+names[0],linux_version=VERSION,linux_download_url=assets[names[1]]['browser_download_url'],linux_sha256=verified[names[1]][1],linux_size=assets[names[1]]['size'])

new_manifest['release_notes']='Sunday 0.3.28：修复安装版插件样式被安全策略拦截；左侧项目名旁新增单图标新建会话按钮。'

next_link=ROOT/('site.next-'+STAMP)

next_manifest=ROOT/('desktop-update.next-'+STAMP+'.json')

sync_path=pathlib.Path('/var/tmp/sunday-sync-public-site-0.3.28.sh')

sync_path.write_bytes(base64.b64decode('IyEvYmluL3NoCiMgS2VlcCB0aGUgcHVibGljIGRvbWFpbiBpbiBzdGVwIHdpdGggdGhlIHB1Ymxpc2hlZCB1cGRhdGUgY2hhbm5lbC4KIwojIFRoZSByZWdpc3RlcmVkIGRvbWFpbiBjYXJyaWVzIGl0cyBvd24gY29waWVzIG9mIHRoZSBwcm9kdWN0IHBhZ2VzOiB0aGUKIyBTdW5kYXkgcGFnZSBob2xkcyB0aGUgZG93bmxvYWQgbGFiZWxzLCBhbmQgL3ByZXZpZXcvIGVtYmVkcyB0aGUgcHJvZHVjdCBVSS4KIyBUaGUgc2l0ZSBwdWJsaXNoIHN0ZXAgb25seSByZXBvaW50cyAvdmFyL3d3dy9sYW10b29scy9zaXRlLCBzbyB3aXRob3V0IHRoaXMKIyBzdGVwIHRob3NlIGNvcGllcyBzaWxlbnRseSBrZWVwIHRoZSB2ZXJzaW9uIHRoZXkgd2VyZSBidWlsdCB3aXRoLiBUaGUKIyB2ZXJzaW9ucyBhcmUgcmVhZCBiYWNrIGZyb20gdGhlIG1hbmlmZXN0cyB0aGUgcmVsZWFzZSBqdXN0IHB1Ymxpc2hlZCwgc28gYQojIGRlc2t0b3Atb25seSBvciBtb2JpbGUtb25seSByZWxlYXNlIHVwZGF0ZXMgZXhhY3RseSB0aGUgbGFiZWwgaXQgY2hhbmdlZC4KIwojIFJ1bnMgb24gdGhlIHNlcnZlciAoQ2xvdWQgQXNzaXN0YW50IG9yIHNzaCkuIGAtLWNoZWNrYCBvbmx5IHJlYWRzLgojCiMgICBzeW5jLXB1YmxpYy1zaXRlLnNoIFstLWNoZWNrXQojCiMgRXhpdCBjb2RlczogMCBpbiBzdGVwIChvciByZXBhaXJlZCksIDEgb3V0IG9mIHN0ZXAgdW5kZXIgLS1jaGVjay4KCnNldCAtZXUKCkNIRUNLPTAKWyAiJHsxOi19IiA9ICItLWNoZWNrIiBdICYmIENIRUNLPTEKClBVQkxJQ19ST09UPS92YXIvd3d3L2FpbmFyaXQKUFJFVklFVz0vdmFyL3d3dy9haW5hcml0LXByZXZpZXcKU0lURT0vdmFyL3d3dy9sYW10b29scy9zaXRlCkJBQ0tVUFM9L3Zhci9iYWNrdXBzL2FpbmFyaXQKT1JJR0lOPWh0dHBzOi8vYWluYXJpdC5jb20KTkVFRExFPSdTVU5EQVkgWzAtOS5dKiBcfFNVTkRBWSBNT0JJTEUgWzAtOS5dKiBcfFN1bmRheV9bMC05Ll0qX2FtZDY0JwoKZGllKCkgeyBlY2hvICJzeW5jLXB1YmxpYy1zaXRlOiAkMSIgPiYyOyBleGl0IDE7IH0KCnZlcnNpb25zKCkgewogICAgcHl0aG9uMyAtIDw8J1BZJwppbXBvcnQganNvbgppbXBvcnQgcGF0aGxpYgoKZGVmIHJlYWQocGF0aCk6CiAgICByZXR1cm4ganNvbi5sb2FkcyhwYXRobGliLlBhdGgocGF0aCkucmVhZF90ZXh0KGVuY29kaW5nPSd1dGYtOCcpKQoKZGVza3RvcCA9IHJlYWQoJy92YXIvd3d3L2xhbXRvb2xzL2Rlc2t0b3AtdXBkYXRlLmpzb24nKQptb2JpbGUgPSByZWFkKCcvdmFyL3d3dy9sYW10b29scy9tb2JpbGUtdXBkYXRlLmpzb24nKQpwcmludChkZXNrdG9wWyd2ZXJzaW9uJ10sIG1vYmlsZVsndmVyc2lvbiddLCBkZXNrdG9wLmdldCgnbGludXhfdmVyc2lvbicsIGRlc2t0b3BbJ3ZlcnNpb24nXSkpClBZCn0KCiMgVGhlIHN0YW1wZWQgcGFnZSBpcyB0aGUgc291cmNlIG9mIHRydXRoIGZvciB3aGF0IHZpc2l0b3JzIHJlYWQsIHNvIGNvbXBhcmUgaXQKIyBhZ2FpbnN0IHRoZSBtYW5pZmVzdHMgcmF0aGVyIHRoYW4gdHJ1c3RpbmcgdGhhdCB0aGUgbGFzdCBydW4gc3VjY2VlZGVkLgpwYWdlX2lzX2N1cnJlbnQoKSB7CiAgICB3YW50ZWRfZGVza3RvcD0kMQogICAgd2FudGVkX21vYmlsZT0kMgogICAgd2FudGVkX2xpbnV4PSQzCiAgICBncmVwIC1xICJTVU5EQVkgJHdhbnRlZF9kZXNrdG9wICIgIiRQVUJMSUNfUk9PVC9zdW5kYXkuaHRtbCIgJiYKICAgICAgICBncmVwIC1xICJTVU5EQVkgTU9CSUxFICR3YW50ZWRfbW9iaWxlICIgIiRQVUJMSUNfUk9PVC9zdW5kYXkuaHRtbCIgJiYKICAgICAgICBncmVwIC1xICJTdW5kYXlfJHt3YW50ZWRfbGludXh9X2FtZDY0IiAiJFBVQkxJQ19ST09UL3N1bmRheS5odG1sIgp9CgpwcmV2aWV3X2lzX2N1cnJlbnQoKSB7CiAgICBbIC1mICIkUFJFVklFVy9pbmRleC5odG1sIiBdIHx8IHJldHVybiAxCiAgICAjIHVzZXI64oCc5rWL6K+V77yM5o+Q5Lqk5omT5YyF5Y+R5biD4oCdKyjniYjmnKzlhYPmlbDmja7kuI7lrp7pmYXotYTmupDpg73lv4Xpobvlr7nlupTmnKzmrKHlj5HluIMp44CCCiAgICBncmVwIC1xICJuYW1lPVwic3VuZGF5LXZlcnNpb25cIiBjb250ZW50PVwiJHdhbnRlZF9kZXNrdG9wXCIiICIkUFJFVklFVy9pbmRleC5odG1sIiB8fCByZXR1cm4gMQogICAgIyBUaGUgZW1iZWRkZWQgVUkgbXVzdCBiZSB0aGUgYnVuZGxlIHRoZSBzaXRlIHJlbGVhc2UgaXMgc2VydmluZy4KICAgIGVudHJ5PSQoc2VkIC1uICdzfC4qL3ByZXZpZXcvXChhc3NldHMvcHJldmlldy1bQS1aYS16MC05Ll8tXSpcLmpzXCkuKnxcMXxwJyAiJFBSRVZJRVcvaW5kZXguaHRtbCIgfCBoZWFkIC0xKQogICAgWyAtbiAiJGVudHJ5IiBdIHx8IHJldHVybiAxCiAgICBbIC1mICIkUFJFVklFVy8kZW50cnkiIF0gfHwgcmV0dXJuIDEKICAgIGNtcCAtcyAiJFBSRVZJRVcvJGVudHJ5IiAiJFNJVEUvJGVudHJ5Igp9CgpzdGFtcF9wYWdlKCkgewogICAgcHl0aG9uMyAtIDw8J1BZJwppbXBvcnQganNvbgppbXBvcnQgcGF0aGxpYgppbXBvcnQgcmUKCmRlc2t0b3AgPSBqc29uLmxvYWRzKHBhdGhsaWIuUGF0aCgnL3Zhci93d3cvbGFtdG9vbHMvZGVza3RvcC11cGRhdGUuanNvbicpLnJlYWRfdGV4dChlbmNvZGluZz0ndXRmLTgnKSkKbW9iaWxlID0ganNvbi5sb2FkcyhwYXRobGliLlBhdGgoJy92YXIvd3d3L2xhbXRvb2xzL21vYmlsZS11cGRhdGUuanNvbicpLnJlYWRfdGV4dChlbmNvZGluZz0ndXRmLTgnKSkKZHYsIG12ID0gZGVza3RvcFsndmVyc2lvbiddLCBtb2JpbGVbJ3ZlcnNpb24nXQpsdiA9IGRlc2t0b3AuZ2V0KCdsaW51eF92ZXJzaW9uJywgZHYpCgpjaGFuZ2VkID0gW10KZm9yIHBhdGggaW4gc29ydGVkKHBhdGhsaWIuUGF0aCgnL3Zhci93d3cvYWluYXJpdCcpLnJnbG9iKCcqJykpOgogICAgaWYgbm90IHBhdGguaXNfZmlsZSgpIG9yIHBhdGguc3VmZml4Lmxvd2VyKCkgbm90IGluIHsnLmh0bWwnLCAnLmpzJywgJy5jc3MnLCAnLmpzb24nLCAnLnN2Zyd9OgogICAgICAgIGNvbnRpbnVlCiAgICB0ZXh0ID0gcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9J3V0Zi04JykKICAgIGJlZm9yZSA9IHRleHQKICAgIHRleHQgPSByZS5zdWIocidTVU5EQVkgKFxkK1wuXGQrXC5cZCspKD89XHMrLlxzK1g2NCknLCAnU1VOREFZICcgKyBkdiwgdGV4dCkKICAgIHRleHQgPSByZS5zdWIocidTVU5EQVkgTU9CSUxFIChcZCtcLlxkK1wuXGQrKSg/PVxzKy5ccytBUEspJywgJ1NVTkRBWSBNT0JJTEUgJyArIG12LCB0ZXh0KQogICAgdGV4dCA9IHJlLnN1YihyJ1N1bmRheV9cZCtcLlxkK1wuXGQrX2FtZDY0JywgJ1N1bmRheV8nICsgbHYgKyAnX2FtZDY0JywgdGV4dCkKICAgIGlmIHRleHQgIT0gYmVmb3JlOgogICAgICAgIHBhdGgud3JpdGVfdGV4dCh0ZXh0LCBlbmNvZGluZz0ndXRmLTgnKQogICAgICAgIGNoYW5nZWQuYXBwZW5kKHBhdGgubmFtZSkKcHJpbnQoJ3BhZ2Ugc3RhbXBlZCBmb3IgZGVza3RvcCB7fSAvIG1vYmlsZSB7fSAvIExpbnV4IHt9OiB7fScuZm9ybWF0KGR2LCBtdiwgbHYsICcsICcuam9pbihjaGFuZ2VkKSBvciAnYWxyZWFkeSBjdXJyZW50JykpClBZCn0KCiMgL3ByZXZpZXcvIHNlcnZlcyB0aGUgcHJvZHVjdCBVSSBvdXQgb2YgYSBkaXJlY3Rvcnkgb2YgaXRzIG93biwgc28gaXQgbmVlZHMgdGhlCiMgcmVsZWFzZWQgYnVuZGxlIHdpdGggcHJldmlldy5odG1sIHByb21vdGVkIHRvIHRoZSBpbmRleCBhbmQgdGhlIGFzc2V0IHByZWZpeAojIHJld3JpdHRlbiBmb3IgdGhlIHN1YnBhdGggQ2FkZHkgc3RyaXBzLgpzeW5jX3ByZXZpZXcoKSB7CiAgICBzdGFnaW5nPSIkUFJFVklFVy5zdGFnaW5nLiQkIgogICAgcm0gLXJmICIkc3RhZ2luZyIKICAgIG1rZGlyIC1wICIkc3RhZ2luZyIKICAgIGNwIC1hTCAiJFNJVEUiLy4gIiRzdGFnaW5nIi8KICAgIHJtIC1mICIkc3RhZ2luZy9pbmRleC5odG1sIgogICAgY3AgIiRzdGFnaW5nL3ByZXZpZXcuaHRtbCIgIiRzdGFnaW5nL2luZGV4Lmh0bWwiCiAgICBzZWQgLWkgJ3N8PSIvYXNzZXRzL3w9Ii9wcmV2aWV3L2Fzc2V0cy98ZycgIiRzdGFnaW5nL2luZGV4Lmh0bWwiCgogICAgZm9yIHJlZiBpbiAkKHNlZCAtbiAnc3wuKlwoL3ByZXZpZXcvYXNzZXRzL1tBLVphLXowLTkuXy1dKlwpLip8XDF8cCcgIiRzdGFnaW5nL2luZGV4Lmh0bWwiIHwgc29ydCAtdSk7IGRvCiAgICAgICAgWyAtZSAiJHN0YWdpbmcvJHtyZWYjL3ByZXZpZXcvfSIgXSB8fCBkaWUgInRoZSByZWxlYXNlZCBidW5kbGUgaXMgbWlzc2luZyAkcmVmIgogICAgZG9uZQoKICAgIHJtIC1yZiAiJFBSRVZJRVcucmVwbGFjZWQuJCQiCiAgICBtdiAiJFBSRVZJRVciICIkUFJFVklFVy5yZXBsYWNlZC4kJCIKICAgIG12ICIkc3RhZ2luZyIgIiRQUkVWSUVXIgogICAgcm0gLXJmICIkUFJFVklFVy5yZXBsYWNlZC4kJCIKfQoKYmFja3VwKCkgewogICAgbWtkaXIgLXAgIiRCQUNLVVBTIgogICAgc3RhbXA9JChkYXRlIC11ICslWSVtJWRUJUglTSVTWikKICAgIHRhciAtY3pmICIkQkFDS1VQUy9zdW5kYXktYmVmb3JlLSRzdGFtcC50YXIuZ3oiIC1DICIkUFVCTElDX1JPT1QiIHN1bmRheS5odG1sCiAgICB0YXIgLWN6ZiAiJEJBQ0tVUFMvYWluYXJpdC1wcmV2aWV3LWJlZm9yZS0kc3RhbXAudGFyLmd6IiAtQyAvdmFyL3d3dyBhaW5hcml0LXByZXZpZXcKICAgIGVjaG8gImJhY2t1cHM6ICRCQUNLVVBTL3N1bmRheS1iZWZvcmUtJHN0YW1wLnRhci5neiAkQkFDS1VQUy9haW5hcml0LXByZXZpZXctYmVmb3JlLSRzdGFtcC50YXIuZ3oiCn0KCnZlcmlmeV9saXZlKCkgewogICAgd2FudGVkX2Rlc2t0b3A9JDEKICAgIHdhbnRlZF9tb2JpbGU9JDIKICAgIHdhbnRlZF9saW51eD0kMwogICAgcGFnZT0kKGN1cmwgLXNTIC1tIDMwICIkT1JJR0lOL3N1bmRheS5odG1sIikKICAgIGVjaG8gIiRwYWdlIiB8IGdyZXAgLXEgIlNVTkRBWSAkd2FudGVkX2Rlc2t0b3AgIiB8fCBkaWUgIiRPUklHSU4gc3RpbGwgZG9lcyBub3QgcmVhZCBkZXNrdG9wICR3YW50ZWRfZGVza3RvcCIKICAgIGVjaG8gIiRwYWdlIiB8IGdyZXAgLXEgIlNVTkRBWSBNT0JJTEUgJHdhbnRlZF9tb2JpbGUgIiB8fCBkaWUgIiRPUklHSU4gc3RpbGwgZG9lcyBub3QgcmVhZCBtb2JpbGUgJHdhbnRlZF9tb2JpbGUiCiAgICBlY2hvICIkcGFnZSIgfCBncmVwIC1xICJTdW5kYXlfJHt3YW50ZWRfbGludXh9X2FtZDY0IiB8fCBkaWUgIiRPUklHSU4gc3RpbGwgbGlua3MgdGhlIG9sZCBMaW51eCBidWlsZCIKCiAgICBwcmV2aWV3PSQoY3VybCAtZnNTIC1tIDMwICIkT1JJR0lOL3ByZXZpZXcvIikKICAgIGVjaG8gIiRwcmV2aWV3IiB8IGdyZXAgLXEgIm5hbWU9XCJzdW5kYXktdmVyc2lvblwiIGNvbnRlbnQ9XCIkd2FudGVkX2Rlc2t0b3BcIiIgfHwgZGllICIkT1JJR0lOL3ByZXZpZXcvIGhhcyB0aGUgd3JvbmcgYnVpbGQgdmVyc2lvbiIKICAgIGVudHJ5PSQoZWNobyAiJHByZXZpZXciIHwKICAgICAgICBzZWQgLW4gJ3N8LipcKC9wcmV2aWV3L2Fzc2V0cy9wcmV2aWV3LVtBLVphLXowLTkuXy1dKlwuanNcKS4qfFwxfHAnIHwgaGVhZCAtMSkKICAgIFsgLW4gIiRlbnRyeSIgXSB8fCBkaWUgIiRPUklHSU4vcHJldmlldy8gc2VydmVzIG5vIHByb2R1Y3QgYnVuZGxlIgogICAgIyB1c2VyOuKAnOa1i+ivle+8jOaPkOS6pOaJk+WMheWPkeW4g+KAnSso5YWl5Y+j5YiG5YyF5LiN5LiA5a6a5ZCr54mI5pys5paH5pys77yM5pS55Li65qCh6aqM5YWs5byA6LWE5rqQ5LiO5bey5Y+R5biD5paH5Lu255qE5a6M5pW05pGY6KaBKeOAggogICAgc2VydmVkX3NoYT0kKGN1cmwgLWZzUyAtbSA2MCAiJE9SSUdJTiRlbnRyeSIgfCBzaGEyNTZzdW0gfCBhd2sgJ3twcmludCAkMX0nKQogICAgZXhwZWN0ZWRfc2hhPSQoc2hhMjU2c3VtICIkU0lURS8ke2VudHJ5Iy9wcmV2aWV3L30iIHwgYXdrICd7cHJpbnQgJDF9JykKICAgIFsgIiRzZXJ2ZWRfc2hhIiA9ICIkZXhwZWN0ZWRfc2hhIiBdIHx8IGRpZSAiJE9SSUdJTiRlbnRyeSBkaWZmZXJzIGZyb20gdGhlIHB1Ymxpc2hlZCBidW5kbGUiCiAgICBlY2hvICJsaXZlOiAkT1JJR0lOL3N1bmRheS5odG1sIHJlYWRzICR3YW50ZWRfZGVza3RvcCAvICR3YW50ZWRfbW9iaWxlOyAvcHJldmlldy8gc2VydmVzICRlbnRyeSIKfQoKc2V0IC0tICQodmVyc2lvbnMpCndhbnRlZF9kZXNrdG9wPSQxCndhbnRlZF9tb2JpbGU9JDIKd2FudGVkX2xpbnV4PSQzCmVjaG8gInB1Ymxpc2hlZCBjaGFubmVsOiBkZXNrdG9wICR3YW50ZWRfZGVza3RvcCwgbW9iaWxlICR3YW50ZWRfbW9iaWxlLCBMaW51eCAkd2FudGVkX2xpbnV4IgoKWyAtZCAiJFNJVEUiIF0gfHwgZGllICIkU0lURSBpcyBhYnNlbnQ7IHB1Ymxpc2ggdGhlIHNpdGUgcmVsZWFzZSBmaXJzdCIKCmlmIHBhZ2VfaXNfY3VycmVudCAiJHdhbnRlZF9kZXNrdG9wIiAiJHdhbnRlZF9tb2JpbGUiICIkd2FudGVkX2xpbnV4IiAmJiBwcmV2aWV3X2lzX2N1cnJlbnQ7IHRoZW4KICAgIGVjaG8gInB1YmxpYyBzaXRlIGFscmVhZHkgaW4gc3RlcCIKICAgIFsgIiRDSEVDSyIgLWVxIDEgXSAmJiBleGl0IDAKICAgIHZlcmlmeV9saXZlICIkd2FudGVkX2Rlc2t0b3AiICIkd2FudGVkX21vYmlsZSIgIiR3YW50ZWRfbGludXgiCiAgICBleGl0IDAKZmkKCmlmIFsgIiRDSEVDSyIgLWVxIDEgXTsgdGhlbgogICAgcGFnZV9pc19jdXJyZW50ICIkd2FudGVkX2Rlc2t0b3AiICIkd2FudGVkX21vYmlsZSIgIiR3YW50ZWRfbGludXgiIHx8IGVjaG8gIm91dCBvZiBzdGVwOiAkUFVCTElDX1JPT1Qvc3VuZGF5Lmh0bWwiCiAgICBwcmV2aWV3X2lzX2N1cnJlbnQgfHwgZWNobyAib3V0IG9mIHN0ZXA6ICRQUkVWSUVXIgogICAgZXhpdCAxCmZpCgpiYWNrdXAKc3RhbXBfcGFnZQpzeW5jX3ByZXZpZXcKc3lzdGVtY3RsIGlzLWFjdGl2ZSBjYWRkeS1sYW10b29scyBsYW10b29scy1yZWxheQp2ZXJpZnlfbGl2ZSAiJHdhbnRlZF9kZXNrdG9wIiAiJHdhbnRlZF9tb2JpbGUiICIkd2FudGVkX2xpbnV4Igo='))

assert (ROOT/'desktop-update.json').read_bytes()==(backup/'desktop-update.json').read_bytes() and os.readlink(site_link)==old_site, 'public release changed during transfer; re-inspect before switching'

try:

    next_link.symlink_to(site_dir);next_link.replace(site_link)

    next_latest=ROOT/('Sunday-latest.next-'+STAMP)

    next_latest.symlink_to(names[0]);next_latest.replace(latest_path)

    next_manifest.write_text(json.dumps(new_manifest,ensure_ascii=False,indent=2)+'\n');next_manifest.replace(ROOT/'desktop-update.json')

    subprocess.run(['sh',str(sync_path)],check=True)

    subprocess.run(['sh',str(sync_path),'--check'],check=True)

    # Linux distribution remains on its canonical GitHub release; the website

    # links use the exact version rather than waiting for an unnecessary mirror.

    import re

    for page in pathlib.Path('/var/www/ainarit').rglob('*.html'):

        text=page.read_text()

        for name in names[1:3]:

            text=re.sub(r'(?:https://(?:www[.])?ainarit[.]com)?/downloads/'+re.escape(name),assets[name]['browser_download_url'],text)

        page.write_text(text)

    with urllib.request.urlopen('https://ainarit.com/downloads/desktop-update.json',timeout=30) as response:

        live=json.load(response)

    assert live['version']==VERSION and live['sha256']==manifest['sha256']

    for name in [names[0],'Sunday-latest-x64-setup.exe']:

        request=urllib.request.Request('https://ainarit.com/downloads/'+name,method='HEAD')

        with urllib.request.urlopen(request,timeout=30) as response:assert response.status==200

    print('PUBLISHED',json.dumps({'version':VERSION,'backup':str(backup),'site':str(site_dir),'windows_sha256':manifest['sha256'],'services_changed':False}),flush=True)

except BaseException:

    shutil.copy2(backup/'desktop-update.json',ROOT/'desktop-update.json')

    restore_latest=ROOT/('Sunday-latest.restore-'+STAMP)

    if old_latest is None:

        latest_path.unlink(missing_ok=True)

    elif old_latest[0]=='symlink':

        restore_latest.symlink_to(old_latest[1]);restore_latest.replace(latest_path)

    else:

        os.link(old_latest[1],restore_latest);restore_latest.replace(latest_path)

    next_link.unlink(missing_ok=True);next_link.symlink_to(old_site);next_link.replace(site_link)

    subprocess.run(['tar','-xzf',str(backup/'public-root.tar.gz'),'-C','/var/www'],check=True)

    subprocess.run(['tar','-xzf',str(backup/'preview.tar.gz'),'-C','/var/www'],check=True)

    print('ROLLBACK_RESTORED',str(backup),flush=True)

    raise

