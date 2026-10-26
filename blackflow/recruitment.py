"""只读内置MAA招募结果，执行用户的严格指定约束，不重新识别/点击。

固定引擎的公开回调不含选人名字，名称来自该版本select_oper的原生日志。
按本次日志偏移增量读取；不可读/格式变化时失败关闭，不能猜选人成功。
"""
import re
from pathlib import Path
class NativeRecruitAudit:
 def __init__(self,path,config,phase):
  self.path=Path(path);self.offset=self.path.stat().st_size if self.path.exists() else 0
  self.partial=b'';self.config=config;self.phase=phase;self.index=0;self.selected=[];self.pending=[];self.misses=[]
  self.slots=([['机械师']] if phase=='prepare' else [config.allowed_six(),*[ [n] for n in config.four_stars]] if phase=='formal' else [])
 def expected(self):
  return self.slots[self.index] if self.index<len(self.slots) else None
 def poll(self):
  expected=self.expected()
  if not self.path.exists():return
  size=self.path.stat().st_size
  if size<self.offset:raise RuntimeError('原生招募日志发生轮转，无法核对本次选人，保留现场')
  with self.path.open('rb') as f:f.seek(self.offset);data=f.read();self.offset=f.tell()
  lines=(self.partial+data).split(b'\n');self.partial=lines.pop()
  for raw in lines:
   line=raw.decode('utf-8',errors='replace')
   pick=re.search(r'RoguelikeRecruitTaskPlugin::select_oper \| Choose oper: (.+?) \( elite (\d+) level (\d+) \)',line)
   if pick:
    name=pick[1];self.selected.append(name);self.pending.append(name)
    if expected is not None and name not in expected:raise RuntimeError(f'MAA选人结果不符合指定：需要{expected}，实际选择{name}；已停止并保留现场')
   miss=re.search(r'RoguelikeRecruitTaskPlugin::recruit_appointed_char \| Cannot find oper `(.+?)`',line)
   if miss:
    name=miss[1];self.misses.append(name)
    # 六星允许回退时交给MAA；严格六星、指定四星找不到立即停止，避免默认遍历。
    if expected is not None and name in expected and (self.phase=='prepare' or self.index>0 or len(expected)==1):
     raise RuntimeError(f'MAA遍历后未找到指定干员{name}；可能未拥有、券/希望不符或原生识别失败。已停止并保留现场，不进入默认选人')
 def complete(self):
  self.poll();expected=self.expected()
  if expected is not None and (len(self.pending)!=1 or self.pending[0] not in expected):
   raise RuntimeError(f'MAA未提供可核对的本券选人结果：需要{expected}，结果{self.pending}；保留现场')
  self.pending.clear();self.index+=1
 def snapshot(self):return {'source':'bundled-maa-native-log','selected':self.selected,'missing':self.misses,'completed_slots':self.index}
