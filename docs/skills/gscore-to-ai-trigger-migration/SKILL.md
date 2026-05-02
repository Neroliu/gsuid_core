---
name: gscore-to-ai-trigger-migration
description: >
  批量改造 GsCore 插件的触发器，为 sv.on_xxx 装饰器添加 to_ai 参数，并在数据获取层注入 ai_return() 调用，
  使触发器能被 AI 以 Tool Call 形式调用。适用于所有类型的 GsCore 插件：股票行情、游戏工具、娱乐功能等。
  当用户要求"改造插件触发器支持 AI 调用"、"给触发器加 to_ai"、"让 AI 能调用插件命令"时触发此 SKILL。
---

# GsCore `to_ai` 触发器改造 SKILL

## 一、背景：你要做的事

将现有 GsCore 插件的 `@sv.on_xxx(...)` 装饰器改造为支持 AI Tool Call 调用。
改造后，插件的每个触发器命令：
- **用户直接发命令**：行为完全不变，走原有逻辑
- **AI 调用**：AI 按照 `to_ai` docstring 构建合适的 `text` 参数，触发器在 AI 上下文中执行，`ai_return()` 收集的文本内容返回给 AI 决策

改造涉及**两个独立层**，必须都做：
1. **触发器层**：在 `@sv.on_xxx(...)` 加 `to_ai="..."` 参数
2. **数据/渲染层**：在生成图片/结果前，调用 `ai_return()` 将结构化文本数据注入给 AI

---

## 二、改造前必须理解的核心机制

### 2.1 `to_ai` 参数

```python
# 改造前
@sv.on_command("个股")
async def send_stock_img(bot: Bot, ev: Event):
    ...

# 改造后
@sv.on_command(
    "个股",
    to_ai="""查询指定股票或ETF的K线图或分时图。
    当用户询问某只股票走势、分时图、K线图时调用。

    Args:
        text: 查询内容，格式为 "[周期前缀] 股票名称或代码"
              - 无前缀：默认分时图，例如 "证券ETF"
              - "日k"/"周k"/"月k": K线图，例如 "日k 证券ETF"
              - 多个标的以空格分隔，例如 "证券ETF 白酒ETF"
    """,
)
async def send_stock_img(bot: Bot, ev: Event):
    ...
```

**`to_ai` 的本质**：这段字符串就是 AI 看到的工具 docstring。AI 依据它判断"什么时候调这个工具"以及"text 参数应该填什么"。

### 2.2 `ai_return(text)` 的作用

```python
from gsuid_core.ai_core.trigger_bridge import ai_return
```

- **AI 调用时**：调用 `ai_return("某些文字")` 会将文字收集起来，作为工具的返回值传回给 AI
- **用户直接触发时**：`ai_return()` 什么都不做，完全透明，不影响原有逻辑

**关键原则**：`ai_return()` 应该在**数据已经拿到、图片还没生成时**调用，传递的是结构化的文本数据摘要，让 AI 能够"读懂"这次查询的结果，从而决定如何向用户描述。

### 2.3 `MockBot` 拦截机制（自动处理，开发者无需干预）

当 AI 调用触发器时：
- `bot` 对象被自动替换为 `MockBot`
- `bot.send(bytes)` / `bot.send(Message(type="image"))` → 图片暂存到上下文，不传给 AI 也不发送给用户
- `bot.send(str)` / `bot.send(纯文字 Message)` → 文字被收集，作为工具返回值传回给 AI
- AI 收到工具返回值（含文本描述"已生成 N 张图片"）后，决定是否调用 `send_trigger_images` 发出图片
- 用户直接触发时，`bot` 是真实 `Bot`，`bot.send` 立即发送，行为不变

---

## 三、改造流程

### Step 1：阅读插件代码，识别所有触发器

找出所有 `@sv.on_command/on_prefix/on_fullmatch/on_keyword/on_suffix/on_regex` 装饰器，列出：
- 命令名称（keyword）
- 触发器类型（command/fullmatch/prefix...）
- 函数名
- 函数的实际功能（查什么数据、返回什么）
- 函数从 `ev.text` 里读取的参数格式

