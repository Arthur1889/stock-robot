import requests
import os
import re
import json
import io
import html
import time
from datetime import datetime, timedelta, timezone
import concurrent.futures
import bs4
import pypdf
import pandas as pd
import akshare as ak
from chinese_calendar import is_workday

BEIJING_TZ = timezone(timedelta(hours=8))

def get_beijing_time():
    """获取当前北京时间 (UTC+8)"""
    return datetime.now(BEIJING_TZ)

def is_trading_day(dt):
    """
    精确判断是否为 A股与国内公募基金 交易日：
    1. 周末 (周六、周日) 股市一律不开市 (即使因法定节假日调休补班，股市也坚决休市)；
    2. 法定节假日 (春节、国庆、五一、中秋、端午、清明、元旦) 股市一律休市。
    """
    d = dt.date() if isinstance(dt, datetime) else dt
    if d.weekday() >= 5:
        return False
    return is_workday(d)

# 从环境变量中读取凭据
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://fundf10.eastmoney.com/'
}

# ==================== 原有功能：韭圈儿指数估值 ====================

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

def fetch_single_index(name, code):
    """抓取单只指数行情数据并计算3年历史分位"""
    try:
        if code == 'HSTECH':
            fetch_hk = getattr(ak, 'index_hk_daily_sina', None) or getattr(ak, 'stock_hk_index_daily_sina')
            df = fetch_hk(symbol='HSTECH')
        else:
            fetch_zh = getattr(ak, 'index_zh_daily_sina', None) or getattr(ak, 'stock_zh_index_daily')
            df = fetch_zh(symbol=code)
        
        current_price = df['close'].iloc[-1]
        df_3y = df.tail(750)
        p_min, p_max = df_3y['close'].min(), df_3y['close'].max()
        pos = (current_price - p_min) / (p_max - p_min) * 100
        clean_name = re.sub(r'\s*\(.*?\)', '', name).strip()
        
        return {
            'name': name,
            'clean_name': clean_name,
            'code': code,
            'pos': round(pos, 1),
            'price': current_price,
            'bar': create_bar(pos),
            'status': get_valuation_status(pos)
        }
    except Exception as e:
        print(f"抓取指数 {name} ({code}) 失败: {e}")
        return None

def create_valuation_summary(items):
    """根据核心指数估值分位自动生成每日总结"""
    if not items:
        return ""
    
    low_items = [x for x in items if x['pos'] < 20]
    mid_items = [x for x in items if 20 <= x['pos'] <= 80]
    high_items = [x for x in items if x['pos'] > 80]
    
    avg_pos = sum(x['pos'] for x in items) / len(items)
    min_item = min(items, key=lambda x: x['pos'])
    max_item = max(items, key=lambda x: x['pos'])
    
    # 市场温度与情绪研判
    if avg_pos < 30:
        temp_status = "🟢 整体处于历史偏低估值区间，中长期配置性价比突出"
        advice = "多数核心资产位于价值洼地，建议保持积极心态，逢低分批定投布局。"
    elif avg_pos > 70:
        temp_status = "🔴 整体估值处于偏高水位，需警惕短期高位震荡风险"
        advice = "部分板块估值较为亢奋，建议以稳健持仓为主，注意控制仓位防守。"
    else:
        temp_status = "🟡 整体估值处于合理适中区间，结构性分化较为明显"
        advice = "宽基与行业分化并存，建议采取哑铃策略，侧重低估宽基与高景气龙头均衡配置。"

    summary = "<b>📝 【今日估值每日总结】</b>\n"
    summary += f"• <b>大盘温度</b>：{temp_status}（核心指数平均估值分位 <b>{avg_pos:.1f}%</b>）。\n"
    summary += f"• <b>格局分布</b>：监控的 {len(items)} 个核心板块中，<b>{len(low_items)}</b> 个低估、<b>{len(mid_items)}</b> 个适中、<b>{len(high_items)}</b> 个高估。\n"
    summary += f"• <b>估值洼地</b>：<b>{min_item['clean_name']}</b> 分位仅 <code>{min_item['pos']:.1f}%</code>，处低位布局舒适区。\n"
    summary += f"• <b>估值高位</b>：<b>{max_item['clean_name']}</b> 分位达 <code>{max_item['pos']:.1f}%</code>，注意高位波动与回调风险。\n"
    summary += f"• <b>投资策略</b>：{advice}\n"
    return summary

def generate_valuation_report(today):
    broad_indices = {
        "沪深300 (白马蓝筹)": "sh000300",
        "创业板指 (科技成长)": "sz399006",
        "中证500 (中小盘)": "sh000905",
        "中证1000 (微盘代表)": "sh000852"
    }
    
    industry_indices = {
        "中证白酒 (消费核心)": "sz399997",
        "半导体指 (硬科技)": "sz399812",
        "恒生科技 (港股互联)": "HSTECH"
    }

    # 抓取宽基指数
    broad_results = []
    broad_items = []
    for name, code in broad_indices.items():
        item = fetch_single_index(name, code)
        if item:
            broad_items.append(item)
            broad_results.append(f"<b>{item['name']}</b>\n<code>{item['bar']}</code> {item['pos']}%\n状态：{item['status']}\n")

    # 抓取行业指数
    industry_results = []
    industry_items = []
    for name, code in industry_indices.items():
        item = fetch_single_index(name, code)
        if item:
            industry_items.append(item)
            industry_results.append(f"<b>{item['name']}</b>\n<code>{item['bar']}</code> {item['pos']}%\n状态：{item['status']}\n")

    # 生成开头的每日总结
    all_items = broad_items + industry_items
    daily_summary = create_valuation_summary(all_items)

    session_tag = "早报" if today.hour < 12 else "收盘"
    msg = f"<b>📅 韭圈儿指数估值日报 ({today.strftime('%m/%d')} {session_tag})</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if daily_summary:
        msg += daily_summary + "\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "<b>【宽基指数】</b>\n" + "\n".join(broad_results)
    msg += "\n<b>【重点行业】</b>\n" + "\n".join(industry_results)
    
    msg += "\n<b>🔗 数据详查</b>\n"
    msg += "👉 <a href='https://mp.weixin.qq.com/s/p0eMEsEuUkl57A2ali-dNg'>点击进入【韭圈儿】官网日报</a>\n"
    msg += "\n<i>注：分位基于过去3年历史点位计算。</i>"
    return msg

# ==================== 新增功能：纳斯达克100 QDII 场外指数基金监控 ====================

def is_c_class(name):
    """判断是否为 C 类基金份额 (需排除)"""
    n = name.strip()
    return bool(re.search(r'[Cc](?:类|人民币|\(人民币\)|\(美元\)|份额|$)', n))

