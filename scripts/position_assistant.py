#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股股票筛选脚本 - HK Stock Screener
基于 PB、PE、股息率等价值指标筛选港股，生成分析报告

配置说明：
1. 复制 config.example.json 为 config.json 并填写你的配置
2. 设置环境变量 LIXINGZHE_TOKEN 为你的理杏仁 API Token
3. 可选：设置 HTTP_PROXY 环境变量使用代理
"""

import requests
import json
import pandas as pd
from datetime import datetime
import os
import sys
import time
import re
import statistics

# ══════════════════════════════════════════════════════════════
# 配置读取
# ══════════════════════════════════════════════════════════════

def get_config():
    """从配置文件和环境变量读取配置"""
    config_path = os.environ.get('CONFIG_PATH', 'config.json')
    
    # 默认配置
    config = {
        'api_token': os.environ.get('LIXINGZHE_TOKEN', ''),
        'base_url': 'https://open.lixinger.com/api',
        'proxy': os.environ.get('HTTP_PROXY', ''),
        'telegram': {
            'enabled': False,
            'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN', ''),
            'chat_id': os.environ.get('TELEGRAM_CHAT_ID', ''),
        },
        'output_dir': os.environ.get('OUTPUT_DIR', './reports'),
        'cache_dir': os.environ.get('CACHE_DIR', './cache'),
        'filters': {
            'min_market_cap': 50,  # 亿港元
            'max_pe': 15,
            'min_pe': 0.01,
            'max_pb': 1.5,
            'min_pb': 0.01,
        },
        'exclude_codes': [],
        'exclude_local_banks': True,
        'local_banks': [
            '天津银行', '晋商银行', '东莞农商银行', '泸州银行', '贵州银行', '重庆银行',
            '重庆农村商业银行', '中原银行', '郑州银行', '威海银行', '广州农商银行',
            '渤海银行', '哈尔滨银行', '甘肃银行', '江西银行', '九江银行'
        ],
        'exchange_rates': {
            'usd_to_cny': 7.2,
            'hkd_to_cny': 0.92,
        },
        'portfolio': {
            'hk_stocks': [],  # 港股持仓
            'a_stocks': [],   # A股持仓
            'cash_rmb': 0,
            'crypto_assets': {
                'usdt': 0,
                'btc_usd': 0,
                'bnb_usd': 0,
                'other_usd': 0,
            }
        }
    }
    
    # 读取配置文件
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                config.update(user_config)
        except Exception as e:
            print(f"⚠️ 配置文件读取失败: {e}")
    
    # 验证必要配置
    if not config['api_token']:
        raise ValueError("缺少 API Token，请设置 LIXINGZHE_TOKEN 环境变量或在 config.json 中配置")
    
    return config

# ══════════════════════════════════════════════════════════════
# 全局变量（运行时初始化）
# ══════════════════════════════════════════════════════════════

_CONFIG = None
_PROXIES = None
_LAST_REQUEST_TS = 0.0
_REQUEST_INTERVAL_SEC = 1.0  # 限速 1 req/s

# ══════════════════════════════════════════════════════════════
# 行业映射
# ══════════════════════════════════════════════════════════════

FS_TYPE_INDUSTRY_MAP = {
    'non_financial': '非金融',
    'bank': '银行',
    'insurance': '保险',
    'security': '证券',
    'reit': 'REIT',
    'other_financial': '其他金融'
}

INVALID_INDUSTRIES = {'', '未知', '其他', '综合企业'}

INDUSTRY_CANONICAL_MAP = {
    '地产建筑业': '地产',
    '地产发展商': '地产',
    '建筑业': '建筑',
    '建筑及工程': '建筑',
    '基础建设': '建筑',
}

INDUSTRY_KEYWORDS = [
    ('地产', ['地产', '物业开发', '物业投资', '房地产']),
    ('建筑', ['建筑工程', '土木工程', '基建建设', '工程承包', '铁路建设', '交通建设',
              '路桥建设', '市政工程', '中铁', '铁建', '建工集团', '建设集团', '施工']),
    ('银行', ['银行', '商业银行', '城商行', '农商行']),
    ('保险', ['保险', '寿险', '财险', '再保险']),
    ('证券', ['证券', '经纪', '投行']),
    ('金融', ['融资租赁', '金融控股', '金融集团', '财务公司', '租赁', '投资控股']),
    ('运输', ['航运', '集装箱', '海运', '船舶运输', '物流运输', '高速公路', '港口',
              '铁路运输', '运输']),
    ('电力', ['发电', '电力', '电网', '新能源发电', '清洁能源', '光伏', '太阳能发电',
              '风电', '水电', '核电']),
    ('电信', ['电信', '通信网络', '运营商', '5g', '通信', '电讯']),
    ('煤炭', ['煤炭', '焦煤', '动力煤']),
    ('石油天然气', ['石油', '天然气', '油气', '炼化', '油田', '海油']),
    ('医药', ['医药', '制药', '生物科技', '医疗器械', '医疗集团', '医院', '健康服务']),
    ('消费', ['食品', '饮料', '零售', '消费品', '家电', '酒店', '味精', '氨基酸',
              '农产品加工', '餐饮', '烟草']),
    ('公用事业', ['环保', '水务', '燃气', '智慧能源', '创业环保', '固废处理', '垃圾发电']),
    ('科技', ['软件', '信息技术', 'it服务', '数字化', '云计算', '人工智能', '互联网',
              '半导体', '芯片', '数据中心', '科技集团']),
    ('工业', ['制造', '工业', '装备', '机械', '工程服务', '造纸', '通号',
              '航空制造', '汽车零部件', '零部件', '轴承', '包装']),
]

# 手动行业映射表（针对特定股票代码）
MANUAL_INDUSTRY_MAP = {
    '00552': '电信',      # 中国通信服务
    '01883': '电信',      # 中信国际电讯
    '00152': '运输',      # 深圳国际
    '00576': '运输',      # 浙江沪杭甬
    '02880': '运输',      # 辽港股份
    '00598': '运输',      # 中国外运
    '00316': '运输',      # 东方海外国际
    '01065': '公用事业',  # 天津创业环保
    '01083': '公用事业',  # 港华智慧能源
    '00257': '公用事业',  # 光大环境
    '03868': '电力',      # 信义能源
    '00579': '电力',      # 京能清洁能源
    '00968': '工业',      # 信义光能
    '02883': '石油天然气', # 中海油田服务
    '00857': '石油天然气', # 中国石油股份
    '00071': '消费',      # 美丽华酒店
    '00546': '消费',      # 阜丰集团
    '00142': '地产',      # 第一太平
    '00390': '建筑',      # 中国中铁
    '01186': '建筑',      # 中国铁建
    '01800': '建筑',      # 中国交通建设
    '01066': '医药',      # 威高股份
    '02666': '医药',      # 环球医疗
    '00564': '科技',      # 中创智领
    '00586': '工业',      # 海螺创业
    '01766': '工业',      # 中国中车
    '02357': '工业',      # 中航科工
    '00267': '金融',      # 中信股份
    '01905': '金融',      # 海通恒信
    '00440': '金融',      # 大新金融
    '00086': '金融',      # 新鸿基公司
}

# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def api_post(endpoint: str, payload: dict, timeout: int = 30):
    """统一API请求：全局限速"""
    global _LAST_REQUEST_TS, _CONFIG, _PROXIES
    
    wait = _REQUEST_INTERVAL_SEC - (time.time() - _LAST_REQUEST_TS)
    if wait > 0:
        time.sleep(wait)
    
    url = f"{_CONFIG['base_url']}/{endpoint}"
    resp = requests.post(url, json=payload, headers={"Accept-Encoding": "gzip"}, 
                         proxies=_PROXIES, timeout=timeout)
    _LAST_REQUEST_TS = time.time()
    return resp.json()


def get_effective_usd_to_cny():
    """获取实时 USD/CNY 汇率"""
    sources = [
        "https://open.er-api.com/v6/latest/USD",
        "https://api.frankfurter.app/latest?from=USD&to=CNY",
    ]
    
    for url in sources:
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            data = r.json()
            rates = data.get('rates') or {}
            cny = rates.get('CNY')
            if cny is not None:
                return float(cny)
        except Exception:
            continue
    
    # 回退到配置值
    return _CONFIG['exchange_rates']['usd_to_cny']


def get_effective_hkd_to_cny():
    """获取实时 HKD/CNY 汇率"""
    sources = [
        "https://open.er-api.com/v6/latest/HKD",
        "https://api.frankfurter.app/latest?from=HKD&to=CNY",
    ]
    
    for url in sources:
        try:
            r = requests.get(url, timeout=8)
            data = r.json()
            cny = (data.get('rates') or {}).get('CNY')
            if cny:
                return float(cny)
        except Exception:
            continue
    
    return _CONFIG['exchange_rates']['hkd_to_cny']


def normalize_industry(name: str) -> str:
    n = (name or '').strip()
    if n in INDUSTRY_CANONICAL_MAP:
        n = INDUSTRY_CANONICAL_MAP[n]
    return n


def is_invalid_industry(name: str) -> bool:
    n = (name or '').strip()
    if not n:
        return True
    if n in INVALID_INDUSTRIES:
        return True
    if '其他' in n:
        return True
    return False


def fetch_industry_by_code(stock_code: str):
    """通过 API 获取股票行业分类"""
    payload = {"token": _CONFIG['api_token'], "stockCode": stock_code}
    try:
        result = api_post('hk/company/industries', payload, timeout=8)
        if result.get('code') == 1:
            items = result.get('data') or []
            return pick_best_industry(items)
    except Exception:
        pass
    return None


def pick_best_industry(items):
    """从多个行业来源中选择最合适的"""
    if not items:
        return None
    source_priority = {'sw_2021': 1, 'sw_2014': 2, 'gics': 3, 'hsi': 4}

    def score(it):
        src = (it.get('source') or '').lower()
        src_rank = source_priority.get(src, 9)
        name = (it.get('name') or '').strip()
        detail_rank = -len(name)
        generic_penalty = 5 if name in INVALID_INDUSTRIES else 0
        return (generic_penalty, src_rank, detail_rank)

    best = sorted(items, key=score)[0]
    return normalize_industry((best.get('name') or '').strip() or None)


def infer_industry_from_text(company_name: str, original_industry: str, summary: str):
    merged = f"{company_name or ''} {original_industry or ''} {summary or ''}".lower()
    for target, words in INDUSTRY_KEYWORDS:
        if any(w.lower() in merged for w in words):
            return target
    return None


def resolve_industry(company: dict) -> str:
    """确定股票行业分类"""
    stock_code = company.get('stockCode') or ''

    # 第一层：手动映射表
    if stock_code in MANUAL_INDUSTRY_MAP:
        return MANUAL_INDUSTRY_MAP[stock_code]

    # 第二层：使用 API 返回的 industryName
    name = normalize_industry(company.get('industryName') or company.get('industry') or '')
    if name and not is_invalid_industry(name):
        return name

    # 第三层：调用 industries 接口
    if stock_code:
        api_industry = fetch_industry_by_code(stock_code)
        if api_industry and not is_invalid_industry(api_industry):
            return api_industry

    # 第四层：公司名 + 主营业务关键词匹配
    summary_parts = [
        company.get('companyProfileSummary'),
        company.get('profileSummary'),
        company.get('mainBusiness'),
        company.get('businessSummary'),
        company.get('introduction'),
        company.get('description'),
    ]
    summary = ' '.join(str(x) for x in summary_parts if x)
    inferred = infer_industry_from_text(company.get('name', ''), name, summary)
    if inferred:
        inferred = normalize_industry(inferred)
        if inferred and not is_invalid_industry(inferred):
            return inferred

    # 第五层：fsTableType 区分金融子类
    fs_type = company.get('fsTableType') or ''
    if fs_type in ('bank', 'insurance', 'security', 'reit'):
        return FS_TYPE_INDUSTRY_MAP[fs_type]

    # 最终兜底
    return '工业'


# ══════════════════════════════════════════════════════════════
# 九神指数 (ahr999) 获取
# ══════════════════════════════════════════════════════════════

def fetch_nine_index():
    """从非小号 API 获取 ahr999（九神指数）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.feixiaohao.com/data/ahrdata.html",
    }
    
    try:
        r = requests.get(
            "https://dncapi.flink1.com/api/v2/index/arh999?code=bitcoin",
            headers=headers, proxies=_PROXIES, timeout=15
        )
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                latest = data[-1]
                idx = round(float(latest[1]), 4)
                print(f"   九神指数(非小号ahr999): {idx}")
                return idx
    except Exception as e:
        print(f"⚠️ 非小号 ahr999 获取失败: {e}")

    # 备用：Binance klines
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=365",
            headers={"User-Agent": headers["User-Agent"]}, proxies=_PROXIES, timeout=15
        )
        if r.status_code == 200:
            closes = [float(d[4]) for d in r.json()]
            if len(closes) >= 100:
                ma365 = sum(closes) / len(closes)
                current = closes[-1]
                idx = round(current / ma365, 3)
                print(f"   九神指数(Binance MA365备用): {idx}")
                return idx
    except Exception as e:
        print(f"⚠️ Binance klines 获取失败: {e}")

    print("⚠️ 所有网络源获取失败，使用默认值0.84")
    return 0.84