### Step 2：为每个触发器撰写 `to_ai` docstring

`to_ai` docstring 必须包含：

```
<一句话功能描述>
<用户在什么场景下会触发这个功能（自然语言描述）>

Args:
    text: <text 参数的完整格式说明，包括：>
          - <基础格式>
          - <可选前缀/后缀>
          - <多个值的分隔方式>
          - <具体例子>
          <如果是 on_fullmatch 且无参数，写"无需参数，留空即可">
```

**撰写要点**：
- 第一句话要让 AI 在自然对话中准确识别意图，要覆盖用户的多种说法
- `text` 的格式说明必须详细到 AI 能直接按说明构建参数，不能有歧义
- 如果命令有多个 keyword（tuple），在描述中提及所有同义叫法
- 不需要描述错误处理逻辑，那是触发器函数自己的事

**不同插件类型的描述风格**：

| 插件类型 | 描述风格示例 |
|---------|------------|
| 股票/行情 | "当用户询问某只股票今日走势、涨跌幅、K线图时调用" |
| 游戏查询 | "当用户查询原神/崩铁等游戏的角色、装备、副本信息时调用" |
| 娱乐功能 | "当用户想要...、请求...、发起...时调用" |
| 绑定/设置 | "当用户要绑定账号/UID/游戏ID时调用" |
| 无参数功能 | "...无需参数，留空即可" |

### Step 3：找出数据层，注入 `ai_return()`

这是改造中**最需要思考**的步骤。

**原则**：找到函数链中"已经拿到原始数据、但还没开始生成图片/发送消息"的那个位置，在那里提取关键信息并调用 `ai_return()`。

**寻找注入点的方法**：

1. 从触发器函数出发，追踪 `render_image()` / `get_data()` 等调用
2. 找到实际获取数据的 `get_xxx()` 函数调用之后、`render_image_by_pw()` / `fig.write_html()` 等生成图片之前的位置
3. 通常这个位置在渲染层的某个 `render_xxx()` 函数内部

**注入位置选择**：

```python
# ✅ 正确：在渲染前注入
async def render_html(market, sector, ...):
    raw_data = await get_xxx(...)   # 数据已拿到

    # 在这里注入 ai_return
    _ai_return_xxx(raw_data)        # ← 注入点

    fig = await to_fig(raw_data)    # 图片生成
    fig.write_html(file)
    return file

# ❌ 错误：在触发器函数内注入（通常拿不到原始数据）
async def send_xxx(bot, ev):
    im = await render_image(...)    # 数据和渲染都在里面，触发器层看不到原始数据
    await bot.send(im)
```

**不同数据类型的提取思路**：

| 数据类型 | 提取什么 |
|---------|---------|
| 股票行情 | 名称、最新价、涨跌幅、开/高/低、换手率、成交额 |
| K线数据 | 名称、周期、最近N条：日期、开/收/高/低、涨跌幅 |
| 排行榜/云图 | 领涨前N、领跌前N、涨/跌/平统计 |
| 游戏角色 | 名称、等级、核心数值、关键属性 |
| 游戏副本/任务 | 名称、进度、完成状态、剩余次数 |
| 娱乐数据 | 核心结果字段 |
| 错误情况 | 错误原因（`ai_return("错误：xxx")`） |

### Step 4：编写 `_ai_return_xxx()` 辅助函数

为每类数据类型各写一个辅助函数：

```python
def _ai_return_xxx(raw_data, ...):
    """从 xxx 数据中提取文本信息，通过 ai_return 返回给 AI 分析"""
    try:
        # 提取关键字段
        # 格式化为可读文本
        # 调用 ai_return(result)
    except Exception as e:
        logger.warning(f"[插件名] ai_return xxx数据提取失败: {e}")
```

**注意**：
- 用 `try/except` 包裹（这里允许，因为这不是业务逻辑，是辅助的观测代码，提取失败不影响图片生成）
- 错误只 `logger.warning`，不影响主流程
- 文本要简洁、结构化，用 `【标题】` 标注分区

---

