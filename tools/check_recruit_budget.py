"""原生ProcessTask次数回归：只有JustReturn/DoNothing，无连接和游戏输入。"""
import ctypes as C
import argparse
import json
import os
from pathlib import Path
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from blackflow.config import Config

c=Config.load()
parser=argparse.ArgumentParser()
parser.add_argument('--limit',type=int,default=40)
parser.add_argument('--reset',type=int,default=40)
args=parser.parse_args()
limit,reset=args.limit,args.reset
assert 1<=reset<=limit<=40
folder=Path(f'runtime/recruit-native-budget-20261025-{limit}-{reset}').resolve()
(folder/'resource/tasks').mkdir(parents=True,exist_ok=True)
cfg=json.loads((Path(c.maa_dir)/'resource/config.json').read_text(encoding='utf-8'))
cfg['options']['taskDelay']=0
(folder/'resource/config.json').write_text(json.dumps(cfg),encoding='utf-8')
p='AutoUtopia@RecruitProbe'
tasks={p+'Tick':{'algorithm':'JustReturn','action':'DoNothing','maxTimes':limit,
                'next':[p+'Tick'],'exceededNext':[p+'TicketB']},
       p+'Stop':{'algorithm':'JustReturn','action':'Stop'}}
for name,next_name in (('TicketA','TicketB'),('TicketB','TicketC'),('TicketC','Stop')):
    tasks[p+name]={'algorithm':'JustReturn','action':'DoNothing','maxTimes':1,
                  'reduceOtherTimes':[p+f'Tick*{reset}'],'next':[p+'Tick'],'exceededNext':[p+next_name]}
(folder/'resource/tasks/tasks.json').write_text(json.dumps(tasks),encoding='utf-8')
events=[]
cbtype=C.CFUNCTYPE(None,C.c_int,C.c_char_p,C.c_void_p)
@cbtype
def callback(msg,data,_):
    events.append((msg,json.loads(data.decode()) if data else {}))
with os.add_dll_directory(c.maa_dir):
    core=C.WinDLL(str(Path(c.maa_dir)/'MaaCore.dll'))
    for name in ('AsstSetUserDir','AsstLoadResource'):
        f=getattr(core,name);f.argtypes=[C.c_char_p];f.restype=C.c_bool
    core.AsstCreateEx.argtypes=[cbtype,C.c_void_p];core.AsstCreateEx.restype=C.c_void_p
    core.AsstAppendTask.argtypes=[C.c_void_p,C.c_char_p,C.c_char_p];core.AsstAppendTask.restype=C.c_int
    core.AsstStart.argtypes=[C.c_void_p];core.AsstStart.restype=C.c_bool
    core.AsstRunning.argtypes=[C.c_void_p];core.AsstRunning.restype=C.c_bool
    core.AsstStop.argtypes=[C.c_void_p];core.AsstDestroy.argtypes=[C.c_void_p]
    assert core.AsstSetUserDir(str(folder).encode())
    assert core.AsstLoadResource(c.maa_dir.encode()) and core.AsstLoadResource(str(folder).encode())
    handle=core.AsstCreateEx(callback,None)
    assert handle
    try:
        assert core.AsstAppendTask(handle,b'Custom',json.dumps({'task_names':[p+'TicketA']}).encode())
        assert core.AsstStart(handle)
        deadline=time.monotonic()+10
        while core.AsstRunning(handle) and time.monotonic()<deadline:
            time.sleep(.02)
        assert not core.AsstRunning(handle),'native test timed out'
    finally:
        core.AsstStop(handle);core.AsstDestroy(handle)
counts=[d['details']['exec_times'] for msg,d in events if msg==20001 and
        d.get('details',{}).get('task','').endswith('RecruitProbeTick')]
assert counts==list(range(1,limit+1))+list(range(limit-reset+1,limit+1))*2,counts
out={'native_counter_reset_passed':True,'per_ticket_ticks':[limit,reset,reset],
     'connected_to_game':False,'game_inputs':False}
(folder/'verification.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out))
