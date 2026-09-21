import os
import sys
import json
import re
import argparse
import getpass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class KomgaApi:
    def __init__(self, base_url, username, password, api_key=None):
        self.base_url = base_url.rstrip("/") + "/api"
        self.session = requests.Session()
        self.session.mount("http://", HTTPAdapter(max_retries=3))
        self.session.mount("https://", HTTPAdapter(max_retries=3))
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "KomgaExportMylar/1.0"
        })
        self.username = username
        self.password = password
        # Komga 支持 X-API-Key（优先）或 basic 认证
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})
        else:
            self.session.auth = (username, password)
        # 库根目录缓存（library_id → root），由内部从 Komga API 自动获取，无需 --library-root。
        self._library_roots = {}

        validate_url = f"{self.base_url}/v1/libraries"
        resp = self.session.get(validate_url)
        if resp.status_code == 401:
            print("登录失败，状态码: 401 — 请检查用户名/密码或 KOMGA_URL", file=sys.stderr)
            sys.exit(1)

    def get_library_root(self, library_id):
        """内部获取库根目录（GET /v1/libraries/{id} → root），带进程内缓存。失败返回 None。"""
        if library_id in self._library_roots:
            return self._library_roots[library_id]
        try:
            resp = self.session.get(f"{self.base_url}/v1/libraries/{library_id}")
            resp.raise_for_status()
            root = resp.json().get("root")
        except requests.RequestException as e:
            print(f"获取库 {library_id} 根目录失败: {e}", file=sys.stderr)
            root = None
        self._library_roots[library_id] = root
        return root

    def list_series_in_library(self, library_id):
        all_series = []
        page = 0
        size = 2000
        while True:
            url = f"{self.base_url}/v1/series/list"
            params = {"size": size, "page": page}
            payload = {
                "condition": {
                    "allOf": [
                        {"libraryId": {"operator": "is", "value": library_id}},
                        {"deleted": {"operator": "isFalse"}}
                    ]
                }
            }

            try:
                resp = self.session.post(url, params=params, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("content", [])
                all_series.extend(content)
                if len(content) < size:
                    break
                page += 1
            except requests.RequestException as e:
                print(f"获取库 {library_id} 的系列失败（第 {page} 页）: {e}", file=sys.stderr)
                break
        return all_series

    def list_books_in_series(self, series_id):
        all_books = []
        page = 0
        size = 1000
        while True:
            url = f"{self.base_url}/v1/books/list"
            params = {"size": size, "page": page}
            payload = {
                "condition": {
                    "allOf": [
                        {"seriesId": {"operator": "is", "value": str(series_id)}},
                        {"deleted": {"operator": "isFalse"}}
                    ]
                }
            }

            try:
                resp = self.session.post(url, params=params, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("content", [])
                all_books.extend(content)
                if len(content) < size:
                    break
                page += 1
            except requests.RequestException as e:
                print(f"获取系列 {series_id} 的图书失败（第 {page} 页）: {e}", file=sys.stderr)
                break
        return all_books

    def get_komga_series_data(self, komga_series_id):
        url = f"{self.base_url}/v1/series/{komga_series_id}"
        try:
            resp = self.session.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data
        except Exception as e:
            print(f"获取系列 {komga_series_id} 数据失败")
            return None

    def update_series_metadata(self, series_id, metadata):
        url = f"{self.base_url}/v1/series/{series_id}/metadata"
        try:
            resp = self.session.patch(url, json=metadata)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"更新系列 {series_id} 的 metadata 失败: {e}", file=sys.stderr)

    def update_book_metadata(self, book_id, metadata):
        url = f"{self.base_url}/v1/books/{book_id}/metadata"
        try:
            resp = self.session.patch(url, json=metadata)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"更新图书 {book_id} 的 metadata 失败: {e}", file=sys.stderr)

volume_title_pattern = re.compile(
    r'(?:vol(?:ume)?s?|巻|卷|册|冊)[\W_]*?(?P<volNum>\d+)|'
    r'第\s*(?P<volNum2>\d+)\s*(?:巻|卷|册|冊|集)|'
    r'(?P<volNum3>\d+)\s*(?:巻|卷|册|冊|集)',
    re.IGNORECASE
)

def extract_vol_num(book) -> str | None:
    bookname = book.get("name")
    booktitle = (book.get("metadata") or {}).get("title") or ""
    match = volume_title_pattern.search(bookname) or volume_title_pattern.search(booktitle)
    if match:
        vol_str = match.group("volNum") or match.group("volNum2") or match.group("volNum3")
        if vol_str:
            vol_num = int(vol_str)
            return str(vol_num).zfill(2)
    return None

def normalize_age_rating(value):
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip().lower()
        if value.isdigit():
            value = int(value)
        else:
            return None

    if value <= 0:
        return "All"
    elif value < 12:
        return "9+"
    elif value < 15:
        return "12+"
    elif value < 17:
        return "15+"
    elif value < 18:
        return "17+"
    else:
        return "Adult"