## 四、完整改造示例（股票插件）

以下是改造前后的完整对比，覆盖了各种情况。

### 4.1 触发器层改造（`__init__.py` 或主逻辑文件）

**改造前：**
```python
from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

sv = SV("大盘云图")

@sv.on_command(("大盘云图"))
async def send_cloudmap_img(bot: Bot, ev: Event):
    im = await render_image("大盘云图", ev.text.strip())
    await bot.send(im)

@sv.on_fullmatch(("我的个股"))
async def send_my_stock_img(bot: Bot, ev: Event):
    uid = await SsBind.get_uid_list_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send("您还未添加自选呢~")
    txt = " ".join(convert_list(uid)[:5])
    im = await render_image(txt, "single-stock")
    await bot.send(im)

@sv.on_command(("个股"))
async def send_stock_img(bot: Bot, ev: Event):
    content = ev.text.strip().lower()
    if not content:
        return await bot.send("请后跟股票代码使用")
    # ... 逻辑 ...
    await bot.send(im)
```

**改造后：**
```python
from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

sv = SV("大盘云图")

@sv.on_command(
    ("大盘云图"),
    to_ai="""查看A股大盘行业板块涨跌分布云图（热力图）。
    当用户询问大盘行情、今日市场整体表现、行业板块涨跌分布、大盘热力图时调用。

    Args:
        text: 可选的板块筛选条件。留空显示全部行业板块的大盘云图。
              例如 "" 或 "医药" 或 "科技"
    """,
)
async def send_cloudmap_img(bot: Bot, ev: Event):
    im = await render_image("大盘云图", ev.text.strip())
    await bot.send(im)


@sv.on_fullmatch(
    ("我的个股"),
    to_ai="""查看用户自选股列表的当日分时行情图。
    当用户询问"我的股票"、"自选股今天怎么样"、"帮我看看我的持仓"时调用。
    无需参数，自动读取当前用户的自选股列表。

    Args:
        text: 无需参数，留空即可
    """,
)
async def send_my_stock_img(bot: Bot, ev: Event):
    user_id = ev.at if ev.at else ev.user_id
    uid = await SsBind.get_uid_list_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send("您还未添加自选呢~或者后跟具体股票代码")
    uid = convert_list(uid)
    if len(uid) > 5:
        uid = uid[:5]
    txt = " ".join(uid)
    im = await render_image(txt, "single-stock")
    await bot.send(im)


@sv.on_command(
    ("个股"),
    to_ai='''查询指定股票或ETF的K线图或分时图。
    当用户询问某只股票/ETF今天走势、分时图、日K、周K、月K时调用。
    支持同时查询多只股票。

    Args:
        text: 查询内容，格式为 "[周期前缀] 股票名称或代码"
              - 无前缀：默认显示分时图，例如 "证券ETF"
              - "日k": 日K线，例如 "日k 证券ETF"
              - "周k": 周K线，例如 "周k 白酒ETF"
              - "月k"/"季k"/"年k": 对应周期K线
              - 多个标的以空格分隔，例如 "证券ETF 白酒ETF"
              - VIX指数：例如 "300vix"（仅支持分时，不支持K线）
    ''',
)
async def send_stock_img(bot: Bot, ev: Event):
    content = ev.text.strip().lower()
    if not content:
        return await bot.send("请后跟股票代码使用, 例如：个股 证券ETF")
    # ... 原有逻辑完全不变 ...
    await bot.send(im)
```

### 4.2 数据/渲染层改造（`get_cloudmap.py` 或渲染文件）

**新增 import：**
```python
from gsuid_core.ai_core.trigger_bridge import ai_return
```

