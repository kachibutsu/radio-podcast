"""
ラジオ自動録音 → ポッドキャストRSS配信 パイプライン
（yt-dlp + ffmpeg版）
"""

import os
import re
import glob
import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import formatdate

# ============================================================
#  設定（ここだけ書き換えてください）
# ============================================================

CONFIG = {
    # --- 録音設定 ---
    "station": "TBS",
    "duration": 1800,
    "program_name": "",               # 番組名（空の場合は局名を使用）
    "podcast_title": "マイラジオ録音",
    "podcast_desc": "自動録音ポッドキャスト",

    # --- ファイルパス ---
    "episodes_dir": "episodes",
    "feed_file": "feed.xml",

    # --- 公開URL ---
    "base_url": "https://kachibutsu.github.io/radio-podcast",

    # --- Git自動push ---
    "auto_git_push": True,

    # --- Dropbox同期フォルダ内のアーカイブ先 ---
    "archive_dir": r"C:\Users\soich\Dropbox\radio-archive",

    # --- 削除ではなくアーカイブ（Dropbox）へ移動する番組と、その日数 ---
    "archive_days_by_title": {
        "GURUGURU": 30,
        "ジャンク": 30,
    },

    # --- 削除される番組と、その日数（archive_days_by_titleに無いものが対象）---
    "cleanup_days": 30,
    "cleanup_days_by_title": {
        "あったかタイム": 14,
        "めるる": 14,
        "日曜サンデー": 21,
    },

    # --- 優先する配信サーバー（この順番で試す）---
    "preferred_formats": ["dr-wowza.radiko-cf.com", "si-c-radiko.smartstream.ne.jp", "si-f-radiko.smartstream.ne.jp"],
}

# ============================================================
#  ユーティリティ
# ============================================================

JST = timezone(timedelta(hours=9))