def export_series_as_mylar_json(api: KomgaApi, library_id, download_covers, output_dir=None):
    print(f"开始导出库 {library_id} 的系列到 {output_dir}")
    series_list = api.list_series_in_library(library_id)
    if not series_list:
        print("未获取到任何系列，退出")
        return

    print(f"共获取到系列数：{len(series_list)}")

    valid_series = []
    for s in series_list:
        metadata = s.get("metadata", {})
        books_metadata = s.get("booksMetadata", {})
        books_count_outer = s.get("booksCount")
        title = metadata.get("title") or s.get("name")
        total_books = metadata.get("totalBookCount") or books_count_outer
        if not total_books or total_books <= 0:
            print(f"[跳过] 系列 '{title}' 书籍数异常: totalBookCount={metadata.get('totalBookCount')} booksCount={books_count_outer}")
            continue
        valid_series.append(s)

    print(f"过滤后有效系列数：{len(valid_series)}")

    for series in valid_series:
        metadata = series.get("metadata", {})
        books_metadata = series.get("booksMetadata", {})
        title = metadata.get("title") or series.get("name")
        komga_status = (metadata.get("status") or "").upper()
        mylar_status = {
            "ONGOING": "Continuing",
            "HIATUS": "Continuing",
            "ABANDONED": "Continuing",
            "ENDED": "Ended"
        }.get(komga_status)

        series_local_path = series.get("url")
        if not series_local_path:
            print(f"[跳过] 系列 '{title}' 缺少目录信息，无法确定保存路径")
            continue

        url_path = Path(series_local_path)
        # oneshot 系列的 url 指向书籍 zip 文件（Komga 行为）：
        # 目录基准为 zip 父目录、导出文件名取 zip 去扩展名
        if series.get("oneshot") is True:
            series_dir = url_path.parent
            series_file_stem = url_path.stem
        else:
            series_dir = url_path
            series_file_stem = None

        # 库根目录由内部从 Komga API 自动获取，用于还原相对目录结构。
        library_root = api.get_library_root(library_id)
        if output_dir:
            if library_root:
                library_root_path = Path(library_root).resolve()
                try:
                    series_path_obj = series_dir.resolve()
                    relative_path = series_path_obj.relative_to(library_root_path)
                    output_series_dir = Path(output_dir) / relative_path
                except Exception as e:
                    print(f"[跳过] 系列 '{title}' 的路径无法相对于库根目录解析：{e}")
                    continue
            else:
                output_series_dir = Path(output_dir) / series_dir.name
        else:
            output_series_dir = series_dir

        output_series_dir.mkdir(parents=True, exist_ok=True)
        if series.get("oneshot") is True:
            series_file = output_series_dir / f"{series_file_stem}.oneshot.json"
        else:
            series_file = output_series_dir / "series.json"

        mylar_data = {
            "version": "1.0.2",
            "metadata": {
                "type": "comicSeries",
                "publisher": metadata.get("publisher") or "",
                "imprint": None,
                "name": title or "",
                "comicid": 9527,
                "year": 2001,
                "description_text": metadata.get("summary") or books_metadata.get("summary") or "",
                "description_formatted": None,
                "volume": None,
                "booktype": "Print",
                "age_rating": normalize_age_rating(metadata.get("ageRating")) or None,
                "collects": None,
                "comic_image": "",
                "total_issues": int(metadata.get("totalBookCount") or series.get("booksCount")),
                "publication_run": "",
                "status": mylar_status or "Continuing",
                "language": metadata.get("language") or None,
                "readingDirection": metadata.get("readingDirection") or None,
                "releaseDate": books_metadata.get("releaseDate") or None,
                "authors": books_metadata.get("authors") or None,
                "links":  metadata.get("links") or None,
                "alternateTitles": metadata.get("alternateTitles") or None,
                "genres": metadata.get("genres") or None,
                "tags": metadata.get("tags") or books_metadata.get("tags") or None,
            }
        }

        release_date = books_metadata.get("releaseDate")
        if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
            mylar_data["metadata"]["year"] = int(release_date[:4])

        with series_file.open("w", encoding="utf-8", newline="\n") as f:
            json_str = json.dumps(mylar_data, ensure_ascii=False, indent=2)
            f.write(json_str)

        print(f"✅ 已导出系列 '{title}' 到 {series_file}")

        if download_covers:
            if series.get("oneshot") is True:
                cover_path = output_series_dir / f"{series_file_stem}.cover.jpg"
            else:
                cover_path = output_series_dir / "cover.jpg"
            if cover_path.exists():
                print(f"封面已存在，跳过下载: {cover_path}")
            else:
                thumbnail_url = f"{api.base_url}/v1/series/{series['id']}/thumbnail"
                try:
                    headers = {"Accept": "image/*"}
                    r = api.session.get(thumbnail_url, headers=headers)
                    r.raise_for_status()
                    with open(cover_path, "wb") as f:
                        f.write(r.content)
                    print(f"🖼️ 已保存封面到 {cover_path}")
                except Exception as e:
                    print(f"[⚠️] 系列 '{title}' 封面下载失败: {e}")