**在 `render_html()` 中的注入点：**
```python
async def render_html(market, sector, start_time, end_time):
    # ... 数据获取逻辑 ...
    raw_data = await get_xxx(...)

    if sector == "single-stock":
        if raw_datas:
            fig = await to_multi_fig(raw_datas)
            _ai_return_single_stock(raw_datas, is_multi=True)   # ← 注入
        else:
            fig = await to_single_fig(raw_data)
            _ai_return_single_stock(raw_data)                    # ← 注入
    elif sector == "compare-stock":
        fig = await to_compare_fig(raw_datas)
        _ai_return_compare_stock(raw_datas)                      # ← 注入
    elif sector and sector.startswith("single-stock-kline"):
        fig = await to_single_fig_kline(raw_data)
        _ai_return_kline(raw_data, sector)                       # ← 注入
    else:
        fig = await to_fig(raw_data, market, sector, ...)
        _ai_return_cloudmap(raw_data, market, sector)            # ← 注入

    # ... 图片生成逻辑 ...
```

**各类辅助函数：**

```python
def _ai_return_single_stock(raw_data, is_multi: bool = False):
    """从个股分时数据中提取文本摘要，通过 ai_return 返回给 AI"""
    try:
        if is_multi:
            parts = []
            for rd in raw_data:
                if isinstance(rd, str):
                    continue
                d = rd.get("data", {})
                name = d.get("f58", "N/A")
                price = d.get("f43", "N/A")
                change = d.get("f170", "N/A")
                turnover = d.get("f168", "N/A")
                open_p = d.get("f60", "N/A")
                high = d.get("f44", "N/A")
                low = d.get("f45", "N/A")
                amount = d.get("f48", "N/A")
                parts.append(
                    f"【{name}】最新价: {price}  涨跌幅: {change}%  "
                    f"开盘: {open_p}  最高: {high}  最低: {low}  "
                    f"换手率: {turnover}%  成交额: {amount}"
                )
            if parts:
                ai_return("【多股分时行情对比】\n" + "\n".join(parts))
        else:
            d = raw_data.get("data", {})
            name = d.get("f58", "N/A")
            price = d.get("f43", "N/A")
            change = d.get("f170", "N/A")
            turnover = d.get("f168", "N/A")
            open_p = d.get("f60", "N/A")
            high = d.get("f44", "N/A")
            low = d.get("f45", "N/A")
            amount = d.get("f48", "N/A")
            ai_return(
                f"【{name} 分时行情】\n"
                f"最新价: {price}  涨跌幅: {change}%\n"
                f"开盘价: {open_p}  最高价: {high}  最低价: {low}\n"
                f"换手率: {turnover}%  成交额: {amount}"
            )
    except Exception as e:
        logger.warning(f"[插件名] ai_return 分时数据提取失败: {e}")


def _ai_return_kline(raw_data, sector: str):
    """从K线数据中提取文本摘要"""
    try:
        d = raw_data.get("data", {})
        name = d.get("name", "N/A")
        klines = d.get("klines", [])
        if not klines:
            return
        period_map = {"101": "日K", "102": "周K", "103": "月K", ...}
        code = sector.replace("single-stock-kline-", "")
        period_name = period_map.get(code, "K线")
        result = f"【{name} {period_name}数据（最近10条）】\n"
        result += "日期        开盘    收盘    最高    最低    涨跌幅\n"
        for line in klines[-10:]:
            values = line.split(",")
            if len(values) >= 9:
                result += f"{values[0]}  {values[1]:>8}  {values[2]:>8}  {values[3]:>8}  {values[4]:>8}  {values[8]:>6}%\n"
        ai_return(result)
    except Exception as e:
        logger.warning(f"[插件名] ai_return K线数据提取失败: {e}")


def _ai_return_cloudmap(raw_data, market: str, sector=None):
    """从大盘/板块云图数据中提取涨跌统计"""
    try:
        diff = raw_data.get("data", {}).get("diff", [])
        if not diff:
            return
        valid_items = [i for i in diff if i.get("f3") != "-" and i.get("f14")]
        valid_items.sort(key=lambda x: float(x.get("f3", 0)), reverse=True)
        result = f"【{market}涨跌分布】\n"
        result += "领涨:\n" + "".join(
            f"  {i.get('f14')}({i.get('f100', '')}): {i.get('f3')}%\n"
            for i in valid_items[:5]
        )
        result += "领跌:\n" + "".join(
            f"  {i.get('f14')}({i.get('f100', '')}): {i.get('f3')}%\n"
            for i in valid_items[-5:]
        )
        up = sum(1 for i in valid_items if float(i.get("f3", 0)) > 0)
        dn = sum(1 for i in valid_items if float(i.get("f3", 0)) < 0)
        fl = len(valid_items) - up - dn
        result += f"统计：上涨 {up} 家  下跌 {dn} 家  平盘 {fl} 家"
        ai_return(result)
    except Exception as e:
        logger.warning(f"[插件名] ai_return 云图数据提取失败: {e}")
```

