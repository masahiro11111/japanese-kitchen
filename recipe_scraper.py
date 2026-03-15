#!/usr/bin/env python3
"""
=============================================================
 Japanese Recipe Scraper + Multi-Language Translator
 対応言語: EN / ZH-TW / ZH-CN / VI / HI / RU / TH / ID / MS / KO
 翻訳エンジン: Google翻訳（無料・APIキー不要）
=============================================================
 使い方:
   1. pip install requests beautifulsoup4
   2. python recipe_scraper.py
=============================================================
"""

import os
import re
import json
import time
import hashlib
import logging
import requests
import urllib.parse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from bs4 import BeautifulSoup

# ─── ログ設定 ────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── 対応言語 ─────────────────────────────────────────────
LANGUAGES = {
    "en":    "English",
    "zh_tw": "Traditional Chinese (繁體中文)",
    "zh_cn": "Simplified Chinese (简体中文)",
    "vi":    "Vietnamese (Tiếng Việt)",
    "hi":    "Hindi (हिन्दी)",
    "ru":    "Russian (Русский)",
    "th":    "Thai (ภาษาไทย)",
    "id":    "Indonesian (Bahasa Indonesia)",
    "ms":    "Malay (Bahasa Melayu)",
    "ko":    "Korean (한국어)",
}

# ─── アフィリエイト設定 ───────────────────────────────────
AFFILIATE = {
    "amazon_tag":  os.getenv("AMAZON_TAG", "YOUR_AMAZON_TAG-22"),
    "rakuten_tag": os.getenv("RAKUTEN_TAG", "YOUR_RAKUTEN_TAG"),
}

# ─── スクレイピング対象サイト ─────────────────────────────
# MAX_RECIPES_PER_SITE: 1サイトあたりの最大取得件数
MAX_RECIPES_PER_SITE = 50

TARGET_SITES = [
    # ── Kewpie（マヨネーズ・ドレッシング・パスタソース）──
    {
        "name": "Kewpie_Mayo",
        "url":  "https://www.kewpie.co.jp/recipes/products/mayonnaise/",
        "parser": "kewpie",
    },
    {
        "name": "Kewpie_Dressing",
        "url":  "https://www.kewpie.co.jp/recipes/products/dressing/",
        "parser": "kewpie",
    },
    {
        "name": "Kewpie_Pasta",
        "url":  "https://www.kewpie.co.jp/recipes/products/pasta/",
        "parser": "kewpie",
    },
    # ── Kikkoman（醤油・だし・みりん）──
    {
        "name": "Kikkoman_Popular",
        "url":  "https://www.kikkoman.co.jp/homecook/theme/popular/namasyoyu_basic_recipes.html",
        "parser": "kikkoman",
    },
    {
        "name": "Kikkoman_Theme",
        "url":  "https://www.kikkoman.co.jp/homecook/theme/",
        "parser": "kikkoman",
    },
    # ── 味の素 ──
    {
        "name": "Ajinomoto",
        "url":  "https://www.ajinomoto.co.jp/recipe/",
        "parser": "kewpie",
    },
    # ── ミツカン ──
    {
        "name": "Mizkan",
        "url":  "https://www.mizkan.co.jp/recipe/",
        "parser": "kikkoman",
    },
    # ── ヤマサ醤油 ──
    {
        "name": "Yamasa",
        "url":  "https://www.yamasa.com/recipe/",
        "parser": "kikkoman",
    },
    # ── マルコメ ──
    {
        "name": "Marukome",
        "url":  "https://www.marukome.co.jp/recipe/",
        "parser": "kewpie",
    },
    # ── ハウス食品 ──
    {
        "name": "House",
        "url":  "https://housefoods.jp/recipe/",
        "parser": "kewpie",
    },
]

# ─── データ構造 ───────────────────────────────────────────
@dataclass
class Ingredient:
    name_ja: str
    amount: str
    name_translated: dict = field(default_factory=dict)   # lang -> str
    amazon_url: str = ""
    rakuten_url: str = ""

@dataclass
class Recipe:
    id: str
    source_url: str
    source_site: str
    title_ja: str
    description_ja: str
    ingredients: list[Ingredient]
    steps_ja: list[str]
    image_url: str = ""
    # 翻訳結果
    title: dict = field(default_factory=dict)          # lang -> str
    description: dict = field(default_factory=dict)    # lang -> str
    steps: dict = field(default_factory=dict)          # lang -> list[str]