def update_komga_metadata_from_series_json(api: KomgaApi, series_list, mylar_metadata_path=None):
    if not series_list:
        return
    # 库根目录由内部从 Komga API 自动获取（与导出端一致）。
    library_id = series_list[0].get("libraryId")
    library_root = api.get_library_root(library_id) if library_id else None
    for series in series_list:
        metadatas = series.get("metadata", {})
        series_local_path = series.get("url")
        if not series_local_path:
            continue

        url_path = Path(series_local_path)
        if series.get("oneshot") is True:
            series_dir = url_path.parent
            file_stem = url_path.stem
        else:
            series_dir = url_path
            file_stem = None

        if mylar_metadata_path and library_root:
            library_root = library_root.rstrip('/')
            mylar_metadata_path = mylar_metadata_path.rstrip('/')
            series_dir_str = str(series_dir)
            if series_dir_str.startswith(library_root):
                series_dir_str = mylar_metadata_path + series_dir_str[len(library_root):]
            series_dir = Path(series_dir_str)

        if series.get("oneshot") is True:
            json_path = series_dir / f"{file_stem}.oneshot.json"
        else:
            json_path = series_dir / "series.json"
        if not json_path.exists():
            print(f"未找到 series.json: {json_path}", file=sys.stderr)
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取 {json_path} 失败: {e}", file=sys.stderr)
            continue

        metadata = data.get("metadata", {})
        series_metadata = {}

        for field in ["language", "readingDirection", "genres", "tags", "links", "alternateTitles"]:
            value = metadata.get(field)
            if value:
                series_metadata[field] = value

        series_title = metadatas.get("title") or series.get("name")
        if series_metadata:
            print(f"更新系列 {series_title} ({series['id']}) 元数据: {list(series_metadata.keys())}")
            try:
                api.update_series_metadata(series["id"], series_metadata)
            except Exception as e:
                print(f"更新系列元数据失败: {e}", file=sys.stderr)

        authors = metadata.get("authors")
        books = api.list_books_in_series(series["id"])
        book_metadata = {}
        for book in books:
            if authors:
                book_metadata = {"authors": authors}
            book_number_for_display = extract_vol_num(book)
            if book_number_for_display:
                book_metadata["title"] = f"卷 {book_number_for_display}"
                book_metadata["number"] = book_number_for_display
            if series.get("oneshot") is True:
                book_metadata["summary"] = metadatas.get("summary")
                book_metadata["links"] = series_metadata.get("links")
                book_metadata["tags"] = series_metadata.get("tags")
            if book_metadata:
                print(f"更新图书 {book['name']} ({book['id']}) 元数据: {list(book_metadata.keys())}")
                try:
                    api.update_book_metadata(book["id"], book_metadata)
                except Exception as e:
                    print(f"更新图书 {book['name']} ({book['id']}) 元数据失败: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Komga 元数据导入导出 mylar 工具")
    parser.add_argument("--url", help="Komga 地址，形如 http://localhost:25600", default=os.getenv("KOMGA_URL"))
    parser.add_argument("--username", help="用户名", default=os.getenv("KOMGA_USERNAME"))
    parser.add_argument("--api-key", help="Komga API Key（优先于用户名/密码）", default=os.getenv("KOMGA_API_KEY"))
    parser.add_argument("--library-id", help="库ID", default=os.getenv("KOMGA_LIBRARY_ID"))
    parser.add_argument("--output", help="导出目录", default="")
    parser.add_argument("--mylar-metadata-path", help="Mylar 元数据路径（用于替换库根目录前缀）")
    parser.add_argument("--save-cover", help="是否保存系列封面", action="store_true")
    parser.add_argument("--update-from-mylar-metadata", action="store_true",
                        help="根据 series.url 路径读取 series.json 并写入 Komga 元数据")

    args = parser.parse_args()

    if not args.url:
        args.url = input("请输入 Komga URL: ").strip()
    if not args.username:
        args.username = input("请输入用户名: ").strip()
    password = os.getenv("KOMGA_PASSWORD")
    if not password:
        password = getpass.getpass("请输入密码: ")

    if not args.library_id:
        print("错误：必须指定 --library-id 或环境变量 KOMGA_LIBRARY_ID", file=sys.stderr)
        sys.exit(1)

    api = KomgaApi(args.url, args.username, password, args.api_key)
    if args.update_from_mylar_metadata:
        series_list = api.list_series_in_library(args.library_id)
        update_komga_metadata_from_series_json(api, series_list, args.mylar_metadata_path)
    else:
        export_series_as_mylar_json(api, args.library_id, args.save_cover, args.output)

if __name__ == "__main__":
    main()