FIRM_MAP = {
    '大成': '大成', '华夏': '华夏', '博时': '博时', '南方': '南方',
    '嘉实': '嘉实', '天弘': '天弘', '汇添富': '汇添富', '摩根': '摩根',
    '万家': '万家', '华泰柏瑞': '华泰', '招商': '招商', '宝盈': '宝盈',
    '华安': '华安', '国泰': '国泰', '易方达': '易方达', '广发': '广发',
    '建信': '建信', '富国': '富国', '景顺': '景顺'
}

def clean_fund_name(raw_name):
    """
    规范化纳指基金简称：统一为 {公司}纳指100{份额类别}
    去除冗余的'ETF联接'、'指数证券投资基金'、'发起式'等修饰词，保证整齐直观
    """
    firm = None
    for k in sorted(FIRM_MAP.keys(), key=lambda x: -len(x)):
        if k in raw_name:
            firm = FIRM_MAP[k]
            break
    if not firm:
        firm = raw_name[:2]
    
    m = re.search(r'([A-Za-z])(?:类|人民币|\(人民币\)|\(美元\)|份额|$)', raw_name)
    share_class = m.group(1).upper() if m else 'A'
    return f'{firm}纳指100{share_class}'

def display_width(s):
    """计算包含中英文字符的终端/等宽字体显示宽度 (全角汉字算2，半角字符算1)"""
    w = 0
    for ch in s:
        if '\u4e00' <= ch <= '\u9fff' or '\uff01' <= ch <= '\uffee':
            w += 2
        else:
            w += 1
    return w

def pad_to(s, target_w, align='left'):
    """按显示宽度填充半角空格，确保在等宽字体下精准对齐"""
    w = display_width(s)
    if w >= target_w:
        return s
    pad = ' ' * (target_w - w)
    return (s + pad) if align == 'left' else (pad + s)

def format_limit_cell(desc):
    """
    将限购描述转换为固定宽度单元格，右对齐数值/状态
    例如: '100元' -> '  100元', '10元' -> '   10元', '5元' -> '    5元', '暂停' -> '   暂停'
    在等宽显示下严格占据 7 个半角字符宽度，保证列绝对垂直对齐
    """
    if not desc or '暂停' in desc:
        return '   暂停'
    if '开放' in desc:
        return '   开放'
    if '大额' in desc:
        return '   大额'
    m = re.search(r'(\d+)', desc)
    if m:
        val = int(m.group(1))
        if val >= 10000:
            s_val = f'{val//10000}万'
            return f'   {s_val:>2}元'
        num_str = str(val)
        spaces = ' ' * (5 - len(num_str))
        return f'{spaces}{num_str}元'
    return '   限购'

def is_purchase_notice(title):
    """过滤筛选申购限制、暂停与恢复相关的有效业务公告"""
    t = re.sub(r'\s+', '', title)
    if re.search(r'节假日|境外主要(?:市场|交易市场|投资场所).*(?:暂停|休市)', t):
        return False
    if re.search(r'费率优惠|优惠活动|终止.*销售|分红|定期报告|季度报告|半年度报告|年度报告', t):
        return False
    if re.search(r'恢复申购|暂停.*?申购|大额申购|暂停大额|恢复大额|限制金额|业务限额|申购.*(?:金额|限制|上限)', t):
        return True
    return False

def parse_notice_pdf(ann_id):
    """解析东方财富公告 PDF 文本"""
    try:
        url = f'https://pdf.dfcfw.com/pdf/H2_{ann_id}_1.pdf'
        res = requests.get(url, headers=HEADERS, timeout=6)
        reader = pypdf.PdfReader(io.BytesIO(res.content))
        return '\n'.join([p.extract_text() for p in reader.pages])
    except:
        return ''

def get_direct_limit(code, agency_st, agency_lim, notices):
    """结合官方公告判断直销渠道（基金公司APP/官网）限购情况"""
    if not notices:
        if agency_st == '暂停申购':
            return '暂停申购', 0
        if agency_lim and 0 < agency_lim < 1000000:
            return f'限额{int(agency_lim) if agency_lim == int(agency_lim) else agency_lim}元/天', agency_lim
        return '开放申购', None

    latest = notices[0]
    title = latest['TITLE']

    # 1. 明确暂停申购公告
    if re.search(r'暂停.*?申购', title) and '大额' not in title:
        if '直销' in title and '代销' not in title:
            return '直销暂停申购', 0
        return '暂停申购', 0

    # 2. 明确恢复申购公告
    if '恢复申购' in title and '大额' not in title:
        return '开放申购', None

    # 3. 大额限额公告，解析 PDF 提取直销具体限额规则
    pdf_text = parse_notice_pdf(latest['ID'])
    clean = re.sub(r'\s+', '', pdf_text)

    # 优先匹配针对直销平台的特别限额
    direct_match = re.search(r'直销(?:机构|渠道|平台|柜台).*?(?:不超过|限制(?:调整)?为|限额(?:为)?|高于|上限(?:为)?)([\d,.]+)(?:万|元)?', clean)
    general_match = re.search(r'限制申购.*?金额.*?([\d,.]+)', clean) or re.search(r'(?:不超过|限制(?:调整)?为|限额(?:为)?|高于)([\d,.]+)(?:万|元)', clean)

    amt = None
    if direct_match:
        try: amt = float(direct_match.group(1).replace(',', ''))
        except: pass
    if amt is None and general_match:
        try: amt = float(general_match.group(1).replace(',', ''))
        except: pass

    if amt is not None:
        amt_str = f'{int(amt)}元/天' if amt == int(amt) else f'{amt}元/天'
        return f'限额{amt_str}', amt

    if agency_st == '暂停申购':
        return '暂停申购', 0
    return '限额申购', None

def fetch_fund_fees(code, cached_fees=None):
    """获取基金管理费率、托管费率、销售服务费率，计算综合运营年费率"""
    for url in [f'http://fundf10.eastmoney.com/jbgk_{code}.html', f'http://fundf10.eastmoney.com/jjfl_{code}.html']:
        try:
            res = requests.get(url, headers=HEADERS, timeout=6)
            soup = bs4.BeautifulSoup(res.content.decode('utf-8', errors='ignore'), 'html.parser')
            data = {}
            for tr in soup.find_all('tr'):
                ths = [th.get_text(strip=True) for th in tr.find_all('th')]
                tds = [td.get_text(strip=True) for td in tr.find_all('td')]
                for th, td in zip(ths, tds): data[th] = td
            m = data.get('管理费率', '0.00%').replace('（每年）', '').strip()
            c = data.get('托管费率', '0.00%').replace('（每年）', '').strip()
            s = data.get('销售服务费率', '0.00%').replace('（每年）', '').strip()

            m_val = float(m.replace('%', '')) if '%' in m else 0.0
            c_val = float(c.replace('%', '')) if '%' in c else 0.0
            s_val = float(s.replace('%', '')) if '%' in s else 0.0
            total_op = m_val + c_val + s_val
            if total_op > 0:
                return f'{total_op:.2f}%', m, c, s
        except:
            time.sleep(0.2)
            continue

    if cached_fees and cached_fees[0] not in ['-', '0.00%']:
        return cached_fees
    return '-', '-', '-', '-'