def log(msg):
    ts = datetime.now(JST).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        log_path = os.path.join("logs", datetime.now(JST).strftime("%Y%m%d") + ".log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # ログ書き込み自体の失敗でパイプラインを止めない

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

# ============================================================
#  Step 1: yt-dlpで配信情報とトークンを取得
# ============================================================

def get_stream_info(station):
    log(f"配信情報を取得中: {station}")
    url = f"https://radiko.jp/#!/live/{station}"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--skip-download", "-j",
        "--no-live-from-start",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp情報取得失敗: {result.stderr}")

    info = json.loads(result.stdout)
    return info

def get_auth_token():
    cache_path = os.path.expanduser("~/.cache/yt-dlp/radiko/auth_data.json")
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["data"][0]

def pick_manifest_url(info):
    formats = {f["format_id"]: f for f in info.get("formats", [])}
    for preferred in CONFIG["preferred_formats"]:
        if preferred in formats:
            return formats[preferred]["manifest_url"]
    # フォールバック: 最初のフォーマット
    if info.get("formats"):
        return info["formats"][0]["manifest_url"]
    raise RuntimeError("利用可能な配信フォーマットが見つかりません")

# ============================================================
#  Step 2: ffmpegで録音
# ============================================================

def record(output_path):
    log(f"録音開始: {CONFIG['station']} → {output_path}")

    info = get_stream_info(CONFIG["station"])
    manifest_url = pick_manifest_url(info)
    token = get_auth_token()

    log(f"使用サーバー: {manifest_url.split('/')[2]}")

    cmd = [
        "ffmpeg", "-y",
        "-headers", f"X-Radiko-AuthToken: {token}",
        "-i", manifest_url,
        "-t", str(CONFIG["duration"]),
        "-c", "copy",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, timeout=CONFIG["duration"] + 60)
    except subprocess.TimeoutExpired:
        log("タイムアウトしましたが、ファイルは保存されている可能性があります")

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
        raise RuntimeError("録音失敗。ファイルが作成されていないか小さすぎます。")

    log("録音完了")
    return output_path

# ============================================================
#  Step 3: RSSフィード生成
# ============================================================

def build_rss_item(ep_path):
    filename = os.path.basename(ep_path)
    title = filename.rsplit(".", 1)[0]
    url = f"{CONFIG['base_url']}/episodes/{filename}"
    size = os.path.getsize(ep_path)
    ext = filename.rsplit(".", 1)[-1]
    mime = "audio/mpeg" if ext == "mp3" else "audio/mp4" if ext in ("m4a", "aac") else "audio/aac"
    pub_date = formatdate(os.path.getmtime(ep_path), localtime=False)

    return f"""
    <item>
      <title>{title}</title>
      <enclosure url="{url}" length="{size}" type="{mime}"/>
      <guid isPermaLink="false">{url}</guid>
      <pubDate>{pub_date}</pubDate>
      <itunes:duration>{CONFIG['duration']}</itunes:duration>
    </item>"""

def generate_rss(episodes_dir):
    log("RSSフィード生成中...")

    ep_files = sorted(
        [f for f in glob.glob(os.path.join(episodes_dir, "*.mp3")) if "_chap" not in f] +
        [f for f in glob.glob(os.path.join(episodes_dir, "*.aac")) if "_chap" not in f] +
        [f for f in glob.glob(os.path.join(episodes_dir, "*.m4a")) if "_chap" not in f],
        reverse=True
    )[:20]

    items = "".join(build_rss_item(ep) for ep in ep_files)

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{CONFIG['podcast_title']}</title>
    <link>{CONFIG['base_url']}</link>
    <description>{CONFIG['podcast_desc']}</description>
    <language>ja</language>
    <atom:link href="{CONFIG['base_url']}/feed.xml" rel="self" type="application/rss+xml"/>
    {items}
  </channel>
</rss>"""

    feed_path = CONFIG["feed_file"]
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(rss)
    log(f"RSSフィード保存: {feed_path}")
    return feed_path

# ============================================================
#  Step 4: Git push
# ============================================================

def git_push(episode_path, feed_path, max_retries=3, retry_wait=30):
    log("GitHubにpush中...")
    add_commit_cmds = [
        ["git", "add", "."],
        ["git", "commit", "-m", f"new episode: {os.path.basename(episode_path)}"],
    ]
    for cmd in add_commit_cmds:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            log(f"警告: gitコマンド失敗: {' '.join(cmd)}")
            return

    for attempt in range(1, max_retries + 1):
        result = subprocess.run(["git", "push"])
        if result.returncode == 0:
            log("push完了")
            return
        log(f"警告: git push失敗（試行 {attempt}/{max_retries}）")
        if attempt < max_retries:
            time.sleep(retry_wait)

    log("エラー: git pushが全て失敗しました。手動でpushしてください。")

# ============================================================
#  Step 5: 古いファイルの自動整理
#  - archive_days_by_titleに指定された番組: 期限を超えたらDropboxのarchive_dirへ移動（削除しない）
#  - それ以外の番組: cleanup_days_by_title（無ければcleanup_days）の期限を超えたら完全削除
# ============================================================

def cleanup_old_files(days=30):
    now = time.time()
    deleted = 0
    archived = 0
    archive_dir = CONFIG.get("archive_dir")
    archive_rules = CONFIG.get("archive_days_by_title", {})

    if archive_dir:
        ensure_dir(archive_dir)

    for f in glob.glob(os.path.join(CONFIG["episodes_dir"], "*")):
        filename = os.path.basename(f)
        name_no_ext = filename.rsplit(".", 1)[0]
        parts = name_no_ext.split("_", 1)
        title = parts[1] if len(parts) > 1 else ""

        if title in archive_rules:
            # アーカイブ対象の番組: 期限を超えたら削除ではなくDropboxのarchive_dirへ移動
            cutoff = now - (archive_rules[title] * 86400)
            if os.path.getmtime(f) < cutoff:
                dest = os.path.join(archive_dir, filename)
                os.rename(f, dest)
                log(f"アーカイブ移動: {filename}（{title} / {archive_rules[title]}日超過）")
                archived += 1
        else:
            # 通常の削除対象番組
            title_days = CONFIG.get("cleanup_days_by_title", {}).get(title, days)
            cutoff = now - (title_days * 86400)
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
                log(f"削除: {filename}（保持{title_days}日超過）")
                deleted += 1

    if deleted or archived:
        log(f"{deleted}件削除、{archived}件アーカイブ移動しました")
    else:
        log("対象なし")

# ============================================================
#  メイン
# ============================================================

def main():
    log("=== ラジオポッドキャスト パイプライン 開始 ===")

    ensure_dir(CONFIG["episodes_dir"])
    ensure_dir("logs")

    now = datetime.now(JST).strftime("%Y%m%d")
    name = CONFIG["program_name"] if CONFIG["program_name"] else CONFIG["station"]
    filename = f"{now}_{name}.aac"
    output_path = os.path.join(CONFIG["episodes_dir"], filename)

    # Step 1-2: 録音
    record(output_path)

    # Step 3: RSS生成
    feed_path = generate_rss(CONFIG["episodes_dir"])

    # Step 4: 古いファイル整理（pushの前に実行し、当日中にGitHubへ反映する）
    cleanup_old_files(days=CONFIG["cleanup_days"])

    # Step 5: Git push
    if CONFIG["auto_git_push"]:
        git_push(output_path, feed_path)

    log("=== パイプライン完了 ===")
    log(f"録音ファイル : {output_path}")
    log(f"RSSフィード  : {feed_path}")


if __name__ == "__main__":
    main()