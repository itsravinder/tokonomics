#!/usr/bin/env bash
# Downloads the official rtk binary into tokonomics/bin/ for macOS or Linux.
# rtk is licensed Apache-2.0 (https://github.com/rtk-ai/rtk).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
bindir="$root/tokonomics/bin"
mkdir -p "$bindir"

os="$(uname -s)"
arch="$(uname -m)"
case "$os-$arch" in
  Darwin-arm64)  asset="rtk-aarch64-apple-darwin.tar.gz" ;;
  Darwin-x86_64) asset="rtk-x86_64-apple-darwin.tar.gz" ;;
  Linux-x86_64)  asset="rtk-x86_64-unknown-linux-musl.tar.gz" ;;
  Linux-aarch64) asset="rtk-aarch64-unknown-linux-gnu.tar.gz" ;;
  *) echo "Unsupported platform: $os-$arch" >&2; exit 1 ;;
esac

echo "Resolving latest rtk release..."
url="$(curl -fsSL https://api.github.com/repos/rtk-ai/rtk/releases/latest \
  | grep -o "https://[^\" ]*${asset}" | head -n1)"
[ -n "$url" ] || { echo "Asset $asset not found in latest release" >&2; exit 1; }

echo "Downloading $asset ..."
tmp="$(mktemp -d)"
curl -fsSL "$url" -o "$tmp/rtk.tgz"
tar -xzf "$tmp/rtk.tgz" -C "$tmp"
rtkbin="$(find "$tmp" -type f -name rtk | head -n1)"
[ -n "$rtkbin" ] || { echo "rtk binary not found in archive" >&2; exit 1; }
install -m 0755 "$rtkbin" "$bindir/rtk"
rm -rf "$tmp"

echo "rtk installed at $bindir/rtk"
"$bindir/rtk" --version
