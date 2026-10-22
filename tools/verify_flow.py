r"""账户实测入口。至少完成一次正式局的一层检查后，通过正常停止接口结束测试。

这只是联调脚本；产品中的自动循环没有次数上限。
运行：.venv\Scripts\python.exe -m tools.verify_flow
"""
import json
import sys
import argparse
import threading
from blackflow.config import Config
from blackflow.runner import Runner


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-capacity-once", action="store_true")
    parser.add_argument('--with-nodes',action='store_true')
    args = parser.parse_args()
    config = Config.load()
    if args.with_nodes:
        config.node_filter_enabled=True
        config.min_effective_nodes=1
    if args.require_capacity_once:
        config.reward_target = "空间租赁（背包+2）"
    checked = False
    runner = None

    def log(text):
        nonlocal checked
        print(text, flush=True)
        if "检查第一层实托邦" in text:
            checked = True
        if "没有出现指定的开局奖励" in text:
            runner.config.reward_target = "默认排序"  # 联调只检查一次奖励筛选分支。
        if checked and "轮：准备局" in text:
            runner.stop_now()

    runner = Runner(config, log)

    def commands():
        for line in sys.stdin:
            if line.strip() == "stop":
                runner.stop_now()
                return

    threading.Thread(target=commands, daemon=True).start()
    print("SESSION=" + str(runner.session), flush=True)
    result = runner.run()
    summary = {"result": result, "checked_first_floor": checked, "cycles": runner.cycle,
               "reward_target": config.reward_target, "account_flow_passed": checked and result in ("found", "stopped")}
    (runner.session / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not summary["account_flow_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
