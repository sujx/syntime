#!/usr/bin/env bash
# 由 _shots/ 的 PNG 母图（2x）生成宣传站交付图：WebP（2x，主用）+ PNG（1x，兜底）+ OG 图。
# 用法：bash website/tools/build_images.sh
set -euo pipefail
IMG="$(cd "$(dirname "$0")/../source/images" && pwd)"
SRC="$IMG/_shots"
for n in settlement dashboard events governance; do
  magick "$SRC/$n.png" -quality 80 -define webp:method=6 "$IMG/gallery/$n.webp"
  magick "$SRC/$n.png" -resize 1440x -strip "$IMG/gallery/$n.png"
done
magick "$SRC/login.png" -quality 82 -define webp:method=6 "$IMG/hero-login.webp"
# OG 图 1200x630：从仪表盘的 1x 图裁内容区（跳过侧栏），**保持原生字号**。
# 注意不要「整页缩到 1200 宽」——那会把 14px 正文压成 ~6px，抓取后完全不可读。
magick "$IMG/gallery/dashboard.png" -crop 1200x630+240+0 +repage -strip "$IMG/og-image.png"
echo "产物："
for f in "$IMG"/*.webp "$IMG"/*.png "$IMG"/gallery/*.webp "$IMG"/gallery/*.png; do
  [ -e "$f" ] || continue
  printf '  %-44s %s\n' "${f#"$IMG"/}" "$(identify -format '%wx%h %b' "$f")"
done