---

## 五、非股票插件的改造示例

### 5.1 游戏查询插件（有 UID 绑定，返回角色/账号数据）

```python
# 触发器层
@sv_genshin.on_command(
    ("查角色", "角色信息"),
    to_ai="""查询原神游戏中指定角色的详细信息和培养数据。
    当用户询问某个角色的命座、圣遗物、天赋等培养情况时调用。
    需要用户已绑定原神 UID。

    Args:
        text: 角色名称，例如 "雷电将军"、"胡桃"、"纳西妲"
              支持角色昵称，例如 "雷神"、"影"、"小草神"
    """,
)
async def get_char_info(bot: Bot, ev: Event):
    ...
```

```python
# 数据层注入（在拿到角色数据后、生成图片前）
async def render_char_image(uid: str, char_name: str):
    char_data = await fetch_char_data(uid, char_name)

    # AI 注入
    _ai_return_char(char_data, char_name)

    fig = build_char_figure(char_data)
    return await render_image_by_pw(fig)


def _ai_return_char(char_data: dict, char_name: str):
    """提取角色关键数据"""
    try:
        level = char_data.get("level", "N/A")
        const = char_data.get("constellation", 0)
        atk = char_data.get("fight_prop", {}).get("FIGHT_PROP_CUR_ATTACK", "N/A")
        crit_rate = char_data.get("fight_prop", {}).get("FIGHT_PROP_CRITICAL", "N/A")
        crit_dmg = char_data.get("fight_prop", {}).get("FIGHT_PROP_CRITICAL_HURT", "N/A")
        weapon = char_data.get("weapon", {}).get("name", "N/A")
        ai_return(
            f"【{char_name} 角色数据】\n"
            f"等级: {level}  命座: {const}命\n"
            f"攻击力: {atk:.0f}  暴击率: {crit_rate:.1%}  暴击伤害: {crit_dmg:.1%}\n"
            f"武器: {weapon}"
        )
    except Exception as e:
        logger.warning(f"[GenshinUID] ai_return 角色数据提取失败: {e}")
```

### 5.2 无返回数据的写操作（绑定/设置类）

绑定、设置等命令**不需要 `ai_return`**，但触发器本身发送的文字会被 MockBot 收集并返回给 AI：

```python
@sv.on_command(
    ("绑定", "bind"),
    to_ai="""绑定用户的游戏 UID 到账号。
    当用户说"帮我绑定UID"、"我的uid是xxx"、"bind xxx"时调用。

    Args:
        text: 用户的游戏 UID，纯数字，例如 "123456789"
    """,
)
async def bind_uid(bot: Bot, ev: Event):
    uid = ev.text.strip()
    if not uid.isdigit():
        return await bot.send("UID 格式不正确，请输入纯数字")
    await GameDB.bind_uid(ev.user_id, uid)
    await bot.send(f"✅ 已成功绑定 UID: {uid}")
    # bot.send 的文字会被 MockBot 收集，AI 会知道"绑定成功"
```

### 5.3 娱乐/随机类功能

```python
@sv_fun.on_fullmatch(
    ("今日运势", "运势"),
    to_ai="""查看用户今日运势/幸运指数。
    当用户想看今天运势、问今天是否适合做某事时调用。
    无需参数，根据用户 ID 和日期生成唯一结果。

    Args:
        text: 无需参数，留空即可
    """,
)
async def get_fortune(bot: Bot, ev: Event):
    result = calculate_fortune(ev.user_id)
    im = await render_fortune_image(result)
    await bot.send(im)
```

