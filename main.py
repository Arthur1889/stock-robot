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
    bar = "🟩" * filled + "⬜" * (length - filled)
    return bar

def get_valuation():
    # 参考韭圈儿标准，挑选最主流的基金跟踪指数
    index_list = {
        "沪深300(价值蓝筹)": "sh000300",
        "创业板指(科技成长)": "sz399006",
        "中证500(中小盘)": "sh000905",
        "恒生科技(港股互联网)": "sh000501",
        "纳斯达克(美股科技)": "sh000001", # 示例，实际生产可替换为对应QDII
        "中证白酒(核心消费)": "sz399997"
    }
    
    report = []
    for name, code in index_list.items():
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            current_price = df['close'].iloc[-1]
            
            # 采用3年视角计算分位
            df_3y = df.tail(750)
            p_min = df_3y['close'].min()
            p_max = df_3y['close'].max()
            pos = (current_price - p_min) / (p_max - p_min) * 100
            
            # 图形化展示
            bar = create_bar(pos)
            
            if pos < 20:
                status = "💎 极度低估"
            elif pos > 80:
                status = "🔥 极度高估"
            else:
                status = "⚖️ 估值适中"
            
            item_msg = (
                f"<b>{name}</b>\n"
                f"<code>{bar}</code> {round(pos, 1)}%\n"
                f"状态：{status}\n"
            )
            report.append(item_msg)
        except:
            continue
    return "\n".join(report)

def push_to_tg(content):
    # 如果你想发送图片，通常需要生成本地图片文件。
    # 这里我们使用 Telegram 消息卡片模式，效果接近图片展示。
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": content,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    requests.post(url, json=payload)

def main():
    if not TG_BOT_TOKEN: return
    
    body = get_valuation()
    header = "<b>📊 主流基金/指数估值体检报告</b>\n"
    header += "━━━━━━━━━━━━━━━\n"
    footer = "\n<i>注：进度条越短表示越便宜。数据参考韭圈儿标准。</i>"
    
    push_to_tg(header + body + footer)

if __name__ == "__main__":
    main()