def fetch_qdii_nasdaq_funds(cache_file='qdii_cache.json'):
    """抓取全市场纳斯达克100场外QDII基金信息（排除C类基金）"""
    print("正在拉取纳斯达克100 QDII场外基金目录...")
    r = requests.get('https://fund.eastmoney.com/js/fundcode_search.js', headers=HEADERS, timeout=10)
    match = re.search(r'\[.*\]', r.text)
    funds = json.loads(match.group(0))
    nasdaq = [f for f in funds if ('纳斯达克' in f[2] or '纳指' in f[2]) and '100' in f[2]]
    # 排除纯场内ETF（保留联接基金及场外普通指数基金）
    otc = [f for f in nasdaq if not (f[0].startswith(('15', '51')) and '联接' not in f[2])]
    cny_funds = [f for f in otc if not any(c in f[2] for c in ['美元', '美钞', '美汇'])]
    
    # 核心要求 1：排除掉 C 类基金
    target_funds = [f for f in cny_funds if not is_c_class(f[2])]
    print(f"筛选得到纳斯达克100场外基金共 {len(target_funds)} 只 (已排除所有C类份额)")

    # 读取旧缓存用于重试保底
    old_cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                old_cache = json.load(f)
        except:
            old_cache = {}

    print("正在获取天天基金实时代销申购状态与费率...")
    df_pur = ak.fund_purchase_em()
    pur_map = {}
    for _, row in df_pur[df_pur['基金代码'].isin([f[0] for f in target_funds])].iterrows():
        pur_map[row['基金代码']] = {
            'status': row['申购状态'],
            'limit': row['日累计限定金额'],
            'fee': row['手续费']
        }

    print("正在并发解析直销限额公告及运营费率...")
    def process_fund(fund):
        code, _, name, _, _ = fund
        pur = pur_map.get(code, {})
        agency_st = pur.get('status', '未知')
        agency_lim = pur.get('limit', 0)
        buy_fee = pur.get('fee', 0.0)

        # 代销限额描述
        if agency_st == '暂停申购':
            agency_desc = '暂停申购'
            agency_amt = 0
        elif agency_st in ['限大额', '开放申购']:
            if 0 < agency_lim < 1000000:
                agency_desc = f'限额{int(agency_lim) if agency_lim == int(agency_lim) else agency_lim}元/天'
                agency_amt = agency_lim
            elif agency_st == '开放申购':
                agency_desc = '开放(不限额)'
                agency_amt = 999999999
            else:
                agency_desc = '限大额'
                agency_amt = agency_lim
        else:
            agency_desc = agency_st
            agency_amt = 0

        # 获取官方公告列表
        notices = []
        try:
            url = f'https://api.fund.eastmoney.com/f10/JJGG?fundcode={code}&pageIndex=1&pageSize=15&type=5'
            res = requests.get(url, headers=HEADERS, timeout=5).json()
            items = res.get('Data', [])
            notices = [n for n in items if is_purchase_notice(n['TITLE'])]
        except:
            pass

        direct_desc, direct_amt = get_direct_limit(code, agency_st, agency_lim, notices)

        # 缓存费率备用
        cached_fee_info = None
        if code in old_cache and old_cache[code].get('op_fee') and old_cache[code]['op_fee'] != '-/年':
            cached_fee_info = (old_cache[code]['op_fee'].replace('/年', ''), '-', '-', '-')
        op_total, m_fee, c_fee, s_fee = fetch_fund_fees(code, cached_fee_info)

        # 记录最近3日内新发布的公告
        recent_notices = []
        three_days_ago = (get_beijing_time() - timedelta(days=3)).strftime('%Y-%m-%d')
        for n in notices:
            p_date = n.get('PUBLISHDATEDesc', '')
            if p_date >= three_days_ago:
                recent_notices.append(f"{p_date} {n['TITLE']}")

        return {
            'code': code,
            'name': name,
            'clean_name': clean_fund_name(name),
            'agency': agency_desc,
            'agency_amt': agency_amt,
            'direct': direct_desc,
            'direct_amt': direct_amt or 0,
            'buy_fee': f'{buy_fee:.2f}%' if isinstance(buy_fee, (int, float)) else str(buy_fee),
            'op_fee': f'{op_total}/年',
            'op_detail': f'管{m_fee}+托{c_fee}' + (f'+销{s_fee}' if s_fee != '0.00%' else ''),
            'recent_notices': recent_notices
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(process_fund, target_funds))

    return results

