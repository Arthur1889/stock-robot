import requests
import os
import pandas as pd
import akshare as ak

# 从 Secrets 中读取凭据
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def push_to_telegram(content):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": content, "parse_mode": "HTML"}
    requests.post(url, json=payload, timeout=10)

def get_market_position():
    """
    通过计算当前价格在过去一年（250个交易日）的高低位置来判断水位
    这种方法不依赖专门的估值接口，非常稳健
    """
    # 目标指数：上证指数, 沪深300, 创业板指, 中证500
    targets = {
        "上证指数": "sh000001",
        "沪深300": "sh000300",
        "创业板指": "sz399006",
        "中证500": "sh000905"
    }
    
    results = []
    for name, code in targets.items():
        try:
            # 获取历史行情数据 (这是 akshare 最核心、最不可能挂的接口)
            df = ak.stock_zh_index_daily(symbol=code)
            
            # 取最近一年的数据 (约250个交易日)
            recent_df = df.tail(250)
            current_price = recent_df['close'].iloc[-1]
            min_price = recent_df['close'].min()
            max_price = recent_df['close'].max()
            
            # 计算当前价格在一年内的位置百分比 (0%表示一年最低，100%表示一年最高)
            position_pct = round((current_price - min_price) / (max_price - min_price) * 100, 2)
            
            icon = "✅" if position_pct < 20 else "⚠️" if position_pct > 80 else "🔹"
            results.append(
                f"<b>{name}</b>\n"
                f"当前点位：<code>{round(current_price, 2)}</code>\n"
                f"一年内分位：<code>{position_pct}%</code> {icon}\n"
            )
        except Exception as e:
            print(f"{name} 抓取失败: {e}")
            
    return "\n".join(results)

def main():
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return

    content = get_market_position()
    
    if content:
        final_msg = (
            f"<b>📊 A股指数强弱日报 (一年视角)</b>\n\n"
            f"{content}\n"
            f"<i>注：百分位越低表示离一年内底部越近。</i>"
        )
        push_to_telegram(final_msg)
    else:
        push_to_telegram("今日数据抓取异常，请检查接口。")

if __name__ == "__main__":
    main()
