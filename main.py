import requests
import os
import pandas as pd
import akshare as ak

# 从 Secrets 中读取
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def get_valuation():
    """参考韭圈儿日报，获取核心板块数据"""
    # 模拟韭圈儿的分类：宽基、行业、海外
    index_list = {
        "全A指数(大盘)": "sh000001",
        "沪深300(价值)": "sh000300",
        "创业板指(成长)": "sz399006",
        "恒生科技(港股)": "sh000501", # 示例代码
        "中证白酒(消费)": "sz399997",
        "芯片产业(科技)": "sz399812"
    }
    
    report = []
    for name, code in index_list.items():
        try:
            # 抓取历史日线数据
            df = ak.stock_zh_index_daily(symbol=code)
            current_price = df['close'].iloc[-1]
            
            # 计算3年(750天)的位置，这比1年更具估值参考价值
            df_3y = df.tail(750)
            p_min = df_3y['close'].min()
            p_max = df_3y['close'].max()
            pos = (current_price - p_min) / (p_max - p_min) * 100
            
            # 颜色预警逻辑（参考韭圈儿红绿灯）
            if pos < 20:
                color, icon = "🟢", "<b>[极度低估]</b>"
            elif pos > 80:
                color, icon = "🔴", "<b>[高估风险]</b>"
            else:
                color, icon = "🟡", "<b>[估值适中]</b>"
            
            report.append(f"{color} <b>{name}</b>\n点位: {round(current_price,1)} | 分位: {round(pos,1)}%\n状态: {icon}\n")
        except:
            continue
    return "\n".join(report)

def push_to_tg(content):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": content,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)

def main():
    if not TG_BOT_TOKEN: return
    
    body = get_valuation()
    header = "<b>🔔 指数估值日报 (参考韭圈儿标准)</b>\n"
    footer = f"\n<a href='https://mp.weixin.qq.com/s/p0eMEsEuUkl57A2ali-dNg'>🔗 点击查看完整版图表</a>"
    
    push_to_tg(header + "\n" + body + footer)

if __name__ == "__main__":
    main()
