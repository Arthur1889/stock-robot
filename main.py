import requests
import os
import pandas as pd
import akshare as ak
from datetime import datetime
from chinese_calendar import is_workday

# 从 Secrets 中读取凭据
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def create_bar(pct):
    """创建韭圈儿风格的可视化进度条"""
    length = 10
    filled = int(max(0, min(pct, 100)) / 10)
    return "🟩" * filled + "⬜" * (length - filled)

def get_valuation_status(pos):
    """参考韭圈儿红绿灯逻辑"""
    if pos < 20:
        return "🟢 处于低估 (适合布局)"
    elif pos > 80:
        return "🔴 处于高估 (注意风险)"
    else:
        return "🟡 估值适中 (正常持有)"

def fetch_index_data(targets):
    results = []
    for name, code in targets.items():
        try:
            # 抓取行情数据
            df = ak.stock_zh_index_daily(symbol=code)
            current_price = df['close'].iloc[-1]
            # 韭圈儿通常参考3年(750天)周期
            df_3y = df.tail(750)
            p_min, p_max = df_3y['close'].min(), df_3y['close'].max()
            pos = (current_price - p_min) / (p_max - p_min) * 100
            
            bar = create_bar(pos)
            status = get_valuation_status(pos)
            
            results.append(f"<b>{name}</b>\n<code>{bar}</code> {round(pos, 1)}%\n状态：{status}\n")
        except:
            continue
    return "\n".join(results)

def main():
    # 1. 交易日检查
    today = datetime.now()
    if not is_workday(today):
        print(f"今日 {today.strftime('%Y-%m-%d')} 为非交易日，脚本退出。")
        return

    if not TG_BOT_TOKEN: return

    # 2. 定义韭圈儿核心监控板块
    broad_indices = {
        "沪深300 (白马蓝筹)": "sh000300",
        "创业板指 (科技成长)": "sz399006",
        "中证500 (中小盘)": "sh000905",
        "中证1000 (微盘代表)": "sh000852"
    }
    
    industry_indices = {
        "中证白酒 (消费核心)": "sz399997",
        "半导体指 (硬科技)": "sz399812",
        "恒生科技 (港股互联)": "sh000501"
    }

    # 3. 组装消息
    msg = f"<b>📅 韭圈儿指数估值日报 ({today.strftime('%m/%d')})</b>\n"
    msg += "━━━━━━━━━━━━━━━\n\n"
    
    msg += "<b>【宽基指数】</b>\n" + fetch_index_data(broad_indices)
    msg += "\n<b>【重点行业】</b>\n" + fetch_index_data(industry_indices)
    
    msg += "\n<b>🔗 数据详查</b>\n"
    msg += "👉 <a href='https://mp.weixin.qq.com/s/p0eMEsEuUkl57A2ali-dNg'>点击进入【韭圈儿】官网日报</a>\n"
    
    msg += "\n<i>注：分位基于过去3年历史点位计算。</i>"

    # 4. 发送至 Telegram
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TG_CHAT_ID, 
        "text": msg, 
        "parse_mode": "HTML", 
        "disable_web_page_preview": True
    })

if __name__ == "__main__":
    main()
