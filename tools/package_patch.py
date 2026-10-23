"""为已打包的两个版本生成增量覆盖包；不携带个人配置或删除旧文件。"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file,'sha256').hexdigest()


def package_patch(base, target, output, version):
    base,target,output=map(Path,(base,target,output))
    engine='_internal/maa/engine.json'
    if json.loads((base/engine).read_text(encoding='utf-8')) != json.loads((target/engine).read_text(encoding='utf-8')):
        raise ValueError('引擎发生变化，必须使用完整发行包')
    changed={}
    for file in target.rglob('*'):
        if not file.is_file():
            continue
        name=file.relative_to(target).as_posix()
        if name=='config.json':
            continue
        checksum=digest(file)
        old=base/name
        if not old.is_file() or digest(old)!=checksum or name in ('LICENSE','THIRD_PARTY_NOTICES.md','源码.zip'):
            changed[name]=checksum
    assert '自动实托邦.exe' in changed and 'blackflow-worker.exe' in changed
    manifest={'base':'v0.1.0','version':version,'files':changed,
              'configuration_included':False,'engine_changed':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in changed:
            archive.write(target/name,name)
        archive.writestr('patch-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        archive.writestr('补丁使用说明.txt',
            f'{version} 覆盖补丁，适用于已完整解压的 v0.1.0、rc.1/rc.2及v0.1.1目录。\n'
            '请关闭程序及其后台 worker，再把本补丁解压覆盖到原来包含“自动实托邦.exe”的目录。\n'
            '不能在单独的补丁文件夹启动。未安装者先下载 v0.1.0 完整 Windows 包。\n'
            '本补丁不包含 config.json，不覆盖用户数据目录的配置与日志。\n'
            '包括节点统计逐位置跨轮复核，以及奖励Top N、羽蛇四列确认、零动物收获、加载恢复等修正。\n'
            '天马蓝卡单次选择已在真实账户通过；其余回归范围与限制见随包验证记录.md。\n'
            '报错记录位于 %LOCALAPPDATA%\\BlackFlowUtopia\\artifacts\\时间目录\\errors。\n'
            '源码、AGPL许可证及第三方说明随补丁提供；MAA核心未修改，沿用v0.1.0完整包。\n')
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert 'config.json' not in archive.namelist()
        for name,checksum in changed.items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==checksum
    return {'files':len(changed),'bytes':output.stat().st_size,'sha256':digest(output)}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',required=True)
    parser.add_argument('--target',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--version',required=True)
    print(json.dumps(package_patch(**vars(parser.parse_args()))))