def build_qdii_report(results, today=None, cache_file='qdii_cache.json'):
    """生成汇报消息：先说整体，说今天的变化情况，然后以适合手机阅读的表格与Markdown格式列表展示"""
    if today is None:
        today = get_beijing_time()
    session_tag = "早报" if today.hour < 12 else "收盘"
    today_str = f"{today.strftime('%m/%d')} {session_tag}"
    total_count = len(results)

    # 1. 分类：可申购基金 vs 暂停申购基金
    purchasable = []
    suspended = []

    for r in results:
        can_buy_agency = ('限额' in r['agency'] or '开放' in r['agency'])
        can_buy_direct = ('限额' in r['direct'] or '开放' in r['direct'])
        if can_buy_agency or can_buy_direct:
            purchasable.append(r)
        else:
            suspended.append(r)

    # 可申购基金按最高额度降序排序
    purchasable.sort(key=lambda item: max(item['direct_amt'], item['agency_amt']), reverse=True)
    suspended.sort(key=lambda x: x['code'])

    # 2. 比对缓存获取今日变动
    old_cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                old_cache = json.load(f)
        except:
            old_cache = {}

    changes = []
    for r in results:
        code = r['code']
        if code in old_cache:
            old = old_cache[code]
            c_name = r['clean_name']
            if old.get('agency') != r['agency']:
                changes.append(f"• <b>{c_name}({code})</b>: 代销由 <code>{old.get('agency')}</code> 变为 <code>{r['agency']}</code>")
            if old.get('direct') != r['direct']:
                changes.append(f"• <b>{c_name}({code})</b>: 直销由 <code>{old.get('direct')}</code> 变为 <code>{r['direct']}</code>")
            if old.get('op_fee') != r['op_fee']:
                changes.append(f"• <b>{c_name}({code})</b>: 运营费变更为 <code>{r['op_fee']}</code>")

    # 汇总近2日最新公告
    ann_highlights = []
    seen_ann = set()
    for r in results:
        for ann in r.get('recent_notices', []):
            if ann not in seen_ann:
                seen_ann.add(ann)
                ann_highlights.append(f"📢 <b>{r['clean_name']}</b>: {ann}")

    # 保存今日快照
    new_cache = {
        r['code']: {
            'name': r['name'],
            'agency': r['agency'],
            'direct': r['direct'],
            'buy_fee': r['buy_fee'],
            'op_fee': r['op_fee']
        } for r in results
    }
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(new_cache, f, ensure_ascii=False, indent=2)
    except:
        pass

    # 3. 组装消息 (按整体 -> 今日变化 -> 列表展示)
    msg = f"<b>🇺🇸 纳斯达克100 QDII 场外指数基金日报 ({today_str})</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    # 【先说整体】
    msg += "<b>📊 【整体概况】</b>\n"
    msg += f"• <b>监控范围</b>：共 <b>{total_count}</b> 只场外基金（已剔除所有C类份额）\n"
    msg += f"• <b>申购状态</b>：<b>{len(purchasable)}</b> 只可申购(大多大额限购)，<b>{len(suspended)}</b> 只暂停申购\n"
    if purchasable:
        max_d = max(r['direct_amt'] for r in purchasable)
        max_a = max(r['agency_amt'] for r in purchasable)
        msg += f"• <b>额度极值</b>：代销单日最高 <b>{int(max_a)}元/天</b>，直销单日最高 <b>{int(max_d)}元/天</b>\n"
    msg += "• <b>额度现状</b>：QDII外汇额度整体依然极度紧俏，仅少数基金公司留有少量每日小额申购限额。\n\n"

    # 【说今天的变化情况】
    msg += "<b>⚡ 【今日变化情况】</b>\n"
    if changes:
        msg += "\n".join(changes[:8]) + "\n"
    elif not old_cache:
        msg += "• ℹ️ 首次建立非C类基准快照，明日起将实时对比并汇报额度变动。\n"
    else:
        msg += "• 今日申购状态及限额与昨日持平，暂无最新调整。\n"

    if ann_highlights:
        msg += "<b>最新公告动态：</b>\n" + "\n".join(ann_highlights[:3]) + "\n"
    msg += "\n"

    # 【然后列表展示 - 方便手机阅读的表格与Markdown卡片】
    msg += "<b>📋 【基金限购与费率列表】</b>\n\n"
    
    # 1. 可申购基金紧凑表格 (针对 iPhone 13pm 等手机端屏幕优化，严格定宽对齐且绝不折行)
    msg += "<b>🟢 可申购 / 限额申购基金速览表：</b>\n"
    msg += "<pre>\n"
    msg += "代码   基金简称       代销    直销   运营费\n"
    msg += "----------------------------------------\n"
    for r in purchasable:
        p_name = pad_to(r['clean_name'], 14)
        a_cell = format_limit_cell(r['agency'])
        d_cell = format_limit_cell(r['direct'])
        op = r['op_fee'].replace('/年', '')
        msg += f"{r['code']} {p_name} {a_cell} {d_cell}  {op}\n"
    msg += "</pre>\n\n"

    # 2. 可申购基金逐只详细卡片 (突出直销/代销额度与费率)
    msg += "<b>🔍 可申购基金明细（含申购费与运营明细）：</b>\n"
    for r in purchasable:
        msg += f"<b>• {r['clean_name']}</b> (<code>{r['code']}</code>)\n"
        msg += f"  ├ <b>限购</b>：代销 <code>{r['agency']}</code> ｜ 直销 <code>{r['direct']}</code>\n"
        msg += f"  └ <b>费用</b>：申购 <code>{r['buy_fee']}</code> ｜ 运营 <code>{r['op_fee']}</code> ({r['op_detail']})\n"

    # 3. 暂停申购基金表格清单
    msg += f"\n<b>🔴 暂停申购基金清单 (共 {len(suspended)} 只)：</b>\n"
    msg += "<pre>\n"
    msg += "代码   基金简称       状态     运营费\n"
    msg += "------------------------------------\n"
    for r in suspended:
        p_name = pad_to(r['clean_name'], 14)
        op = r['op_fee'].replace('/年', '')
        msg += f"{r['code']} {p_name} 暂停申购  {op}\n"
    msg += "</pre>\n"

    msg += "\n<i>💡 份额说明：A类为常规前端收费(免销售服务费)；I类为机构/互联网专属低费率份额(0申购费+极低销售服务费)；D类为电子直销定制份额(0申购费+计提销售服务费)。\n注：申购费通常可享代销平台1折优惠(约0.10%-0.12%)。直销限额以基金官方APP为准，代销以天天基金/蚂蚁为准。</i>"
    return msg

# ==================== 新增功能 2：全球主要股指 & 纳指100/标普500 估值日报 ====================

GLOBAL_INDICES_SPEC = [
    # (显示简称, 行情源, 代码, 蛋卷估值代码, Yahoo参考ETF代码)
    ('纳指100', 'us_sina', '.NDX', 'NDX', 'QQQ'),
    ('标普500', 'us_sina', '.INX', 'SP500', 'SPY'),
    ('道琼斯', 'us_sina', '.DJI', None, 'DIA'),
    ('德国DAX', 'em_global', '德国DAX30', 'GDAXI', 'EWG'),
    ('英国富时', 'em_global', '英国富时100', None, 'EWU'),
    ('法国CAC', 'em_global', '法国CAC40', None, 'EWQ'),
    ('欧洲50', 'em_global', '欧洲斯托克50', None, 'FEZ'),
    ('日经225', 'em_global', '日经225', None, 'EWJ'),
    ('印度孟买', 'em_global', '印度孟买SENSEX', '935600', 'INDA'),
    ('韩国综合', 'em_global', '韩国KOSPI', None, 'EWY'),
    ('恒生指数', 'em_global', '恒生指数', 'HKHSI', None),
    ('沪深300', 'em_global', '沪深300', 'SH000300', None),
]

def fetch_danjuan_valuations():
    """从蛋卷估值接口获取核心指数官方 PE/PB/分位/ROE/股息率 及 纳指100/标普500 PE参考线"""
    dj_map = {}
    pe_bands = {}
    headers = {'User-Agent': HEADERS['User-Agent']}
    try:
        res = requests.get('https://danjuanfunds.com/djapi/index_eva/dj', headers=headers, timeout=10).json()
        for it in res.get('data', {}).get('items', []):
            dj_map[it.get('index_code')] = it
    except Exception as e:
        print(f"获取蛋卷全市场估值失败: {e}")

    for code in ['NDX', 'SP500']:
        try:
            res = requests.get(f'https://danjuanfunds.com/djapi/index_eva/pe_history/{code}?day=all', headers=headers, timeout=10).json()
            lines = {ln.get('line_name'): ln.get('line_value') for ln in res.get('data', {}).get('horizontal_lines', [])}
            hist = res.get('data', {}).get('index_eva_pe_growths', [])
            pe_vals = [h['pe'] for h in hist if h.get('pe')]
            pe_bands[code] = {
                'p30': lines.get('30分位值'),
                'p50': lines.get('中位值'),
                'p70': lines.get('70分位值'),
                'min_10y': min(pe_vals) if pe_vals else None,
                'max_10y': max(pe_vals) if pe_vals else None,
            }
        except Exception as e:
            print(f"获取蛋卷 {code} PE历史参考线失败: {e}")

    return dj_map, pe_bands