# ─── Google翻訳エンジン（APIキー不要）───────────────────
# Google翻訳の言語コードマッピング
GOOGLE_LANG_CODES = {
    "en":    "en",
    "zh_tw": "zh-TW",
    "zh_cn": "zh-CN",
    "vi":    "vi",
    "hi":    "hi",
    "ru":    "ru",
    "th":    "th",
    "id":    "id",
    "ms":    "ms",
    "ko":    "ko",
}

class Translator:
    """Google翻訳を使った無料翻訳エンジン"""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    def __init__(self):
        self._cache: dict = {}

    def translate(self, text: str, target_lang: str) -> str:
        """1テキストを翻訳して返す"""
        if not text or not text.strip():
            return text

        gl = GOOGLE_LANG_CODES.get(target_lang, target_lang)
        cache_key = hashlib.md5(f"{gl}:{text}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                "client": "gtx",
                "sl":     "ja",
                "tl":     gl,
                "dt":     "t",
                "q":      text,
            }
            r = requests.get(url, params=params, headers=self.HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
            result = "".join(part[0] for part in data[0] if part[0])
            self._cache[cache_key] = result
            time.sleep(0.3)   # レート制限対策
            return result
        except Exception as e:
            log.warning(f"翻訳失敗 ({target_lang}): {e}")
            return text   # 失敗時は原文を返す

    def translate_recipe(self, recipe: "Recipe", langs: list[str]) -> "Recipe":
        log.info(f"翻訳中: {recipe.title_ja}")

        for lang in langs:
            # タイトル
            recipe.title[lang] = self.translate(recipe.title_ja, lang)

            # 説明文
            recipe.description[lang] = self.translate(recipe.description_ja, lang) if recipe.description_ja else ""

            # 材料名
            for ing in recipe.ingredients:
                ing.name_translated[lang] = self.translate(ing.name_ja, lang)

            # 手順（1ステップずつ翻訳）
            translated_steps = []
            for step in recipe.steps_ja:
                translated_steps.append(self.translate(step, lang))
            recipe.steps[lang] = translated_steps

        return recipe

# ─── スクレイパー基底クラス ──────────────────────────────
class BaseScraper:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; RecipeBot/1.0; +https://example.com/bot)",
        "Accept-Language": "ja,en-US;q=0.9",
    }

    def fetch(self, url: str) -> BeautifulSoup:
        log.info(f"Fetching: {url}")
        r = requests.get(url, headers=self.HEADERS, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        return BeautifulSoup(r.text, "html.parser")

    def make_id(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()[:8]

    def parse(self, url: str) -> list[Recipe]:
        raise NotImplementedError

# ─── Kewpie スクレイパー ─────────────────────────────────
class KewpieScraper(BaseScraper):
    def parse(self, url: str) -> list[Recipe]:
        soup = self.fetch(url)
        recipes = []

        # レシピカード一覧を取得（構造はサイトに合わせて調整）
        cards = soup.select("article, .recipe-item, li.item, .p-recipe-card")[:MAX_RECIPES_PER_SITE]

        if not cards:
            # フォールバック: リンク一覧からレシピページURLを収集
            links = [a["href"] for a in soup.select("a[href*='/recipes/']") if a.get("href")]
            links = list(dict.fromkeys(links))[:MAX_RECIPES_PER_SITE]  # 重複排除して最大N件
            for link in links:
                full_url = link if link.startswith("http") else "https://www.kewpie.co.jp" + link
                try:
                    r = self._parse_detail(full_url)
                    if r:
                        recipes.append(r)
                    time.sleep(1)
                except Exception as e:
                    log.warning(f"スキップ: {full_url} ({e})")
        else:
            for card in cards:
                a = card.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else "https://www.kewpie.co.jp" + href
                try:
                    r = self._parse_detail(full_url)
                    if r:
                        recipes.append(r)
                    time.sleep(1)
                except Exception as e:
                    log.warning(f"スキップ: {full_url} ({e})")

        log.info(f"Kewpie: {len(recipes)} レシピ取得")
        return recipes

    def _parse_detail(self, url: str) -> Optional[Recipe]:
        soup = self.fetch(url)

        title = (
            soup.select_one("h1.recipe-title, h1.p-recipe-detail__title, h1") or
            soup.select_one("title")
        )
        title_text = title.get_text(strip=True) if title else "（タイトル不明）"

        desc_el = soup.select_one(".recipe-description, .p-recipe-detail__description, .intro, p")
        desc_text = desc_el.get_text(strip=True) if desc_el else ""

        # 材料
        ingredients = []
        for li in soup.select(".ingredient-list li, .p-recipe-detail__ingredient li, ul.ingredients li"):
            text = li.get_text(strip=True)
            # 「大さじ1 醤油」のような形式を分割
            parts = re.split(r"\s{2,}|　", text, maxsplit=1)
            if len(parts) == 2:
                ingredients.append(Ingredient(name_ja=parts[1], amount=parts[0]))
            else:
                ingredients.append(Ingredient(name_ja=text, amount="適量"))

        # 手順
        steps = []
        for step in soup.select(".recipe-step, .p-recipe-detail__step, ol.steps li, .step-text"):
            txt = step.get_text(strip=True)
            if txt:
                steps.append(txt)

        img = soup.select_one("img.recipe-image, .p-recipe-detail__image img, article img")
        img_url = img["src"] if img and img.get("src") else ""

        if not title_text or title_text == "（タイトル不明）":
            return None

        # 材料も手順もない＝レシピページではない → スキップ
        if not ingredients and not steps:
            log.info(f"非レシピページをスキップ: {title_text[:30]}")
            return None

        return Recipe(
            id=self.make_id(url),
            source_url=url,
            source_site="Kewpie",
            title_ja=title_text,
            description_ja=desc_text,
            ingredients=ingredients,
            steps_ja=steps,
            image_url=img_url,
        )

# ─── Kikkoman スクレイパー ───────────────────────────────
class KikkomanScraper(BaseScraper):
    def parse(self, url: str) -> list[Recipe]:
        soup = self.fetch(url)
        recipes = []

        links = []
        for a in soup.select("a[href]"):
            href = a["href"]
            # 個別レシピページのみ対象（/recipe/数字/ の形式）
            if re.search(r"/recipe/\d+/", href):
                links.append(href)
        links = list(dict.fromkeys(links))[:MAX_RECIPES_PER_SITE]

        for link in links:
            full_url = link if link.startswith("http") else "https://www.kikkoman.co.jp" + link
            try:
                r = self._parse_detail(full_url)
                if r:
                    recipes.append(r)
                time.sleep(1)
            except Exception as e:
                log.warning(f"スキップ: {full_url} ({e})")

        log.info(f"Kikkoman: {len(recipes)} レシピ取得")
        return recipes

    def _parse_detail(self, url: str) -> Optional[Recipe]:
        soup = self.fetch(url)

        # タイトル
        title = soup.select_one("h1")
        title_text = title.get_text(strip=True) if title else "（タイトル不明）"

        # 説明文
        desc_el = soup.select_one("h1 + p, .recipe-lead, .lead")
        desc_text = desc_el.get_text(strip=True) if desc_el else ""

        # 材料（「材料」という見出しを含むsection内のli）
        ingredients = []
        for section in soup.find_all("section"):
            h2 = section.find(["h2","h3"])
            if h2 and "材料" in h2.get_text():
                for li in section.select("li"):
                    text = li.get_text(separator="\n", strip=True)
                    if not text or text in ["（A）","（B）","（C）"]:
                        continue
                    parts = [p.strip() for p in text.split("\n") if p.strip()]
                    if len(parts) >= 2:
                        ingredients.append(Ingredient(name_ja=parts[0], amount=parts[-1]))
                    else:
                        ingredients.append(Ingredient(name_ja=text, amount="適量"))
                break

        # 手順（「つくり方」という見出しを含むsection内のol > li）
        steps = []
        for section in soup.find_all("section"):
            h2 = section.find(["h2","h3"])
            if h2 and "つくり方" in h2.get_text():
                for li in section.select("ol li"):
                    txt = re.sub(r"^\d+\s*", "", li.get_text(strip=True))
                    if txt:
                        steps.append(txt)
                break

        # 画像（レシピIDから直接生成）
        recipe_id_match = re.search(r"/recipe/(\d+)/", url)
        if recipe_id_match:
            recipe_id = recipe_id_match.group(1)
            # Google画像プロキシ経由でホットリンクブロックを回避
            orig = f"https://www.kikkoman.co.jp/homecook/assets/img/{recipe_id}.jpg"
            img_url = f"https://images.weserv.nl/?url={orig}&w=600&output=jpg"
        else:
            img_url = ""

        if not title_text or title_text == "（タイトル不明）":
            return None

        # 材料も手順もない＝レシピページではない → スキップ
        if not ingredients and not steps:
            log.info(f"非レシピページをスキップ: {title_text[:30]}")
            return None

        return Recipe(
            id=self.make_id(url),
            source_url=url,
            source_site="Kikkoman",
            title_ja=title_text,
            description_ja=desc_text,
            ingredients=ingredients,
            steps_ja=steps,
            image_url=img_url,
        )

# ─── アフィリエイトリンク生成 ────────────────────────────
def build_affiliate_links(recipe: Recipe) -> Recipe:
    """材料名からAmazon・楽天の検索URLを生成"""
    tag_a = AFFILIATE["amazon_tag"]
    tag_r = AFFILIATE["rakuten_tag"]

    for ing in recipe.ingredients:
        q = requests.utils.quote(ing.name_ja)
        ing.amazon_url  = f"https://www.amazon.co.jp/s?k={q}&tag={tag_a}"
        ing.rakuten_url = f"https://search.rakuten.co.jp/search/mall/{q}/?tag={tag_r}"

    return recipe

# ─── HTML 出力 ───────────────────────────────────────────
def build_html(recipes: list[Recipe], langs: list[str]) -> str:
    flags  = {"en":"🇺🇸","zh_tw":"🇹🇼","zh_cn":"🇨🇳","vi":"🇻🇳","hi":"🇮🇳","ru":"🇷🇺","th":"🇹🇭","id":"🇮🇩","ms":"🇲🇾","ko":"🇰🇷"}
    labels = {"en":"English","zh_tw":"繁體中文","zh_cn":"简体中文","vi":"Tiếng Việt","hi":"हिन्दी","ru":"Русский","th":"ภาษาไทย","id":"Bahasa Indonesia","ms":"Bahasa Melayu","ko":"한국어"}
    sec_tr = {
        "en":    {"ingredients":"Ingredients","steps":"Steps","buy":"🛒 Buy Ingredients","search_placeholder":"Search recipes...","source":"Source","back":"← Back to list","page":"Page"},
        "zh_tw": {"ingredients":"食材","steps":"步驟","buy":"🛒 購買食材","search_placeholder":"搜尋食譜...","source":"來源","back":"← 返回列表","page":"頁"},
        "zh_cn": {"ingredients":"食材","steps":"步骤","buy":"🛒 购买食材","search_placeholder":"搜索食谱...","source":"来源","back":"← 返回列表","page":"页"},
        "vi":    {"ingredients":"Nguyên Liệu","steps":"Các Bước","buy":"🛒 Mua Nguyên Liệu","search_placeholder":"Tìm kiếm công thức...","source":"Nguồn","back":"← Quay lại","page":"Trang"},
        "hi":    {"ingredients":"सामग्री","steps":"चरण","buy":"🛒 सामग्री खरीदें","search_placeholder":"रेसिपी खोजें...","source":"स्रोत","back":"← वापस जाएं","page":"पृष्ठ"},
        "ru":    {"ingredients":"Ингредиенты","steps":"Шаги","buy":"🛒 Купить","search_placeholder":"Поиск рецептов...","source":"Источник","back":"← Назад","page":"Стр."},
        "th":    {"ingredients":"ส่วนผสม","steps":"ขั้นตอน","buy":"🛒 ซื้อวัตถุดิบ","search_placeholder":"ค้นหาสูตรอาหาร...","source":"แหล่งที่มา","back":"← กลับ","page":"หน้า"},
        "id":    {"ingredients":"Bahan","steps":"Langkah","buy":"🛒 Beli Bahan","search_placeholder":"Cari resep...","source":"Sumber","back":"← Kembali","page":"Hal"},
        "ms":    {"ingredients":"Bahan","steps":"Langkah","buy":"🛒 Beli Bahan","search_placeholder":"Cari resipi...","source":"Sumber","back":"← Kembali","page":"Halaman"},
        "ko":    {"ingredients":"재료","steps":"만드는 법","buy":"🛒 재료 구매","search_placeholder":"레시피 검색...","source":"출처","back":"← 목록으로","page":"페이지"},
    }
    used_sec = {l: sec_tr.get(l, sec_tr["en"]) for l in langs}

    # 言語ドロップダウン options
    options = "".join(f'<option value="{l}">{flags.get(l,"")} {labels.get(l,l)}</option>' for l in langs)

    # レシピデータをJSONに変換（JS側で使用）
    recipe_data = []
    for recipe in recipes:
        ing_list = []
        for ing in recipe.ingredients:
            ing_list.append({
                "name_ja": ing.name_ja,
                "amount": ing.amount,
                "translated": ing.name_translated,
                "amazon": ing.amazon_url,
                "rakuten": ing.rakuten_url,
            })
        steps_dict = {}
        for l in langs:
            steps_dict[l] = recipe.steps.get(l, recipe.steps_ja)
        recipe_data.append({
            "id": recipe.id,
            "source_url": recipe.source_url,
            "source_site": recipe.source_site,
            "image": recipe.image_url,
            "title": recipe.title,
            "title_ja": recipe.title_ja,
            "desc": recipe.description,
            "desc_ja": recipe.description_ja,
            "ingredients": ing_list,
            "steps": steps_dict,
        })

    recipes_json = json.dumps(recipe_data, ensure_ascii=False).replace("</script>", "<\\/script>")
    sec_json     = json.dumps(used_sec, ensure_ascii=False).replace("</script>", "<\\/script>")
    default_lang = langs[0]
    title_en     = recipes[0].title.get("en", recipes[0].title_ja) if recipes else "Japanese Kitchen"

    return f"""<!DOCTYPE html>
<html lang="{default_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_en} | JapaneseKitchen</title>
<style>
:root{{--ink:#1a0a00;--rice:#faf7f0;--gold:#c9a84c;--red:#c0392b;--brown:#5c2d1a;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:sans-serif;background:var(--rice);color:var(--ink);}}
/* ── HEADER ── */
header{{background:var(--ink);padding:.9rem 1.5rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;position:sticky;top:0;z-index:100;}}
.logo{{color:var(--gold);font-size:1.3rem;font-weight:bold;cursor:pointer;}}
.lang-select{{padding:.4rem .9rem;border:1.5px solid var(--gold);background:var(--ink);color:var(--gold);border-radius:2rem;cursor:pointer;font-size:.85rem;font-weight:bold;outline:none;}}
/* ── SEARCH BAR ── */
.search-bar{{background:#fff;border-bottom:2px solid #e8d9b0;padding:.9rem 1.5rem;position:sticky;top:52px;z-index:99;}}
.search-bar input{{width:100%;max-width:600px;display:block;margin:0 auto;padding:.6rem 1rem;border:1.5px solid #c9a84c;border-radius:2rem;font-size:.95rem;outline:none;}}
/* ── LIST VIEW ── */
#list-view{{max-width:960px;margin:1.5rem auto;padding:0 1rem 4rem;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1.2rem;}}
.recipe-thumb{{background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.1);overflow:hidden;border:1px solid #e8d9b0;cursor:pointer;transition:transform .2s,box-shadow .2s;}}
.recipe-thumb:hover{{transform:translateY(-3px);box-shadow:0 6px 20px rgba(0,0,0,.15);}}
.recipe-thumb img{{width:100%;height:180px;object-fit:cover;display:block;background:#e8d9b0;}}
.recipe-thumb .no-img{{width:100%;height:180px;background:linear-gradient(135deg,#2d1200,#5c2d1a);display:flex;align-items:center;justify-content:center;font-size:2.5rem;}}
.thumb-body{{padding:.9rem;}}
.thumb-title{{font-size:.92rem;font-weight:bold;color:var(--ink);line-height:1.4;margin-bottom:.3rem;}}
.thumb-site{{font-size:.72rem;color:#999;}}
/* ── PAGINATION ── */
.pagination{{display:flex;justify-content:center;gap:.4rem;margin:1.5rem 0;flex-wrap:wrap;}}
.page-btn{{padding:.4rem .9rem;border:1.5px solid var(--gold);background:transparent;color:var(--gold);border-radius:1rem;cursor:pointer;font-size:.82rem;font-weight:bold;}}
.page-btn.active,.page-btn:hover{{background:var(--gold);color:var(--ink);}}
/* ── DETAIL VIEW ── */
#detail-view{{display:none;max-width:860px;margin:1.5rem auto;padding:0 1rem 4rem;}}
.back-btn{{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1.1rem;background:var(--ink);color:var(--gold);border:none;border-radius:2rem;cursor:pointer;font-size:.88rem;font-weight:bold;margin-bottom:1.2rem;}}
.detail-card{{background:#fff;border-radius:12px;box-shadow:0 3px 20px rgba(0,0,0,.1);overflow:hidden;border:1px solid #e8d9b0;}}
.detail-img{{width:100%;max-height:300px;object-fit:cover;display:block;}}
.detail-head{{background:linear-gradient(135deg,#2d1200,#5c2d1a);color:var(--rice);padding:1.5rem;}}
.detail-head h2{{color:var(--gold);font-size:1.4rem;margin-bottom:.4rem;}}
.detail-head p{{opacity:.8;font-size:.88rem;}}
.source-link{{display:inline-block;margin-top:.6rem;font-size:.75rem;color:var(--gold);opacity:.8;text-decoration:underline;}}
.detail-body{{padding:1.5rem;}}
.sec{{font-weight:bold;color:#8b6914;border-bottom:2px solid var(--gold);padding-bottom:.2rem;margin:1.2rem 0 .8rem;}}
.ing-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.5rem;}}
.ing{{background:var(--rice);border-left:3px solid var(--gold);padding:.5rem .8rem;border-radius:6px;font-size:.88rem;display:flex;flex-direction:column;gap:.2rem;}}
.ing .amt{{color:var(--red);font-weight:bold;font-size:.8rem;}}
.ing .aff-row{{display:flex;gap:.3rem;flex-wrap:wrap;margin-top:.2rem;}}
.aff-link{{padding:.2rem .55rem;border-radius:4px;font-size:.68rem;font-weight:bold;text-decoration:none;}}
.amz{{background:#FF9900;color:#000;}}
.rkt{{background:#BF0000;color:#fff;}}
.steps ol{{padding-left:1.3rem;}}
.steps li{{margin-bottom:.7rem;line-height:1.7;font-size:.9rem;}}
.aff-box{{background:#fffdf5;border:1.5px solid var(--gold);border-radius:8px;padding:1rem;margin-top:1.5rem;}}
.aff-box .ttl{{font-weight:bold;color:#8b6914;margin-bottom:.4rem;font-size:.9rem;}}
#jp-wall{{display:none;position:fixed;inset:0;background:#111;color:#faf7f0;z-index:9999;align-items:center;justify-content:center;flex-direction:column;gap:1rem;text-align:center;padding:2rem;}}
#jp-wall h2{{color:var(--gold);font-size:1.8rem;}}
#jp-wall a{{color:var(--gold);}}
footer{{background:var(--ink);color:rgba(250,247,240,.5);text-align:center;padding:1.2rem;font-size:.75rem;line-height:1.8;}}
footer a{{color:var(--gold);}}
</style>
</head>
<body>
<div id="jp-wall">
  <h2>🇯🇵 このサイトは日本国内では表示されません</h2>
  <p>This site is for international visitors only.</p>
  <a href="https://www.kewpie.co.jp/recipes/" target="_blank">→ Kewpie 公式サイトへ</a>
</div>

<header>
  <div class="logo" onclick="showList()">🍱 JapaneseKitchen</div>
  <select class="lang-select" onchange="setLang(this.value)">{options}</select>
</header>

<div class="search-bar">
  <input type="text" id="search-input" placeholder="Search recipes..." oninput="onSearch()">
</div>

<!-- LIST VIEW -->
<div id="list-view">
  <div class="grid" id="recipe-grid"></div>
  <div class="pagination" id="pagination"></div>
</div>

<!-- DETAIL VIEW -->
<div id="detail-view">
  <button class="back-btn" onclick="showList()">← Back</button>
  <div class="detail-card">
    <img id="d-img" class="detail-img" src="" alt="" onerror="this.style.display='none'">
    <div class="detail-head">
      <h2 id="d-title"></h2>
      <p id="d-desc"></p>
      <a id="d-source" class="source-link" href="#" target="_blank" rel="nofollow"></a>
    </div>
    <div class="detail-body">
      <div class="sec" id="d-sec-ing">Ingredients</div>
      <div class="ing-grid" id="d-ing-grid"></div>
      <div class="sec" id="d-sec-steps">Steps</div>
      <div class="steps"><ol id="d-steps-list"></ol></div>
      <div class="aff-box">
        <div class="ttl" id="d-aff-ttl">🛒 Buy These Ingredients</div>
      </div>
    </div>
  </div>
</div>

<footer>
  © 2025 JapaneseKitchen.site · Recipes inspired by <a href="https://www.kewpie.co.jp/recipes/" target="_blank">Kewpie</a> and <a href="https://www.kikkoman.co.jp/homecook/" target="_blank">Kikkoman</a> · Affiliate links included
</footer>

<script>
const RECIPES = {recipes_json};
const SEC     = {sec_json};
const PER_PAGE = 10;
let currentLang = '{default_lang}';
let currentPage = 1;
let filtered = RECIPES;

// ── 言語切替 ──
function setLang(lang) {{
  currentLang = lang;
  document.querySelector('.lang-select').value = lang;
  document.getElementById('search-input').placeholder = (SEC[lang]||SEC['{default_lang}']).search_placeholder;
  document.querySelector('.back-btn').textContent = (SEC[lang]||SEC['{default_lang}']).back;
  renderList();
}}

// ── 検索 ──
function onSearch() {{
  const q = document.getElementById('search-input').value.toLowerCase();
  filtered = q ? RECIPES.filter(r => {{
    const t = (r.title[currentLang]||r.title_ja||'').toLowerCase();
    return t.includes(q);
  }}) : RECIPES;
  currentPage = 1;
  renderList();
}}

// ── 一覧表示 ──
function showList() {{
  document.getElementById('list-view').style.display = 'block';
  document.getElementById('detail-view').style.display = 'none';
  renderList();
}}

function renderList() {{
  const grid = document.getElementById('recipe-grid');
  const total = filtered.length;
  const pages = Math.ceil(total / PER_PAGE);
  const start = (currentPage - 1) * PER_PAGE;
  const slice = filtered.slice(start, start + PER_PAGE);

  grid.innerHTML = slice.map(r => {{
    const title = r.title[currentLang] || r.title_ja;
    const imgHtml = r.image
      ? `<img src="${{r.image}}" alt="${{title}}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=no-img>🍽️</div>'">`
      : `<div class="no-img">🍽️</div>`;
    return `<div class="recipe-thumb" onclick="showDetail('${{r.id}}')">
      ${{imgHtml}}
      <div class="thumb-body">
        <div class="thumb-title">${{title}}</div>
        <div class="thumb-site">${{r.source_site}}</div>
      </div>
    </div>`;
  }}).join('');

  // ページネーション
  const pag = document.getElementById('pagination');
  if (pages <= 1) {{ pag.innerHTML = ''; return; }}
  const s = SEC[currentLang]||SEC['{default_lang}'];
  pag.innerHTML = Array.from({{length: pages}}, (_, i) =>
    `<button class="page-btn${{i+1===currentPage?' active':''}}" onclick="goPage(${{i+1}})">${{s.page}} ${{i+1}}</button>`
  ).join('');
}}

function goPage(p) {{
  currentPage = p;
  renderList();
  window.scrollTo(0,0);
}}

// ── 詳細表示 ──
function showDetail(id) {{
  const r = RECIPES.find(x => x.id === id);
  if (!r) return;
  const lang = currentLang;
  const s = SEC[lang]||SEC['{default_lang}'];

  // 画像
  const img = document.getElementById('d-img');
  if (r.image) {{ img.src = r.image; img.alt = r.title[lang]||r.title_ja; img.style.display='block'; }}
  else img.style.display = 'none';

  // タイトル・説明
  document.getElementById('d-title').textContent = r.title[lang]||r.title_ja;
  document.getElementById('d-desc').textContent  = r.desc[lang]||r.desc_ja||'';

  // 出典リンク
  const srcEl = document.getElementById('d-source');
  srcEl.textContent = `${{s.source}}: ${{r.source_site}}`;
  srcEl.href = r.source_url;

  // セクション見出し
  document.getElementById('d-sec-ing').textContent   = s.ingredients;
  document.getElementById('d-sec-steps').textContent = s.steps;
  document.getElementById('d-aff-ttl').textContent   = s.buy;
  document.querySelector('.back-btn').textContent    = s.back;

  // 材料
  const ingGrid = document.getElementById('d-ing-grid');
  ingGrid.innerHTML = r.ingredients.map(ing => {{
    const name = (ing.translated&&ing.translated[lang]) || ing.name_ja;
    const aff = [
      ing.amazon  ? `<a class="aff-link amz" href="${{ing.amazon}}"  target="_blank" rel="nofollow">Amazon</a>` : '',
      ing.rakuten ? `<a class="aff-link rkt" href="${{ing.rakuten}}" target="_blank" rel="nofollow">楽天</a>`   : '',
    ].join('');
    return `<div class="ing">
      <span class="amt">${{ing.amount}}</span>
      <span>${{name}}</span>
      ${{aff ? `<div class="aff-row">${{aff}}</div>` : ''}}
    </div>`;
  }}).join('');

  // 手順
  const stepsList = r.steps[lang] || r.steps['{default_lang}'] || [];
  document.getElementById('d-steps-list').innerHTML = stepsList.map(s => `<li>${{s}}</li>`).join('');

  document.getElementById('list-view').style.display   = 'none';
  document.getElementById('detail-view').style.display = 'block';
  window.scrollTo(0,0);
}}

// ── GEO BLOCK JAPAN（テスト中は無効）──
// async function checkGeo() {{
//   try {{
//     const r = await fetch('https://ipapi.co/json/');
//     const d = await r.json();
//     if (d.country_code === 'JP') {{
//       document.getElementById('jp-wall').style.display = 'flex';
//       document.body.style.overflow = 'hidden';
//     }}
//   }} catch(e) {{}}
// }}
// checkGeo();

// ── ブラウザ言語自動選択 ──
(function() {{
  const c = (navigator.language||'').toLowerCase().slice(0,2);
  const map = {{'zh':'zh_cn','vi':'vi','hi':'hi','ru':'ru','th':'th','id':'id','ms':'ms','ko':'ko'}};
  if (map[c]) {{ currentLang = map[c]; document.querySelector('.lang-select').value = map[c]; }}
  showList();
}})();
</script>
</body>
</html>"""

# ─── メイン処理 ───────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Japanese Recipe Scraper + Translator")
    print("  対応言語:", ", ".join(LANGUAGES.keys()))
    print("=" * 60)

    # 使用言語を選択（必要なら絞り込み）
    selected_langs = ["en", "zh_tw", "zh_cn", "vi", "hi", "ru", "th", "id", "ms", "ko"]

    # Translator初期化（APIキー不要）
    translator = Translator()

    # ── 既存JSONキャッシュを読み込む（翻訳済みレシピを再翻訳しない）──
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    json_path = out_dir / "recipes.json"

    existing_ids: set[str] = set()
    existing_recipes: list[Recipe] = []
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            cached = json.load(f)
        for d in cached:
            r = Recipe(**{
                k: v for k, v in d.items()
                if k in Recipe.__dataclass_fields__
            })
            r.ingredients = [Ingredient(**i) for i in d.get("ingredients", [])]
            # 材料も手順もないキャッシュは除外（前回の不正データ）
            if not r.ingredients and not r.steps_ja:
                continue
            existing_recipes.append(r)
            existing_ids.add(r.id)
        log.info(f"キャッシュ: {len(existing_recipes)} 件読み込み済み")

    all_recipes: list[Recipe] = list(existing_recipes)

    # ── スクレイピング ──
    scrapers = {
        "kewpie":   KewpieScraper(),
        "kikkoman": KikkomanScraper(),
    }

    new_count = 0
    for site in TARGET_SITES:
        parser_key = site["parser"]
        scraper = scrapers.get(parser_key)
        if not scraper:
            log.warning(f"パーサー未定義: {parser_key}")
            continue
        try:
            recipes = scraper.parse(site["url"])
            for r in recipes:
                if r.id not in existing_ids:   # ← 重複スキップ
                    all_recipes.append(r)
                    existing_ids.add(r.id)
                    new_count += 1
        except Exception as e:
            log.error(f"スクレイピング失敗 ({site['name']}): {e}")

    log.info(f"新規レシピ: {new_count} 件 / 合計: {len(all_recipes)} 件")

    if not all_recipes:
        log.warning("レシピが取得できませんでした。サンプルレシピを使用します。")
        all_recipes = [_sample_recipe()]

    # ── 翻訳 + アフィリエイトリンク生成（新規のみ）──
    untranslated = [r for r in all_recipes if not r.title]
    log.info(f"翻訳対象: {len(untranslated)} 件")
    for i, recipe in enumerate(untranslated):
        log.info(f"  [{i+1}/{len(untranslated)}] 翻訳中: {recipe.title_ja}")
        recipe = translator.translate_recipe(recipe, selected_langs)
        recipe = build_affiliate_links(recipe)

    # ── JSON保存（全件上書き）──
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in all_recipes], f, ensure_ascii=False, indent=2)
    log.info(f"JSON保存: {json_path}")

    # ── HTML生成 ──
    html = build_html(all_recipes, selected_langs)
    html_path = out_dir / "index.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"HTML保存: {html_path}")

    print("\n✅ 完了!")
    print(f"   📄 JSON  : {json_path}")
    print(f"   🌐 HTML  : {html_path}")
    print(f"   総レシピ数 : {len(all_recipes)} 件（新規 {new_count} 件追加）")
    print(f"   言語数     : {len(selected_langs)}")

def _sample_recipe() -> Recipe:
    """スクレイピング失敗時のサンプルデータ"""
    return Recipe(
        id="sample01",
        source_url="https://www.kewpie.co.jp/recipes/",
        source_site="Kewpie",
        title_ja="キューピーマヨネーズのポテトサラダ",
        description_ja="キューピーマヨネーズを使った定番のポテトサラダ。クリーミーで美味しい。",
        ingredients=[
            Ingredient(name_ja="じゃがいも", amount="2個"),
            Ingredient(name_ja="キューピーマヨネーズ", amount="大さじ3"),
            Ingredient(name_ja="きゅうり", amount="1/4本"),
            Ingredient(name_ja="ハム", amount="2枚"),
            Ingredient(name_ja="塩こしょう", amount="少々"),
        ],
        steps_ja=[
            "じゃがいもを皮をむいて一口大に切り、塩水で15分ゆでる。",
            "きゅうりを薄く切り、塩もみして水けを絞る。",
            "ゆでたじゃがいもをつぶし、全ての材料と混ぜる。",
            "キューピーマヨネーズで和えて、塩こしょうで味を調える。",
        ],
    )

if __name__ == "__main__":
    main()
