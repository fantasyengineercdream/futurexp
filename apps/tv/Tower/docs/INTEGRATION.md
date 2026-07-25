# Integration Guide

这份文档给后续接入后端项目或游戏逻辑使用。当前 Demo 已通过同源代理消费
Living World 日循环产品投影；电视与素材仍保持纯静态前端。

## 当前真实接线

```text
POST /api/living-world/day-loop-runs
        ↓
room-bridge.js 校验并映射 0.1 DTO
        ↓
app.js 每 6 秒应用一个展示画面
        ↓
OO / CC 房间在家或外出 + 公共屏奶蛙持续移动
        ↓
POST /api/living-world/day-loop-runs/{runId}/advance
```

前端只读取 `actors`、`timeline`、`event.intents/checks/publicNarrative` 与
`memoryRefs`。五个真实 timeline 阶段中，`in_event` 仅在展示层拆成“各自行动”和
“规则检定”两拍；D20、DC、成功与否全部直接显示后端 DTO，不在前端计算。
`memoryRefs` 只用于确认“有新经历”，前端不会取得记忆正文。前端不解析
Canonical Event、Rule Receipt、StateEffect 或 private OS。API 失败时只进入明确标记的
`PREVIEW · OFFLINE`，不会把 fixture 冒充实时 Agent。

OO / CC 的房间链接统一携带 `runId + residentId + roomId`。房间应用锁定到当前
resident，电视塔不会预取其他 OC 的 POV 或 private OS。电视塔只把已经通过校验的
真实公共投影写入 `sessionStorage`；Room 返回或浏览器 back 后恢复该投影，不会重新
创建 D1。恢复后下一次 `advance` 仍使用原 `runId`。`complete` 阶段恢复 OO / CC
房间入口，确保看完公共结果后可以立即进入房间。

## 入口文件

```text
index.html
styles.css
app.js
```

建议后续接入时，优先改 `app.js` 的数据层和 `selectTv(tv)`，不要先大规模重写 CSS。

## 核心数据模型

当前楼层数据：

```js
{
  name: "SlimeCore",
  y: 380,
  hue: "slime",
  folder: "SlimeCore",
  ids: [1, 2, 3, 4, 7, 8],
  spin: 0.017
}
```

建议后端返回类似结构：

```js
{
  id: "slimecore",
  name: "SlimeCore",
  theme: "slime",
  wallpaperUrl: "/assets/residents/SlimeCore/wallpaper.jpg",
  y: 380,
  spin: 0.017,
  rooms: [
    {
      id: "slimecore-001",
      title: "Moss Garden Slime",
      status: "occupied",
      thumbnailUrl: "/assets/tv-content/SlimeCore/1.png",
      roomUrl: "/rooms/slimecore-001"
    },
    {
      id: "slimecore-empty-001",
      status: "vacant"
    }
  ]
}
```

## 电视生成入口

电视在 `makeTower()` 中生成：

```js
function makeTower() {
  FLOORS.forEach((floor, floorIndex) => {
    ...
  });
}
```

当前每台电视的关键数据来自：

```js
tv.dataset.room = `${floor.name} · R${row + 1}-${col + 1}`;
tv.dataset.variant = floor.hue;
tv.dataset.tv = String(tvIndex % TV_COUNT);
tv.dataset.status = hasResident(row, col, floorIndex) ? "occupied" : "vacant";
```

建议后续补充这些字段：

```js
tv.dataset.floorId = floor.id;
tv.dataset.roomId = room.id;
tv.dataset.roomUrl = room.roomUrl;
tv.dataset.thumbnailUrl = room.thumbnailUrl;
```

## 点击接口

当前点击函数：

```js
function selectTv(tv) {
  selectedTv?.classList.remove("is-selected");
  selectedTv = tv;
  selectedTv.classList.add("is-selected");
  selection.hidden = false;
  selectionName.textContent = tv.dataset.room;
}
```

可以改成：

```js
function selectTv(tv) {
  selectedTv?.classList.remove("is-selected");
  selectedTv = tv;
  selectedTv.classList.add("is-selected");

  const payload = {
    floorId: tv.dataset.floorId,
    roomId: tv.dataset.roomId,
    room: tv.dataset.room,
    status: tv.dataset.status,
    variant: tv.dataset.variant,
    roomUrl: tv.dataset.roomUrl,
  };

  window.dispatchEvent(new CustomEvent("tv-room-selected", { detail: payload }));
}
```

外部项目监听：

```js
window.addEventListener("tv-room-selected", (event) => {
  console.log(event.detail);
  // 打开房间、请求后端、路由跳转等
});
```

如果使用 React/Vue/Svelte，也可以把这个事件桥接到框架状态里。

## 悬停接口

当前 hover 主要由 CSS 控制：