def fetch_us_10y_yield():
    """获取美国10年期国债收益率 (%) 作为无风险利率基准"""
    try:
        r = requests.get(
            'https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d',
            headers={'User-Agent': HEADERS['User-Agent']},
            timeout=6
        ).json()
        val = r['chart']['result'][0]['meta'].get('regularMarketPrice')
        if val is not None:
            return float(val)
    except Exception:
        pass
    try:
        df_bond = ak.bond_zh_us_yield_em()
        s = df_bond['美国国债收益率10年'].dropna()
        if not s.empty:
            return float(s.iloc[-1])
    except Exception as e:
        print(f"获取10年期美债收益率失败: {e}")
    return None

def fetch_yahoo_etf_pes(symbols):
    """补充获取境外指数对应旗舰 ETF 的 TTM PE (仅作辅助参考)"""
    etf_pe = {}
    syms = [s for s in symbols if s]
    if not syms:
        return etf_pe
    try:
        sess = requests.Session()
        sess.headers.update({'User-Agent': HEADERS['User-Agent']})
        sess.get('https://fc.yahoo.com', timeout=6)
        crumb = sess.get('https://query2.finance.yahoo.com/v1/test/getcrumb', timeout=6).text.strip()
        if crumb and '<' not in crumb:
            url = f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={','.join(syms)}&crumb={crumb}"
            res = sess.get(url, timeout=8).json()
            for q in res.get('quoteResponse', {}).get('result', []):
                if q.get('trailingPE'):
                    etf_pe[q['symbol']] = float(q['trailingPE'])
    except Exception as e:
        print(f"获取Yahoo ETF PE辅助数据失败(不影响主流程): {e}")
    return etf_pe

def calc_pos_5y(series):
    """计算最新点位在近5年(约1250个交易日)历史中的位置分位 (0~100)"""
    s = series.dropna().tail(1250)
    if len(s) < 2:
        return None
    cur = float(s.iloc[-1])
    p_min, p_max = float(s.min()), float(s.max())
    if p_max == p_min:
        return 50.0
    return (cur - p_min) / (p_max - p_min) * 100

def get_global_status_emoji(pe_pct=None, pos_5y=None):
    """根据估值分位(优先)或5年点位分位返回红绿灯标记"""
    metric = pe_pct if pe_pct is not None else pos_5y
    if metric is None:
        return '⚪'
    if metric < 30:
        return '🟢'
    if metric > 70:
        return '🔴'
    return '🟡'

