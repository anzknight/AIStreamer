"""
動画と音声クリップを自動合成するスクリプト

使い方:
  python mix_video.py 録画ファイル.mp4
  python mix_video.py 録画ファイル.mp4 --offset 5.0

--offset: OBS録画開始からAITuber起動までの時間差（秒）
          例: OBSを5秒先に押してからpython main.pyを起動した場合は --offset 5
"""
import json
import sys
import subprocess
import argparse
from pathlib import Path

AUDIO_DIR = Path("data/audio_clips")
TIMELINE_FILE = AUDIO_DIR / "timeline.json"


def main():
    parser = argparse.ArgumentParser(description="動画と音声クリップを自動合成")
    parser.add_argument("video", help="OBSの録画ファイル（.mp4）")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="録画開始からAITuber起動までの時間差（秒）")
    parser.add_argument("--output", default="output.mp4", help="出力ファイル名")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"エラー: {video_path} が見つかりません")
        sys.exit(1)

    if not TIMELINE_FILE.exists():
        print(f"エラー: {TIMELINE_FILE} が見つかりません")
        print("SAVE_AUDIO_FILES=true にして収録してください")
        sys.exit(1)

    timeline = json.loads(TIMELINE_FILE.read_text(encoding="utf-8"))
    if not timeline:
        print("エラー: タイムラインが空です")
        sys.exit(1)

    print(f"[合成] 動画: {video_path}")
    print(f"[合成] クリップ数: {len(timeline)}")
    print(f"[合成] オフセット: {args.offset}秒")
    print()

    # FFmpegのフィルターグラフを構築
    # 動画のオリジナル音声 + 各クリップを指定タイミングでミックス
    inputs = ["-i", str(video_path)]
    filter_parts = []
    amix_inputs = ["[0:a]"]  # 元の動画音声

    for i, entry in enumerate(timeline):
        clip_path = AUDIO_DIR / entry["clip"]
        if not clip_path.exists():
            print(f"  スキップ: {entry['clip']} が見つかりません")
            continue
        offset_sec = entry["offset_sec"] + args.offset
        inputs += ["-i", str(clip_path)]
        idx = i + 1
        filter_parts.append(
            f"[{idx}:a]adelay={int(offset_sec * 1000)}|{int(offset_sec * 1000)}[a{idx}]"
        )
        amix_inputs.append(f"[a{idx}]")
        print(f"  {entry['clip']:20s}  {offset_sec:6.1f}秒  {entry['text'][:30]}")

    print()

    n = len(amix_inputs)
    filter_str = ";".join(filter_parts)
    if filter_str:
        filter_str += ";"
    filter_str += f"{''.join(amix_inputs)}amix=inputs={n}:duration=first:dropout_transition=0[aout]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        args.output,
    ]

    print(f"[合成] 出力: {args.output}")
    print("[合成] FFmpegを実行中...")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"\n完成！ → {args.output}")
    else:
        print("\nエラーが発生しました。FFmpegがインストールされているか確認してください。")
        print("https://ffmpeg.org/download.html")


if __name__ == "__main__":
    main()