def get_btc_cash_ratio_by_nine_index(nine_index):
    """九神指数仓位规则"""
    x = float(nine_index)
    if x < 0.21:
        return 80, 20, '< 0.21'
    elif x <= 0.315:
        return 75, 25, '0.21 ~ 0.315'
    elif x <= 0.49:
        return 70, 30, '0.315 ~ 0.49'
    elif x <= 0.84:
        return 60, 40, '0.49 ~ 0.84'
    elif x <= 1.26:
        return 45, 55, '0.84 ~ 1.26'
    elif x <= 1.75:
        return 30, 70, '1.26 ~ 1.75'
    else:
        return 20, 80, '> 1.75'


# ══════════════════════════════════════════════════════════════
# 仓位计算
# ══════════════════════════════════════════════════════════════

def calculate_stock_positions(hkd_to_cny):
    """计算股票持仓价值"""
    portfolio = _CONFIG['portfolio']
    hk_stocks = portfolio.get('hk_stocks', [])
    a_stocks = portfolio.get('a_stocks', [])
    
    hk_total = sum(s['shares'] * s['price_hkd'] * hkd_to_cny for s in hk_stocks)
    a_total = sum(s['shares'] * s['price_cny'] for s in a_stocks)
    return hk_total, a_total, hk_total + a_total