def generate_global_valuation_report(today):
    """生成独立报表3：全世界主要股指估值日报 + 纳斯达克100与标普500深度估值表"""
    session_tag = "早报" if today.hour < 12 else "收盘"
    print("正在拉取全球主要股指行情与估值数据...")

    dj_map, pe_bands = fetch_danjuan_valuations()
    us_10y = fetch_us_10y_yield()

    spot_chg_map = {}
    try:
        df_spot = ak.index_global_spot_em()
        for _, row in df_spot.iterrows():
            spot_chg_map[row['名称']] = float(row['涨跌幅'])
    except Exception as e:
        print(f"获取东财全球指数实时涨跌幅失败: {e}")

    need_etfs = [spec[4] for spec in GLOBAL_INDICES_SPEC if spec[3] is None and spec[4]]
    etf_pe_map = fetch_yahoo_etf_pes(need_etfs)

    def fetch_item(spec):
        label, source, code, dj_code, etf_sym = spec
        price, chg, pos_5y, trade_date = None, None, None, ''
        try:
            if source == 'us_sina':
                df = ak.index_us_daily_sina(symbol=code)
                price = float(df['close'].iloc[-1])
                prev = float(df['close'].iloc[-2])
                chg = (price - prev) / prev * 100
                pos_5y = calc_pos_5y(df['close'])
                trade_date = str(df['date'].iloc[-1])
            else:
                df = ak.index_global_hist_em(symbol=code)
                price = float(df['最新价'].iloc[-1])
                prev = float(df['最新价'].iloc[-2])
                chg = spot_chg_map.get(code, (price - prev) / prev * 100)
                pos_5y = calc_pos_5y(df['最新价'])
                trade_date = str(df['日期'].iloc[-1])
        except Exception as e:
            print(f"抓取全球指数 {label} ({code}) 失败: {e}")

        dj = dj_map.get(dj_code) if dj_code else None
        pe = float(dj['pe']) if dj and dj.get('pe') else etf_pe_map.get(etf_sym)
        pe_pct = float(dj['pe_percentile']) * 100 if dj and dj.get('pe_percentile') is not None else None
        pb = float(dj['pb']) if dj and dj.get('pb') else None
        pb_pct = float(dj['pb_percentile']) * 100 if dj and dj.get('pb_percentile') is not None else None
        roe = float(dj['roe']) * 100 if dj and dj.get('roe') is not None else None
        div_yield = float(dj['yeild']) * 100 if dj and dj.get('yeild') is not None else None
        peg = float(dj['peg']) if dj and dj.get('peg') is not None else None

        return {
            'label': label,
            'dj_code': dj_code,
            'price': price,
            'chg': chg,
            'pos_5y': pos_5y,
            'trade_date': trade_date,
            'pe': pe,
            'pe_pct': pe_pct,
            'pb': pb,
            'pb_pct': pb_pct,
            'roe': roe,
            'div_yield': div_yield,
            'peg': peg,
            'has_index_pe': bool(dj and dj.get('pe')),
        }

    # ak.index_us_daily_sina 内部依赖 py_mini_racer (V8 引擎)，多线程并发易触发段错误，这里按序拉取即可(仅约3秒)
    items = [fetch_item(spec) for spec in GLOBAL_INDICES_SPEC]

    valid_chg = [x for x in items if x['chg'] is not None]
    up_cnt = sum(1 for x in valid_chg if x['chg'] > 0)
    down_cnt = sum(1 for x in valid_chg if x['chg'] < 0)

    ndx = next((x for x in items if x['dj_code'] == 'NDX'), None)
    spx = next((x for x in items if x['dj_code'] == 'SP500'), None)

    # 1. 组装头部与全球市场概览
    msg = f"<b>🌍 全球主要股指 &amp; 美股核心估值日报 ({today.strftime('%m/%d')} {session_tag})</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += "<b>🌐 【全球市场总览】</b>\n"
    msg += f"• <b>涨跌分布</b>：监控 <b>{len(valid_chg)}</b> 个全球主要市场，<b>{up_cnt}</b> 涨 <b>{down_cnt}</b> 跌。\n"
    if us_10y is not None:
        msg += f"• <b>全球定价锚</b>：美国10年期国债收益率 <code>{us_10y:.2f}%</code>。\n"

    # 2. 纳斯达克100 & 标普500 深度估值表
    if ndx and spx:
        def fmt_num(v, fmt='{:.2f}'):
            return fmt.format(v) if v is not None else '-'

        def fmt_pct(v):
            return f'{v:.1f}%' if v is not None else '-'

        def fmt_pe_band(code):
            b = pe_bands.get(code, {})
            if b.get('p30') and b.get('p50') and b.get('p70'):
                return f"{round(b['p30'])}/{round(b['p50'])}/{round(b['p70'])}"
            return '-'

        def fmt_ey(pe):
            return f"{100 / pe:.2f}%" if pe and pe > 0 else '-'

        def fmt_erp(pe):
            if pe and pe > 0 and us_10y is not None:
                return f"{(100 / pe - us_10y):+.2f}%"
            return '-'

        us_rows = [
            ('最新点位', fmt_num(ndx['price']), fmt_num(spx['price'])),
            ('日涨跌幅', f"{ndx['chg']:+.2f}%" if ndx['chg'] is not None else '-', f"{spx['chg']:+.2f}%" if spx['chg'] is not None else '-'),
            ('五年点位', fmt_pct(ndx['pos_5y']), fmt_pct(spx['pos_5y'])),
            ('市盈率PE', fmt_num(ndx['pe']), fmt_num(spx['pe'])),
            ('PE历史分位', fmt_pct(ndx['pe_pct']), fmt_pct(spx['pe_pct'])),
            ('PE30/50/70', fmt_pe_band('NDX'), fmt_pe_band('SP500')),
            ('市净率PB', fmt_num(ndx['pb']), fmt_num(spx['pb'])),
            ('PB历史分位', fmt_pct(ndx['pb_pct']), fmt_pct(spx['pb_pct'])),
            ('ROE回报率', f"{ndx['roe']:.1f}%" if ndx['roe'] is not None else '-', f"{spx['roe']:.1f}%" if spx['roe'] is not None else '-'),
            ('股息率', f"{ndx['div_yield']:.2f}%" if ndx['div_yield'] is not None else '-', f"{spx['div_yield']:.2f}%" if spx['div_yield'] is not None else '-'),
            ('PEG估值', fmt_num(ndx['peg']), fmt_num(spx['peg'])),
            ('盈利收益率', fmt_ey(ndx['pe']), fmt_ey(spx['pe'])),
            ('风险溢价ERP', fmt_erp(ndx['pe']), fmt_erp(spx['pe'])),
        ]

        msg += "\n<b>🇺🇸 【纳指100 &amp; 标普500 估值对比表】</b>\n"
        msg += "<pre>\n"
        msg += f"{pad_to('核心指标', 12)} {pad_to('纳指100', 10, 'right')} {pad_to('标普500', 10, 'right')}\n"
        msg += "-" * 34 + "\n"
        for k, v1, v2 in us_rows:
            msg += f"{pad_to(k, 12)} {pad_to(v1, 10, 'right')} {pad_to(v2, 10, 'right')}\n"
        msg += "</pre>\n"

        # 美股估值简评
        def eva_label(pct):
            if pct is None: return '暂无'
            if pct < 30: return '🟢 偏低估'
            if pct > 70: return '🔴 偏高估'
            return '🟡 适中'

        msg += (
            f"• <b>纳指100</b>：PE <code>{fmt_num(ndx['pe'])}</code> (10年分位 <code>{fmt_pct(ndx['pe_pct'])}</code>，{eva_label(ndx['pe_pct'])})\n"
            f"• <b>标普500</b>：PE <code>{fmt_num(spx['pe'])}</code> (10年分位 <code>{fmt_pct(spx['pe_pct'])}</code>，{eva_label(spx['pe_pct'])})\n"
        )

    # 3. 全世界主要股指估值表
    msg += "\n<b>📊 【全世界主要股指估值速览表】</b>\n"
    msg += "<pre>\n"
    msg += f"{pad_to('全球指数', 9)} {pad_to('涨跌', 7, 'right')} {pad_to('PE', 5, 'right')} 分位/状态\n"
    msg += "-" * 35 + "\n"
    for x in items:
        chg_s = f"{x['chg']:+.2f}%" if x['chg'] is not None else '-'
        pe_s = f"{x['pe']:.1f}" if x['pe'] is not None else '-'
        emoji = get_global_status_emoji(x['pe_pct'], x['pos_5y'])
        if x['pe_pct'] is not None:
            stat_s = f"PE{x['pe_pct']:>2.0f}% {emoji}"
        elif x['pos_5y'] is not None:
            stat_s = f"位{x['pos_5y']:>2.0f}% {emoji}"
        else:
            stat_s = f" -   {emoji}"
        msg += f"{pad_to(x['label'], 9)} {pad_to(chg_s, 7, 'right')} {pad_to(pe_s, 5, 'right')} {stat_s}\n"
    msg += "</pre>\n"

    msg += (
        "\n<i>注：1) 纳指100/标普500/德国DAX/印度/恒生/沪深300 的PE与分位采自蛋卷近10年指数估值口径；"
        "其余市场展示5年点位分位，PE参考其海外旗舰ETF口径。\n"
        "2) 🟢代表分位&lt;30%偏低，🟡为30%~70%适中，🔴为&gt;70%偏高；ERP = 盈利收益率(1/PE) - 10年期美债收益率。</i>"
    )
    return msg

# ==================== 新增功能 3：国内外偏股市政策与宏观风向日报 ====================

