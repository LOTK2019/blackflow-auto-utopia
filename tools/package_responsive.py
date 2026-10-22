"""为已构建的自适应独立版补齐源码、许可和说明，输出完整包。"""
from pathlib import Path
import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blackflow.config import Config


def package(bundle_path='dist-responsive/自动实托邦', output='release/自动实托邦-Windows-自适应独立版.zip', version='v0.1.0', build='20261022-ap-guard'):
    bundle = ROOT / bundle_path
    prior = ROOT / 'dist-standalone-final/自动实托邦'
    for name in ('EXE使用说明.txt', 'LICENSE', 'README.md', '验证记录.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, bundle / name)
    manifest=json.loads((bundle/'_internal/maa/engine.json').read_text(encoding='utf-8'))
    source_name=f"MAA-{manifest['version']}-source.zip"
    shutil.copy2(ROOT/'release'/source_name,bundle/source_name)
    for name in ('N16实托邦实测.png', '独立版验证.json'):
        shutil.copy2(prior / name, bundle / name)
    shutil.copytree(prior / '第三方许可', bundle / '第三方许可', dirs_exist_ok=True)
    (bundle/'第三方许可'/'MAA源码提供说明.txt').write_text(
        f"内置原版 MAA {manifest['version']}，源码见包根目录 {source_name}。\n"
        f"上游来源：{manifest['source_url']}\n提交：{manifest['source_commit']}\n"
        "本项目的增量资源生成与脚本源码见包根目录 源码.zip；许可为AGPL-3.0。\n"
        "N16实托邦实测.png 与 独立版验证.json 为2026-10-21历史版本实测。\n",encoding='utf-8')
    shutil.copy2(ROOT / 'runtime/layout-check.json', bundle / '界面布局验证.json')
    verification=ROOT/'runtime/seed-flow-verification.json'
    if verification.is_file():
        shutil.copy2(verification,bundle/'种植流程验证.json')
        shutil.copy2(ROOT/'artifacts/20261022-141547-429128/001-nodes-1.png',bundle/'有效节点人工核对.png')
    ap_verification=ROOT/'runtime/ap-budget-verification.json'
    if ap_verification.is_file():
        shutil.copy2(ap_verification,bundle/'步数预算验证.json')
    (bundle/'版本信息.json').write_text(json.dumps({'build':build,'version':version,
        'packaged_at':datetime.now().isoformat(),'engine':manifest['version'],
        'movement_budget':'移动前硬过滤','minimum_remaining_ap':1,
        'before_third_floor_exploration_min_ap':2},ensure_ascii=False,indent=2),encoding='utf-8')
    Config().save(bundle / 'config.json')
    source = bundle / '源码.zip'
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for folder in ('blackflow', 'tools', 'tests', 'assets', '.github'):
            for file in (ROOT / folder).rglob('*'):
                if file.is_file() and '__pycache__' not in file.parts:
                    z.write(file, file.relative_to(ROOT).as_posix())
        for file in ROOT.iterdir():
            if file.is_file() and (file.suffix in ('.py', '.ps1', '.spec', '.md', '.txt', '.cmd') or file.name in ('LICENSE', 'config.example.json')):
                z.write(file, file.name)
        z.writestr('config.json', (bundle / 'config.json').read_bytes())
    release = ROOT / output
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in bundle.rglob('*'):
            if file.is_file():
                z.write(file, file.relative_to(bundle.parent).as_posix(),
                        compress_type=zipfile.ZIP_STORED if file.suffix == '.zip' else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(release) as z:
        assert z.testzip() is None
        cfg = json.loads(z.read('自动实托邦/config.json'))
        assert cfg['maa_dir'] == '' and cfg['adb_path'] == '' and cfg['address'] == 'auto'
    print(json.dumps({'release': str(release), 'bytes': release.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', default='dist-responsive/自动实托邦')
    parser.add_argument('--output', default='release/自动实托邦-Windows-自适应独立版.zip')
    parser.add_argument('--version',default='v0.1.0')
    parser.add_argument('--build',default='20261022-ap-guard')
    args = parser.parse_args()
    package(args.bundle, args.output,args.version,args.build)
