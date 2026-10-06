# 海淘管家（daigou-agent）

日韩代购多Agent协作系统：把"收集表下单 → 物流追踪 → 快照核对 → 国际物流选择 → 海关追踪 → 国内分包 → 用户同步"这条业务链交给 1个主控Agent + 9个专职Agent 协作处理。

## 启动方式

**最简单：双击项目文件夹里的 `启动海淘管家.bat`**，浏览器会自动打开系统。

终端方式（可选）：

```bash
cd D:\wibecoding\daigou-agent
D:\wibecoding\venv\Scripts\activate
streamlit run app.py
```

首次使用：复制 `.env.example` 为 `.env`，填入 API Key（没有 Key 也能用，对应功能自动降级为"手动/待人工"模式）。

## 目录结构

```
app.py                  # 入口：登录 + 页面导航
config/settings.py      # 集中配置（.env、模型端点、业务常量）
db/                     # 数据层：建表、连接、数据访问
tools/                  # 工具层：LLM客户端、网页抓取、图片处理
agents/                 # Agent层：主控(LangGraph) + 各专职Agent
services/               # 业务层：导入、运行日志、总览统计
ui/pages/               # 界面：各功能页面
tests/                  # 单元测试（无需API Key即可运行）
data/                   # 运行时生成：数据库、上传文件（不入库）
logs/                   # 运行时生成：运行日志（不入库）
```

## 开发进度

- [x] P0 骨架+导入：目录结构、SQLite、总览页、收集表导入 + 订单解析Agent + 商品核对（人工登记）
- [x] P1 用户台账：台账Agent + 按用户明细/汇总界面
- [x] P2 物流选择：乐一番7线路知识库（779档阶梯价）+ 物流选择Agent克重区间矩阵
- [x] P3 物流追踪：17TRACK接入 + 追踪Agent（签收联动订单/异常预警）+ 每日巡检
- [x] P4 快照与售后：快照分拣Agent（单号→归属）+ 用户确认登记 + 售后Agent（日韩文翻译）
- [x] P5 分包与话术：打包清单 + 国内发货通知 + 话术中心
- [ ] P6 用户查询端+上云：群友查询页 + 云服务器部署
