import requests
import os
import akshare as ak
import pandas as pd

# 从 Secrets 中读取凭据
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

def get_valuation_data():
    """获取指数估值数据 - 使用最新备用接口"""
    try:
        # 尝试获取主流指数估值（改用最新的指数 PE/PB 列表接口）
        # 这里抓取的是全量数据，我们随后进行筛选
        df = ak.index_value_name_funddb() 
        return df
    except Exception:
        try:
            # 如果上面接口失效，尝试备用接口 (针对沪深300等)
            print("尝试备用接口...")
            df = ak.index_baidue_value_baidu() # 百度股市通接口
            return df
        except Exception as e:
            print(f"所有数据抓取接口均失败: {e}")
            return None

def push_to_telegram(content):
    """通过 Telegram Bot 发送消息"""
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": content,
        "parse_mode": "HTML"
    }
    res = requests.post(url, json=payload)
    print(f"TG 返回结果: {res.text}")

def main():
    # 注意：由于 akshare 接口不稳定，我们这里直接抓取几个代表性宽基
    # 如果想更稳定，我们手动定义关注的几个核心指数
    indices = {
        "沪深300": "sz399300",
        "中证500": "sh000905",
        "创业板指": "sz399006",
        "上证50": "sh000016"
    }
    
    msg = "<b>📊 A股指数估值日报</b>\n\n"
    
    try:
        for name, code in indices.items():
            # 获取单个指数的历史估值
            df = ak.index_value_hist_funddb(symbol=name, indicator="市盈率")
            if not df.empty:
                current_pe = df['市盈率'].iloc[-1]
                # 计算分位数 (简单逻辑：当前值在历史序列中的排名)
                pe_list = df['市盈率'].tolist()
                pe_pct = round(sum(1 for x in pe_list if x < current_pe) / len(pe_list) * 100, 2)
                
                icon = "✅" if pe_pct < 20 else "⚠️" if pe_pct > 80 else "🔹"
                msg += f"<b>{name}</b>\n"
                msg += f"当前PE：<code>{current_pe}</code>\n"
                msg += f"历史分位：<code>{pe_pct}%</code> {icon}\n\n"
        
        msg += "<i>数据更新于: 2026年</i>"
        push_to_telegram(msg)
        print("发送完毕")
    except Exception as e:
        push_to_telegram(f"脚本运行出错: {str(e)}")

if __name__ == "__main__":
    main()