def calculate_crypto_detail(usd_to_cny):
    """计算数字货币明细"""
    crypto = _CONFIG['portfolio'].get('crypto_assets', {})
    
    usdt_usd = crypto.get('usdt', 0)
    btc_usd = crypto.get('btc_usd', 0)
    bnb_usd = crypto.get('bnb_usd', 0)
    other_usd = crypto.get('other_usd', 0)

    non_usdt_usd = btc_usd + bnb_usd + other_usd
    total_usd = crypto.get('total_usd', non_usdt_usd + usdt_usd)

    return {
        'usdt_usd': usdt_usd,
        'usdt_cny': usdt_usd * usd_to_cny,
        'btc_usd': btc_usd,
        'btc_cny': btc_usd * usd_to_cny,
        'bnb_usd': bnb_usd,
        'bnb_cny': bnb_usd * usd_to_cny,
        'other_usd': other_usd,
        'other_cny': other_usd * usd_to_cny,
        'non_usdt_usd': non_usdt_usd,
        'non_usdt_cny': non_usdt_usd * usd_to_cny,
        'total_usd': total_usd,
        'total_cny': total_usd * usd_to_cny,
    }


# ══════════════════════════════════════════════════════════════
# PB 仓位规则
# ══════════════════════════════════════════════════════════════

def get_stock_cash_ratio_by_pb(avg_pb):
    """基于PB的股现比例规则"""
    if avg_pb > 2.00:
        return 20, 80
    elif avg_pb >= 1.75:
        return 30, 70
    elif avg_pb >= 1.45:
        return 40, 60
    elif avg_pb >= 1.15:
        return 50, 50
    elif avg_pb >= 0.85:
        return 60, 40
    elif avg_pb >= 0.60:
        return 70, 30
    else:
        return 80, 20


# ══════════════════════════════════════════════════════════════
# 数据获取
# ══════════════════════════════════════════════════════════════

def get_all_hk_stocks():
    """从理杏仁API获取港股公司列表"""
    companies = []
    page = 0
    max_pages = 200

    while page < max_pages:
        payload = {"token": _CONFIG['api_token'], "pageIndex": page}
        result = api_post("hk/company", payload, timeout=30)
        data = result.get('data') or []
        if result.get('code') != 1 or not data:
            break
        companies.extend(data)
        page += 1

    return companies


_LATEST_DATA_DATE_CACHE = None

