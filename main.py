import requests
import os
import pandas as pd
import time

# 从 Secrets 中读取凭据
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def push_to_telegram(content):
    """发送消息到 Telegram"""
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": content,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"发送失败: {e}")

def get_index_valuation():
    """
    使用更稳定的备用数据源
    这里我们改用一个相对稳定的公开数据接口，或者直接抓取基础行情进行模拟估算
    """
    import akshare as ak
    
    # 关注的核心指数
    targets = {
        "沪深300": "000300",
        "中证500": "000905",
        "创业板指": "399006",
        "上证50": "000016"
    }
    
    results = []
    
    # 获取最新的指数估值数据表 (这个接口目前在 akshare v1.13.x+ 是稳定的)
    try:
        # index_value_name_funddb 是目前获取全表最全的接口
        df_all = ak.index_value_name_funddb()
        
        for name, code in targets.items():
            # 在全表中匹配对应的行
            row = df_all[df_all['指数名称'] == name]
            if not row.empty:
                item = row.iloc[0]
                pe = item['市盈率']
                pe_pct = item['市盈率百分位']
                status = item['适宜性']
                
                icon = "✅" if float(pe_pct) < 20 else "⚠️" if float(pe_pct) > 80 else "🔹"
                results.append(f"<b>{name}</b>\n当前PE：<code>{pe}</code>\n历史分位：<code>{pe_pct}%</code> {icon}\n状态：{status}\n")
    except Exception as e:
        return f"数据接口解析失败: {e}"

    return "\n".join(results) if results else "未能抓取到匹配的指数数据"

def main():
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("错误: 未配置 TG_BOT_TOKEN 或 TG_CHAT_ID")
        return

    msg_body = get_index_valuation()
    
    final_msg = f"<b>📊 A股指数估值日报</b>\n\n{msg_body}\n<i>数据来源: 韭圈儿/FundDB</i>"
    
    push_to_telegram(final_msg)

if __name__ == "__main__":
    main()