NEWS_NOISE_RE = re.compile(
    r'见闻历|神历|会员|课程|优惠|点击|风险提示|快评|专题片|今晚播出|致信祝贺|复信|贺电|友谊|文艺|联欢|天气预报|'
    r'文化情缘|的来信|结束出访|回到北京|抵达.*出席|宣讲团|防长|国防部长|召回|爱泼斯坦|甲醛|烹饪协会|'
    r'13F|段永平|捐股|AI央行|知乎|声网|短剧|整点回顾|盘中涨超|临停'
)
# 海外央行利率、通胀、贸易管制与影响全球股市定价的政策
INTL_MARKET_POLICY_RE = re.compile(
    r'美联储|鲍威尔|哈马克|威廉姆斯|沃勒|古尔斯比|卡什卡利|FOMC|利率决议|点阵图|缩表|加息|降息|'
    r'欧央行|日本央行|日央行|英国央行|瑞士央行|强美元|弱美元|美元流动性|美债收益率|美债|'
    r'关税|出口管制|芯片限制|贸易战|贸易协议|制裁|财政刺激|债务上限|白宫|特朗普.*(?:关税|贸易|美联储|加息|降息)|'
    r'通胀|PCE|非农|(?:美国|日本|欧元区|欧洲|中国)(?:CPI|PPI|GDP|失业率|经济)'
)
# 国内直接影响 A股/港股走势的金融监管、货币与财政产业政策
DOMESTIC_MARKET_POLICY_RE = re.compile(
    r'人民银行|中国央行|央行.*(?:降|利率|货币|流动性|再贷款)|降准|LPR|MLF|逆回购|再贷款|互换便利|'
    r'证监会|金监总局|中长期资金|长线资金|资本市场|并购重组|市值管理|退市|分红新规|IPO节奏|'
    r'财政部|国家发改委|发改委|工信部|商务部|国常会|政治局.*经济|中央经济工作会议|特别国债|化债|赤字|稳增长|促消费|以旧换新|房地产.*(?:政策|金融)|专项债|'
    r'中加经济财金|本币使用|出口管制.*(?:中方|商务部|外交部)'
)
# 市场资金面与核心主线风向
MARKET_FLOW_RE = re.compile(
    r'宽基ETF|ETF|成交额|放量|沪深300|创业板指|科创50|恒指|恒科指|纳指|标普|芯片|半导体|台积电|英伟达|AI|国债|原油|黄金|瑞银|高盛|大摩|摩根大通|德银|中国股票'
)

def _clean_news_text(text, max_len=90):
    """清理新闻文本中的冗余前缀与空白，并安全裁剪长度"""
    t = re.sub(r'\s+', ' ', str(text or '')).strip()
    t = re.sub(r'^【.*?】\s*', '', t)
    t = re.sub(r'^(?:财联社|新华网|央视新闻|中新网)\d{1,2}月\d{1,2}日电[，,]\s*', '', t)
    if len(t) > max_len:
        t = t[:max_len - 1] + '…'
    return t

def _is_similar(clean, seen_texts):
    """检查核心6字短语或数字实体重合，避免同一新闻跨源重复"""
    norm = re.sub(r'[^\w\u4e00-\u9fff]', '', clean)
    if not norm:
        return False
    ngrams = [norm[i:i+6] for i in range(0, max(1, len(norm) - 5))]
    tokens = re.findall(r'[A-Za-z0-9]{4,}', clean)
    for prev in seen_texts:
        if any(g in prev for g in ngrams):
            return True
        if any(tok in prev for tok in tokens):
            return True
    return False

def _dedup_append(bucket, text, seen_texts, limit):
    """去重与降噪添加条目"""
    if len(bucket) >= limit:
        return
    clean = _clean_news_text(text)
    if not clean or len(clean) < 10 or NEWS_NOISE_RE.search(clean):
        return
    norm = re.sub(r'[^\w\u4e00-\u9fff]', '', clean)
    if not norm or _is_similar(clean, seen_texts):
        return
    seen_texts.append(norm)
    bucket.append(clean)

def fetch_cctv_policy_headlines(today):
    """仅从《新闻联播》筛选直接涉及经济/金融/财政/资本市场政策的要闻"""
    econ_kw = re.compile(r'经济|金融|货币|财政|央行|证监会|国务院常务|政治局|发改委|外资|关税|贸易|民营经济|国债|消费')
    for delta in [0, 1, 2, 3]:
        d_str = (today - timedelta(days=delta)).strftime('%Y%m%d')
        try:
            df = ak.alternative_news_cctv(date=d_str)
            if df is not None and not df.empty:
                hits = [str(t) for t in df['title'].tolist() if t and econ_kw.search(str(t)) and not NEWS_NOISE_RE.search(str(t))]
                return d_str, hits
        except Exception:
            continue
    return None, []

def fetch_cjzc_sections():
    """拉取东方财富《财经早餐》每日精选与环球市场要闻"""
    sections = {'每日精选': [], '环球市场': []}
    try:
        df = ak.stock_news_cjzc_em()
        if df is None or df.empty:
            return sections
        url = df.iloc[0]['链接']
        res = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=8)
        soup = bs4.BeautifulSoup(res.content.decode('utf-8', errors='ignore'), 'html.parser')
        body = soup.find('div', id='ContentBody') or soup.find('div', class_='txtinfos')
        if not body:
            return sections

        cur_sec = ''
        buf_title = ''
        for el in body.find_all(['h3', 'p']):
            if el.name == 'h3':
                cur_sec = el.get_text(strip=True)
                buf_title = ''
            elif el.name == 'p' and cur_sec in sections:
                txt = re.sub(r'\s+', ' ', el.get_text(strip=True))
                if not txt or '点击' in txt or '风险提示' in txt:
                    continue
                if txt.endswith(('：', ':')) and len(txt) < 35:
                    buf_title = txt.rstrip('：:')
                else:
                    merged = f"{buf_title}：{txt}" if buf_title else txt
                    sections[cur_sec].append(merged)
                    buf_title = ''
    except Exception as e:
        print(f"抓取东方财富财经早餐失败: {e}")
    return sections

def fetch_wscn_policy_feeds():
    """拉取华尔街见闻全球头条及美股/A股/全球频道快讯"""
    articles, lives = [], []
    headers = {'User-Agent': HEADERS['User-Agent']}
    try:
        r1 = requests.get(
            'https://api-one.wallstcn.com/apiv1/content/fabricate-articles?channel=global&limit=35',
            headers=headers, timeout=8
        ).json()
        for it in r1.get('data', {}).get('items', []):
            res_obj = it.get('resource') or {}
            title = it.get('title') or res_obj.get('title', '')
            if title:
                articles.append(title)
    except Exception as e:
        print(f"抓取华尔街见闻全球头条失败: {e}")

    for ch in ['global-channel', 'us-stock-channel', 'a-stock-channel']:
        try:
            r2 = requests.get(
                f'https://api-one.wallstcn.com/apiv1/content/lives?channel={ch}&limit=60',
                headers=headers, timeout=8
            ).json()
            for it in r2.get('data', {}).get('items', []):
                score = it.get('score', 1)
                txt = (it.get('title') or it.get('content_text') or '').strip()
                if txt and not txt.startswith('提醒：'):
                    lives.append((score, txt))
        except Exception as e:
            print(f"抓取华尔街见闻 {ch} 失败: {e}")
    return articles, lives

