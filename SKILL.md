---
name: position-assistant
description: "Portfolio position assistant for Hong Kong stock screening and allocation. Screens HK stocks based on value metrics (PE, PB, dividend yield), calculates position allocation based on PB tiers and the Nine Gods Index (ahr999) for crypto, and generates HTML reports. Use when screening Hong Kong stocks for value investing, analyzing stock portfolio allocation, generating daily stock screening reports, or integrating with OpenClaw cron jobs for automated position analysis."
---

# HK Stock Screener - 港股股票筛选工具

基于价值投资理念的港股筛选工具，结合 PB 估值和九神指数（ahr999）进行仓位管理。

## Features

- **港股筛选**：基于 PE、PB、股息率、市值等指标筛选港股
- **行业分类**：自动行业归类，支持手动映射表修正
- **详细评分**：
  - 前景评分（100分）：ROE、毛利率、营收增长、现金流、负债率
  - 分红评分（100分）：连续分红年数、派息率、增长趋势
- **仓位建议**：
  - 股票仓位：基于平均 PB 的 7 档建议
  - 数字货币仓位：基于九神指数（ahr999）的 7 档建议
- **HTML 报告**：生成美观的筛选报告，支持 Telegram 推送

## Requirements

- Python 3.8+
- pandas
- requests

```bash
pip install pandas requests
```

## Quick Start

1. **获取理杏仁 API Token**
   - 访问 https://www.lixinger.com/open/api
   - 注册并获取 API Token

2. **配置环境变量（推荐）**
   ```bash
   export LIXINGZHE_TOKEN="your_api_token_here"
   export OUTPUT_DIR="./reports"
   ```

3. **或创建配置文件**
   ```bash
   cp scripts/config.example.json scripts/config.json
   # 编辑 config.json 填入你的配置
   ```

4. **运行筛选**
   ```bash
   python3 scripts/position_assistant.py
   ```

## Configuration

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LIXINGZHE_TOKEN` | 理杏仁 API Token | 必填 |
| `CONFIG_PATH` | 配置文件路径 | `config.json` |
| `OUTPUT_DIR` | 报告输出目录 | `./reports` |
| `CACHE_DIR` | 缓存目录 | `./cache` |
| `HTTP_PROXY` | HTTP 代理地址 | 无 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 无 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 无 |

### 配置文件 (config.json)

```json
{
  "api_token": "your_token",
  "proxy": "http://127.0.0.1:7890",
  "telegram": {
    "enabled": true,
    "bot_token": "your_bot_token",
    "chat_id": "your_chat_id"
  },
  "filters": {
    "min_market_cap": 50,
    "max_pe": 15,
    "min_pe": 0.01,
    "max_pb": 1.5,
    "min_pb": 0.01
  },
  "portfolio": {
    "hk_stocks": [
      {"code": "00700", "name": "腾讯控股", "shares": 100, "price_hkd": 400}
    ],
    "a_stocks": [],
    "cash_rmb": 100000,
    "crypto_assets": {
      "usdt": 10000,
      "btc_usd": 50000
    }
  }
}
```

## Screening Criteria

### 初筛条件

- 市值 ≥ 50 亿港元
- 0.01 ≤ PE ≤ 15
- 0.01 ≤ PB ≤ 1.5
- 排除指定股票代码
- 可选：排除本地银行

### 评分维度

| 维度 | 权重 | 指标 |
|------|------|------|
| ROE水平 | 20分 | 最新ROE |
| ROE稳定性 | 10分 | 5年ROE标准差 |
| ROE趋势 | 8分 | 最近3年趋势 |
| 净利率趋势 | 8分 | 最近3年趋势 |
| 净利润CAGR | 10分 | 4年复合增长 |
| 营收CAGR | 10分 | 4年复合增长 |
| 现金流 | 10分 | OCF/净利润 + 趋势 |
| 毛利率 | 14分 | 水平 + 趋势 |
| 负债率 | 10分 | 最新负债率 |

### 分红评分

| 维度 | 权重 | 说明 |
|------|------|------|
| 连续分红年数 | 30分 | 连续分红年限 |
| 派息率合理性 | 30分 | 20%-70%为最佳 |
| 分红增长趋势 | 25分 | 最近3年趋势 |
| 可持续性 | 15分 | 派息率健康度 |

## Position Allocation Rules

### 股票仓位（基于PB）

| PB 区间 | 股票仓位 | 现金仓位 |
|---------|----------|----------|
| < 0.60 | 80% | 20% |
| 0.60 - 0.85 | 70% | 30% |
| 0.85 - 1.15 | 60% | 40% |
| 1.15 - 1.45 | 50% | 50% |
| 1.45 - 1.75 | 40% | 60% |
| 1.75 - 2.00 | 30% | 70% |
| ≥ 2.00 | 20% | 80% |

### 数字货币仓位（基于ahr999九神指数）

| ahr999 区间 | BTC仓位 | 现金仓位 |
|-------------|---------|----------|
| < 0.21 | 80% | 20% |
| 0.21 - 0.315 | 75% | 25% |
| 0.315 - 0.49 | 70% | 30% |
| 0.49 - 0.84 | 60% | 40% |
| 0.84 - 1.26 | 45% | 55% |
| 1.26 - 1.75 | 30% | 70% |
| > 1.75 | 20% | 80% |

## OpenClaw Integration

### Cron Job Setup

```json
{
  "name": "position-assistant",
  "schedule": {"kind": "cron", "expr": "0 3 * * *", "tz": "Asia/Shanghai"},
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Run position assistant: python3 ~/.openclaw/skills/position-assistant/scripts/position_assistant.py",
    "timeoutSeconds": 1200
  }
}
```

## API Data Sources

- **理杏仁 (Lixinger)**: 港股基本面数据、财务报表、分红数据
- **非小号 (Feixiaohao)**: 九神指数 (ahr999)
- **Binance**: BTC 价格数据（备用）
- **汇率 API**: 实时 USD/CNY、HKD/CNY 汇率

## Output

- HTML 报告保存至 `OUTPUT_DIR`（默认 `./reports`）
- 缓存数据保存至 `CACHE_DIR`（默认 `./cache`）
- Telegram 推送（如启用）

## License

MIT