def get_latest_data_date():
    """找最近有数据的交易日"""
    global _LATEST_DATA_DATE_CACHE
    if _LATEST_DATA_DATE_CACHE:
        return _LATEST_DATA_DATE_CACHE
    
    for delta in range(0, 7):
        d = (datetime.now() - pd.Timedelta(days=delta)).strftime('%Y-%m-%d')
        try:
            payload = {"token": _CONFIG['api_token'], "stockCodes": ["00700"],
                       "metricsList": ["pb"], "date": d, "pageIndex": 0}
            r = api_post("hk/company/fundamental/non_financial", payload, timeout=10)
            if r.get('code') == 1 and r.get('data'):
                _LATEST_DATA_DATE_CACHE = d
                return d
        except Exception:
            continue
    
    fallback = (datetime.now() - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    _LATEST_DATA_DATE_CACHE = fallback
    return fallback


def get_fundamental_data(stock_codes, fs_type='non_financial'):
    """获取估值与盈利指标"""
    endpoint_map = {
        'non_financial': 'non_financial',
        'bank': 'bank',
        'insurance': 'insurance',
        'security': 'security',
        'reit': 'reit',
        'other_financial': 'other_financial'
    }
    fs_endpoint = endpoint_map.get(fs_type, 'non_financial')
    all_data = []
    
    for i in range(0, len(stock_codes), 100):
        batch = stock_codes[i:i+100]
        payload = {
            "token": _CONFIG['api_token'],
            "stockCodes": batch,
            "metricsList": ["pe_ttm", "pb", "dyr", "mc"],
            "date": get_latest_data_date(),
            "pageIndex": 0
        }
        try:
            result = api_post(f"hk/company/fundamental/{fs_endpoint}", payload, timeout=30)
            if result.get('code') == 1 and result.get('data'):
                all_data.extend(result['data'])
        except Exception:
            continue

    return all_data


def load_cache_stocks():
    """从缓存加载数据"""
    cache_path = os.path.join(_CONFIG['cache_dir'], 'hk_stock_cache.json')
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                print(f"✅ 从缓存加载 {len(df)} 只港股")
                return df
    except Exception as e:
        print(f"⚠️ 缓存加载失败: {e}")
    return None


def save_cache_stocks(df):
    """保存数据到缓存"""
    cache_path = os.path.join(_CONFIG['cache_dir'], 'hk_stock_cache.json')
    os.makedirs(_CONFIG['cache_dir'], exist_ok=True)
    try:
        df.to_json(cache_path, orient='records', force_ascii=False)
    except Exception as e:
        print(f"⚠️ 缓存保存失败: {e}")


def load_real_stocks_from_api():
    """加载港股数据并完成初筛"""
    try:
        companies = get_all_hk_stocks()
        if not companies:
            print("⚠️ 未获取到港股公司列表，尝试使用缓存...")
            df = load_cache_stocks()
            if df is not None:
                return df
            raise RuntimeError("未获取到港股公司列表且缓存不可用")

        filters = _CONFIG['filters']
        
        by_type = {}
        company_map = {}
        for c in companies:
            code = c.get('stockCode')
            if not code:
                continue
            fs_type = c.get('fsTableType', 'non_financial')
            by_type.setdefault(fs_type, []).append(code)
            company_map[code] = c

        all_fundamentals = []
        for fs_type, codes in by_type.items():
            all_fundamentals.extend(get_fundamental_data(codes, fs_type))

        if not all_fundamentals:
            print("⚠️ 未获取到港股基本面数据，尝试使用缓存...")
            df = load_cache_stocks()
            if df is not None:
                return df
            raise RuntimeError("未获取到港股基本面数据且缓存不可用")

        fund_dict = {d.get('stockCode'): d for d in all_fundamentals if d.get('stockCode')}

        # 合并数据
        merged_data = []
        for code, company in company_map.items():
            if code not in fund_dict:
                continue
            f = fund_dict[code]
            market_cap_hkd = (f.get('mc') or 0) / 100000000
            pe = f.get('pe_ttm') or 0
            pb = f.get('pb') or 0
            dividend = (f.get('dyr') or 0) * 100

            merged_data.append({
                'code': code,
                'name': company.get('name', ''),
                '_company': company,
                'market_cap': market_cap_hkd,
                'pe': pe,
                'pb': pb,
                'dividend': dividend,
            })

        df = pd.DataFrame(merged_data)
        if df.empty:
            print("⚠️ 合并后的港股数据为空，尝试使用缓存...")
            df = load_cache_stocks()
            if df is not None:
                return df
            raise RuntimeError("合并后的港股数据为空且缓存不可用")

        # 初筛
        df = df[
            (df['pe'] >= filters['min_pe']) & (df['pe'] <= filters['max_pe']) &
            (df['pb'] >= filters['min_pb']) & (df['pb'] <= filters['max_pb']) &
            (df['market_cap'] >= filters['min_market_cap'])
        ].copy()

        # 行业确定
        print(f"   初筛后 {len(df)} 只候选股，开始行业确定...")
        df['industry'] = df['_company'].apply(resolve_industry)
        df = df.drop(columns=['_company'])

        # 保存缓存
        save_cache_stocks(df)

        return df

    except Exception as e:
        print(f"⚠️ API调用异常: {e}，尝试使用缓存...")
        df = load_cache_stocks()
        if df is not None:
            return df
        raise RuntimeError(f"API失败且缓存不可用: {e}")


# ══════════════════════════════════════════════════════════════
# 详细打分模块
# ══════════════════════════════════════════════════════════════

def get_fs_history(code: str) -> list:
    """拉取5年财务数据"""
    metrics = [
        "q.m.roe.ttm",
        "q.m.np_s_r.ttm",
        "q.m.ncffoa_np_r.ttm",
        "q.m.np_pc.t",
        "q.ps.gp.t",
        "q.ps.toi.t",
        "q.bs.tl.t",
        "q.bs.ta.t",
    ]
    d = api_post("hk/company/fs/non_financial", {
        "token": _CONFIG['api_token'], "stockCodes": [code],
        "startDate": "2019-01-01", "metricsList": metrics
    })
    rows = []
    for row in d.get("data", []):
        if row.get("reportType") != "annual_report":
            continue
        q = row.get("q", {}).get("m", {})
        ps = row.get("q", {}).get("ps", {})
        bs = row.get("q", {}).get("bs", {})
        gp = (ps.get("gp", {}) or {}).get("t")
        toi = (ps.get("toi", {}) or {}).get("t")
        tl = (bs.get("tl", {}) or {}).get("t")
        ta = (bs.get("ta", {}) or {}).get("t")
        gpm = (gp / toi) if (gp is not None and toi is not None and toi > 0) else None
        dar = (tl / ta) if (tl is not None and ta is not None and ta > 0) else None
        rows.append({
            "year": row["date"][:4],
            "roe": (q.get("roe", {}) or {}).get("ttm"),
            "npm": (q.get("np_s_r", {}) or {}).get("ttm"),
            "ocf_np": (q.get("ncffoa_np_r", {}) or {}).get("ttm"),
            "np_abs": (q.get("np_pc", {}) or {}).get("t"),
            "gpm": gpm,
            "revenue": toi,
            "dar": dar,
        })
    return sorted(rows, key=lambda x: x["year"])


def get_dividend_history(code: str) -> list:
    """拉取分红历史"""
    d = api_post("hk/company/dividend", {
        "token": _CONFIG['api_token'], "stockCode": code, "startDate": "2018-01-01"
    })
    divs = [x for x in d.get("data", []) if x.get("dividend", 0) > 0]
    return sorted(divs, key=lambda x: x["date"])


def score_prospect_detailed(fs_rows: list) -> tuple:
    """前景打分，满分100"""
    import statistics
    
    roes = [r["roe"] for r in fs_rows if r["roe"] is not None]
    npms = [r["npm"] for r in fs_rows if r["npm"] is not None]
    ocfs = [r["ocf_np"] for r in fs_rows if r["ocf_np"] is not None]
    nps = [r["np_abs"] for r in fs_rows if r["np_abs"] is not None]
    gpms = [r["gpm"] for r in fs_rows if r.get("gpm") is not None]
    revs = [r["revenue"] for r in fs_rows if r.get("revenue") is not None]
    dars = [r["dar"] for r in fs_rows if r.get("dar") is not None]

    # ROE水平 (20)
    rl = roes[-1] if roes else None
    roe_lvl = (20 if rl is not None and rl >= 0.20 else
               16 if rl is not None and rl >= 0.15 else
               12 if rl is not None and rl >= 0.10 else
               6 if rl is not None and rl >= 0.05 else
               2 if rl is not None and rl >= 0 else 0)

    # ROE稳定性 (10)
    if len(roes) >= 3:
        std = statistics.stdev(roes)
        roe_stab = 10 if std < 0.03 else 7 if std < 0.06 else 4 if std < 0.10 else 1 if std < 0.15 else 0
    else:
        roe_stab = 4

    # ROE趋势 (8)
    if len(roes) >= 3:
        r3 = roes[-3:]
        roe_trend = (8 if r3[-1] > r3[-2] > r3[-3] and r3[-1] > 0 else
                     6 if r3[-1] > r3[0] and r3[-1] > 0 else
                     5 if all(r > 0.10 for r in r3) else
                     3 if r3[-1] > 0 else 0)
    else:
        roe_trend = 3

    # 净利率趋势 (8)
    if len(npms) >= 3:
        n3 = npms[-3:]
        npm_trend = (8 if n3[-1] > n3[-2] > n3[-3] else
                     6 if n3[-1] >= n3[0] else
                     3 if n3[-1] > 0 else 0)
    else:
        npm_trend = 3

    # 净利润CAGR (10)
    if len(nps) >= 4 and nps[-4] and nps[-4] > 0 and nps[-1] > 0:
        np_cagr = (nps[-1] / nps[-4]) ** (1 / 3) - 1
        np_g = 10 if np_cagr >= 0.15 else 7 if np_cagr >= 0.08 else 4 if np_cagr >= 0 else 0
    else:
        np_g = 0

    # 营收CAGR (10)
    if len(revs) >= 4 and revs[-4] and revs[-4] > 0 and revs[-1] and revs[-1] > 0:
        rev_cagr = (revs[-1] / revs[-4]) ** (1 / 3) - 1
        rev_g = 10 if rev_cagr >= 0.15 else 7 if rev_cagr >= 0.08 else 4 if rev_cagr >= 0 else 0
    else:
        rev_g = 0

    # 现金流 (10)
    avg_ocf = sum(ocfs) / len(ocfs) if ocfs else None
    ocf_base = (7 if avg_ocf is not None and avg_ocf >= 1.2 else
                5 if avg_ocf is not None and avg_ocf >= 0.8 else
                2 if avg_ocf is not None and avg_ocf > 0 else 0)
    if len(ocfs) >= 2 and avg_ocf and avg_ocf > 0:
        ocf_trend_bonus = 3 if ocfs[-1] > avg_ocf else 1 if ocfs[-1] >= avg_ocf * 0.9 else 0
    else:
        ocf_trend_bonus = 0
    ocf_s = min(10, ocf_base + ocf_trend_bonus)

    # 毛利率 (14)
    gm_curr = gpms[-1] if gpms else None
    gm_prev = gpms[-2] if len(gpms) >= 2 else None
    gm_lvl = (8 if gm_curr is not None and gm_curr >= 0.40 else
              6 if gm_curr is not None and gm_curr >= 0.25 else
              4 if gm_curr is not None and gm_curr >= 0.15 else
              2 if gm_curr is not None and gm_curr >= 0.05 else 0)
    if gm_curr is not None and gm_prev is not None:
        gm_trend = (6 if gm_curr > gm_prev + 0.01 else
                    4 if abs(gm_curr - gm_prev) <= 0.01 else
                    2 if gm_curr > gm_prev - 0.05 else 0)
    else:
        gm_trend = 0
    gm_s = gm_lvl + gm_trend

    # 负债率 (10)
    dar_latest = dars[-1] if dars else None
    debt_s = (10 if dar_latest is not None and dar_latest <= 0.30 else
              8 if dar_latest is not None and dar_latest <= 0.45 else
              6 if dar_latest is not None and dar_latest <= 0.55 else
              4 if dar_latest is not None and dar_latest <= 0.65 else
              2 if dar_latest is not None and dar_latest <= 0.75 else
              0 if dar_latest is not None else 0)

    score = roe_lvl + roe_stab + roe_trend + npm_trend + np_g + rev_g + ocf_s + gm_s + debt_s
    
    reasons = []
    if rl is not None:
        reasons.append(f"ROE{rl*100:.0f}%")
    if gm_curr is not None:
        reasons.append(f"毛利率{gm_curr*100:.0f}%")
    if dar_latest is not None:
        reasons.append(f"负债率{dar_latest*100:.0f}%")
    if avg_ocf is not None:
        reasons.append(f"OCF{avg_ocf:.1f}x")
    if rev_g > 0 and len(revs) >= 4:
        rev_cagr_val = (revs[-1] / revs[-4]) ** (1 / 3) - 1
        reasons.append(f"营收CAGR{rev_cagr_val*100:.0f}%")
    
    return score, "、".join(reasons) if reasons else "数据不足"


def score_dividend_detailed(divs: list) -> tuple:
    """分红稳定性打分，满分100"""
    if not divs:
        return 0, "低", "无分红记录"

    years = sorted(set(d["date"][:4] for d in divs))
    yi = [int(y) for y in years]
    consec = len(years) if len(yi) > 1 and all(yi[i+1] - yi[i] == 1 for i in range(len(yi) - 1)) else (1 if yi else 0)

    # 连续分红年数 (30)
    div_cont = (30 if consec >= 10 else 25 if consec >= 7 else
                18 if consec >= 5 else 10 if consec >= 3 else 4)

    # 派息率合理性 (30)
    po = divs[-1].get("annualNetProfitDividendRatio")
    if po is None:
        po_sc = 8
    else:
        p = po * 100
        po_sc = (30 if 40 <= p <= 70 else 22 if 20 <= p < 40 else
                 18 if 70 < p <= 80 else 0 if p > 80 else 7)

    # 分红增长趋势 (25)
    amounts = [d["dividend"] for d in divs]
    if len(amounts) >= 3:
        a3 = amounts[-3:]
        grow = (25 if a3[-1] > a3[-2] > a3[-3] else
                17 if a3[-1] >= a3[0] else
                10 if a3[-1] == a3[-2] else 3)
    elif len(amounts) == 2:
        grow = 13 if amounts[-1] >= amounts[0] else 3
    else:
        grow = 5

    # 可持续性 (15)
    if po is not None:
        p = po * 100
        sustain = (15 if 20 <= p <= 70 else 8 if 10 <= p <= 80 else 0)
    else:
        sustain = 4

    score = div_cont + po_sc + grow + sustain
    label = "优质" if score >= 80 else "稳健" if score >= 55 else "一般" if score >= 30 else "低"
    note = f"连续{consec}年/{f'派息率{po*100:.0f}%' if po else 'N/A'}"
    return score, label, note


def enrich_with_detailed_scores(df_pool: pd.DataFrame) -> pd.DataFrame:
    """对候选池详细打分"""
    df = df_pool.copy()
    codes = df['code'].tolist()
    print(f"\n🔍 详细打分：对 {len(codes)} 只股票调用详细API...")

    new_prospect = {}
    new_prospect_reasons = {}
    new_dividend_score = {}
    new_dividend_label = {}
    new_dividend_note = {}

    for i, code in enumerate(codes):
        rows_match = df.loc[df['code'] == code]
        name = rows_match['name'].values[0] if len(rows_match) else code
        print(f"   [{i+1}/{len(codes)}] {name} ({code})", end="", flush=True)

        try:
            fs = get_fs_history(code)
            divs = get_dividend_history(code)
            print(" ✓")
        except Exception as e:
            print(f" ⚠️ {e}")
            fs, divs = [], []

        ps, pr = score_prospect_detailed(fs)
        ds, dl, dn = score_dividend_detailed(divs)

        new_prospect[code] = ps
        new_prospect_reasons[code] = pr
        new_dividend_score[code] = ds
        new_dividend_label[code] = dl
        new_dividend_note[code] = dn

    df['prospect_score'] = df['code'].map(new_prospect)
    df['prospect_reasons'] = df['code'].map(new_prospect_reasons)
    df['dividend_score'] = df['code'].map(new_dividend_score)
    df['dividend_stability'] = df['code'].map(new_dividend_label)
    df['dividend_note'] = df['code'].map(new_dividend_note)

    df['total_score'] = df['prospect_score'] + df['dividend_score']
    df = df.sort_values('total_score', ascending=False).reset_index(drop=True)

    # 评级分布
    n = len(df)
    if n > 0:
        c1 = max(1, round(n * 0.20))
        c2 = max(c1 + 1, round(n * 0.55))
        c3 = max(c2 + 1, round(n * 0.85))
        idx = df.index.tolist()
        df.loc[idx[:c1], 'prospect_rating'] = '优秀'
        df.loc[idx[c1:c2], 'prospect_rating'] = '良好'
        df.loc[idx[c2:c3], 'prospect_rating'] = '一般'
        df.loc[idx[c3:], 'prospect_rating'] = '观察'

    return df


# ══════════════════════════════════════════════════════════════
# 筛选逻辑
# ══════════════════════════════════════════════════════════════

def filter_and_score_stocks(df):
    """筛选和基础评分"""
    # 排除列表
    exclude_codes = _CONFIG.get('exclude_codes', [])
    df = df[~df['code'].isin(exclude_codes)]
    
    # 排除本地银行
    if _CONFIG.get('exclude_local_banks', True):
        local_banks = _CONFIG.get('local_banks', [])
        local_bank_mask = (df['industry'] == '银行') & (df['name'].isin(local_banks))
        df = df[~local_bank_mask].copy()

    df['pe_rank'] = df['pe'].rank(ascending=True)
    df['pb_rank'] = df['pb'].rank(ascending=True)
    df['dividend_rank'] = df['dividend'].rank(ascending=False)
    df['base_score'] = df['pe_rank'] + df['pb_rank'] + df['dividend_rank']
    df['total_score'] = df['base_score']
    
    return df.sort_values('total_score')


def select_top_n(df, n=35, max_per_industry=2):
    """选出TOP N，每行业最多指定数量"""
    result = []
    industry_count = {}

    for _, row in df.iterrows():
        industry = row['industry']
        if industry_count.get(industry, 0) < max_per_industry:
            result.append(row)
            industry_count[industry] = industry_count.get(industry, 0) + 1
        if len(result) >= n:
            break

    # 补足
    if len(result) < n:
        existing_codes = {r['code'] for r in result}
        for _, row in df.iterrows():
            if row['code'] not in existing_codes:
                industry = row['industry']
                if industry_count.get(industry, 0) < max_per_industry:
                    result.append(row)
                    industry_count[industry] = industry_count.get(industry, 0) + 1
            if len(result) >= n:
                break

    return pd.DataFrame(result)


# ══════════════════════════════════════════════════════════════
# 报告生成
# ══════════════════════════════════════════════════════════════

def generate_html_report(df_final, position_data, date_str, rating_dist, nine_info, config):
    """生成HTML报告"""
    
    # 颜色配置
    colors = config.get('report_colors', {
        'bg': '#f4f6f8',
        'panel': '#ffffff',
        'line': '#d9dee6',
        'text': '#2b313b',
        'muted': '#6b7280',
        'accent': '#4f6f8f',
        'good': '#2f6f44',
        'warn': '#9a6b1f',
        'watch': '#7a3e3e',
    })
    
    # 数据准备
    avg_pb = position_data.get('portfolio_pb', round(df_final['pb'].mean(), 2))
    base_stock_ratio, base_cash_ratio = get_stock_cash_ratio_by_pb(avg_pb)
    
    # 评级表格
    rating_rows = ''.join([
        f"<tr><td>{k}</td><td>{v}</td><td>{(v/len(df_final)*100 if len(df_final) else 0):.1f}%</td></tr>"
        for k, v in [('优秀', rating_dist.get('优秀', 0)), 
                     ('良好', rating_dist.get('良好', 0)), 
                     ('一般', rating_dist.get('一般', 0)), 
                     ('观察', rating_dist.get('观察', 0))]
    ])
    
    # 最终股票行
    final_rows = ''
    for _, row in df_final.iterrows():
        final_rows += (
            f"<tr><td>{row['code']}</td><td>{row['name']}</td><td>{row['industry']}</td>"
            f"<td>{row['pe']:.2f}</td><td>{row['pb']:.2f}</td>"
            f"<td>{row['market_cap']:.0f}亿</td><td>{row['dividend']:.2f}%</td>"
            f"<td>{row['prospect_rating']}</td><td>{row['dividend_stability']}</td></tr>\n"
        )
    
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>港股股票筛选报告 - {date_str}</title>
<style>
body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; 
      margin:0; background:{colors['bg']}; color:{colors['text']};}}