def generate_macro_news_report(today):
    """生成独立报表4：国内外偏股市政策与宏观风向日报"""
    session_tag = "早报" if today.hour < 12 else "收盘"
    print("正在汇聚国内外偏股市核心政策与宏观风向...")

    cctv_date, cctv_econ = fetch_cctv_policy_headlines(today)
    cjzc_sections = fetch_cjzc_sections()
    wscn_articles, wscn_lives = fetch_wscn_policy_feeds()

    em_titles = []
    try:
        df_em = ak.stock_news_global_em()
        if df_em is not None and not df_em.empty:
            em_titles = [str(r['标题']) for _, r in df_em.head(150).iterrows()]
    except Exception as e:
        print(f"获取东财全球财经快讯失败: {e}")

    cls_items = []
    try:
        df_cls = ak.stock_news_global_cls(symbol='重点')
        if df_cls is not None and not df_cls.empty:
            cls_items = [str(r['标题'] or r['内容']) for _, r in df_cls.iterrows()]
    except Exception as e:
        print(f"获取财联社重点快讯失败: {e}")

    sorted_lives = [txt for _, txt in sorted(wscn_lives, key=lambda x: -x[0])]
    red_lives = [txt for sc, txt in sorted(wscn_lives, key=lambda x: -x[0]) if sc >= 2]
    all_pool = wscn_articles + sorted_lives + em_titles + cjzc_sections.get('每日精选', []) + cjzc_sections.get('环球市场', [])

    overseas_policy = []
    domestic_policy = []
    market_focus = []
    seen = []

    # 1. 海外货币利率、通胀与贸易政策 (美联储、欧日央行、关税/出口管制)
    for t in all_pool:
        if INTL_MARKET_POLICY_RE.search(t):
            _dedup_append(overseas_policy, t, seen, 6)

    # 2. 国内金融监管、货币与财政产业政策 (央行、证监会、财政部、发改委、资本市场改革)
    for t in cjzc_sections.get('每日精选', []) + wscn_articles + sorted_lives + em_titles + cctv_econ:
        if DOMESTIC_MARKET_POLICY_RE.search(t):
            _dedup_append(domestic_policy, t, seen, 6)

    # 3. 市场资金面与主线风向 (ETF放量、大行定价判断、AI/半导体/债市大宗)
    for t in cls_items + red_lives + wscn_articles + cjzc_sections.get('每日精选', []):
        if MARKET_FLOW_RE.search(t) and not any(k in t for k in ['习近平', '李强', '马斯克', '三星']):
            _dedup_append(market_focus, t, seen, 5)

    msg = f"<b>📰 国内外股市政策与宏观风向日报 ({today.strftime('%m/%d')} {session_tag})</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "<b>🇺🇸 【海外央行利率与宏观政策】</b>\n"
    if overseas_policy:
        for item in overseas_policy:
            msg += f"• {html.escape(item, quote=False)}\n"
    else:
        msg += "• 暂无最新美联储/海外央行重磅政策动态。\n"

    msg += "\n<b>🇨🇳 【国内金融监管与宏观政策】</b>\n"
    if domestic_policy:
        for item in domestic_policy:
            msg += f"• {html.escape(item, quote=False)}\n"
    else:
        msg += "• 暂无最新国内金融监管与宏观重磅政策。\n"

    msg += "\n<b>💹 【市场资金面与主线风向】</b>\n"
    if market_focus:
        for item in market_focus:
            msg += f"• {html.escape(item, quote=False)}\n"
    else:
        msg += "• 暂无最新资金面重大焦点。\n"

    cctv_tag = f"新闻联播财经({cctv_date[4:6]}/{cctv_date[6:]})、" if (cctv_date and cctv_econ) else ""
    msg += f"\n<i>注：聚焦左右股市走向的货币/财政/监管政策与资金风向（汇聚自华尔街见闻、东财全球快讯/财经早餐、财联社及{cctv_tag}已过滤非市场信息）。</i>"
    return msg

# ==================== Telegram 发送辅助 ====================

def send_telegram_message(text):
    """发送消息到 Telegram，超长消息自动切分避免 400 错误"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID or not text:
        print("未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过推送。")
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"

    # Telegram 单条消息上限为 4096 字符，安全切分阈值设为 3900
    if len(text) <= 3900:
        chunks = [text]
    else:
        chunks = []
        current_chunk = ""
        for line in text.splitlines(keepends=True):
            if len(current_chunk) + len(line) > 3900:
                chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += line
        if current_chunk:
            chunks.append(current_chunk)

    for i, chunk in enumerate(chunks, 1):
        try:
            res = requests.post(url, json={
                "chat_id": TG_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }, timeout=15)
            if res.ok:
                print(f"Telegram 消息发送成功 (分片 {i}/{len(chunks)})")
            else:
                print(f"Telegram 发送响应失败: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"Telegram 请求异常: {e}")
        time.sleep(0.5)

# ==================== 主入口 ====================

def main():
    # 1. 交易日检查 (严格使用北京时间，支持通过 FORCE_RUN 强制执行)
    today = get_beijing_time()
    force_run = os.environ.get('FORCE_RUN', '').lower() in ['true', '1', 'yes']
    if not force_run and not is_trading_day(today):
        print(f"今日 {today.strftime('%Y-%m-%d')} 为非交易日，脚本退出。")
        return

    # 2. 原有功能：生成并发送韭圈儿指数估值日报 (开头已增加每日总结)
    print("=== 开始生成韭圈儿指数估值日报 ===")
    try:
        valuation_msg = generate_valuation_report(today)
        print("正在推送韭圈儿估值日报至 Telegram...")
        send_telegram_message(valuation_msg)
    except Exception as e:
        print(f"生成或发送韭圈儿指数估值日报失败: {e}")

    # 3. 单独发送纳斯达克100 QDII 场外基金监控日报 (排除C类，表格化展示)
    print("\n=== 开始生成纳斯达克100 QDII 场外基金日报 ===")
    try:
        qdii_funds = fetch_qdii_nasdaq_funds(cache_file='qdii_cache.json')
        qdii_report = build_qdii_report(qdii_funds, today, cache_file='qdii_cache.json')
        print("正在推送纳斯达克100 QDII 日报至 Telegram (单独发送)...")
        send_telegram_message(qdii_report)
    except Exception as e:
        print(f"生成或发送纳斯达克100 QDII 日报失败: {e}")

    # 4. 独立第3条发送：全球主要股指 & 纳指100/标普500 估值日报
    print("\n=== 开始生成全球主要股指 & 纳指100/标普500 估值日报 ===")
    try:
        global_report = generate_global_valuation_report(today)
        print("正在推送全球主要股指估值日报至 Telegram (单独发送)...")
        send_telegram_message(global_report)
    except Exception as e:
        print(f"生成或发送全球主要股指估值日报失败: {e}")

    # 5. 新增独立第4条发送：国内外主要政治经济金融要闻日报
    print("\n=== 开始生成国内外政经与金融要闻日报 ===")
    try:
        news_report = generate_macro_news_report(today)
        print("正在推送国内外政经与金融要闻日报至 Telegram (单独发送)...")
        send_telegram_message(news_report)
        print("=== 所有任务执行完毕 ===")
    except Exception as e:
        print(f"生成或发送国内外政经与金融要闻日报失败: {e}")

if __name__ == "__main__":
    main()
