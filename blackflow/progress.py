"""保留原生回调中的诊断上下文，避免只报任务链失败。"""
from collections import deque


class WorkerProgress:
    def __init__(self):
        self.task = ""
        self.subtask = ""
        self.floor = None
        self.encounter = ""
        self.options = []
        self.selection = ""
        self.recent = deque(maxlen=12)

    def observe(self, msg, data):
        details = data.get("details") or {}
        task = details.get("task", "")
        if msg in (20001, 20002) and task:
            self.task = task
            if not self.recent or self.recent[-1] != task:
                self.recent.append(task)
        if msg == 20001:
            self.subtask = data.get("subtask", self.subtask)
        what = data.get("what", "")
        if what in ("BlackFlowRoutingDecision", "BlackFlowMapSummary"):
            self.floor = details.get("floor", self.floor)
        if what == "RoguelikeEvent":
            self.encounter = details.get("name", "")
            self.options, self.selection = [], ""
        if what == "RoguelikeEncounterOptions":
            self.options = details.get("options", [])
        if what == "RoguelikeEventSelected":
            self.selection = details.get("option_text", "")

    def summary(self):
        parts = []
        if self.floor is not None:
            parts.append(f"第{self.floor}层")
        if self.encounter:
            parts.append(f"事件={self.encounter}")
        if self.selection:
            parts.append(f"已选={self.selection}")
        if self.task:
            parts.append(f"最后任务={self.task}")
        if self.subtask:
            parts.append(f"子任务={self.subtask}")
        return "；".join(parts) or "尚未收到步骤回调"

    def snapshot(self):
        return {"floor": self.floor, "encounter": self.encounter, "options": self.options,
                "selection": self.selection, "task": self.task, "subtask": self.subtask,
                "recent_tasks": list(self.recent)}
