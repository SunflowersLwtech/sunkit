---
name: phone-use
description: >-
  The one manual for phones and emulators, companion detail skill of the `cua`
  router: Android emulator/phone via adb + uiautomator2, iOS Simulator via
  AXe/Appium, real iOS via WebDriverAgent, cloud real devices (BrowserStack,
  AWS Device Farm); element taps, UI tree, Chinese text input, pinch zoom,
  screenshots/recording, app install with hash proof, logs, deep links, mobile
  QA — plus how to tell whether a human is using the device before you touch it.
---

# phone-use — 手机和模拟器

下面的路径都相对本 SKILL.md 所在目录（记作 `scripts/`）。工具链：
[AXe](https://github.com/cameroncooke/AXe)（iOS 模拟器，brew 装）、
[uiautomator2](https://github.com/openatx/uiautomator2)（安卓，经 `uv run` 免安装使用）、
Appium（真机与云）、adb / xcrun simctl。

## 0. 先确认设备是谁的、能不能动

这一步放最前面，因为点错一下就收不回来。

- **别人的真机默认不碰。** 拿到机主明确授权后，动手前仍要确认他此刻没在用；脚本
  层面再设一道闸：`PHONE_USE_REAL_DEVICE_OK=1` 才允许操作真机（`droid.py` 强制检查，
  物理设备不设就退出码 5）。
  - 动手前先看一眼：屏幕是否点亮、前台是什么 App
    （`adb -s <id> shell dumpsys window | grep -E 'mCurrentFocus|mDreamingLockscreen'`）。
    前台是聊天、相册这类私人 App，或 1 分钟内有人在操作，就等几分钟再来，别抢。
  - 只截自己要的 App 的画面；截到别的 App 的私人内容（聊天、邮件、相册）立刻删掉，
    不外发、不写进笔记。读短信验证码可以，只读需要的那一条。
    - **每次截图都和前台检查写在同一条命令里**：先读 `topResumedActivity`，包名不是
      目标 App 就不截。机主随时会拿起手机切走；相机/人脸验证页开着前置摄像头，截图
      会拍到机主的脸。付款、人脸这类环节交给机主本人时，用前台包名轮询等它结束，
      别截图看进度。
  - 不改机主的设置（屏幕超时、通知、账号、安全）；做完把前台恢复成接手时的样子，
    关掉投屏窗口。
  - 锁屏了就停下来交给机主，不要尝试解锁。
  - **判断有没有人正在用**（安卓上实测可靠的读法）：
    - 最近触摸看 `dumpsys power` 的 `lastUserActivityTime=… (N ms ago)`，直接取括号
      里的数。别拿 `/proc/uptime` 去减，两个时钟差着几十秒。
    - 锁屏看 `dumpsys window` 的 `isKeyguardShowing`。
    - 出声看 `dumpsys media.audio_flinger`：各条 `Tracks of which N are active` 的 N
      加起来大于 0 才是真在出声。
    - 亮屏本身不算证据：很多设备充电时常亮。
- **真机上别装包，也别用会动剪贴板/输入法的输入路径。**
  - `adb install` 在不少机型上会弹生物识别确认，要机主本人通过；没人在旁边就一直卡住。
  - uiautomator2 的 `send_keys`：AdbKeyboard 没装时，它把文字写进剪贴板再粘贴，会覆盖
    机主的剪贴板；装了时，它把默认输入法切成 AdbKeyboard 且不切回来。
  - 真机上往输入框填中文，改用元素的 `set_text`：底层是 jsonrpc `setText`，不经过上
    一条的输入法/剪贴板代码。结束后可核对 `settings get secure default_input_method`
    没被换掉。
  - 网页（WebView）里的输入框，`set_text` 可能只改了原生控件、页面没收到：判据是填
    完后出现了对应的联想词，再点搜索。按文字找「搜索」会先命中 text 同样是「搜索」
    的 WebView 节点本身，要限定 class 是 Button。
  - **购物类 App 里只点带文字的元素，结束时数一次购物车。** 按描述点行可能弹「删除」、
    点无文字按钮可能误加购；看商品详情从搜索页进，不从购物车进；开始和结束各读一次
    购物车件数对比。
  - 前台出现别人的账号安全页（两步验证、设备确认之类）就退开：这要机主本人批准——
    不看、不截、不点，也别用别的 App 盖住它；用前台包名轮询，等它离开前台再继续。
- **多个 agent / 会话共用设备时先认领。** 用「认领文件」排队：在共享的临时目录里
  `mkdir <锁目录>/<设备名>`（成功才算拿到，失败隔一会儿重试），里面写上谁、什么
  时候、要干什么；一段操作做完立刻删除释放。这管不住人，只管得住并发的自动化会话
  ——所以真机在使用前仍要走上面的「确认没人在用」。
- **每条命令都要指名设备。** adb 带 `-s`，`droid.py` 带 `-s`，`axe` 带 `--udid`，
  Appium 填 `appium:udid`。「只连着一台设备」从来不是安全假设——随时可能有别的
  会话的模拟器、或机主的真机挂在上面。
  - `droid.py` 只接受 `emulator-N` 序列号。物理设备序列号会返回 exit 5（见 `PHONE_USE_REAL_DEVICE_OK`）。
- **模拟器也可能是别的会话起的。** `adb devices` 或 `xcrun simctl list devices booted`
  里不是你起的那台，就别动它。分清两类：
  - **共享常驻模拟器**（机器上本来就开着的）：借用跑测试，收尾**不要 shutdown**，
    留给下一个任务热态复用——模拟器冷启动一次能吃掉一两分钟的高负载。
  - **自建临时模拟器**：自己 `xcrun simctl create phone-use-<任务名>` 再 `boot` 的，
    收尾 `xcrun simctl shutdown <U> && xcrun simctl delete <U>`。
  - 在已有人用这台机器跑构建/测试时，`xcodebuild test` 建议 `-collect-diagnostics never`：
    UI 测试失败时它默认自动拉起 `simctl diagnose`，能吃满好几个核。
- 别在同一台已经很忙的机器上同时开安卓和 iOS 模拟器：两个模拟器一起启动能把负载
  顶到数十倍。

## 1. 安卓（模拟器优先）

先在 shell 里定义一个函数（zsh 不对 `$VAR` 分词，所以不能写成变量）：

```bash
dr(){ uv run --quiet --with uiautomator2 python -I scripts/droid.py "$@"; }
```

`droid.py` 走 uiautomator2（无需 root、不装 APK：设备端服务推到
`/data/local/tmp/u2.jar` 用 `app_process` 起；只有 `type` 会装一个输入法 APK，见上）。

| 要做的事 | 命令 | 怎么判断真的成功了 |
|---|---|---|
| 读界面树 | `dr -s emulator-5580 ui`（加 `--all` 列出无文字节点） | 每行「中心坐标 \| text \| desc \| id \| class」 |
| 按元素点击 | `dr -s E tap --text 设置`（也支持 `--desc`、`--id`、`--text-contains`） | 找不到元素 exit 1（UiObjectNotFoundError），不会退回去按坐标点 |
| 输入中文 | `dr -s E type '蓝牙设置' --into-id <resource-id> --check` | 会读回那个输入框；读回不含目标文字 exit 3 |
| 双指缩放 | `dr -s E pinch out --percent 80`（缩小 `pinch in`） | 前后各读一次 `visualViewport.scale`（见下面的量法） |
| 双指缩放（Appium/云） | `mobile: pinchOpenGesture` / `pinchCloseGesture`，参数 `{left,top,width,height,percent}` | 同上。云真机用的就是这套协议 |
| 截图 | `adb -s E exec-out screencap -p > s.png` | 多屏设备要加 `-d <display id>` |
| 录屏 | `adb -s E shell screenrecord --time-limit 5 /sdcard/r.mp4`，`pull` 回来，`ffprobe -count_frames` 数帧 | 画面不动时帧数本来就少（3 秒 2 帧正常） |
| 装 APK | `adb -s E install -r x.apk` | `pm path` 找到装好的文件，设备上 `md5sum` 与本地逐字相等。versionName 不能当证据 |
| 看日志 | 先 `adb -s E logcat -c`，跑完 `adb -s E logcat -d -t 500` | — |
| 深链 / 打开网页 | `adb -s E shell am start -a android.intent.action.VIEW -d '<url>' -p <包名>` | 模拟器访问宿主机用 `10.0.2.2`（即宿主的 127.0.0.1） |
| 折叠屏断点 | `adb -s E shell wm size 1080x2520` 测外屏，`wm size reset` 回内屏 | `-no-window` 下 `emu fold`/`unfold` 常常只切 device_state 不改屏幕尺寸，量尺寸要用 `wm size` |

**网页里的元素不要靠界面树判断。** Chrome 的网页内容在 uiautomator 树里时有时无：
同一页面连续多次 dump 都可能没有它；页面一缩放，WebView 节点也会从树里消失。

- 判读网页走 DevTools：`adb -s E forward tcp:9333 localabstract:chrome_devtools_remote`，
  然后 `curl -s 127.0.0.1:9333/json` 拿每个标签页的 `title` 和 `url`。
- 要操作 DOM，用 Appium 切到 `CHROMIUM` 上下文。
- 原生 app 的界面树是稳的。

**缩放怎么量化**：`scripts/` 目录里起 `python3 -m http.server 8765 --bind 127.0.0.1`，
打开 `pinch-probe.html`（安卓经 `http://10.0.2.2:8765/pinch-probe.html`），页面把
`visualViewport.scale` 同时写进 `document.title` 和一个 `/beacon?scale=…` 请求（服务端
回 404 没关系，日志里留痕），从 DevTools `/json` 或服务日志读数。

## 2. iOS 模拟器

工具是 AXe。`U` 是模拟器的 UDID。

| 要做的事 | 命令 | 怎么判断真的成功了 |
|---|---|---|
| 读界面树 | `axe describe-ui --udid U` | 刚 launch 就读会报 `No translation object` 或空 Application 节点，等 2–3 秒再读 |
| 点击 | `axe tap --id <AXUniqueId> --post-delay 0.5 --udid U`（也可 `--label`、`--value`，配 `--element-type` 缩小范围，`--wait-timeout 10` 等元素出现） | **`--post-delay 0.5` 和 `--tap-style physical` 至少带一个**：默认 tap 在新版 Xcode 上会报 ✓ 退出 0 但什么都没点到（AXe #71）。元素不存在 exit 1 |
| 输入英文 | `axe type 'abc' --udid U` | 只能输美式键盘上的字符 |
| 输入中文 | 先点中输入框，再 `scripts/ios-sim-paste.sh U '无线局域网'` | 没有输入框在焦点、或读不回目标文字，exit 3 |
| 双指缩放 | Appium XCUITest 的 `mobile: pinch`，参数 `{elementId, scale: 3, velocity: 2}` | 缩放后 WebView 会从树里消失、旧的 elementId 变 stale，每次缩放前重新取元素；量法同上（iOS 用 `http://127.0.0.1:8765/pinch-probe.html`） |
| 截图 | `axe screenshot --output s.png --udid U` | 别拿 `simctl io screenshot` 当证据：它可能返回很久以前的缓存帧 |
| 录屏 | 后台 `xcrun simctl io U recordVideo --codec h264 --force x.mp4 &`，结束 `kill -INT` | 屏幕上动过的话帧数大于 1 |
| 装 app / 深链 | `xcrun simctl install U X.app`；`xcrun simctl openurl U '<url>'` | `xcrun simctl get_app_container U <bundle id>` 退出 0 说明装上了。模拟器和宿主机共用网络，`127.0.0.1` 直接可达 |

**捏合缩小别拿 Safari 测。** Safari 里捏合缩小会进入标签页总览，页面本身不会缩小。
要测缩小，用自己的 app。

## 3. iOS 真机

- **能可靠自动化的只有 Appium 的 WebDriverAgent 一条路。**
  前置条件：设备已配对、开发者模式已开、自动锁定设成永不、插着电，**而且启动 WDA
  那一刻屏幕必须是解锁的**。WDA 的签名、构建和排障按 Appium XCUITest 文档做。
- WDA 获取（模拟器版；真机版按文档构建签名）：

  ```bash
  appium driver run xcuitest download-wda -- --kind=sim --platform=iOS --outdir=<一个还不存在的目录>
  ```

  旧命令 `download-wda-sim` 已弃用；目录事先存在会直接报错。
- **常驻 WDA 服务（LaunchAgent 之类）别挂着**：XCUITest 会反复占用手机屏幕，机主
  通常反感。按需起，用完立刻停。
- 其它路子（「iPhone 镜像」窗口、各类 phone-use 项目）在近几代 iOS 上没有可靠的后台
  点击：镜像窗口的辅助功能树里手机画面没有任何元素，按进程合成的点击会被吞掉。别
  把时间花在重试上。
- Mac 上「iPhone 镜像」里验证 App 验的是**这台 Mac 的登录用户**，不是手机的；镜像里
  用不了手机相机，扫码只能本人拿手机。手机一被拿起来用，镜像就断开，要等锁屏后重连。

## 4. 云真机

- BrowserStack、AWS Device Farm 都走 Appium/W3C 协议：capabilities 里把本机
  `appium:udid` 换成平台的设备描述（BrowserStack 用 `bstack:options.deviceName`
  + `osVersion` + `realMobile`）。
- `scripts/bs_probe.py` 是最小连通性探针：开一个真机会话、注入 `scripts/pinch-probe.html`、
  读 title 前后变化、做一次双指缩放、打印 contexts 和窗口尺寸，最后关会话。先跑它
  确认账号、设备型号、手势都通，再上真实测试。
- 手势就是 W3C Actions 的双指 pointer 序列（`bs_probe.py` 里有现成写法）；Web 上下文
  切换用 `GET /contexts` + `POST /context`。
- 账号和密钥走你自己的密钥管理（环境变量或 secret 管理），不要写进仓库、脚本或日志。

## 5. Appium（一次性准备）

- `npm i -g appium`，再装驱动：`appium driver install uiautomator2`、
  `appium driver install xcuitest`。服务端：`appium --address 127.0.0.1 --port 4723`。
- capabilities 模板：
  - 安卓：`{"platformName":"Android","appium:automationName":"UiAutomator2","appium:udid":"emulator-5580","appium:noReset":true}`
  - iOS 模拟器：`{"platformName":"iOS","appium:automationName":"XCUITest","appium:udid":"<U>","appium:usePreinstalledWDA":true,"appium:prebuiltWDAPath":"<WDA.app 路径>","appium:noReset":true}`
- Appium 按 id 找元素要写全名：`com.android.chrome:id/url_bar`，只写 `url_bar` 会
  返回 no such element。

## 6. 看起来成功、其实没成功的情况

- **AXe 的 describe-ui 偶尔会重启 testmanagerd**（AXe #76）。这一下会断掉同一台模拟器
  上别人的 XCUITest、WDA 或 Maestro 会话，而且退出码照样是 0。别人正在驱动的模拟器
  上，不要跑 describe-ui。
- **跑过一次 Appium XCUITest 会话之后**，AXe 的 describe-ui 可能一直返回空的
  Application 节点，重启模拟器才恢复。
- **`xcrun simctl pbcopy` 在部分 Xcode 上不写东西**：退出 0 但粘贴板是空的。写剪贴板
  用 `xcrun devicectl device pasteboard copy -d U`；粘贴时 iOS 弹的「Allow Paste」
  `ios-sim-paste.sh` 会替你点掉。
- **Maestro 在多设备时要显式指定设备**：带物理真机时 `--device emulator-<端口>` 也
  可能落到列表里的第一台设备上（Maestro #2167、#2526）——如果第一台是别人的真机，
  就操作到别人手机上去了。
- **uiautomator2 在负载高时报 `RemoteDisconnected`**：设备端服务断开了，重试一次就
  行，不代表元素不存在。
- **坐标会过期。** 屏幕刷新、键盘弹起、折叠姿态变化之后，之前拿到的坐标就不对了，
  所以每点一下都先重新读一次树。

## 7. 收尾：只关自己起的

```bash
adb -s emulator-5580 emu kill
# 自建临时模拟器（自己 simctl create 的）才 shutdown + delete：
xcrun simctl shutdown <U> && xcrun simctl delete <U>
# 借用的共享常驻模拟器不要 shutdown（见 §0）
kill <appium 的 pid>                     # lsof -tiTCP:4723 -sTCP:LISTEN 查
adb -s emulator-5580 forward --remove tcp:9333
```

- 别跑 `adb kill-server`：它会把别人的连接一起断掉。
- 别跑 `emulator -kill` 这类不指名设备的清理命令。
- 起过的 `http.server`、录屏进程、investigate 用的浏览器窗口，用完都关掉。

## 8. 脚本

| 文件 | 用途 |
|---|---|
| `scripts/droid.py` | 安卓元素级操作（uiautomator2 包装：ui / app / tap / type / pinch / shot），强制 `-s`，真机要 `PHONE_USE_REAL_DEVICE_OK=1` |
| `scripts/ios-sim-paste.sh` | 往 iOS 模拟器焦点输入框贴任意 Unicode（含中文）：devicectl 写粘贴板 → Cmd+V → 自动点「Allow Paste」→ 读回验证 |
| `scripts/pinch-probe.html` | 缩放标定页：把 `visualViewport.scale` 写进标题和 beacon 请求 |
| `scripts/bs_probe.py` | BrowserStack 最小连通性探针（开真机会话、注页面、缩放、关会话） |