.wrap {{max-width:1200px; margin:20px auto; padding:0 16px;}}
.card {{background:{colors['panel']}; border:1px solid {colors['line']}; 
        border-radius:8px; padding:16px; margin-bottom:14px;}}
h1 {{font-size:24px; margin:0 0 6px 0; color:{colors['text']};}}
h2 {{font-size:16px; margin:0 0 12px 0; color:{colors['text']};}}
table {{width:100%; border-collapse:collapse; font-size:13px;}}
th, td {{border:1px solid {colors['line']}; padding:8px 10px; text-align:left;}}
th {{background:{colors['bg']}; color:{colors['text']};}}
.rating-best {{color:{colors['good']}; font-weight:bold;}}
.rating-good {{color:{colors['accent']};}}
.rating-mid {{color:{colors['warn']};}}
.rating-watch {{color:{colors['watch']};}}
</style>
</head>
<body>
<div class="wrap">
<div class="card">
<h1>港股股票筛选报告</h1>
<p>报告日期：{date_str} ｜ 综合PB：{avg_pb:.2f}</p>
<p>建议仓位：股票 {base_stock_ratio}% ｜ 现金 {base_cash_ratio}%</p>
<p>九神指数：{nine_info['index']:.4f}（{nine_info['band']}）=> BTC {nine_info['btc']}% ｜ 现金 {nine_info['cash']}%</p>
</div>
<div class="card">
<h2>评级分布</h2>
<table>
<tr><th>评级</th><th>数量</th><th>占比</th></tr>
{rating_rows}
</table>
</div>
<div class="card">
<h2>筛选结果 TOP {len(df_final)}</h2>
<table>
<tr><th>代码</th><th>名称</th><th>行业</th><th>PE</th><th>PB</th><th>市值</th><th>股息率</th><th>前景</th><th>分红</th></tr>
{final_rows}
</table>
</div>
</div>
</body>
</html>"""

    return html


# ══════════════════════════════════════════════════════════════
# Telegram 发送
# ══════════════════════════════════════════════════════════════

def send_report_to_telegram(report_path, result):
    """发送报告到 Telegram"""
    if not _CONFIG['telegram']['enabled']:
        print("ℹ️ Telegram 推送已禁用")
        return False
    
    import urllib.request
    
    token = _CONFIG['telegram']['bot_token']
    chat_id = _CONFIG['telegram']['chat_id']
    
    if not token or not chat_id:
        print("⚠️ Telegram 配置不完整")
        return False
    
    nine_index = result.get("nine_index", 0)
    nine_band = result.get("nine_band", "?")
    btc_ratio = result.get("btc_ratio", 0)
    
    caption = (
        f"📊 港股筛选报告 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"九神指数: {nine_index:.4f}（{nine_band}）\n"
        f"综合PB: {result.get('portfolio_pb', 0):.2f}\n"
        f"BTC仓位建议: {btc_ratio}% BTC"
    )

    try:
        api_url = f"https://api.telegram.org/bot{token}/sendDocument"
        
        import mimetypes
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        
        with open(report_path, "rb") as doc:
            content = doc.read()
        
        fname = os.path.basename(report_path).encode()
        
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\""
        ).encode() + fname + b"\"\r\nContent-Type: text/html\r\n\r
" + content + (
            f"\r\n--{boundary}--\r\n"
        ).encode()
        
        req = urllib.request.Request(api_url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        
        if _PROXIES:
            proxy_handler = urllib.request.ProxyHandler(_PROXIES)
            opener = urllib.request.build_opener(proxy_handler)
            resp = opener.open(req, timeout=30)
        else:
            resp = urllib.request.urlopen(req, timeout=30)
        
        resp_data = json.loads(resp.read())
        if resp_data.get("ok"):
            print(f"✅ 报告已发送到 Telegram")
            return True
        else:
            print(f"⚠️ Telegram 发送失败: {resp_data}")
            return False
    except Exception as e:
        print(f"⚠️ Telegram 发送异常: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════

def main():
    """主函数"""
    global _CONFIG, _PROXIES
    
    print("=" * 60)
    print("港股股票筛选任务")
    print("=" * 60)

    # 加载配置
    print("\n📋 步骤1：加载配置...")
    _CONFIG = get_config()
    
    if _CONFIG['proxy']:
        _PROXIES = {"http": _CONFIG['proxy'], "https": _CONFIG['proxy']}
    
    os.makedirs(_CONFIG['output_dir'], exist_ok=True)
    os.makedirs(_CONFIG['cache_dir'], exist_ok=True)

    # 获取汇率
    print("\n💱 步骤2：获取汇率...")
    usd_to_cny = get_effective_usd_to_cny()
    hkd_to_cny = get_effective_hkd_to_cny()
    print(f"   USD/CNY: {usd_to_cny:.4f}")
    print(f"   HKD/CNY: {hkd_to_cny:.4f}")

    # 计算持仓
    print("\n💰 步骤3：计算持仓...")
    hk_value, a_value, total_stock_value = calculate_stock_positions(hkd_to_cny)
    crypto_detail = calculate_crypto_detail(usd_to_cny)
    cash_value = _CONFIG['portfolio'].get('cash_rmb', 0)

    print(f"   港股: ¥{hk_value:,.0f}")
    print(f"   A股: ¥{a_value:,.0f}")
    print(f"   数字货币: ¥{crypto_detail['total_cny']:,.0f}")
    print(f"   现金: ¥{cash_value:,.0f}")

    # 获取九神指数
    print("\n📊 步骤4：获取九神指数...")
    nine_index = fetch_nine_index()
    btc_ratio, crypto_cash_ratio, nine_band = get_btc_cash_ratio_by_nine_index(nine_index)
    print(f"   九神指数: {nine_index}（{nine_band}）=> BTC {btc_ratio}% : 现金 {crypto_cash_ratio}%")

    position_data = {
        'hk_value': hk_value,
        'a_value': a_value,
        'total_stock_value': total_stock_value,
        'cash_value': cash_value,
        'crypto_detail': crypto_detail,
        'portfolio_pb': None,  # 稍后计算
    }

    # 加载港股数据
    print("\n📊 步骤5：拉取港股数据...")
    df_real = load_real_stocks_from_api()
    initial_count = len(df_real)
    print(f"   初筛后候选: {initial_count} 只")

    # 基础打分
    print("\n📊 步骤6：基础打分排序...")
    df_scored = filter_and_score_stocks(df_real)
    print(f"   基础打分后: {len(df_scored)} 只")

    # TOP 150
    print("\n📊 步骤7：选出 TOP 150...")
    df_top150 = df_scored.head(150).copy()
    df_top150 = df_top150.reset_index(drop=True)
    df_top150['rank_in_150'] = range(1, len(df_top150) + 1)
    print(f"   TOP 150: {len(df_top150)} 只")

    # 详细打分
    print("\n📊 步骤8：详细打分...")
    df_detailed = enrich_with_detailed_scores(df_top150)
    print(f"   详细打分完成: {len(df_detailed)} 只")

    # 最终筛选
    print("\n📊 步骤9：行业筛选...")
    df_final = select_top_n(df_detailed, n=35, max_per_industry=2)
    final_count = len(df_final)
    print(f"   最终选出: {final_count} 只股票")

    rating_dist = df_final['prospect_rating'].value_counts().reindex(
        ['优秀', '良好', '一般', '观察'], fill_value=0).to_dict()

    # 计算综合PB
    portfolio_pb = round(df_final['pb'].mean(), 2)
    position_data['portfolio_pb'] = portfolio_pb
    print(f"   平均PB: {portfolio_pb:.2f}")

    # 生成报告
    print("\n📝 步骤10：生成HTML报告...")
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    nine_info = {"index": nine_index, "band": nine_band, "btc": btc_ratio, "cash": crypto_cash_ratio}
    html_content = generate_html_report(df_final, position_data, date_str, rating_dist, nine_info, _CONFIG)

    report_path = os.path.join(_CONFIG['output_dir'], f"hk_stock_screening_{date_str}.html")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"✅ 报告已保存: {report_path}")

    result = {
        "ok": True,
        "report_path": report_path,
        "initial_count": initial_count,
        "final_count": final_count,
        "rating_dist": rating_dist,
        "nine_index": nine_index,
        "nine_band": nine_band,
        "btc_ratio": btc_ratio,
        "crypto_cash_ratio": crypto_cash_ratio,
        "portfolio_pb": portfolio_pb,
    }

    # 发送 Telegram
    if _CONFIG['telegram']['enabled']:
        send_report_to_telegram(report_path, result)

    return result


if __name__ == "__main__":
    try:
        result = main()
        sys.exit(0 if result["ok"] else 1)
    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
