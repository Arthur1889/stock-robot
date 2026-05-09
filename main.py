import requests
import os
import pandas as pd
import akshare as ak
from datetime import datetime
from chinese_calendar import is_workday

# 从 Secrets 中读取
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def create_bar(pct):
    length = 10
    filled = int(max(0, min(pct, 100)) / 10)
    return "🟩" * filled + "⬜" * (length - filled)

def get_valuation_logic(pos):
    if pos < 20: return "🔴 买入区间 (极度低估)"
    elif pos < 40: return "🟡 坚持定投 (偏低估)"
    elif pos > 80: return "🔵 卖出区间 (极度高估)"
    return "⚪ 正常持有 (估值适中)"

def fetch_data(targets):
    results = []
    for name, code in targets.items():
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            current_price = df['close'].iloc[-1]
            df_long = df.tail(1250) # 5年视点
            p_min, p_max = df_long['close'].min(), df_long['close'].max()
            pos = (current_price - p_min) / (p_max - p_min) * 100
            results.append(f"<b>{name}</b>\n<code>{create_bar(pos)}</code> {round(pos, 1)}%\n结果：{get_valuation_logic(pos)}\n")
        except: continue
    return "\n".join(results)

def main():
    # --- 核心修改：判断今天是否为交易日 ---
    today = datetime.now()
    # is_workday 结合周六日和法定节假日判断
    if not is_workday(today):
        print(f"今天 {today.strftime('%Y-%m-%d')} 是非交易日/节假日，跳过推送。")
        return

    if not TG_BOT_TOKEN: return
    
    broad_targets = {"沪深300": "sh000300", "创业板指": "sz399006", "中证500": "sh000905"}
    luosiding_targets = {"中证红利": "sh000922", "上证红利": "sh000015", "恒生指数": "sh000001"}
    
    msg = f"<b>📌 股市开仓体检表 ({today.strftime('%m/%d')})</b>\n"
    msg += "━━━━━━━━━━━━━━━\n\n"
    msg += "<b>【宽基策略区】</b>\n" + fetch_data(broad_targets)
    msg += "\n<b>【螺丝钉红利精选】</b>\n" + fetch_data(luosiding_targets)
    
    msg += "\n<b>🔗 外部参考链接</b>\n"
    msg += "👉 <a href='https://weixin.sogou.com/weixin?query=银行螺丝钉'>【银行螺丝钉】最新估值表</a>\n"
    msg += "👉 <a href='https://mp.weixin.qq.com/s/p0eMEsEuUkl57A2ali-dNg'>【韭圈儿】指数估值日报</a>\n"
    msg += "\n<i>🔴=便宜, ⚪=适中, 🔵=贵</i>"

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True})

if __name__ == "__main__":
    main()
