# 黑流树海自动实托邦

MuMu / ADB 桌面脚本，复用 MAA 的开局、干员招募、种植、投资、地图和移动逻辑。当前内置 MaaCore v6.20.1 与配套资源，不依赖用户安装的 MAA。所有游戏输入发往 Android，不移动电脑鼠标。

本项目基于 [MaaAssistantArknights（MAA）](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 的代码、核心和任务资源实现，感谢 Maa Team 与所有贡献者。它不是 MAA 官方项目，与鹰角网络亦无隶属关系。

**下载：** [最新 Windows 独立版](https://github.com/LOTK2019/blackflow-auto-utopia/releases/latest)。下载 Release 中的完整 Windows ZIP，不要把 GitHub 自动生成的 Source code ZIP 当作可执行版本。完整解压后运行 `自动实托邦.exe`，不要只复制 EXE。

## 启动

独立版完整解压后双击 **自动实托邦.exe**，不需要 Python 或本地 MAA。配置和日志存放于 `%LOCALAPPDATA%\BlackFlowUtopia`，内置引擎固定使用随包资源。首次请自动发现 MuMu，或手填本机模拟器的 ADB 路径和地址。

源码开发运行可双击 **启动.cmd**，依赖位于 `.venv`。开发模式的引擎目录由 config.json 的 maa_dir 设置；发布版固定使用内置引擎，界面无需配置 MAA 路径。

窗口初始大小按屏幕可用区域和系统缩放设置，避开任务栏。宽窗口同时显示配置和监控；窄窗口切换“开局配置 / 截图与日志”。配置区支持滚动，底部操作按钮始终可见；截图按比例缩放。

识别恢复版：外围截图判断使用统一预算和连续确认，单帧漏识别会重新截图；主题页正常识别一次通过，地图难度两帧一致，实托邦有邦两帧、无邦四帧。MAA 同一会话内按当前事件/招募确认/楼层页面进行有限恢复，保留当前局进度；招募重读不重新调用整个招募插件，事件不能因漏项随意改选。正常路径缩短任务间空闲，保留动作动画与画面确认；异常进入有限恢复。每阶段记录耗时和恢复次数；已通过离线回归及引擎加载检查，账户实测进展与限制见验证记录。

1. 打开 MuMu 中的明日方舟，手动进入 **黑流树海主题主界面**。
2. 点击“自动发现 MuMu”，或手动填入自己模拟器的 ADB 地址、ADB 路径（地址示例：`127.0.0.1:16384`，以实际实例为准）。
3. 先用“仅连接 / 截图诊断”检查画面，再点击“开始自动烧水 / 筛选”。

雷电也可以手动填写 ADB 路径与设备地址，截图 / 点击均使用通用 ADB。“自动发现”目前针对 MuMu。本机实测使用 MuMu，尚未在雷电上进行实测。

开始按钮会结束主题页上尚未完成的探索。识别异常和手动停止会保留当前画面，不自动恢复或放弃；重新开始前请手动回到主题主界面。

需要重建环境时执行 `setup.ps1`。建议使用标准 Windows Python 3.12 x64；部分 Conda 环境加载 MaaCore 时可能出现 DLL 冲突。源码开发还需要从官方 v6.20.1 Windows 发行包准备引擎，见下方“源码运行与构建”。

准备局需要账号已经具备精二机械师及其开局获得结构性原理的天赋。当前账户已实际验证。完整账户测试记录见 [验证记录](验证记录.md)。

## 固定流程

```
准备局 N0：堡垒战术分队 / 坚不可摧 / 自有精二机械师
    → 优先寻找黄商店并尝试种植；飞行保留给黄商店或终点
    → 通过第一层险路尽头
    → 第二层保留安全探索机会，优先黄商店，再通过险路尽头
    → 第三层尝试可行种植，完成或无安全路线时退出结算
正式局：文明开化分队 / 所选难度（默认 N16）
    → 选择开局奖励、组合与三名干员
    → 到第一层立即停止 MAA，检查楼层名左侧图标槽
        有任意实托邦图标：停止，保留正式局
        连续四帧确认无图标：退出，下一轮从准备局开始
        无法确定：报错停止，保留当前局
```

若商店或终点与当前位置直接相连，允许直接进入该目标节点；避免 MAA 只生成徒步候选时被强制飞行规则卡住。

默认正式局组合为 **灵活部署**：结城理（特种）、冬时（先锋）、深海色（辅助）。前端可以修改组合、六星、两名四星、六星备选和助战开关。四星不接受替代；六星允许按配置回退至其他同职业六星。备选同职业是因为使用同一张招募券。

开局奖励提供全部12项，可上移、下移排序。“必须使用第一项”表示至少选中一次第一项；三头犬带来的后续选择继续按排序挑选。第一项缺席时退出正式局并重新准备。

默认开局奖励优先级为：

**空间租赁（容量 +2） > 林间代步（加工品） > 调查预付款（8 源石锭） > 未编号物 / 退行补偿 > 巢寄生（容量 −1）**。

准备方式默认黄商店种植，也可改回绿商店投资。猫、狗、三头犬分别填写数量，0表示不要求，默认全为0。按数量包含关系匹配，顺序无关，允许多出的动物。羽蛇增加的蓝色奖励由开局奖励排序处理。未指定动物时仍会寻找可行黄商店，未收获动物不会单独触发重烧。

黄商店准备在移动前限制行动力预算：至少留下1点，前两层探索还要预留撤离预算；无满足预算的安全路线时结束可选探索，避免耗尽行动力触发追猎。移动仅使用已核对计费的徒步与结构性原理。

第一层有效节点筛选默认关闭；开启后统计除空地外的节点。数量不足则退出正式局并重新准备，数量不明时独立重扫，仍不明则保留现场。

重开冷却沿用 MAA 的 `StartExploreCD`。不设循环次数上限，直到找到实托邦、手动停止或出错时结束。阶段超时默认 900 秒，用于防止界面卡住，可在 `config.json` 修改。

## 实托邦识别

- OCR 用来定位楼层标题；实托邦只判断标题左侧图标槽是否被徽记占用，不要求识别具体图案或类型。
- 有邦须连续两帧确认，无邦须连续四帧确认。一层标题无法识别、布局不符或图案模糊时一律停止。
- 实际自动运行只处理第一层，其他层的样本仅用于识别验证。
- 当前截图坐标基于 MuMu 16:9 横屏，截图自动缩放到 1280×720；不改变模拟器设置。
- 使用了用户提供的雪花、眼睛两种有邦样本和无邦样本，以及本机实际一层无邦截图进行验证。未穷举全部实托邦图案。

## 日志和诊断

每次运行在数据目录的 `artifacts/时间/` 保存阶段状态、MAA 回调、截图和判断数据。MAA 日志在 `runtime/maa-阶段/debug/`。EXE 数据目录为 `%LOCALAPPDATA%\BlackFlowUtopia`，源码运行则在项目目录。

### 错误反馈

请在本仓库 [Issues](https://github.com/LOTK2019/blackflow-auto-utopia/issues) 使用“错误反馈”模板提交，附上程序版本、Windows 版本、模拟器版本、分辨率与缩放、复现步骤，以及预期/实际行为。

发生卡住、招募失败或错误停止时，先停止程序，保留现场。打开 `%LOCALAPPDATA%\BlackFlowUtopia`，将**出问题那次**的 `artifacts/时间目录/` 和对应的 `runtime/maa-prepare/debug/` 或 `runtime/maa-formal/debug/` 压缩后附到 Issue；如果有 `错误详情.log` 也一起提供。仅有顶层异常或一张截图通常不能定位具体步骤。再次运行可能更新 runtime 日志，建议先备份。源码运行的相同目录位于项目根目录。

运行或连接诊断报错时，会在本次 `artifacts/时间目录/errors/` 保存错误界面 PNG 和包含原始异常、当前阶段、截图路径的 JSON，并在界面日志打印位置。若实时截图失败，会记录原因；如有先前成功截图，会以 `last-known` 文件名另存并注明旧图时间，不能把它视为报错瞬间的画面。自动发现失败、程序尚未连接设备或设备断开时可能无法取得实时截图。手动停止不作为报错处理。

羽蛇兼容修正：正式局奖励入口和后续选择依据“选择支援”页标题，支持蓝色奖励页；普通卡增加同优先级的文字识别回退，确认按钮增加文字定位回退。蓝卡修正已通过资源加载和离线回归，尚待真实蓝卡页面复测。

Issues 和附件公开可见：上传前检查配置、截图和日志，遮盖账号信息、用户名、私人路径及其他不愿公开的内容，不要上传登录凭据。不要直接上传整个用户数据目录。

命令行：

```powershell
.\.venv\Scripts\python.exe app.py --diagnose  # 只连接和截图
.\.venv\Scripts\python.exe app.py --run       # 使用配置执行完整循环
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`--phase prepare|formal|abandon` 仅用于开发联调，跳过完整流程的阶段约束。

界面与脚本没有自动升级 MAA。当前已对本机 **MaaCore v6.20.1** 验证。更换 MAA 版本后需要重新核对任务名与资源结构。

## EXE 打包

### 源码运行与构建

```powershell
git clone https://github.com/LOTK2019/blackflow-auto-utopia.git
cd blackflow-auto-utopia
./setup.ps1
# 从 MAA 官方 v6.20.1 Windows x64 Release 下载并完整解压到独立目录。
./.venv/Scripts/python.exe tools/stage_engine.py "C:/path/to/MAA-v6.20.1"
Copy-Item config.example.json config.json
# config.example.json 使用 vendor/maa；如需改动，请使用自己机器的路径。
./.venv/Scripts/python.exe app.py
# 测试（不会操作游戏）
./.venv/Scripts/python.exe -m unittest discover -s tests -v
# 构建可执行文件
./build-exe.ps1
```

MAA 官方固定版本见 [v6.20.1 Release](https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases/tag/v6.20.1)。Git 仓库不包含原生 DLL、模型、个人配置或运行记录；引擎资源在开发构建时准备，完整独立发行包已内置。

使用 `setup.ps1` 准备依赖后，运行 `build-exe.ps1 -MaaSourcePath <已验证的MAA-v6.20.1目录>`，先准备 vendor/maa，再输出到 `dist/自动实托邦/`。核心与配套资源一起发布，收件人不需要本地 MAA。ADB 使用模拟器自己的版本。整个目录一起使用，详情见 `EXE使用说明.txt`。发布时附带对应 MAA 源码和许可文件，不能只发 EXE。

## 参考与许可

- [MaaAssistantArknights 源码](https://github.com/MaaAssistantArknights/MaaAssistantArknights)：`RoguelikeRecruitTaskPlugin.cpp`、`RoguelikeCustomStartTaskPlugin.cpp`、`BlackFlowLifecycleTaskPlugin.cpp`，以及本机 `resource/roguelike/BlackFlow/strategy.json` 与任务资源。
- [PRTS 黑流数据库](https://prts.wiki/w/沉沦者的黑流树海/黑流数据库)：实托邦资料。
- [PRTS 黑流树海](https://prts.wiki/w/沉沦者的黑流树海)：主题机制。

本项目代码按 **AGPL-3.0** 提供，见 `LICENSE`。MAA 代码及原版核心由 Maa Team 和贡献者按其 AGPL-3.0-only 许可提供，独立版附对应 v6.20.1 源码；游戏图像、模型及第三方库按各自许可归各自权利人所有。没有修改用户本地 MAA；增量配置只生成于用户数据目录的 `runtime/`。