```css
.tv-slot:hover,
.tv-slot.is-selected {
  opacity: 1;
  filter: brightness(1.08) saturate(1) ...;
}
```

如果后续需要鼠标悬停时请求数据，可以在创建电视时添加：

```js
tv.addEventListener("mouseenter", () => {
  window.dispatchEvent(new CustomEvent("tv-room-hover", {
    detail: {
      roomId: tv.dataset.roomId,
      status: tv.dataset.status,
    }
  }));
});
```

注意：不要在 hover 时请求大图。建议只请求轻量 metadata。

## 后端数据接入建议

### 方式 A：启动时一次性加载楼层数据

```js
async function loadFloors() {
  const response = await fetch("/api/tower/floors");
  return await response.json();
}
```

然后用返回值替换 `FLOORS`。

适合：

- 房间数量不大
- 缩略图已经提前生成
- 希望打开页面就看到完整塔

### 方式 B：只加载楼层结构，电视内容按需加载

先加载：

```js
GET /api/tower/floors
```

返回楼层名、wallpaper、电视状态，不返回所有缩略图。

当玩家靠近楼层或 hover 某台电视时再加载：

```js
GET /api/rooms/:roomId/thumbnail
```

适合：

- 房间数量很多
- 后续电视规模继续变大
- 需要更好的性能

## 推荐 API 设计

### 获取楼层

```http
GET /api/tower/floors
```

返回：

```json
[
  {
    "id": "slimecore",
    "name": "SlimeCore",
    "theme": "slime",
    "wallpaperUrl": "/assets/residents/SlimeCore/wallpaper.jpg",
    "y": 380,
    "spin": 0.017
  }
]
```

### 获取某楼层电视

```http
GET /api/tower/floors/slimecore/tvs
```

返回：

```json
[
  {
    "id": "slimecore-r1-c1",
    "row": 1,
    "col": 1,
    "status": "occupied",
    "thumbnailUrl": "/assets/tv-content/SlimeCore/1.png",
    "roomId": "slime-001"
  },
  {
    "id": "slimecore-r1-c2",
    "row": 1,
    "col": 2,
    "status": "vacant"
  }
]
```

### 获取房间详情

```http
GET /api/rooms/slime-001
```

返回：

```json
{
  "id": "slime-001",
  "title": "Moss Garden Slime",
  "floorId": "slimecore",
  "ocImageUrl": "/assets/residents/SlimeCore/1_oc.png",
  "roomImageUrl": "/assets/residents/SlimeCore/1_room.png",
  "thumbnailUrl": "/assets/tv-content/SlimeCore/1.png"
}
```

## 如何增加电视功能

### 增加“进入房间”

在 `selectTv(tv)` 里：

```js
if (tv.dataset.status === "occupied") {
  window.location.href = tv.dataset.roomUrl;
}
```

或：

```js
openRoomModal(tv.dataset.roomId);
```

### 增加“未入驻申请”

```js
if (tv.dataset.status === "vacant") {
  openApplyPanel({
    floorId: tv.dataset.floorId,
    slotId: tv.dataset.slotId,
  });
}
```

### 增加 glitch

低成本做法：继续用 CSS。

```css
.tv-slot:hover .tv-screen {
  animation: glitchFlash 0.4s steps(3) infinite;
}
```

不建议给每台电视使用 canvas 动画，会比较耗性能。

## 素材生成管线

当前 `assets/tv-content` 是预生成的静态图。推荐后续继续保持这种管线：

```text
OC 原图 + 房间原图 -> 后端/脚本合成 4:3 缩略图 -> 前端电视屏幕加载缩略图
```

不要让前端同时加载大尺寸 OC 图和房间图再实时合成。电视数量多时会非常重。

推荐缩略图尺寸：

- `320 x 240`：当前使用，性能好
- `480 x 360`：更清晰，但更重

## 电视型号屏幕位置

当前有 8 种电视框，通过：

```js
tv.dataset.tv = String(tvIndex % TV_COUNT);
```

对应 CSS：

```css
.tv-slot[data-tv="0"] { --screen-x: ... }
...
.tv-slot[data-tv="7"] { --screen-x: ... }
```

如果新增电视框：

1. 放入 `assets/tv-cutout/9.png`
2. 修改 `TV_COUNT`
3. 添加 `.tv-slot[data-tv="8"]` 的屏幕位置参数

## 注意事项

- `floor-panel` 必须在电视外侧：`PANEL_RADIUS > RADIUS`
- 如果玩家主要在塔内部飞，不能把 wallpaper 放到电视内侧
- 电视屏幕内容应使用小图
- 未入驻电视应尽量用 CSS 效果，不要加载占位图片
- CSS 3D 对大量元素有性能上限，如果电视数量继续增加，建议迁移到 Three.js
