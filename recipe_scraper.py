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
    # ── 追加サイトはここに足す ──
    # {"name": "Ajinomoto", "url": "https://www.ajinomoto.co.jp/recipe/", "parser": "kewpie"},
    # {"name": "Mizkan",    "url": "https://www.mizkan.co.jp/recipe/",    "parser": "kikkoman"},
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
            if "/recipe/" in href or "/homecook/" in href:
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

        title = soup.select_one("h1")
        title_text = title.get_text(strip=True) if title else "（タイトル不明）"

        desc_el = soup.select_one(".recipe-introduction, .description, p.intro")
        desc_text = desc_el.get_text(strip=True) if desc_el else ""

        ingredients = []
        for li in soup.select("ul.ingredient li, .ingredients li, .material li"):
            text = li.get_text(strip=True)
            parts = re.split(r"[…・\t]|\s{2,}", text, maxsplit=1)
            if len(parts) == 2:
                ingredients.append(Ingredient(name_ja=parts[0], amount=parts[1]))
            else:
                ingredients.append(Ingredient(name_ja=text, amount="適量"))

        steps = [
            s.get_text(strip=True)
            for s in soup.select("ol li, .step, .procedure li")
            if s.get_text(strip=True)
        ]

        img = soup.select_one("img.recipe-img, .recipe-photo img, article img")
        img_url = img["src"] if img and img.get("src") else ""

        if not title_text or title_text == "（タイトル不明）":
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
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{default_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_en}</title>
<style>
  :root{{--ink:#1a0a00;--rice:#faf7f0;--gold:#c9a84c;--red:#c0392b;}}
  *{{margin:0;padding:0;box-sizing:border-box;}}
  body{{font-family:sans-serif;background:var(--rice);color:var(--ink);}}
  header{{background:var(--ink);padding:1rem 2rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;}}
  .logo{{color:var(--gold);font-size:1.4rem;font-weight:bold;}}
  .lang-bar button{{padding:.3rem .8rem;border:1.5px solid var(--gold);background:transparent;color:var(--gold);border-radius:2rem;cursor:pointer;font-size:.8rem;margin:.1rem;}}
  .lang-bar button.active{{background:var(--gold);color:var(--ink);font-weight:bold;}}
  main{{max-width:860px;margin:2rem auto;padding:0 1rem 4rem;}}
  .card{{background:#fff;border-radius:10px;box-shadow:0 3px 20px rgba(0,0,0,.1);margin-bottom:2rem;overflow:hidden;border:1px solid #e8d9b0;}}
  .card-head{{background:linear-gradient(135deg,#2d1200,#5c2d1a);color:var(--rice);padding:1.5rem;}}
  .card-head h2{{color:var(--gold);font-size:1.4rem;margin-bottom:.4rem;}}
  .card-head p{{opacity:.8;font-size:.88rem;}}
  .card-body{{padding:1.5rem;}}
  .sec{{font-weight:bold;color:#8b6914;border-bottom:2px solid var(--gold);padding-bottom:.2rem;margin:1.2rem 0 .8rem;}}
  .ing-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.5rem;}}
  .ing{{background:var(--rice);border-left:3px solid var(--gold);padding:.5rem .8rem;border-radius:6px;font-size:.88rem;}}
  .ing .amt{{color:var(--red);font-weight:bold;font-size:.8rem;}}
  .steps li{{margin-bottom:.6rem;line-height:1.7;font-size:.9rem;}}
  .aff-box{{background:#fffdf5;border:1.5px solid var(--gold);border-radius:8px;padding:1rem;margin-top:1.5rem;}}
  .aff-box .ttl{{font-weight:bold;color:#8b6914;margin-bottom:.7rem;}}
  .prod-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.6rem;}}
  .prod{{background:#fff;border:1px solid #e8d9b0;border-radius:7px;padding:.7rem;}}
  .prod-name{{font-size:.8rem;font-weight:bold;margin-bottom:.4rem;}}
  .aff-link{{display:inline-block;padding:.25rem .6rem;border-radius:4px;font-size:.72rem;font-weight:bold;text-decoration:none;margin:.2rem .2rem 0 0;}}
  .amz{{background:#FF9900;color:#000;}}
  .rkt{{background:#BF0000;color:#fff;}}
  .note{{font-size:.65rem;color:#aaa;margin-top:.3rem;}}
  #jp-wall{{display:none;position:fixed;inset:0;background:#111;color:#faf7f0;z-index:9999;align-items:center;justify-content:center;flex-direction:column;gap:1rem;text-align:center;padding:2rem;}}
  #jp-wall h2{{color:var(--gold);font-size:1.8rem;}}
  #jp-wall a{{color:var(--gold);}}
  footer{{background:var(--ink);color:rgba(250,247,240,.5);text-align:center;padding:1.2rem;font-size:.75rem;}}
</style>
</head>
<body>
<div id="jp-wall">
  <h2>🇯🇵 このサイトは日本国内では表示されません</h2>
  <p>This site is for international visitors only.</p>
  <a href="https://www.kewpie.co.jp/recipes/" target="_blank">→ Kewpie 公式サイトへ</a>
</div>
<header>
  <div class="logo">🍱 JapaneseKitchen</div>
  <div class="lang-bar">{lang_buttons}</div>
</header>
<main>
{recipe_cards}
</main>
<footer>
  © 2025 JapaneseKitchen.site · Affiliate links included · <a href="#" style="color:var(--gold)">Privacy</a>
</footer>
<script>
{js_code}
</script>
</body>
</html>
"""

def build_html(recipes: list[Recipe], langs: list[str]) -> str:
    # 言語ボタン
    flags = {"en":"🇺🇸","zh_tw":"🇹🇼","zh_cn":"🇨🇳","vi":"🇻🇳","hi":"🇮🇳","ru":"🇷🇺","th":"🇹🇭","id":"🇮🇩","ms":"🇲🇾","ko":"🇰🇷"}
    labels = {"en":"EN","zh_tw":"繁中","zh_cn":"简中","vi":"Việt","hi":"हिं","ru":"RU","th":"ไทย","id":"ID","ms":"MY","ko":"한"}
    buttons = "".join(
        f'<button onclick="setLang(\'{l}\')" id="btn-{l}" class="{"active" if i==0 else ""}">{flags.get(l,"")} {labels.get(l,l)}</button>'
        for i, l in enumerate(langs)
    )

    # レシピカード
    cards_html = ""
    for recipe in recipes:
        # 材料HTML (data属性に各言語を埋め込む)
        ing_items = ""
        for ing in recipe.ingredients:
            tr_attrs = " ".join(
                f'data-{l}="{ing.name_translated.get(l, ing.name_ja)}"'
                for l in langs
            )
            aff = ""
            if ing.amazon_url:
                aff += f'<a class="aff-link amz" href="{ing.amazon_url}" target="_blank" rel="nofollow">Amazon</a>'
            if ing.rakuten_url:
                aff += f'<a class="aff-link rkt" href="{ing.rakuten_url}" target="_blank" rel="nofollow">楽天</a>'
            ing_items += f"""
            <div class="ing">
              <span class="amt">{ing.amount}</span>
              <span class="ing-name" {tr_attrs}>{ing.name_translated.get(langs[0], ing.name_ja)}</span>
              <div>{aff}</div>
            </div>"""

        # 手順HTML
        steps_html = ""
        for l in langs:
            steps_list = recipe.steps.get(l, recipe.steps_ja)
            steps_str = "".join(f"<li>{s}</li>" for s in steps_list)
            hidden = "" if l == langs[0] else ' style="display:none"'
            steps_html += f'<ol class="steps step-block" data-lang="{l}"{hidden}>{steps_str}</ol>'

        # タイトル・説明のdata属性
        title_attrs = " ".join(f'data-{l}="{recipe.title.get(l, recipe.title_ja)}"' for l in langs)
        desc_attrs  = " ".join(f'data-{l}="{recipe.description.get(l, recipe.description_ja)}"' for l in langs)

        cards_html += f"""
<div class="card">
  <div class="card-head">
    <h2 class="t-title" {title_attrs}>{recipe.title.get(langs[0], recipe.title_ja)}</h2>
    <p class="t-desc" {desc_attrs}>{recipe.description.get(langs[0], recipe.description_ja)}</p>
  </div>
  <div class="card-body">
    <div class="sec" data-key="ingredients">Ingredients</div>
    <div class="ing-grid">{ing_items}</div>
    <div class="sec" data-key="steps">Steps</div>
    {steps_html}
    <div class="aff-box">
      <div class="ttl" data-key="buy">🛒 Buy These Ingredients</div>
    </div>
  </div>
</div>"""

    # JavaScript
    sec_translations = {
        "en":    {"ingredients":"Ingredients","steps":"Steps","buy":"🛒 Buy These Ingredients"},
        "zh_tw": {"ingredients":"食材","steps":"步驟","buy":"🛒 購買食材"},
        "zh_cn": {"ingredients":"食材","steps":"步骤","buy":"🛒 购买食材"},
        "vi":    {"ingredients":"Nguyên Liệu","steps":"Các Bước","buy":"🛒 Mua Nguyên Liệu"},
        "hi":    {"ingredients":"सामग्री","steps":"चरण","buy":"🛒 सामग्री खरीदें"},
        "ru":    {"ingredients":"Ингредиенты","steps":"Шаги","buy":"🛒 Купить ингредиенты"},
        "th":    {"ingredients":"ส่วนผสม","steps":"ขั้นตอน","buy":"🛒 ซื้อวัตถุดิบ"},
        "id":    {"ingredients":"Bahan","steps":"Langkah","buy":"🛒 Beli Bahan"},
        "ms":    {"ingredients":"Bahan","steps":"Langkah","buy":"🛒 Beli Bahan"},
        "ko":    {"ingredients":"재료","steps":"만드는 법","buy":"🛒 재료 구매"},
    }
    used_sec = {l: sec_translations.get(l, sec_translations["en"]) for l in langs}

    js = f"""
const SEC = {json.dumps(used_sec, ensure_ascii=False)};
let currentLang = '{langs[0]}';

function setLang(lang) {{
  currentLang = lang;
  // タイトル・説明
  document.querySelectorAll('.t-title').forEach(el => {{
    el.textContent = el.dataset[lang] || el.textContent;
  }});
  document.querySelectorAll('.t-desc').forEach(el => {{
    el.textContent = el.dataset[lang] || el.textContent;
  }});
  // 材料名
  document.querySelectorAll('.ing-name').forEach(el => {{
    el.textContent = el.dataset[lang] || el.textContent;
  }});
  // 手順
  document.querySelectorAll('.step-block').forEach(el => {{
    el.style.display = el.dataset.lang === lang ? '' : 'none';
  }});
  // セクション見出し
  const s = SEC[lang] || SEC['{langs[0]}'];
  document.querySelectorAll('[data-key="ingredients"]').forEach(el => el.textContent = s.ingredients);
  document.querySelectorAll('[data-key="steps"]').forEach(el => el.textContent = s.steps);
  document.querySelectorAll('[data-key="buy"]').forEach(el => el.textContent = s.buy);
  // ボタン
  document.querySelectorAll('.lang-bar button').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('btn-' + lang);
  if (btn) btn.classList.add('active');
}}

// GEO BLOCK JAPAN
async function checkGeo() {{
  try {{
    const r = await fetch('https://ipapi.co/json/');
    const d = await r.json();
    if (d.country_code === 'JP') {{
      document.getElementById('jp-wall').style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }}
  }} catch(e) {{}}
}}
checkGeo();

// ブラウザ言語自動選択
(function() {{
  const nav = navigator.language || '';
  const c = nav.toLowerCase().slice(0,2);
  const map = {{'zh':'zh_cn','vi':'vi','hi':'hi','ru':'ru','th':'th','id':'id','ms':'ms','ko':'ko'}};
  if (map[c] && document.getElementById('btn-' + map[c])) setLang(map[c]);
}})();
"""

    default_lang = langs[0] if langs else "en"
    title_en = recipes[0].title.get("en", recipes[0].title_ja) if recipes else "Japanese Kitchen"

    return HTML_TEMPLATE.format(
        default_lang=default_lang,
        title_en=title_en,
        lang_buttons=buttons,
        recipe_cards=cards_html,
        js_code=js,
    )

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
