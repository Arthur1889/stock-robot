import requests
import os
import pandas as pd
import akshare as ak

# 从 Secrets 中读取
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def create_bar(pct):
    """创建可视化进度条"""
    length = 10
    filled = int(pct / 10)
    filled = max(0, min(filled, 10)) # 确保在0-10之间
    bar = "🟩" * filled + "⬜" * (length - filled)
    return bar

def get_valuation_logic(pos):
    """模仿螺丝钉的红绿灯逻辑"""
    if pos < 20:
        return "🔴 买入区间 (极度低估)"
    elif pos < 40:
        return "🟡 坚持定投 (偏低估)"
    elif pos > 80:
        return "🔵 卖出区间 (极度高估)"
    else:
        return "⚪ 正常持有 (估值适中)"

def fetch_data(targets):
    results = []
    for name, code in targets.items():
        try:
            # 抓取日线数据
            df = ak.stock_zh_index_daily(symbol=code)
            current_price = df['close'].iloc[-1]
            # 螺丝钉更倾向于参考长期（5年，约1250天）的估值分位
            df_long = df.tail(1250)
            p_min = df_long['close'].min()
            p_max = df_long['close'].max()
            pos = (current_price - p_min) / (p_max - p_min) * 100
            
            bar = create_bar(pos)
            status = get_valuation_logic(pos)
            
            results.append(f"<b>{name}</b>\n<code>{bar}</code> {round(pos, 1)}%\n结果：{status}\n")
        except:
            continue
    return "\n".join(results)

def main():
    if not TG_BOT_TOKEN: return
    
    # 1. 宽基基金监控 (韭圈儿视角)
    broad_targets = {
        "沪深300": "sh000300",
        "创业板指": "sz399006",
        "中证500": "sh000905"
    }
    
    # 2. 螺丝钉精选监控 (偏红利与价值)
    luosiding_targets = {
        "中证红利 (核心收息)": "sh000922",
        "上证红利 (高股息)": "sh000015",
        "恒生指数 (港股低估)": "sh000001" # 备注：此处代码仅作逻辑示例
    }
    
    msg = "<b>📌 综合估值日报 (韭圈儿+银行螺丝钉)</b>\n"
    msg += "━━━━━━━━━━━━━━━\n\n"
    
    msg += "<b>【宽基策略区】</b>\n"
    msg += fetch_data(broad_targets)
    
    msg += "\n<b>【螺丝钉红利精选】</b>\n"
    msg += fetch_data(luosiding_targets)
    
    msg += "\n<i>注：分位基于过去5年历史数据计算。</i>\n"
    msg += "<i>🔴=便宜, ⚪=适中, 🔵=贵</i>"

    # 推送至 TG
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"})

if __name__ == "__main__":
    main()
