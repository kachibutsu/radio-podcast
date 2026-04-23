"""
ラジオ自動録音 → チャプター生成 → ポッドキャストRSS配信 パイプライン
（streamlink版）
"""

import os
import re
import glob
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
    "station": "TBS",                 # radiko放送局ID
    "duration": 1800,                 # 録音秒数（1800 = 30分）
    "podcast_title": "マイラジオ録音", # ポッドキャストのタイトル
    "podcast_desc": "自動録音ポッドキャスト",

    # --- ファイルパス ---
    "episodes_dir": "episodes",       # 録音ファイルの保存先フォルダ
    "feed_file": "feed.xml",          # 生成するRSSファイル名

    # --- 公開URL ---
    "base_url": "https://kachibutsu.github.io/radio-podcast",

    # --- チャプター検出設定 ---
    "silence_db": -35,                # 無音とみなすdBレベル（-30〜-40が目安）
    "silence_duration": 0.5,          # 無音とみなす最短秒数
    "min_chapter_sec": 300,            # チャプターとして有効な最短秒数

    # --- Git自動push ---
    "auto_git_push": True,

    # --- 古いファイルの自動削除（日数）---
    "cleanup_days": 90,
}

# ============================================================
#  ユーティリティ
# ============================================================

JST = timezone(timedelta(hours=9))

def log(msg):
    ts = datetime.now(JST).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

# ============================================================
#  Step 1: 録音（streamlink使用）
# ============================================================

def record(output_path):
    log(f"録音開始: {CONFIG['station']} → {output_path}")
    url = f"https://radiko.jp/#!/live/{CONFIG['station']}"
    cmd = [
        sys.executable, "-m", "streamlink",
        "--stream-segmented-duration", str(CONFIG["duration"]),
        url,
        "best",
        "-o", output_path,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("録音失敗。streamlinkのログを確認してください。")
    log("録音完了")
    return output_path

# ============================================================
#  Step 2: 無音検出
# ============================================================

def detect_silences(audio_path):
    log("無音区間を検出中...")
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-af", f"silencedetect=n={CONFIG['silence_db']}dB:d={CONFIG['silence_duration']}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result.stderr)]
    log(f"無音区間検出: {len(ends)}件")
    return ends

# ============================================================
#  Step 3: チャプターポイントの生成
# ============================================================

def build_chapters(silence_ends, total_sec):
    min_sec = CONFIG["min_chapter_sec"]
    boundaries = [0.0] + silence_ends + [total_sec]

    chapters = []
    prev = 0.0
    part = 1

    for t in boundaries[1:]:
        if t - prev >= min_sec:
            chapters.append({
                "index": part,
                "start_ms": int(prev * 1000),
                "end_ms": int(t * 1000),
                "title": f"パート {part}",
            })
            part += 1
            prev = t

    log(f"チャプター生成: {len(chapters)}件")
    for ch in chapters:
        s = ch["start_ms"] // 1000
        e = ch["end_ms"] // 1000
        log(f"  [{ch['index']:02d}] {s//60:02d}:{s%60:02d} 〜 {e//60:02d}:{e%60:02d}  {ch['title']}")

    return chapters

# ============================================================
#  Step 4: チャプターをファイルに埋め込む
# ============================================================

def get_duration_sec(audio_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except:
        return CONFIG["duration"]

def embed_chapters(src_path, chapters):
    log("チャプターをファイルに埋め込み中...")

    meta_path = src_path + ".meta.txt"
    ext = os.path.splitext(src_path)[1]
    out_path = src_path.replace(ext, f"_chap{ext}")

    lines = [";FFMETADATA1\n"]
    for ch in chapters:
        lines += [
            "[CHAPTER]\n",
            "TIMEBASE=1/1000\n",
            f"START={ch['start_ms']}\n",
            f"END={ch['end_ms']}\n",
            f"title={ch['title']}\n",
            "\n",
        ]
    with open(meta_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    cmd = [
        "ffmpeg", "-y",
        "-i", src_path,
        "-i", meta_path,
        "-map_metadata", "1",
        "-codec", "copy",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    os.remove(meta_path)

    if result.returncode != 0:
        log("警告: チャプター埋め込み失敗。元ファイルをそのまま使用します。")
        return src_path

    os.replace(out_path, src_path)
    log("チャプター埋め込み完了")
    return src_path

# ============================================================
#  Step 5: RSSフィード生成
# ============================================================

def build_rss_item(ep_path):
    filename = os.path.basename(ep_path)
    title = filename.rsplit(".", 1)[0]
    url = f"{CONFIG['base_url']}/episodes/{filename}"
    size = os.path.getsize(ep_path)
    ext = filename.rsplit(".", 1)[-1]
    mime = "audio/mpeg" if ext == "mp3" else "audio/mp4"
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
        cd C:\radio-podcast
        glob.glob(os.path.join(episodes_dir, "*.mp3")) +
        glob.glob(os.path.join(episodes_dir, "*.m4a")),
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
#  Step 6: Git push（オプション）
# ============================================================

def git_push(episode_path, feed_path):
    log("GitHubにpush中...")
    cmds = [
        ["git", "add", "."],
        ["git", "commit", "-m", f"new episode: {os.path.basename(episode_path)}"],
        ["git", "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            log(f"警告: gitコマンド失敗: {' '.join(cmd)}")
            return
    log("push完了")

# ============================================================
#  Step 7: 古いファイルの自動削除
# ============================================================

def cleanup_old_files(days=90):
    cutoff = time.time() - (days * 86400)
    deleted = 0
    for f in glob.glob(os.path.join(CONFIG["episodes_dir"], "*")):
        if os.path.getmtime(f) < cutoff:
            os.remove(f)
            log(f"削除: {os.path.basename(f)}")
            deleted += 1
    if deleted:
        log(f"{deleted}件のファイルを削除しました")
    else:
        log("削除対象なし")

# ============================================================
#  メイン
# ============================================================

def main():
    log("=== ラジオポッドキャスト パイプライン 開始 ===")

    ensure_dir(CONFIG["episodes_dir"])
    ensure_dir("logs")

    now = datetime.now(JST).strftime("%Y%m%d_%H%M")
    filename = f"{now}_{CONFIG['station']}.mp3"
    output_path = os.path.join(CONFIG["episodes_dir"], filename)

    # Step 1: 録音
    record(output_path)

    # Step 2〜3: 無音検出 → チャプター生成
    total_sec = get_duration_sec(output_path)
    silence_ends = detect_silences(output_path)
    chapters = build_chapters(silence_ends, total_sec)

    # Step 4: チャプター埋め込み
    if chapters:
        embed_chapters(output_path, chapters)

    # Step 5: RSS生成
    feed_path = generate_rss(CONFIG["episodes_dir"])

    # Step 6: Git push
    if CONFIG["auto_git_push"]:
        git_push(output_path, feed_path)

    # Step 7: 古いファイル削除
    cleanup_old_files(days=CONFIG["cleanup_days"])

    log("=== パイプライン完了 ===")
    log(f"録音ファイル : {output_path}")
    log(f"チャプター数 : {len(chapters)}")
    log(f"RSSフィード  : {feed_path}")


if __name__ == "__main__":
    main()