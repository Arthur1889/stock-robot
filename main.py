import requests
import os
import akshare as ak

# 从你刚刚设置好的 Secrets 中读取凭据
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def get_valuation_data():
    """抓取主流指数估值数据"""
    try:
        # 使用 akshare 获取指数估值
        df = ak.index_value_name_funddb()
        targets = ['沪深300', '中证500', '创业板指', '上证50']
        return df[df['指数名称'].isin(targets)]
    except Exception as e:
        print(f"数据抓取失败: {e}")
        return None

def push_to_telegram(content):
    """通过 Telegram Bot 发送 HTML 格式消息"""
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": content,
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload)

def main():
    data = get_valuation_data()
    if data is not None:
        msg = "<b>📊 A股指数估值日报</b>\n\n"
        for _, row in data.iterrows():
            pe_pct = float(row['市盈率百分位'])
            # 逻辑：低于20%显示绿色✅，高于80%显示警告⚠️
            icon = "✅" if pe_pct < 20 else "⚠️" if pe_pct > 80 else "🔹"
            msg += f"<b>{row['指数名称']}</b>\n"
            msg += f"PE分位：<code>{pe_pct}%</code> {icon}\n"
            msg += f"建议：<u>{row['适宜性']}</u>\n\n"
        
        msg += "<i>自动化推送自 GitHub Actions</i>"
        push_to_telegram(msg)

if __name__ == "__main__":
    main()