```python
# 渲染层注入
async def render_fortune_image(result: dict):
    _ai_return_fortune(result)   # 注入
    fig = build_fortune_figure(result)
    return await render_image_by_pw(fig)


def _ai_return_fortune(result: dict):
    try:
        score = result.get("score", "N/A")
        lucky_color = result.get("lucky_color", "N/A")
        summary = result.get("summary", "")
        ai_return(
            f"【今日运势】\n"
            f"运势指数: {score}/100\n"
            f"幸运色: {lucky_color}\n"
            f"运势概述: {summary}"
        )
    except Exception as e:
        logger.warning(f"[FunPlugin] ai_return 运势数据提取失败: {e}")
```

---

## 六、不需要改造的触发器

以下类型的触发器**不加 `to_ai`**（保持 `to_ai=""` 默认值）：

| 情况 | 原因 |
|------|------|
| 管理员/超级用户专用命令 | AI 不应绕过权限控制 |
| 系统维护命令（重载、清缓存等） | 危险操作，不开放给 AI |
| 需要多轮交互/Response 会话的命令 | 当前机制不支持多轮 |
| 纯文件上传/接收型命令（`on_file`） | AI 无法构建文件输入 |
| 功能过于单一且 AI 无法获得有效信息的命令 | 改造价值低 |

---

## 七、改造质量检查清单

改造完成后，逐项确认：

**触发器层：**
- [ ] 所有应改造的 `on_xxx` 装饰器都已加 `to_ai` 参数
- [ ] `to_ai` 字符串的第一句话能让 AI 准确识别触发意图
- [ ] `text` 参数格式说明清晰，有具体例子
- [ ] `on_fullmatch` 无参数型已注明"无需参数，留空即可"
- [ ] 多 keyword 的 tuple 形式语法正确：`("命令1", "命令2")`

**数据层：**
- [ ] 已 `from gsuid_core.ai_core.trigger_bridge import ai_return`
- [ ] 每类数据都有对应的 `_ai_return_xxx()` 辅助函数
- [ ] 注入点在数据获取后、图片生成前
- [ ] 辅助函数用 `try/except` 包裹，错误只 `logger.warning`
- [ ] `ai_return` 的文本内容包含足够的关键信息（数字、名称等）
- [ ] 错误分支（如数据为空）也有 `ai_return("错误：...")`

**不破坏性检查：**
- [ ] 原触发器函数体**完全未修改**
- [ ] `ai_return()` 调用在辅助函数里，不在触发器函数里
- [ ] 没有给触发器函数添加任何额外参数

---

## 八、常见问题

**Q：`to_ai` 里能写多长？**
A：建议 5~15 行。太短 AI 无法正确构建参数，太长浪费 Token。核心是把 `text` 参数格式说清楚。

**Q：触发器函数本身有前置检查（如用户未绑定 UID），AI 调用时怎么处理？**
A：不用特殊处理。`bot.send("请先绑定UID")` 会被 MockBot 收集，作为工具返回值的一部分告知 AI，AI 会告诉用户"需要先绑定"。

**Q：某个触发器内部有多条 `await bot.send()`，这些都会被拦截吗？**
A：是的，MockBot 会拦截所有 `bot.send()`。但通常只有最后一条发图，中间的文字 send 也会被收集，AI 可以看到。

**Q：渲染层在另一个文件，我找不到合适的注入点怎么办？**
A：向上追踪调用链，找到 `raw_data = await get_xxx()` 之后的位置即可。如果渲染函数不经过这个流程（比如直接从缓存返回），可以在缓存命中分支之前加。

**Q：`on_prefix` 和 `on_command` 有什么区别，`to_ai` 的写法有不同吗？**
A：`on_prefix` 匹配以 keyword 开头的消息；`on_command` 通常也是前缀匹配但语义是命令。`to_ai` 写法相同，`text` 参数描述的都是命令后面的内容。

**Q：多个触发器共享同一个渲染函数，我只注入一次就够了吗？**
A：是的。只要渲染函数内部按不同分支调用了不同的 `_ai_return_xxx()`，每条触发器路径都会被覆盖。
