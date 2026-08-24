"""Chinese display names for supported football clubs."""

import re
import unicodedata


def _normalize(value: str) -> str:
    """Normalize accents, punctuation, and case for provider aliases."""

    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


_RAW_TEAM_NAMES = {
    # Premier League
    "Arsenal": "阿森纳",
    "Aston Villa": "阿斯顿维拉",
    "Bournemouth": "伯恩茅斯",
    "Brentford": "布伦特福德",
    "Brighton": "布莱顿",
    "Brighton and Hove Albion": "布莱顿",
    "Brighton & Hove Albion": "布莱顿",
    "Burnley": "伯恩利",
    "Chelsea": "切尔西",
    "Crystal Palace": "水晶宫",
    "Everton": "埃弗顿",
    "Fulham": "富勒姆",
    "Leeds United": "利兹联",
    "Liverpool": "利物浦",
    "Manchester City": "曼彻斯特城",
    "Manchester United": "曼联",
    "Newcastle United": "纽卡斯尔联",
    "Nottingham Forest": "诺丁汉森林",
    "Sunderland": "桑德兰",
    "Tottenham Hotspur": "托特纳姆热刺",
    "West Ham United": "西汉姆联",
    "Wolverhampton Wanderers": "狼队",
    "Wolverhampton": "狼队",
    "Coventry City": "考文垂",
    "Hull City": "赫尔城",
    "Ipswich Town": "伊普斯维奇",
    # La Liga
    "Alaves": "阿拉维斯",
    "Deportivo Alaves": "阿拉维斯",
    "Athletic Club": "毕尔巴鄂竞技",
    "Athletic Bilbao": "毕尔巴鄂竞技",
    "Atletico Madrid": "马德里竞技",
    "Barcelona": "巴塞罗那",
    "Celta Vigo": "维戈塞尔塔",
    "Elche": "埃尔切",
    "Espanyol": "西班牙人",
    "Getafe": "赫塔费",
    "Girona": "赫罗纳",
    "Las Palmas": "拉斯帕尔马斯",
    "Levante": "莱万特",
    "Mallorca": "马略卡",
    "Malaga": "马拉加",
    "Osasuna": "奥萨苏纳",
    "Rayo Vallecano": "巴列卡诺",
    "Real Betis": "皇家贝蒂斯",
    "Real Madrid": "皇家马德里",
    "Real Oviedo": "皇家奥维耶多",
    "Real Sociedad": "皇家社会",
    "Sevilla": "塞维利亚",
    "Valencia": "瓦伦西亚",
    "Villarreal": "比利亚雷亚尔",
    "Deportivo La Coruna": "拉科鲁尼亚",
    "Deportivo de A Coruna": "拉科鲁尼亚",
    "Racing de Santander": "桑坦德竞技",
    "Racing Santander": "桑坦德竞技",
    # Chinese Super League
    "Beijing Guoan": "北京国安",
    "Changchun Yatai": "长春亚泰",
    "Chengdu Rongcheng": "成都蓉城",
    "Chongqing Tonglianglong": "重庆铜梁龙",
    "Dalian Yingbo": "大连英博",
    "Henan": "河南队",
    "Henan FC": "河南队",
    "Meizhou Hakka": "梅州客家",
    "Liaoning Tieren": "辽宁铁人",
    "Qingdao Hainiu": "青岛海牛",
    "Qingdao West Coast": "青岛西海岸",
    "Shandong Taishan": "山东泰山",
    "Shanghai Port": "上海海港",
    "Shanghai Shenhua": "上海申花",
    "Shenzhen Peng City": "深圳新鹏城",
    "Tianjin Jinmen Tiger": "天津津门虎",
    "Wuhan Three Towns": "武汉三镇",
    "Yunnan Yukun": "云南玉昆",
    "Zhejiang Professional": "浙江队",
    "Zhejiang FC": "浙江队",
}

TEAM_NAMES_ZH = {_normalize(name): chinese_name for name, chinese_name in _RAW_TEAM_NAMES.items()}


def to_chinese_team_name(name: str) -> str:
    """Return a standard Chinese club name or the provider name when unknown."""

    return TEAM_NAMES_ZH.get(_normalize(name), name)
